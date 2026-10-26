"""Strict public contracts and minimal, oracle-authored counterevidence.

No source, callable, arbitrary expression, score, or natural-language reward is
accepted by this protocol. Contracts describe declared semantics, not proof that
an implementation obeys them.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

SCHEMA = "tomolab-mold-spec-v1"
OPERATIONS = ("integer-addition", "integer-subtraction", "integer-multiplication")


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def exact_keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise ValueError("object has missing or unsupported fields")


def text_id(value, field="identifier"):
    if not isinstance(value, str) or not 1 <= len(value) <= 160 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
        raise ValueError(f"invalid {field}")
    return value


def integer(value, low, high, field="integer"):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{field} must be an integer in [{low}, {high}]")
    return value


def validate_spec(spec):
    exact_keys(spec, ("schema", "task_id", "variables", "operation", "invariant", "semantic_contract"))
    if spec["schema"] != SCHEMA or spec["operation"] not in OPERATIONS:
        raise ValueError("unsupported schema or operation")
    for field in ("task_id", "invariant", "semantic_contract"):
        text_id(spec[field], field)
    if not isinstance(spec["variables"], list) or len(spec["variables"]) != 2:
        raise ValueError("exactly two variables are supported")
    for var in spec["variables"]:
        exact_keys(var, ("name", "role", "type", "low", "high"))
        if not isinstance(var["name"], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", var["name"]):
            raise ValueError("invalid variable name")
        if var["type"] != "int" or var["role"] not in ("left", "right"):
            raise ValueError("only left/right integer roles are supported")
        integer(var["low"], -1000000, 1000000, "lower bound")
        integer(var["high"], var["low"], min(1000000, var["low"] + 64), "upper bound")
    if len({v["name"] for v in spec["variables"]}) != 2 or {v["role"] for v in spec["variables"]} != {"left", "right"}:
        raise ValueError("variable names and roles must be unique")
    return deepcopy(spec)


def roles(spec):
    return {v["role"]: v for v in spec["variables"]}


def point_from_inputs(inputs, spec):
    by_role = roles(spec)
    exact_keys(inputs, [v["name"] for v in spec["variables"]])
    return tuple(integer(inputs[by_role[role]["name"]], by_role[role]["low"],
                         by_role[role]["high"], "input") for role in ("left", "right"))


def point_to_inputs(point, spec):
    by_role = roles(spec)
    return {by_role[role]["name"]: point[i] for i, role in enumerate(("left", "right"))}


def normalize_evidence(evidence, spec):
    """REFUTATION is a checked non-violation, not a scalar success reward.

    It refutes every membership hypothesis predicting the named invariant's
    failure on this queried input. A FAILURE supports membership; neither proves
    causation, completeness, or transfer validity.
    """
    exact_keys(evidence, ("kind", "evidence_id", "inputs", "invariant", "signature"))
    if evidence["kind"] not in ("FAILURE", "REFUTATION"):
        raise ValueError("only structured counterevidence is accepted")
    text_id(evidence["evidence_id"], "evidence_id")
    if evidence["invariant"] != spec["invariant"] or evidence["signature"] != "integer-mismatch":
        raise ValueError("evidence does not match the declared invariant/signature")
    point_from_inputs(evidence["inputs"], spec)
    return deepcopy(evidence)


def default_spec(task_id="public-demo", low=-16, high=16):
    return validate_spec({"schema": SCHEMA, "task_id": task_id,
                          "variables": [{"name": "x", "role": "left", "type": "int", "low": low, "high": high},
                                        {"name": "y", "role": "right", "type": "int", "low": low, "high": high}],
                          "operation": "integer-addition", "invariant": "result-equals-addition",
                          "semantic_contract": "int-add-v1"})
