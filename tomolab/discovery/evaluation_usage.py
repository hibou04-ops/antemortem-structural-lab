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

    def claim_corroboration(self, permits, expected_contexts, *, output=None):
        """Consume reviewed identities as CORR without fabricating final PASS.

        The same authority's existing final readiness/claim path sees these
        START tokens. The permit has no final, publication or feedback power.
        Interrupted development reservations remain consumed as before.
        """
        from .corroboration_permit import CorroborationExecutionPermit, SCOPE
        if not isinstance(permits, (list, tuple)) or not permits or len(permits) != len(expected_contexts):
            raise PermissionError("matching reviewed CORR permits and external approvals required")
        entries, seen = [], set()
        for permit, expected in zip(permits, expected_contexts):
            if not isinstance(permit, CorroborationExecutionPermit):
                raise PermissionError("CORR reservation does not accept final readiness receipts")
            permit.validate(expected)
            context = permit.context
            if context["authority_id"] != self.authority_id:
                raise PermissionError("CORR permit and fixed host usage authority differ")
            identity = context["approved_implementation_identity"]["usage_identity"]
            token = digest(identity)
            if token not in seen:
                entries.append(dict(identity=deepcopy(identity),evaluation_role="CORROBORATION_DEVELOPMENT",control_group=None))
                seen.add(token)
        tokens = batch_identity_tokens(entries)
        permit_digests = [permit.permit_digest for permit in permits]
        if len(set(permit_digests)) != len(permit_digests):
            raise ValueError("duplicate CORR plan approvals in one reservation")
        payload = dict(scope=SCOPE,authorization_kind="EXTERNALLY_APPROVED_CORR_PERMIT_NOT_FINAL_READINESS",
            target_identities=[entry["identity"] for entry in entries],targets=entries,
            permit_digests=permit_digests,authorization_sha256=digest(expected_contexts),
            output=str(Path(output).resolve()) if output is not None else None,
            final_evaluation_authorized=False,publication_authorized=False,feedback_to_generator=False)
        claim_id = digest(payload)
        with self._exclusive():
            state = self.inspect()
            if tokens & set(state["consumed_tokens"]):
                raise PermissionError("CORR identity was already consumed in this fixed usage authority")
            return self._append("START",claim_id,payload,state["receipt_sha256"])

    def claim_experimental(self, targets, profile, *, expected_profile, output=None):
        """Reserve algorithm-frozen, target-local online development.

        The external host supplies the expected registration. This extension
        does not reinterpret an E8 permit or a final-readiness receipt. Its
        tokens use the same append-only authority as CORR and final claims.
        """
        required = {"schema", "scope", "authority_id", "algorithm_digest",
                    "initial_knowledge_digest", "configuration_digest",
                    "target_local_feedback", "cross_target_feedback",
                    "final_evaluation_authorized", "publication_authorized"}
        if (not isinstance(profile, dict) or set(profile) != required
                or profile != expected_profile
                or profile["schema"] != "tomolab-online-execution-profile-v1"
                or profile["scope"] != "EXPERIMENTAL_PROBE"
                or profile["authority_id"] != self.authority_id
                or profile["target_local_feedback"] is not True
                or any(profile[name] is not False for name in
                       ("cross_target_feedback", "final_evaluation_authorized", "publication_authorized"))):
            raise PermissionError("externally registered target-local experimental profile required")
        for name in ("algorithm_digest", "initial_knowledge_digest", "configuration_digest"):
            if not isinstance(profile[name], str) or not re.fullmatch(r"[a-f0-9]{64}", profile[name]):
                raise ValueError("frozen algorithm, knowledge and configuration identities required")
        entries = [{"identity":deepcopy(t.get("identity", t)),
                    "evaluation_role":t.get("evaluation_role", "EXPERIMENTAL_PROBE"),
                    "control_group":t.get("control_group")} for t in targets]
        if not entries:
            raise ValueError("empty experimental reservation")
        tokens = batch_identity_tokens(entries)
        payload = dict(profile=deepcopy(profile), target_identities=[t["identity"] for t in entries],
                       targets=entries, output=str(Path(output).resolve()) if output is not None else None,
                       final_evaluation_authorized=False, publication_authorized=False)
        claim_id = digest(payload)
        with self._exclusive():
            state = self.inspect()
            if tokens & set(state["consumed_tokens"]):
                raise PermissionError("experimental identity already consumed in this fixed authority")
            return self._append("START", claim_id, payload, state["receipt_sha256"])

    def complete(self, claim_id, summary):
        with self._exclusive():
            state = self.inspect()
            if claim_id not in state["open_claim_ids"]:
                raise ValueError("usage claim is not open")
            return self._append("COMPLETE", claim_id, json.loads(canonical(summary)), state["receipt_sha256"])
