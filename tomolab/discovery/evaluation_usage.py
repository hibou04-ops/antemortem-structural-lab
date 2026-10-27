"""Cooperative host authority for individually consumed final identities.

Exclusive creation coordinates cooperating writers. This is not an OS sandbox,
hostile-host protection, or a global registry across arbitrary authority roots.
An interrupted START remains consumed; a lock is never silently removed.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import re

from .schema import canonical, digest, keys

IDENTITY_FIELDS = ("canonical_function_identity", "cross_revision_function_key",
                   "normalized_ast_clone_sha256", "implementation_sha256")


def identity_tokens(identity):
    keys(identity, IDENTITY_FIELDS)
    for value in identity.values():
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
            raise ValueError("reviewed individual SHA-256 identities required")
    # Cross-revision, clone, and implementation values deliberately do not bind
    # Oracle, output, seed, alias, or evaluation batch membership.
    return {field + ":" + identity[field] for field in IDENTITY_FIELDS}


def batch_identity_tokens(targets):
    """Allow a reviewed buggy/fixed control pair, never an alias duplicate."""
    tokens, prior = set(), []
    for target in targets:
        identity = target.get("identity", target)
        current = identity_tokens(identity)
        for old, old_tokens in prior:
            if not current & old_tokens:
                continue
            old_identity = old.get("identity", old)
            pair = (target.get("control_group") and target.get("control_group") == old.get("control_group")
                    and {target.get("evaluation_role"), old.get("evaluation_role")} == {"POSITIVE_REPRODUCTION", "CLEAN_CONTROL"}
                    and identity["canonical_function_identity"] != old_identity["canonical_function_identity"]
                    and identity["implementation_sha256"] != old_identity["implementation_sha256"])
            if not pair:
                raise ValueError("overlapping final identities require a distinct buggy/fixed control pair")
        prior.append((target, current)); tokens.update(current)
    return tokens


class UsageLedger:
    def __init__(self, authority_path, *, authority_id=None):
        self.path = Path(authority_path).resolve()
        self.authority_id = authority_id or digest({"fixed_authority_path": str(self.path)})
        if not re.fullmatch(r"[a-f0-9]{64}", self.authority_id):
            raise ValueError("fixed host authority identity required")

    @contextmanager
    def _exclusive(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_name(self.path.name + ".lock")
        with lock.open("x", encoding="utf-8") as handle:
            handle.write(self.authority_id); handle.flush(); os.fsync(handle.fileno())
        try:
            yield
        finally:
            lock.unlink()

    def inspect(self):
        rows, previous, starts, completed, consumed = [], None, {}, set(), set()
        if self.path.exists():
            raw = self.path.read_bytes()
            if raw and not raw.endswith(b"\n"):
                raise ValueError("interrupted usage append lacks terminal newline")
            for raw_line in raw.split(b"\n")[:-1]:
                line = raw_line.decode("utf-8")
                row = json.loads(line)
                if canonical(row) != line:
                    raise ValueError("usage ledger requires canonical append bytes")
                keys(row, ("event", "claim_id", "authority_id", "previous_sha256", "payload", "receipt_sha256"))
                if row["previous_sha256"] != previous or row["authority_id"] != self.authority_id:
                    raise ValueError("usage authority or append chain mismatch")
                if row["receipt_sha256"] != digest({k:v for k,v in row.items() if k != "receipt_sha256"}):
                    raise ValueError("usage receipt mismatch")
                claim = row["claim_id"]
                if row["event"] == "START":
                    if claim in starts:
                        raise ValueError("duplicate usage START")
                    identities = row["payload"]["target_identities"]
                    if not identities:
                        raise ValueError("empty final claim")
                    targets = row["payload"]["targets"]
                    if [t["identity"] for t in targets] != identities:
                        raise ValueError("final identity metadata mismatch")
                    tokens = batch_identity_tokens(targets)
                    if tokens & consumed:
                        raise ValueError("repeated final identity in usage ledger")
                    consumed.update(tokens); starts[claim] = row
                elif row["event"] == "COMPLETE":
                    if claim not in starts or claim in completed:
                        raise ValueError("unmatched final completion")
                    completed.add(claim)
                else:
                    raise ValueError("unsupported usage event")
                previous = row["receipt_sha256"]; rows.append(row)
        return {"authority_id":self.authority_id, "rows":deepcopy(rows),
                "consumed_tokens":sorted(consumed), "receipt_sha256":previous,
                "open_claim_ids":sorted(set(starts)-completed)}

    def _append(self, event, claim_id, payload, previous):
        row = dict(event=event, claim_id=claim_id, authority_id=self.authority_id,
                   previous_sha256=previous, payload=payload)
        row["receipt_sha256"] = digest(row)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical(row) + "\n"); handle.flush(); os.fsync(handle.fileno())
        return row

    def claim(self, targets, authorization_receipt, *, output=None):
        """Called only after the runner reauthorizes its live readiness object.

        The receipt is an integrity binding, not self-authenticating permission.
        The runner owns the fixed authority configuration and execution gate.
        """
        if authorization_receipt.get("status") != "PASS":
            raise PermissionError("readiness authorization required")
        if authorization_receipt.get("bindings", {}).get("authority_id") != self.authority_id:
            raise PermissionError("readiness authority differs")
        entries = [{"identity":deepcopy(t.get("identity", t)), "evaluation_role":t.get("evaluation_role"),
                    "control_group":t.get("control_group")} for t in targets]
        identities = [t["identity"] for t in entries]
        tokens = batch_identity_tokens(entries)
        if not identities:
            raise PermissionError("empty final batch")
        payload = {"target_identities":identities, "targets":entries, "authorization_sha256":digest(authorization_receipt),
                   "output":str(Path(output).resolve()) if output is not None else None}
        claim_id = digest(payload)
        with self._exclusive():
            state = self.inspect()
            if tokens & set(state["consumed_tokens"]):
                raise PermissionError("final identity already consumed, including interrupted START")
            return self._append("START", claim_id, payload, state["receipt_sha256"])

    def complete(self, claim_id, summary):
        with self._exclusive():
            state = self.inspect()
            if claim_id not in state["open_claim_ids"]:
                raise ValueError("usage claim is not open")
            return self._append("COMPLETE", claim_id, json.loads(canonical(summary)), state["receipt_sha256"])
