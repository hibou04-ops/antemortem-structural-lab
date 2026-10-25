"""Finite, typed predicate comparison and evidence-lifting authority.

This interprets data-only expressions, never Python target code. The formal
claim is a supplied interpretation anchor, not an independently verified
translation of the natural-language claim. Relations are pointwise on the
same admissible support, and therefore sufficient to preserve a common
quantifier. They need not be complete for quantified entailment.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import time
from typing import Any

SCHEMA = "c1-contract-v1"
MAX_STATES = 100_000
MAX_VARIABLES = 16
MAX_DEPTH = 32
MAX_NODES = 4_096
MAX_WORK = 5_000_000
MAX_BYTES = 262_144
MAX_INT = 1_000_000_000
MAX_VALUE_BITS = 128


class ContractError(ValueError):
    """Malformed or unsupported data cannot supply logical authority."""


def contract_hash(contract: dict[str, Any]) -> str:
    """Bind evidence to exact JSON meaning with canonical key ordering."""
    raw = json.dumps(contract, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ContractError("CONTRACT_BYTE_LIMIT")
    return hashlib.sha256(raw).hexdigest()


def _fail(reason: str) -> None:
    raise ContractError(reason)


def _fields(value: Any, required: set[str], optional: set[str], name: str) -> None:
    if type(value) is not dict or not required <= value.keys():
        _fail(f"INVALID_{name}_FIELDS")
    if value.keys() - required - optional:
        _fail(f"UNKNOWN_{name}_FIELDS")


def _text(value: Any, name: str) -> None:
    if type(value) is not str or not value.strip():
        _fail(f"INVALID_{name}")


def _type(expr: Any, variables: dict[str, str], count: list[int], depth: int = 0) -> str:
    count[0] += 1
    if count[0] > MAX_NODES or depth > MAX_DEPTH:
        _fail("EXPRESSION_RESOURCE_LIMIT")
    if type(expr) is bool:
        return "bool"
    if type(expr) is int:
        if abs(expr) > MAX_INT:
            _fail("INTEGER_LITERAL_LIMIT")
        return "int"
    if type(expr) is str:
        if expr not in variables:
            _fail("UNDECLARED_VARIABLE")
        return variables[expr]
    if type(expr) is not list or not expr or type(expr[0]) is not str:
        _fail("INVALID_EXPRESSION")
    op, args = expr[0], expr[1:]
    if op in {"and", "or"}:
        if len(args) < 2:
            _fail("INVALID_ARITY")
        expected, result = "bool", "bool"
    elif op == "not":
        if len(args) != 1:
            _fail("INVALID_ARITY")
        expected, result = "bool", "bool"
    elif op == "implies":
        if len(args) != 2:
            _fail("INVALID_ARITY")
        expected, result = "bool", "bool"
    elif op in {"+", "-", "*", "<", "<=", ">", ">="}:
        if len(args) != 2:
            _fail("INVALID_ARITY")
        expected = "int"
        result = "int" if op in {"+", "-", "*"} else "bool"
    elif op in {"==", "!="}:
        if len(args) != 2:
            _fail("INVALID_ARITY")
        left = _type(args[0], variables, count, depth + 1)
        right = _type(args[1], variables, count, depth + 1)
        if left != right:
            _fail("TYPE_MISMATCH")
        return "bool"
    else:
        _fail("UNSUPPORTED_OPERATOR")
    if any(_type(a, variables, count, depth + 1) != expected for a in args):
        _fail("TYPE_MISMATCH")
    return result


def evaluate(expr: Any, environment: dict[str, int | bool]) -> int | bool:
    """Evaluate a validated expression without eval, exec, or target imports."""
    if type(expr) in {bool, int}:
        return expr
    if type(expr) is str:
        return environment[expr]
    op = expr[0]
    args = [evaluate(a, environment) for a in expr[1:]]
    if op == "and":
        return all(args)
    if op == "or":
        return any(args)
    if op == "not":
        return not args[0]
    a, b = args
    if op == "implies":
        return not a or b
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    if op == "+":
        result = a + b
    elif op == "-":
        result = a - b
    elif op == "*":
        result = a * b
    else:
        _fail("UNSUPPORTED_OPERATOR")
    if abs(result).bit_length() > MAX_VALUE_BITS:
        _fail("ARITHMETIC_RESOURCE_LIMIT")
    return result


def _validate(contract: Any) -> tuple[dict[str, list | range], str | None]:
    required = {"schema", "id", "claim_text", "assumptions", "variables", "claim",
                "obligation", "quantifier", "exceptions", "time", "evidence_scope",
                "interpretation"}
    _fields(contract, required, {"obligation_quantifier", "metadata"}, "CONTRACT")
    contract_hash(contract)
    if contract["schema"] != SCHEMA:
        _fail("UNSUPPORTED_SCHEMA")
    _text(contract["id"], "ID")
    _text(contract["claim_text"], "CLAIM_TEXT")
    _fields(contract["interpretation"], {"status", "source"}, set(), "INTERPRETATION")
    _text(contract["interpretation"]["source"], "INTERPRETATION_SOURCE")
    status = contract["interpretation"]["status"]
    if status not in {"reviewed", "ambiguous", "out_of_scope"}:
        _fail("INVALID_INTERPRETATION_STATUS")
    _fields(contract["evidence_scope"], {"kind", "description"}, set(), "EVIDENCE_SCOPE")
    _text(contract["evidence_scope"]["description"], "SCOPE_DESCRIPTION")
    _fields(contract["time"], {"kind", "horizon"}, set(), "TIME")
    temporal = contract["time"]
    if type(temporal["horizon"]) is not int or temporal["horizon"] < 0:
        _fail("INVALID_TIME_HORIZON")
    if temporal["kind"] not in {"state", "transition"}:
        return {}, "OUT_OF_SCOPE_TIME_KIND"
    if (temporal["kind"] == "state" and temporal["horizon"] != 0
            or temporal["kind"] == "transition" and temporal["horizon"] != 1):
        return {}, "OUT_OF_SCOPE_TIME_HORIZON"
    if contract["evidence_scope"]["kind"] != "finite":
        return {}, "OUT_OF_SCOPE_EVIDENCE"
    if contract["quantifier"] not in {"forall", "exists"}:
        return {}, "OUT_OF_SCOPE_QUANTIFIER"
    oq = contract.get("obligation_quantifier", contract["quantifier"])
    if oq not in {"forall", "exists"}:
        return {}, "OUT_OF_SCOPE_QUANTIFIER"
    if oq != contract["quantifier"]:
        return {}, "MIXED_QUANTIFIERS"
    variables = contract["variables"]
    if type(variables) is not dict or not 1 <= len(variables) <= MAX_VARIABLES:
        _fail("INVALID_VARIABLES_OR_LIMIT")
    types: dict[str, str] = {}
    domains: dict[str, list | range] = {}
    cardinality = 1
    for name, declaration in variables.items():
        if (type(name) is not str or not name.isidentifier()
                or name.startswith("_") or len(name) > 64):
            _fail("INVALID_VARIABLE_NAME")
        if type(declaration) is not dict:
            _fail("INVALID_VARIABLE_DECLARATION")
        kind = declaration.get("type")
        if kind == "bool":
            _fields(declaration, {"type"}, set(), "BOOL_VARIABLE")
            domains[name] = [False, True]
            width = 2
        elif kind == "int":
            _fields(declaration, {"type", "min", "max"}, set(), "INT_VARIABLE")
            lo, hi = declaration["min"], declaration["max"]
            if type(lo) is not int or type(hi) is not int or lo > hi:
                _fail("INVALID_INTEGER_DOMAIN")
            if max(abs(lo), abs(hi)) > MAX_INT:
                _fail("INTEGER_DOMAIN_LIMIT")
            width = hi - lo + 1
            domains[name] = range(lo, hi + 1)
        else:
            return {}, "OUT_OF_SCOPE_VARIABLE_TYPE"
        cardinality *= width
        if cardinality > MAX_STATES:
            _fail("STATE_SPACE_LIMIT")
        types[name] = kind
    if type(contract["assumptions"]) is not list or type(contract["exceptions"]) is not list:
        _fail("INVALID_PREMISE_LIST")
    count = [0]
    for expr in [contract["claim"], contract["obligation"],
                 *contract["assumptions"], *contract["exceptions"]]:
        if _type(expr, types, count) != "bool":
            _fail("PREDICATE_REQUIRED")
    if count[0] * cardinality > MAX_WORK:
        _fail("EXHAUSTIVE_WORK_LIMIT")
    if status == "ambiguous":
        return domains, "AMBIGUOUS_INTERPRETATION"
    if status == "out_of_scope":
        return domains, "OUT_OF_SCOPE_INTERPRETATION"
    return domains, None


def _admissible(contract: dict, environment: dict) -> bool:
    return (all(evaluate(a, environment) for a in contract["assumptions"])
            and not any(evaluate(e, environment) for e in contract["exceptions"]))


def _environments(domains: dict[str, list | range]):
    names = list(domains)
    for values in itertools.product(*(domains[n] for n in names)):
        yield dict(zip(names, values))


def analyze(contract: dict[str, Any]) -> dict[str, Any]:
    """Compare supplied predicates on all admissible finite assignments.

    NECESSARY_ONLY means C => O but not O => C. SUFFICIENT_ONLY means
    O => C but not C => O. UNKNOWN carries no implication authority.
    """
    started = time.perf_counter()
    result: dict[str, Any] = {
        "relation": "UNKNOWN", "reason": None, "premise_satisfiable": None,
        "c_implies_o": None, "o_implies_c": None,
        "witnesses": {"c_not_o": None, "o_not_c": None},
        "checked_states": 0, "admissible_states": 0,
        "contract_sha256": None, "formal_anchor_only": True,
        "relation_scope": "pointwise predicates on common finite admissible support",
    }
    try:
        domains, blocked = _validate(contract)
        result["contract_sha256"] = contract_hash(contract)
        if blocked:
            result["reason"] = blocked
            if blocked.startswith("AMBIGUOUS"):
                result["relation"] = "AMBIGUOUS"
            elif blocked.startswith("OUT_OF_SCOPE"):
                result["relation"] = "OUT_OF_SCOPE"
            return result
        for environment in _environments(domains):
            result["checked_states"] += 1
            if not _admissible(contract, environment):
                continue
            result["admissible_states"] += 1
            c = evaluate(contract["claim"], environment)
            o = evaluate(contract["obligation"], environment)
            if c and not o and result["witnesses"]["c_not_o"] is None:
                result["witnesses"]["c_not_o"] = environment
            if o and not c and result["witnesses"]["o_not_c"] is None:
                result["witnesses"]["o_not_c"] = environment
        result["premise_satisfiable"] = result["admissible_states"] > 0
        if not result["premise_satisfiable"]:
            result["reason"] = "INCONSISTENT_OR_EMPTY_PREMISES"
            return result
        c_to_o = result["witnesses"]["c_not_o"] is None
        o_to_c = result["witnesses"]["o_not_c"] is None
        result["c_implies_o"] = c_to_o
        result["o_implies_c"] = o_to_c
        result["relation"] = {
            (True, True): "EQUIVALENT", (True, False): "NECESSARY_ONLY",
            (False, True): "SUFFICIENT_ONLY", (False, False): "INCOMPARABLE",
        }[c_to_o, o_to_c]
        result["reason"] = "FINITE_EXHAUSTIVE_PREDICATE_COMPARISON"
    except (ContractError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        result["reason"] = str(exc) if isinstance(exc, ContractError) else "INVALID_CONTRACT"
        # Partial enumeration cannot establish either direction.
        result["relation"] = "UNKNOWN"
        result["c_implies_o"] = result["o_implies_c"] = None
    finally:
        result["elapsed_seconds"] = time.perf_counter() - started
    return result


def _valid_environment(contract: dict, environment: Any) -> bool:
    if type(environment) is not dict or environment.keys() != contract["variables"].keys():
        return False
    for name, declaration in contract["variables"].items():
        value = environment[name]
        if declaration["type"] == "bool":
            if type(value) is not bool:
                return False
        elif type(value) is not int or not declaration["min"] <= value <= declaration["max"]:
            return False
    return _admissible(contract, environment)


def adjudicate(contract: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """Independently recheck evidence and lift only a justified implication.

    FAIL is a single in-domain obligation violation. PASS_EXHAUSTIVE is
    independently recomputed over the complete admissible support using the
    obligation's quantifier. It is never a sampled-test proof.
    """
    started = time.perf_counter()
    analysis = analyze(contract)
    result: dict[str, Any] = {
        "status": "UNKNOWN", "reason": "NO_LOGICAL_AUTHORITY", "authority": None,
        "evidence_valid": False, "analysis": analysis, "formal_anchor_only": True,
    }
    try:
        if analysis["relation"] not in {
            "EQUIVALENT", "NECESSARY_ONLY", "SUFFICIENT_ONLY", "INCOMPARABLE"
        }:
            result["reason"] = analysis["reason"]
            return result
        _fields(evidence, {"status"}, {"witness", "contract_sha256"}, "EVIDENCE")
        if ("contract_sha256" in evidence
                and evidence["contract_sha256"] != analysis["contract_sha256"]):
            result["reason"] = "EVIDENCE_CONTRACT_MISMATCH"
            return result
        if evidence["status"] == "FAIL":
            witness = evidence.get("witness")
            if not _valid_environment(contract, witness):
                result["reason"] = "INVALID_OR_OUT_OF_DOMAIN_WITNESS"
                return result
            if evaluate(contract["obligation"], witness):
                result["reason"] = "WITNESS_DOES_NOT_VIOLATE_OBLIGATION"
                return result
            result["evidence_valid"] = True
            if contract["quantifier"] != "forall":
                result["reason"] = "SINGLE_FAILURE_CANNOT_REFUTE_EXISTENTIAL"
                return result
            if analysis["c_implies_o"] is not True:
                result["reason"] = "OBLIGATION_FAILURE_LACKS_C_IMPLIES_O"
                return result
            if evaluate(contract["claim"], witness):
                # Defense in depth against an inconsistent or tampered analysis.
                result["reason"] = "WITNESS_DOES_NOT_REFUTE_FORMAL_CLAIM"
                return result
            result.update(status="REFUTED", reason="VALID_FAILURE_AND_C_IMPLIES_O",
                          authority="contraposition of C => O; universal finite support")
        elif evidence["status"] == "PASS_EXHAUSTIVE":
            if "witness" in evidence:
                result["reason"] = "EXHAUSTIVE_EVIDENCE_MUST_NOT_INCLUDE_SINGLE_WITNESS"
                return result
            domains, _ = _validate(contract)
            values = [evaluate(contract["obligation"], env)
                      for env in _environments(domains) if _admissible(contract, env)]
            q = contract.get("obligation_quantifier", contract["quantifier"])
            holds = all(values) if q == "forall" else any(values)
            if not holds:
                result["reason"] = "EXHAUSTIVE_OBLIGATION_PASS_NOT_REPRODUCED"
                return result
            result["evidence_valid"] = True
            if analysis["o_implies_c"] is not True:
                result["reason"] = "OBLIGATION_PASS_LACKS_O_IMPLIES_C"
                return result
            result.update(status="PROVED_BOUNDED", reason="EXHAUSTIVE_PASS_AND_O_IMPLIES_C",
                          authority="O => C; exhaustive finite support only")
        else:
            result["reason"] = "UNSUPPORTED_OR_SAMPLED_EVIDENCE"
    except (ContractError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        result["reason"] = str(exc) if isinstance(exc, ContractError) else "INVALID_EVIDENCE"
    finally:
        result["elapsed_seconds"] = time.perf_counter() - started
    return result
