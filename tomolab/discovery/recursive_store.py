"""Trusted-host append-only selector generations, separate from E7 claims.

Locks coordinate cooperating writers.  A broken final append is preserved and
rejected; this is not a distributed transaction or adversarial-host boundary.
"""
from copy import deepcopy
import json
import math
import os
from pathlib import Path

from .recursive_policy import (ALGORITHM, ALGORITHM_DIGEST, SELECTOR_SCHEMA, RUNTIME_SELECTOR_SCHEMA,
    MANIFEST_SCHEMA, _sha, validate_selector, validate_development_manifest)
from .schema import canonical, digest, identifier, keys

GENERATION_SCHEMA = "tomolab-selector-generation-v1"
STORE_SCHEMA = "tomolab-selector-store-v1"
MAX_STORE_BYTES = 64 * 1024 * 1024
MAX_GENERATIONS = 256
COST_FIELDS = ("target_calls", "oracle_calls", "reset_calls", "observation_wall_seconds",
               "learning_seconds", "validation_seconds", "io_seconds")
GENERATION_FIELDS = ("schema", "generation_id", "parent_generation_id", "parent_generation_digest",
    "update_algorithm_version", "update_algorithm_digest", "mold_digest", "input_contract_digest",
    "related_schema_versions", "consumed_development_manifest", "consumed_paired_receipts", "new_paired_receipts",
    "selector", "cost_ledger", "candidate_validation", "e7_linkage", "sha256")


def _cost_floor(selector):
    rows = selector["evidence"]
    return dict(target_calls=sum(row["cost"]["target_calls"] for row in rows),
        oracle_calls=sum(row["cost"]["oracle_calls"] for row in rows),
        reset_calls=sum(row["cost"]["reset_calls"] for row in rows),
        observation_wall_seconds=sum(row["cost"]["wall_seconds"] for row in rows),
        learning_seconds=0.0, validation_seconds=0.0, io_seconds=0.0)


def _validate_cost(cost, selector):
    keys(cost, COST_FIELDS)
    floor = _cost_floor(selector)
    for name in COST_FIELDS:
        value = cost[name]
        if name.endswith("calls"):
            if type(value) is not int or value < floor[name]:
                raise ValueError("generation cost cannot erase observed calls")
        elif type(value) not in (int, float) or not math.isfinite(value) or value < floor[name]:
            raise ValueError("generation cost cannot erase observed time")


def _validate_e7(link):
    if not isinstance(link, dict):
        raise ValueError("explicit E7 linkage status required")
    if link.get("status") == "E7_LINKAGE_UNKNOWN":
        keys(link, ("status",))
    elif link.get("status") == "REVIEWED_E7_ARCHIVE_RECEIPT":
        keys(link, ("status", "record_id", "store_receipt_sha256", "snapshot_sha256"))
        identifier(link["record_id"])
        _sha(link["store_receipt_sha256"]); _sha(link["snapshot_sha256"])
    else:
        raise ValueError("unsupported E7 linkage; selector scores do not confer semantic authority")


def record_e7_linkage(store, frozen_snapshot, *, record_id):
    """Reuse the existing E7 validator/store; never fabricate rule-to-claim IDs."""
    from .knowledge import KnowledgeArchive
    from .knowledge_store import KnowledgeStore
    if not isinstance(store, KnowledgeStore):
        raise TypeError("the reviewed existing E7 KnowledgeStore is required")
    archive = KnowledgeArchive.from_snapshot(frozen_snapshot)
    if not archive.frozen:
        raise ValueError("E7 linkage requires a frozen archive")
    receipt = store.append(frozen_snapshot, record_id=record_id)
    return dict(status="REVIEWED_E7_ARCHIVE_RECEIPT", record_id=record_id,
        store_receipt_sha256=receipt["sha256"], snapshot_sha256=digest(frozen_snapshot))


def validate_generation(generation):
    keys(generation, GENERATION_FIELDS)
    if generation["schema"] != GENERATION_SCHEMA:
        raise ValueError("unsupported selector generation schema")
    identifier(generation["generation_id"])
    if generation["parent_generation_id"] is None:
        if generation["parent_generation_digest"] is not None:
            raise ValueError("root generation has no parent digest")
    else:
        identifier(generation["parent_generation_id"])
        _sha(generation["parent_generation_digest"])
        if generation["parent_generation_id"] == generation["generation_id"]:
            raise ValueError("generation cannot parent itself")
    if (generation["update_algorithm_version"] != ALGORITHM
            or generation["update_algorithm_digest"] != ALGORITHM_DIGEST):
        raise ValueError("generation update algorithm differs")
    selector = validate_selector(generation["selector"], mold_digest=generation["mold_digest"])
    if selector["schema"] != SELECTOR_SCHEMA:
        raise ValueError("generation requires complete host selector experience")
    if generation["input_contract_digest"] != selector["input_contract_digest"]:
        raise ValueError("generation input contract differs from selector")
    expected_versions = dict(selector=SELECTOR_SCHEMA, runtime_selector=RUNTIME_SELECTOR_SCHEMA, development_manifest=MANIFEST_SCHEMA,
                             paired_receipt="tomolab-paired-receipt-v1")
    if generation["related_schema_versions"] != expected_versions:
        raise ValueError("generation schema bindings differ")
    manifest = generation["consumed_development_manifest"]
    if manifest is not None:
        validate_development_manifest(manifest)
        reviewed = {row["source_lineage_id"]: row for row in manifest["lineages"]}
        for evidence in selector["evidence"]:
            if evidence["manifest_digest"] != manifest["manifest_digest"]:
                continue
            lineage = reviewed.get(evidence["source_lineage_id"])
            if lineage is None or any(evidence[name] != lineage[name] for name in (
                    "project_id", "mechanism_id", "independence_id", "implementation_sha256",
                    "oracle_sha256", "input_contract_sha256")):
                raise ValueError("generation experience differs from reviewed lineage manifest")
            if evidence["evidence_class"] != manifest["evidence_class"]:
                raise ValueError("generation cannot relabel synthetic experience as real")
    receipts = generation["consumed_paired_receipts"]
    expected_receipts = [dict(reservation_id=row["reservation_id"],
        pair_receipt_sha256=row["pair_receipt_sha256"], manifest_digest=row["manifest_digest"])
        for row in selector["evidence"]]
    if receipts != expected_receipts:
        raise ValueError("generation receipt lineage differs from selector evidence")
    raw_receipts = generation["new_paired_receipts"]
    if not isinstance(raw_receipts, list) or len(raw_receipts) > len(receipts):
        raise ValueError("bounded new paired receipts required")
    seen = set()
    evidence_by_id = {row["reservation_id"]: row for row in selector["evidence"]}
    if raw_receipts:
        from .recursive_observe import validate_pair_receipt
    for receipt in raw_receipts:
        validate_pair_receipt(receipt)
        token = receipt["reservation_id"]
        if token in seen:
            raise ValueError("duplicate raw paired receipt")
        seen.add(token)
        evidence = evidence_by_id.get(token)
        if evidence is None or manifest is None or evidence["manifest_digest"] != manifest["manifest_digest"]:
            raise ValueError("raw paired receipt has no bound development experience")
        if receipt["experiment_contract_sha256"] != manifest["experiment_contract_sha256"]:
            raise ValueError("raw receipt experiment contract differs from manifest")
        for name in ("pair_receipt_sha256", "source_lineage_id", "project_id", "mechanism_id",
                     "input_contract_sha256", "context", "label", "cost"):
            if evidence[name] != receipt[name]:
                raise ValueError("preserved paired receipt differs from selector summary")
        for name in ("implementation_sha256", "oracle_sha256"):
            if evidence[name] != receipt["identity"][name]:
                raise ValueError("preserved paired code identity differs from selector")
        if receipt["mold_digest"] != generation["mold_digest"]:
            raise ValueError("preserved paired Mold identity differs from generation")
    _validate_cost(generation["cost_ledger"], selector)
    validation = generation["candidate_validation"]
    keys(validation, ("status", "reason", "default_adoption"))
    if validation["status"] not in ("FUNCTIONALLY_VALIDATED", "HOLD", "NO_NEW_EXPERIENCE"):
        raise ValueError("explicit candidate validation outcome required")
    if validation["default_adoption"] != "HOLD":
        raise PermissionError("functional validation does not authorize default policy adoption")
    if not isinstance(validation["reason"], str) or not 1 <= len(validation["reason"]) <= 2048:
        raise ValueError("bounded candidate validation reason required")
    _validate_e7(generation["e7_linkage"])
    _sha(generation["sha256"])
    if generation["sha256"] != digest({k: v for k, v in generation.items() if k != "sha256"}):
        raise ValueError("generation digest mismatch")
    # RNG state may arrive as tuples from Python.  Normalize once to the
    # canonical JSON data model so an append/read cycle is identity-preserving.
    return json.loads(canonical(generation))


def _extends(parent, child):
    if child["parent_generation_id"] != parent["generation_id"] or child["parent_generation_digest"] != parent["sha256"]:
        raise ValueError("generation parent identity or digest mismatch")
    for name in ("mold_digest", "input_contract_digest", "update_algorithm_digest"):
        if child[name] != parent[name]:
            raise ValueError("generation cannot replace its frozen learning contract")
    before, after = parent["selector"], child["selector"]
    if after["evidence"][:len(before["evidence"])] != before["evidence"] or len(after["evidence"]) < len(before["evidence"]):
        raise ValueError("generation would discard prior experience or counterevidence")
    old_manifests = before["consumed_manifest_digests"]
    if after["consumed_manifest_digests"][:len(old_manifests)] != old_manifests:
        raise ValueError("generation would discard consumed development manifests")
    new = after["evidence"][len(before["evidence"]):]
    manifest = child["consumed_development_manifest"]
    if new:
        if manifest is None or any(row["manifest_digest"] != manifest["manifest_digest"] for row in new):
            raise ValueError("new experience must bind the preserved development manifest")
    if [row["reservation_id"] for row in child["new_paired_receipts"]] != [row["reservation_id"] for row in new]:
        raise ValueError("every new experience needs its preserved validated paired receipt")
    for name in COST_FIELDS:
        if child["cost_ledger"][name] < parent["cost_ledger"][name]:
            raise ValueError("generation cannot roll back cumulative costs")


def make_generation(generation_id, selector, *, parent=None, development_manifest=None,
                    paired_receipts=None, cost_ledger=None, candidate_validation=None, e7_linkage=None):
    selector = validate_selector(selector)
    if selector["schema"] != SELECTOR_SCHEMA:
        raise ValueError("generation requires complete host selector experience")
    if parent is not None:
        parent = validate_generation(parent)
    elif selector["evidence"]:
        raise ValueError("G0 must have no learned support")
    raw_by_id = {}
    if paired_receipts is not None:
        if not isinstance(paired_receipts, list):
            raise ValueError("paired receipt batch must be a list")
        for row in paired_receipts:
            token = row.get("reservation_id") if isinstance(row, dict) else None
            if token in raw_by_id and raw_by_id[token] != row:
                raise ValueError("conflicting duplicate raw paired receipt")
            raw_by_id[token] = deepcopy(row)
    new_evidence = selector["evidence"][len(parent["selector"]["evidence"]) if parent else 0:]
    if any(row["reservation_id"] not in raw_by_id for row in new_evidence):
        raise ValueError("new generation requires the complete raw paired receipt batch")
    cost = _cost_floor(selector) if cost_ledger is None else deepcopy(cost_ledger)
    if parent is not None and cost_ledger is None:
        # Carry installation/validation/update costs already recorded by parent.
        previous_floor = _cost_floor(parent["selector"])
        for name in COST_FIELDS:
            cost[name] += parent["cost_ledger"][name]-previous_floor[name]
    generation = dict(schema=GENERATION_SCHEMA, generation_id=generation_id,
        parent_generation_id=parent["generation_id"] if parent else None,
        parent_generation_digest=parent["sha256"] if parent else None,
        update_algorithm_version=ALGORITHM, update_algorithm_digest=ALGORITHM_DIGEST,
        mold_digest=selector["mold_digest"], input_contract_digest=selector["input_contract_digest"],
        related_schema_versions=dict(selector=SELECTOR_SCHEMA, runtime_selector=RUNTIME_SELECTOR_SCHEMA, development_manifest=MANIFEST_SCHEMA,
                                     paired_receipt="tomolab-paired-receipt-v1"),
        consumed_development_manifest=deepcopy(development_manifest),
        consumed_paired_receipts=[dict(reservation_id=row["reservation_id"],
            pair_receipt_sha256=row["pair_receipt_sha256"], manifest_digest=row["manifest_digest"])
            for row in selector["evidence"]],
        new_paired_receipts=[raw_by_id[row["reservation_id"]] for row in new_evidence],
        selector=selector, cost_ledger=cost,
        candidate_validation=deepcopy(candidate_validation) if candidate_validation is not None else dict(
            status="HOLD", reason="Explicit experimental use only; real utility not established",
            default_adoption="HOLD"),
        e7_linkage=deepcopy(e7_linkage) if e7_linkage is not None else dict(status="E7_LINKAGE_UNKNOWN"))
    generation["sha256"] = digest(generation)
    generation = validate_generation(generation)
    if parent is not None:
        _extends(parent, generation)
    return generation


class GenerationStore:
    """Canonical JSONL with strict chain replay and exclusive cooperative lock."""
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("generation store must not be a symbolic link")

    def records(self):
        if not self.path.exists():
            return []
        if self.path.is_symlink() or not self.path.is_file() or self.path.stat().st_size > MAX_STORE_BYTES:
            raise ValueError("generation store is not a bounded regular file")
        raw = self.path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            raise ValueError("incomplete generation append; preserve bytes for explicit recovery")
        records, ids, previous, parent = [], set(), "0" * 64, None
        for line in raw.splitlines():
            if len(records) >= MAX_GENERATIONS:
                raise ValueError("generation count cap exceeded")
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError) as error:
                raise ValueError("corrupt generation store") from error
            keys(row, ("schema", "previous_sha256", "generation", "sha256"))
            if line != canonical(row).encode("utf-8"):
                raise ValueError("rewritten or noncanonical generation record")
            if (row["schema"] != STORE_SCHEMA or row["previous_sha256"] != previous
                    or row["sha256"] != digest({k: v for k, v in row.items() if k != "sha256"})):
                raise ValueError("generation append chain mismatch")
            generation = validate_generation(row["generation"])
            if generation["generation_id"] in ids:
                raise ValueError("duplicate generation ID in journal")
            if parent is None:
                if generation["parent_generation_id"] is not None or generation["selector"]["evidence"]:
                    raise ValueError("generation journal must begin with empty G0")
            else:
                _extends(parent, generation)
            parent = generation; ids.add(generation["generation_id"])
            previous = row["sha256"]; records.append(row)
        return records

    def append(self, generation):
        generation = validate_generation(generation)
        if self.path.is_symlink():
            raise ValueError("generation store must not be a symbolic link")
        lock = self.path.with_name(self.path.name + ".lock")
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            records = self.records()
            old = next((row for row in records if row["generation"]["generation_id"] == generation["generation_id"]), None)
            if old is not None:
                if old["generation"] != generation:
                    raise ValueError("generation ID content conflict")
                return dict(status="ALREADY_COMMITTED", generation_id=generation["generation_id"], sha256=old["sha256"])
            if len(records) >= MAX_GENERATIONS:
                raise ValueError("generation count cap exceeded")
            if records:
                _extends(records[-1]["generation"], generation)
            elif generation["parent_generation_id"] is not None or generation["selector"]["evidence"]:
                raise ValueError("generation store must begin with empty G0")
            row = dict(schema=STORE_SCHEMA, previous_sha256=records[-1]["sha256"] if records else "0" * 64,
                       generation=generation)
            row["sha256"] = digest(row)
            encoded = (canonical(row) + "\n").encode("utf-8")
            if (self.path.stat().st_size if self.path.exists() else 0) + len(encoded) > MAX_STORE_BYTES:
                raise ValueError("generation store byte cap exceeded")
            with self.path.open("ab") as output:
                output.write(encoded); output.flush(); os.fsync(output.fileno())
            return dict(status="COMMITTED", generation_id=generation["generation_id"], sha256=row["sha256"])
        finally:
            os.close(fd); lock.unlink()

    def latest(self):
        rows = self.records()
        return deepcopy(rows[-1]["generation"]) if rows else None

    def get(self, generation_id):
        identifier(generation_id)
        row = next((row for row in self.records() if row["generation"]["generation_id"] == generation_id), None)
        if row is None:
            raise ValueError("unknown selector generation")
        return deepcopy(row["generation"])
