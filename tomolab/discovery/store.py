"""Caller-side append-only SQLite evidence chain. Never loaded by Generator."""
from pathlib import Path
import sqlite3

from .schema import canonical,digest


class FailureStore:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.connection=sqlite3.connect(self.path,timeout=10)
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("CREATE TABLE IF NOT EXISTS evidence (seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, previous_sha256 TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL)")
        self.connection.execute("CREATE TRIGGER IF NOT EXISTS evidence_no_update BEFORE UPDATE ON evidence BEGIN SELECT RAISE(ABORT,'append-only evidence'); END")
        self.connection.execute("CREATE TRIGGER IF NOT EXISTS evidence_no_delete BEFORE DELETE ON evidence BEGIN SELECT RAISE(ABORT,'append-only evidence'); END")
        self.connection.commit()

    def append(self,event_id,payload):
        if not isinstance(event_id,str) or not 1<=len(event_id)<=160:
            raise ValueError("bounded event ID required")
        encoded=canonical(payload)
        if len(encoded)>4_000_000:
            raise ValueError("record too large")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            previous=self.connection.execute("SELECT seq,sha256 FROM evidence ORDER BY seq DESC LIMIT 1").fetchone()
            seq,prior=(previous[0]+1,previous[1]) if previous else (1,"0"*64)
            sha=digest({"seq":seq,"event_id":event_id,"previous_sha256":prior,"payload":payload})
            self.connection.execute("INSERT INTO evidence VALUES (?,?,?,?,?)",(seq,event_id,prior,encoded,sha))
            self.connection.commit()
            return {"seq":seq,"sha256":sha,"previous_sha256":prior}
        except Exception:
            self.connection.rollback()
            raise

    def verify(self):
        import json
        previous="0"*64
        count=0
        for seq,event_id,prior,payload,sha in self.connection.execute("SELECT * FROM evidence ORDER BY seq"):
            count+=1
            if seq!=count or prior!=previous or sha!=digest({"seq":seq,"event_id":event_id,"previous_sha256":prior,"payload":json.loads(payload)}):
                raise ValueError("evidence chain invalid")
            previous=sha
        return {"status":"PASS","records":count,"head_sha256":previous,
                "boundary":"local tamper-evident chain; not a signature or protection against database-owner rewriting"}

    def close(self):
        self.connection.close()

    def __enter__(self): return self
    def __exit__(self,*exc): self.close()
