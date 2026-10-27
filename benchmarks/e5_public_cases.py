"""New, reviewed public development fixtures for E5 software QA.

Faults are deliberately authored mutations, not newly found real-world defects.
The two controls call existing user-owned project functions unchanged.
"""
from __future__ import annotations

from copy import deepcopy
import inspect
import textwrap


def add_model(x: int, y: int) -> int:
    return x + y


def add_development(x: int, y: int) -> int:
    if x < y:
        return x + y + 1
    return x + y


def strip_model(text: str) -> str:
    if text:
        return text.strip()
    return text


def strip_development(text: str) -> str:
    if text:
        return text.strip(" ")
    return text


def unique_model(items: list[int]) -> list[int]:
    result = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def unique_development(items: list[int]) -> list[int]:
    return sorted(set(items))


def absolute_model(value: float) -> float:
    return abs(value)


def absolute_development(value: float) -> float:
    if value < 0:
        return value
    return abs(value)


def balance_model(trace: list[tuple[str, int]]) -> int:
    balance = 0
    for operation, amount in trace:
        if operation == "add":
            balance += amount
        else:
            balance = 0
    return balance


def balance_development(trace: list[tuple[str, int]]) -> int:
    balance = 0
    for operation, amount in trace:
        if operation == "add":
            balance += amount
        else:
            balance = amount
    return balance


def actual_feature_control(x: int, y: int) -> int:
    from tomolab.mold.relations import feature
    return feature("sum", x, y)


def actual_normalize_control(text: str) -> str:
    from tomolab.claim import _normalize
    return _normalize(text)


def normalize_model(text: str) -> str:
    ending_trimmed = text.rstrip()
    if ending_trimmed.endswith("."):
        ending_trimmed = ending_trimmed[:-1]
    return " ".join(ending_trimmed.split())


INT = {"kind": "int", "min": -16, "max": 16}
TEXT = {"kind": "str", "alphabet": "ab .\t\n", "min_size": 0, "max_size": 8}
ITEMS = {"kind": "list", "items": {"kind": "int", "min": -4, "max": 4}, "min_size": 0, "max_size": 8}
FLOAT = {"kind": "float", "min": -4.0, "max": 4.0}
TRACE = {"kind": "list", "min_size": 0, "max_size": 6,
         "items": {"kind": "tuple", "items": [
             {"kind": "str", "alphabet": "aderst", "min_size": 3, "max_size": 5,
              "choices": ["add", "reset"]},
             {"kind": "int", "min": -3, "max": 3}]}}


def _case(case_id, family, target, oracle, inputs, *, fault=True, e4=False, operation=None, category="mismatch"):
    return {"case_id": case_id, "family_id": family, "target": target, "oracle": oracle,
            "inputs": deepcopy(inputs), "expected_fault": fault, "e4_eligible": e4,
            "operation": operation or family, "category": category,
            "origin": "NEW_REVIEWED_AUTHORED_MUTATION" if fault else "EXISTING_USER_PROJECT_CLEAN_CONTROL",
            "public_model": textwrap.dedent(inspect.getsource(oracle)),
            "public_model_function": oracle.__name__}


CASES = [
    _case("dev-add-order", "addition-order-guard", add_development, add_model,
          [("x", "left", INT), ("y", "right", INT)], e4=True, operation="integer-addition"),
    _case("dev-strip", "whitespace-normalization", strip_development, strip_model,
          [("text", "text", TEXT)]),
    _case("dev-stable-unique", "stable-deduplication-order", unique_development, unique_model,
          [("items", "items", ITEMS)]),
    _case("dev-absolute", "negative-float-sign", absolute_development, absolute_model,
          [("value", "operand", FLOAT)]),
    _case("dev-balance", "reset-state-transition", balance_development, balance_model,
          [("trace", "trace", TRACE)], category="state_violation"),
    _case("control-project-feature", "project-addition-control", actual_feature_control, add_model,
          [("x", "left", INT), ("y", "right", INT)], fault=False, e4=True, operation="integer-addition"),
    _case("control-project-normalize", "project-normalization-control", actual_normalize_control, normalize_model,
          [("text", "text", TEXT)], fault=False),
]


def case_by_id(case_id):
    return next(case for case in CASES if case["case_id"] == case_id)
