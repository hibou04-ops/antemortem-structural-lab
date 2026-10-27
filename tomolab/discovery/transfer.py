"""Pure structural transfer validation, with no source/file execution API."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _annotation_matches(annotation, declared):
    if annotation == "UNKNOWN":
        # A missing annotation is not inferred; the public contract supplies it.
        return True
    if isinstance(annotation, str):
        return annotation == declared["kind"]
    if not isinstance(annotation, dict):
        return False
    if annotation.get("kind") != declared["kind"]:
        return False
    parts = annotation.get("items", [])
    if declared["kind"] == "list":
        return len(parts) == 1 and _annotation_matches(parts[0], declared["items"])
    if declared["kind"] == "dict":
        return len(parts) == 2 and parts[0] == "str" and _annotation_matches(parts[1], declared["values"])
    if declared["kind"] == "tuple":
        return len(parts) == len(declared["items"]) and all(_annotation_matches(a,t) for a,t in zip(parts,declared["items"]))
    return False


def validate_transfer(source_spec, target_spec, source_ir, target_ir, mapping=None):
    """Validate declared typed/graph correspondence; never certify recurrence."""
    from .schema import validate_spec, type_subset
    source_spec, target_spec = validate_spec(source_spec), validate_spec(target_spec)
    left = {item["role"]: item for item in source_spec["inputs"]}
    right = {item["role"]: item for item in target_spec["inputs"]}
    expected = {left[role]["name"]: right[role]["name"] for role in left.keys() & right.keys()}
    reasons = []
    if left.keys() != right.keys() or (mapping is not None and mapping != expected):
        reasons.append("semantic roles must correspond bijectively")
    for role in left.keys() & right.keys():
        if not type_subset(right[role]["type"], left[role]["type"]):
            reasons.append(f"type/domain mismatch: {role}")
    for key in ("id", "operation", "preconditions", "invariants", "state_model"):
        if source_spec["contract"][key] != target_spec["contract"][key]:
            reasons.append(f"contract mismatch: {key}")
    for spec, ir in ((source_spec, source_ir), (target_spec, target_ir)):
        if not isinstance(ir, dict) or ir.get("schema") != "tomolab-structural-ir-v1":
            reasons.append("approved structural IR missing")
            continue
        from .predicates import validate_public_ir
        try:
            validate_public_ir(ir,spec)
        except ValueError:
            reasons.append("public IR validation failed")
            continue
        if ir.get("semantic_roles") != "DECLARED" or ir.get("status") != "SUPPORTED_STATIC_IR":
            reasons.append("unsupported or undeclared structural IR")
        if _digest(ir.get("graph")) != ir.get("graph_signature"):
            reasons.append("IR graph digest mismatch")
        if ir.get("graph_signature") != spec["contract"]["graph_signature"]:
            reasons.append("contract graph does not match approved IR")
        if {p.get("name"):p.get("role") for p in ir.get("parameters", [])} != {p["name"]:p["role"] for p in spec["inputs"]}:
            reasons.append("IR parameter roles differ from declared contract")
        declared = {p["name"]:p["type"] for p in spec["inputs"]}
        for parameter in ir.get("parameters", []):
            if parameter.get("name") in declared and not _annotation_matches(parameter.get("annotation", "UNKNOWN"), declared[parameter["name"]]):
                reasons.append("source annotation contradicts public type contract")
    if source_spec["contract"]["graph_signature"] == "UNKNOWN" or source_spec["contract"]["graph_signature"] != target_spec["contract"]["graph_signature"]:
        reasons.append("operation graph correspondence not established")
    if isinstance(source_ir,dict) and isinstance(target_ir,dict):
        if sorted(json.dumps(p,sort_keys=True) for p in source_ir.get("predicates",[])) != sorted(json.dumps(p,sort_keys=True) for p in target_ir.get("predicates",[])):
            reasons.append("public predicate constants or operation relations differ")
    return {"status": "UNKNOWN" if reasons else "APPLICABLE_FOR_PROBING", "reasons": reasons,
            "mapping": deepcopy(expected), "source_contract_sha256": _digest(source_spec),
            "target_contract_sha256": _digest(target_spec), "failure_recurrence": "UNKNOWN",
            "claim": "declared contracts and literal-free syntactic graph permit probes only"}
