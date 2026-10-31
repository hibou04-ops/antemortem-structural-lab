"""Append-only host registry. Candidate history is not policy experience."""
from copy import deepcopy
import json
import os
from pathlib import Path

from .schema import canonical, digest, identifier, keys

SCHEMA = "tomolab-harvest-registry-v1"
MAX_BYTES = 64 * 1024 * 1024
MAX_RECORD_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 8192
KINDS = {"CANDIDATE", "REVIEW", "BATCH", "LEARNING", "M0", "PROFILE"}


class HarvestRegistry:
    def __init__(self, workspace):
        self.workspace = Path(workspace)
        if self.workspace.is_symlink():
            raise ValueError("harvest workspace must not be a symbolic link")
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.path = self.workspace / "registry.jsonl"

    def records(self):
        if self.path.is_symlink():
            raise ValueError("harvest journal must not be a symbolic link")
        if not self.path.exists():
            return []
        if self.path.is_symlink() or not self.path.is_file() or self.path.stat().st_size > MAX_BYTES:
            raise ValueError("bounded regular harvest journal required")
        raw = self.path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            raise ValueError("partial harvest record; preserve bytes for explicit recovery")
        rows, previous, ids = [], None, set()
        for line in raw.splitlines():
            if len(line) > MAX_RECORD_BYTES:
                raise ValueError("harvest record byte cap exceeded")
            row = json.loads(line)
            keys(row, ("schema", "kind", "event_id", "candidate_id", "batch_id", "payload", "previous_sha256", "sha256"))
            if line != canonical(row).encode("utf-8") or row["schema"] != SCHEMA or row["kind"] not in KINDS:
                raise ValueError("invalid harvest journal schema or canonical bytes")
            for name in ("event_id", "batch_id"):
                identifier(row[name])
            if row["candidate_id"] is not None:
                identifier(row["candidate_id"])
            if not isinstance(row["payload"], dict):
                raise ValueError("data-only harvest payload required")
            if row["previous_sha256"] != previous or row["event_id"] in ids or row["sha256"] != digest({k:v for k,v in row.items() if k != "sha256"}):
                raise ValueError("harvest chain, identity or digest mismatch")
            ids.add(row["event_id"])
            previous = row["sha256"]
            rows.append(row)
            if len(rows) > MAX_RECORDS:
                raise ValueError("harvest record count cap exceeded")
        return rows

    def append(self, kind, payload, *, batch_id, candidate_id=None, event_id=None):
        if kind not in KINDS or not isinstance(payload, dict):
            raise ValueError("unsupported data-only harvest event")
        identifier(batch_id)
        if candidate_id is not None:
            identifier(candidate_id)
        payload = json.loads(canonical(payload))
        event_id = event_id or digest(dict(kind=kind, candidate_id=candidate_id, batch_id=batch_id, payload=payload))
        identifier(event_id)
        lock = self.path.with_name(self.path.name + ".lock")
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            rows = self.records()
            if kind == "CANDIDATE" and any(r["kind"] == "CANDIDATE" and r["candidate_id"] == candidate_id for r in rows):
                return dict(status="ALREADY_REGISTERED", candidate_id=candidate_id)
            old = next((row for row in rows if row["event_id"] == event_id), None)
            if old is not None:
                if (old["kind"],old["candidate_id"],old["batch_id"],old["payload"]) != (kind,candidate_id,batch_id,payload):
                    raise ValueError("harvest event ID conflict")
                return dict(status="ALREADY_COMMITTED", sha256=old["sha256"])
            if len(rows) >= MAX_RECORDS:
                raise ValueError("harvest record count cap exceeded")
            row = dict(schema=SCHEMA, kind=kind, event_id=event_id, candidate_id=candidate_id,
                batch_id=batch_id, payload=payload, previous_sha256=rows[-1]["sha256"] if rows else None)
            row["sha256"] = digest(row)
            raw = (canonical(row) + "\n").encode("utf-8")
            if len(raw) > MAX_RECORD_BYTES or (self.path.stat().st_size if self.path.exists() else 0)+len(raw)>MAX_BYTES:
                raise ValueError("harvest journal byte cap exceeded")
            with self.path.open("ab") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            return dict(status="COMMITTED", sha256=row["sha256"])
        finally:
            os.close(fd)
            lock.unlink()

    def candidates(self):
        result = {}
        for row in self.records():
            if row["kind"] == "CANDIDATE":
                candidate = row["payload"]["candidate"]
                if candidate["candidate_id"] != row["candidate_id"] or row["candidate_id"] in result:
                    raise ValueError("candidate identity was rewritten")
                result[row["candidate_id"]] = deepcopy(candidate)
        return result

    def known_candidate_ids(self):
        return tuple(sorted(self.candidates()))

    def assessments(self):
        result = {}
        for row in self.records():
            if row["kind"] in ("CANDIDATE", "REVIEW"):
                result[row["candidate_id"]] = deepcopy(row["payload"]["assessment"])
        return result

    def register(self, candidate, assessment, *, batch_id):
        candidate_id = candidate["candidate_id"]
        if candidate_id in self.candidates():
            return dict(status="ALREADY_REGISTERED", candidate_id=candidate_id)
        return self.append("CANDIDATE", dict(candidate=candidate,assessment=assessment),
            candidate_id=candidate_id, batch_id=batch_id)

    def review(self, candidate_id, assessment, review, execution_receipt, *, batch_id):
        if candidate_id not in self.candidates():
            raise ValueError("register candidate provenance before review")
        return self.append("REVIEW", dict(assessment=assessment,review=review,
            execution_receipt=execution_receipt),candidate_id=candidate_id,batch_id=batch_id)

    def reviewed(self, candidate_id):
        candidate = self.candidates().get(candidate_id)
        if candidate is None:
            raise ValueError("unknown harvest candidate")
        rows = [row for row in self.records() if row["candidate_id"] == candidate_id]
        latest = next((row for row in reversed(rows) if row["kind"] == "REVIEW"), None)
        return dict(candidate=candidate, assessment=self.assessments()[candidate_id],
            review=deepcopy(latest["payload"]["review"]) if latest else None,
            execution_receipt=deepcopy(latest["payload"]["execution_receipt"]) if latest else None)

    def record_profile(self, candidate_id, profile, *, batch_id):
        from .harvester_review import validate_candidate_profile
        candidate = self.candidates().get(candidate_id)
        if candidate is None:
            raise ValueError("register original candidate before profile supplement")
        validated = validate_candidate_profile(candidate, profile)
        return self.append("PROFILE", dict(profile=validated), candidate_id=candidate_id, batch_id=batch_id)

    def profiles(self):
        from .harvester_review import validate_candidate_profile
        candidates, result = self.candidates(), {}
        for row in self.records():
            if row["kind"] == "PROFILE":
                candidate = candidates.get(row["candidate_id"])
                if candidate is None:
                    raise ValueError("profile has no original registered candidate")
                result[row["candidate_id"]] = validate_candidate_profile(candidate, row["payload"]["profile"])
        return result
