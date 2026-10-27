"""Four-way, role/action/contract transfer of frozen relational state molds."""
from copy import deepcopy
import re

from .schema import canonical, digest, identifier, integer, keys, type_subset, validate_spec
from .temporal import (normalize_temporal_evidence, simulate_trace, temporal_holds,
                       trace_layout, validate_temporal_contract)
from .temporal_engine import TemporalEngine
from .engine import family_of

STATUSES = {"APPLICABLE_FOR_PROBING", "NOT_APPLICABLE", "UNKNOWN", "CONTRADICTED"}
GATE_FIELDS = ("status", "reasons", "mapping", "source_snapshot_sha256", "source_contract_sha256",
               "target_contract_sha256", "failure_recurrence", "source_evidence_ids",
               "target_contradictions", "transferred_relations", "static_ir_status", "claim")


def validate_temporal_gate(gate):
    keys(gate, GATE_FIELDS)
    if gate["status"] not in STATUSES or gate["failure_recurrence"] != "UNKNOWN":
        raise ValueError("unsupported temporal transfer status")
    for key in ("source_snapshot_sha256", "source_contract_sha256", "target_contract_sha256"):
        if not isinstance(gate[key], str) or not re.fullmatch(r"[a-f0-9]{64}", gate[key]):
            raise ValueError("invalid transfer digest")
    if not isinstance(gate["mapping"], dict) or len(gate["mapping"]) > 64:
        raise ValueError("bounded declared mapping required")
    for a, b in gate["mapping"].items():
        identifier(a); identifier(b)
    for key in ("reasons", "source_evidence_ids"):
        if not isinstance(gate[key], list) or len(gate[key]) > 8192:
            raise ValueError("bounded provenance lists required")
        for value in gate[key]:
            identifier(value)
    if not isinstance(gate["target_contradictions"], list) or len(gate["target_contradictions"]) > 4096:
        raise ValueError("bounded target contradictions required")
    for row in gate["target_contradictions"]:
        keys(row, ("family_id", "constraint_id", "evidence_id"))
        parts = row["family_id"].split("/")
        if len(parts) != 3:
            raise ValueError("invalid contradiction family")
        for value in [*parts, row["constraint_id"], row["evidence_id"]]:
            identifier(value)
    integer(gate["transferred_relations"], 0, 100000)
    if gate["static_ir_status"] not in {"ABSENT", "NOT_TRANSFERRED", "VALIDATED_PUBLIC_IR"}:
        raise ValueError("unsupported static IR provenance")
    if gate["claim"] != "STRUCTURAL_PROBES_ONLY_RECURRENCE_UNKNOWN":
        raise ValueError("unsupported transfer claim")
    return deepcopy(gate)


def _shape(contract):
    return {"state": sorted(({k: deepcopy(v) for k, v in state.items() if k not in {"name", "type"}}
                              for state in contract["state"]), key=lambda v: v["role"]),
            "actions": sorted(({k: deepcopy(v) for k, v in action.items() if k != "name"}
                                for action in contract["actions"]), key=lambda v: v["role"]),
            "invariants": sorted(contract["invariants"], key=lambda v: v["id"]),
            "disabled_action": contract.get("disabled_action", "REJECT")}


def _mapping(source_spec, target_spec, source_contract, target_contract):
    pairs = [(source_spec["inputs"][0]["name"], target_spec["inputs"][0]["name"])]
    for field in ("state", "actions"):
        targets = {item["role"]: item["name"] for item in target_contract[field]}
        pairs.extend((item["name"], targets[item["role"]]) for item in source_contract[field] if item["role"] in targets)
    result = {}
    for a, b in pairs:
        if a in result and result[a] != b:
            raise ValueError("ambiguous names require disjoint projection/action names")
        result[a] = b
    return result


def transfer_temporal(snapshot, target_spec, temporal_contract, *, budget=64, seed=7, pool_size=128,
                      strategy="integrated", mapping=None, target_evidence=(), target_ir=None,
                      candidate_pool=None):
    """Plan with a fresh engine; target callbacks/final labels are never accepted."""
    source = TemporalEngine.from_snapshot(snapshot)
    if not source.frozen:
        raise ValueError("source temporal mold must be frozen")
    target_spec = validate_spec(target_spec)
    target_contract = validate_temporal_contract(temporal_contract, target_spec)
    integer(budget, 1, 4096)
    expected = _mapping(source.spec, target_spec, source.temporal_contract, target_contract)
    if mapping is not None:
        if not isinstance(mapping, dict):
            raise ValueError("explicit mapping must be a declared-name dictionary")
        for a, b in mapping.items():
            identifier(a); identifier(b)
    reasons = []
    source_states = {s["role"]: s for s in source.temporal_contract["state"]}
    target_states = {s["role"]: s for s in target_contract["state"]}
    source_actions = {a["role"] for a in source.temporal_contract["actions"]}
    target_actions = {a["role"] for a in target_contract["actions"]}
    if source_states.keys() != target_states.keys() or source_actions != target_actions:
        reasons.append("state-or-action-role-mismatch")
    for role in source_states.keys() & target_states.keys():
        if not type_subset(target_states[role]["type"], source_states[role]["type"]):
            reasons.append("state-type-or-domain-mismatch")
    source_name, _, source_arg = trace_layout(source.spec)
    target_name, _, target_arg = trace_layout(target_spec)
    if source.spec["inputs"][0]["role"] != target_spec["inputs"][0]["role"] or not type_subset(target_arg, source_arg):
        reasons.append("trace-role-or-argument-domain-mismatch")
    source_trace, target_trace = source.spec["inputs"][0]["type"], target_spec["inputs"][0]["type"]
    if not source_trace["min_size"] <= target_trace["min_size"] <= target_trace["max_size"] <= source_trace["max_size"]:
        reasons.append("trace-length-domain-mismatch")
    for key in ("id", "operation", "preconditions", "invariants", "state_model"):
        if source.spec["contract"][key] != target_spec["contract"][key]:
            reasons.append("declared-contract-mismatch")
    if _shape(source.temporal_contract) != _shape(target_contract):
        reasons.append("state-transition-or-invariant-mismatch")
    if mapping is not None and mapping != expected:
        reasons.append("declared-name-mapping-mismatch")
    static_status = "ABSENT" if source.public_ir is None else "NOT_TRANSFERRED"
    if target_ir is not None:
        from .predicates import validate_public_ir
        validate_public_ir(target_ir, target_spec)
        static_status = "VALIDATED_PUBLIC_IR"
    if not isinstance(target_evidence, (list, tuple)) or len(target_evidence) > 256:
        raise ValueError("at most 256 approved target development evidence records")
    evidence = [normalize_temporal_evidence(event, target_spec, target_contract) for event in target_evidence]
    ids = [e["evidence_id"] for e in evidence]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate target evidence ID")
    labels = {}
    inconsistent = False
    for event in evidence:
        key = (canonical(event["inputs"]), event["invariant"])
        label = (event["kind"], event["signature"] if event["kind"] == "FAILURE" else None,
                 event["first_failure_index"])
        if key in labels and labels[key] != label:
            inconsistent = True
        labels[key] = label
    gate = {"status": "NOT_APPLICABLE" if reasons else "UNKNOWN", "reasons": sorted(set(reasons)),
            "mapping": expected, "source_snapshot_sha256": snapshot["receipt"]["sha256"],
            "source_contract_sha256": digest(source.temporal_contract), "target_contract_sha256": digest(target_contract),
            "failure_recurrence": "UNKNOWN", "source_evidence_ids": sorted(source._ids),
            "target_contradictions": [], "transferred_relations": 0,
            "static_ir_status": static_status, "claim": "STRUCTURAL_PROBES_ONLY_RECURRENCE_UNKNOWN"}
    families = []
    if not reasons and not source.inconsistent and not inconsistent:
        for family_id, group in source.groups.items():
            remaining = group["remaining"] & source.temporal_relations
            if not group["support"]:
                continue
            survivors = set(remaining)
            for event in evidence:
                if event["invariant"] != group["invariant"]:
                    continue
                replay = simulate_trace(event["inputs"], target_spec, target_contract)
                positive = event["kind"] == "FAILURE" and family_of(event) == family_id
                for rid in list(survivors):
                    if temporal_holds(source.relations[rid], replay, event["first_failure_index"]) != positive:
                        survivors.remove(rid)
                        gate["target_contradictions"].append({"family_id": family_id, "constraint_id": rid,
                                                               "evidence_id": event["evidence_id"]})
            if survivors:
                families.append({"family_id": family_id, "invariant": group["invariant"],
                                 "relation_ids": sorted(survivors), "evidence_ids": list(group["support"])})
        gate["transferred_relations"] = sum(len(f["relation_ids"]) for f in families)
        gate["status"] = ("APPLICABLE_FOR_PROBING" if families else
                          "CONTRADICTED" if gate["target_contradictions"] else "UNKNOWN")
    elif not reasons:
        gate["reasons"].append("inconsistent-development-evidence")
    validate_temporal_gate(gate)
    engine = TemporalEngine(target_spec, target_contract, seed=seed, budget=budget,
        pool_size=pool_size, strategy=strategy, candidate_pool=candidate_pool, public_ir=target_ir)
    if families:
        engine.install_temporal_prior({"families": families, "source_snapshot_sha256": gate["source_snapshot_sha256"]}, gate)
    engine.freeze()
    candidates = []
    for _ in range(budget):
        try:
            proposal = engine.propose()
            if proposal is None:
                break
            candidates.append(proposal)
        except ValueError as error:
            if "exhausted" not in str(error):
                raise
            break
    return {"schema": "tomolab-temporal-plan-v1", "gate": gate, "candidates": candidates,
            "candidate_sha256": digest([p["inputs"] for p in candidates]), "snapshot": engine.snapshot(),
            "final_feedback_allowed": False, "source_snapshot_sha256": gate["source_snapshot_sha256"],
            "bug_recurrence": "UNKNOWN"}


# Familiar name for callers of E5's transfer API; implementation is shared.
transfer = transfer_temporal
