"""Data-only runtime validation and selection for compact empirical Molds.

Source learning and Oracle modules are deliberately absent. The pinned semantic
version is compared with the host claim contract by regression tests; unknown
public structural features cannot authorize an edit or become counterevidence.
"""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re

from .schema import canonical, digest

MOLD_SCHEMA = "tomolab-online-mold-v1"
SEMANTIC_VERSION = "e8-r1-claims-v1"
EMPIRICAL = "EMPIRICAL_SEARCH_GUIDANCE"
MAX_MOLD_BYTES = 10 * 1024
MAX_OBSERVATIONS = 1024
MAX_RULES = 12
PRECONDITIONS = {"size_class", "all_equal", "has_negative"}


def _features(point):
    """Public input structure only; no numeric literals become rule constants."""
    result = {}
    if type(point) in (list, dict, str):
        result["size_class"] = "EMPTY" if not point else "SINGLETON" if len(point) == 1 else "MANY"
    if type(point) is list and point and all(type(x) in (int, float, str) for x in point):
        result["all_equal"] = all(x == point[0] for x in point)
    if type(point) in (int, float) and type(point) is not bool:
        result["has_negative"] = point < 0
    elif type(point) is list and point and all(type(x) in (int, float) for x in point):
        result["has_negative"] = any(x < 0 for x in point)
    return result


def _matches(point, preconditions):
    features = _features(point)
    values = [features.get(name) == value if name in features else None
              for name, value in preconditions.items()]
    return False if False in values else None if None in values else True


def validate_mold(mold, *, expected_digest=None):
    """Integrity and scope validation; a hash does not confer execution rights."""
    from .online_schema import common_operators, KINDS
    if not isinstance(mold, dict) or mold.get("schema_version") != MOLD_SCHEMA:
        raise ValueError("unsupported online Mold schema")
    required = {"schema_version", "semantic_contract_version", "usage_scope", "claim_kind", "algorithm",
        "source_observation_digest", "source_summary", "rules", "omitted_rules", "max_bytes",
        "final_target_authorized", "publication_authorized", "artifact_digest"}
    if mold.keys() != required:
        raise ValueError("execution Mold fields must be data-only and explicitly bounded")
    if mold.get("semantic_contract_version") != SEMANTIC_VERSION or mold.get("claim_kind") != EMPIRICAL:
        raise ValueError("online Mold preserves empirical three-valued claim semantics")
    if mold.get("usage_scope") != "EXPERIMENTAL_PROBE" or mold.get("final_target_authorized") is not False or mold.get("publication_authorized") is not False:
        raise PermissionError("an empirical Mold does not grant final or publication authority")
    observed = digest({key: value for key, value in mold.items() if key != "artifact_digest"})
    if observed != mold.get("artifact_digest") or expected_digest is not None and observed != expected_digest:
        raise ValueError("online Mold differs from the externally expected digest")
    limit = mold.get("max_bytes")
    if type(limit) is not int or not 512 <= limit <= MAX_MOLD_BYTES or len(canonical(mold).encode())+1 > limit:
        raise ValueError("online execution Mold exceeds the configured 10KiB ceiling")
    summary = mold.get("source_summary")
    if not isinstance(summary, dict) or summary.keys() != {"observations", "failure_observations", "unknown_observations", "matched_pairs", "unpaired_failures"}:
        raise ValueError("bounded Source summary required")
    if any(type(value) is not int or not 0 <= value <= MAX_OBSERVATIONS**2 for value in summary.values()):
        raise ValueError("invalid Source count")
    if type(mold.get("omitted_rules")) is not int or mold["omitted_rules"] < 0:
        raise ValueError("invalid omitted rule count")
    if not isinstance(mold.get("source_observation_digest"), str) or not re.fullmatch("[a-f0-9]{64}", mold["source_observation_digest"]):
        raise ValueError("Source observation identity required")
    rules = mold.get("rules")
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise ValueError("bounded online rules required")
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("claim_kind") != EMPIRICAL:
            raise ValueError("bounded empirical edit rule required")
        fields = {"kind", "operator_schema", "typed_roles", "preconditions", "edit_composition",
            "source_support", "counterevidence", "applicability", "uncertainty", "claim_kind",
            "semantic_support", "selection_statistics", "provenance", "source_support_digest",
            "counterevidence_digest", "rule_id"}
        if rule.keys() != fields or rule.get("operator_schema") != "COMMON_PRIOR_TYPED_EDITS_V1":
            raise ValueError("unsupported learned rule fields or operator schema")
        if rule.get("kind") not in KINDS:
            raise ValueError("unsupported learned input kind")
        operators = common_operators(rule["kind"])
        if rule.get("typed_roles") != [dict(role="input", kind=rule["kind"])]:
            raise ValueError("only the reviewed single public input role is supported")
        if rule.get("applicability") != "EMPIRICAL_INPUT_STRUCTURE_ONLY" or rule.get("uncertainty") != "UNKNOWN_OUTSIDE_RECORDED_SOURCE_SUPPORT" or rule.get("semantic_support") is not True:
            raise ValueError("empirical rules cannot imply universal failure or causality")
        edits = rule.get("edit_composition")
        if not isinstance(edits, list) or not 1 <= len(edits) <= 2 or any(operator not in operators for operator in edits):
            raise ValueError("unsupported common edit composition")
        predicates = rule.get("preconditions")
        if not isinstance(predicates, dict) or predicates.keys()-PRECONDITIONS:
            raise ValueError("only reviewed public structural preconditions are supported")
        for name, value in predicates.items():
            if name == "size_class" and value not in ("EMPTY", "SINGLETON", "MANY") or name != "size_class" and type(value) is not bool:
                raise ValueError("invalid structural precondition value")
        stats = rule.get("selection_statistics")
        if not isinstance(stats, dict) or stats.keys() != {"support", "counterevidence", "applicable_counterevidence", "empirical_score"}:
            raise ValueError("bounded empirical selection statistics required")
        if any(type(stats[name]) is not int or not 0 <= stats[name] <= MAX_OBSERVATIONS**2 for name in ("support", "counterevidence", "applicable_counterevidence")) or stats["support"] == 0:
            raise ValueError("a learned rule requires observed Source support")
        score = stats["empirical_score"]
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 < score <= 1 or score != stats["support"]/(stats["support"]+stats["applicable_counterevidence"]+1):
            raise ValueError("selection score differs from recorded counts")
        expected_provenance = ["COMMON_PRIOR", "SOURCE_LEARNED_SELECTION"] + (["SOURCE_LEARNED_COMPOSITION"] if len(edits) == 2 else []) + (["SOURCE_LEARNED_APPLICABILITY"] if predicates else [])
        if rule.get("provenance") != expected_provenance:
            raise ValueError("operator prior and learned provenance differ")
        for name in ("source_support", "counterevidence"):
            values = rule.get(name)
            if not isinstance(values, list) or len(values) > 2 or any(not isinstance(value, str) or not re.fullmatch("[a-f0-9]{64}", value) for value in values):
                raise ValueError("only bounded evidence digest samples belong in the execution Mold")
        for name in ("source_support_digest", "counterevidence_digest"):
            if not isinstance(rule.get(name), str) or not re.fullmatch("[a-f0-9]{64}", rule[name]):
                raise ValueError("complete evidence-set digest required")
        if rule.get("rule_id") != digest({key: value for key, value in rule.items() if key != "rule_id"}):
            raise ValueError("learned rule identity changed")
    return deepcopy(mold)


def applicable_rules(mold, point, contract):
    validate_mold(mold)
    return [deepcopy(rule) for rule in mold["rules"]
            if rule["kind"] == contract["kind"] and _matches(point, rule["preconditions"]) is True]


def select_edit(mold, point, contract, rng):
    """Select only among supported rules; target-local state lives in the caller."""
    rules = applicable_rules(mold, point, contract)
    if not rules:
        return None
    weights = [rule["selection_statistics"]["empirical_score"] for rule in rules]
    rule = rng.choices(rules, weights=weights, k=1)[0]
    return dict(rule_id=rule["rule_id"], operators=list(rule["edit_composition"]),
                provenance=list(rule["provenance"]))


def save_mold(path, mold):
    validate_mold(mold)
    path = Path(path)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical(mold)+"\n"); stream.flush(); os.fsync(stream.fileno())
    return dict(artifact_digest=mold["artifact_digest"], serialized_bytes=path.stat().st_size)


def load_mold(path, *, expected_digest):
    path = Path(path)
    if path.stat().st_size > MAX_MOLD_BYTES+1:
        raise ValueError("execution Mold exceeds the 10KiB ceiling")
    return validate_mold(json.loads(path.read_text(encoding="utf-8")), expected_digest=expected_digest)
