"""Trusted-host append-only knowledge persistence, excluded from Generator code.

Explicit file paths are chosen by the caller. Existing bytes are never replaced;
an interrupted/truncated append fails closed and needs operator recovery.
"""
import json
import os
from copy import deepcopy
from pathlib import Path

from .knowledge import KnowledgeArchive
from .schema import canonical, digest, identifier, keys

SCHEMA="tomolab-knowledge-store-v1"
MAX_BYTES=64*1024*1024


def _context(snapshot):
    return digest({k:snapshot[k] for k in ("spec","source","temporal_contract","public_ir")})


def _extends(previous,snapshot):
    before,after=previous["journal"],snapshot["journal"]
    if len(after)<len(before) or after[:len(before)]!=before:
        raise ValueError("knowledge journal rollback would discard archived counterevidence")


class KnowledgeStore:
    def __init__(self,path):
        self.path=Path(path)
        if self.path.is_symlink():
            raise ValueError("knowledge store must not be a symbolic link")

    def records(self):
        if not self.path.exists():
            return []
        if not self.path.is_file() or self.path.stat().st_size>MAX_BYTES:
            raise ValueError("knowledge store is not a bounded regular file")
        raw=self.path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            raise ValueError("incomplete knowledge append; preserve bytes for explicit recovery")
        records=[];previous="0"*64;ids=set();contexts={}
        for line in raw.splitlines():
            try:
                row=json.loads(line)
            except (ValueError,UnicodeError) as error:
                raise ValueError("corrupt knowledge journal") from error
            keys(row,("schema","record_id","previous_sha256","snapshot","sha256"))
            if line!=canonical(row).encode("utf-8"):
                raise ValueError("noncanonical or rewritten knowledge record bytes")
            identifier(row["record_id"])
            if (row["schema"]!=SCHEMA or row["previous_sha256"]!=previous
                    or row["sha256"]!=digest({k:v for k,v in row.items() if k!="sha256"})
                    or row["record_id"] in ids):
                raise ValueError("knowledge append chain or identity mismatch")
            KnowledgeArchive.from_snapshot(row["snapshot"])
            context=_context(row["snapshot"])
            if context in contexts:
                _extends(contexts[context],row["snapshot"])
            contexts[context]=row["snapshot"]
            previous=row["sha256"];ids.add(row["record_id"]);records.append(row)
        return records

    def append(self,snapshot,*,record_id):
        identifier(record_id)
        snapshot=deepcopy(snapshot)
        KnowledgeArchive.from_snapshot(snapshot)
        # Exclusive adjacent lock guards cooperating writers, with no stale-lock
        # deletion or retries. Lock contention is a failure, never silent loss.
        lock=self.path.with_name(self.path.name+".lock")
        fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            records=self.records()
            existing=next((r for r in records if r["record_id"]==record_id),None)
            if existing is not None:
                if existing["snapshot"]!=snapshot:
                    raise ValueError("knowledge record ID conflict")
                return {"status":"ALREADY_COMMITTED","record_id":record_id,"sha256":existing["sha256"]}
            context=_context(snapshot)
            previous=next((r["snapshot"] for r in reversed(records) if _context(r["snapshot"])==context),None)
            if previous is not None:
                _extends(previous,snapshot)
            row={"schema":SCHEMA,"record_id":record_id,"previous_sha256":records[-1]["sha256"] if records else "0"*64,"snapshot":snapshot}
            row["sha256"]=digest(row)
            encoded=(canonical(row)+"\n").encode("utf-8")
            if (self.path.stat().st_size if self.path.exists() else 0)+len(encoded)>MAX_BYTES:
                raise ValueError("knowledge store byte cap exceeded")
            with self.path.open("ab") as output:
                output.write(encoded);output.flush();os.fsync(output.fileno())
            return {"status":"COMMITTED","record_id":record_id,"sha256":row["sha256"]}
        finally:
            os.close(fd);lock.unlink()

    def latest(self):
        records=self.records()
        return KnowledgeArchive.from_snapshot(records[-1]["snapshot"]) if records else None
