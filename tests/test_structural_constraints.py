"""Public synthetic contract checks; independent of consumed E1/E2/E3 data."""
from copy import deepcopy
from itertools import product
import importlib.util

import pytest

from tomolab.mold.schema import default_spec
from tomolab.mold.structural import (check_consistency, compile_relation,
                                     filter_hypotheses, structural_holds,
                                     structural_relation_id, validate_structural_relation)


def test_compound_ast_has_python_integer_semantics_and_role_rename_identity():
    spec = default_spec(low=-3, high=3)
    relation = compile_relation("abs(x - y) <= 2 and (x + y) % 3 == 1", spec)
    for x, y in product(range(-3, 4), repeat=2):
        assert structural_holds(relation, {"x": x, "y": y}, spec) == (abs(x - y) <= 2 and (x + y) % 3 == 1)
    renamed = deepcopy(spec)
    renamed["variables"][0]["name"] = "a"
    renamed["variables"][1]["name"] = "b"
    assert structural_relation_id(relation) == structural_relation_id(
        compile_relation("abs(a - b) <= 2 and (a + b) % 3 == 1", renamed))


@pytest.mark.parametrize("expression", [
    "__import__('os').system('x')", "x.__class__ == y", "x[0] == y", "x ** 100 == y",
    "(lambda: 1)() == x", "sum([x,y]) == 0", "x / 2 == y", "x // 2 == y",
    "x % y == 0", "x % -2 == 0", "x * y == 1", "x is y", "x in [y]",
    "True == x", "x == 1.0", "x", "x and y", "not x", "unknown == y", "+(x == y)",
    "abs(x, y) == 1", "abs(x=x) == 1", "[v for v in (x,y)] == y",
])
def test_non_contract_python_syntax_and_type_confusion_are_rejected(expression):
    with pytest.raises(ValueError):
        compile_relation(expression, default_spec())


def test_arithmetic_unary_boolean_and_chained_comparison_semantics():
    spec = default_spec(low=-2, high=2)
    relation = compile_relation("not (-2 <= x < y <= 2) or -x + 2 * y != +1", spec)
    for x, y in product(range(-2, 3), repeat=2):
        assert structural_holds(relation, {"x": x, "y": y}, spec) == (
            not (-2 <= x < y <= 2) or -x + 2 * y != +1)


def test_serialized_nodes_are_validated_and_bounds_remain_strict():
    spec = default_spec(low=-1, high=1)
    relation = compile_relation("x == y", spec)
    bad = deepcopy(relation)
    bad["expression"][0] = "call"
    with pytest.raises(ValueError):
        validate_structural_relation(bad)
    with pytest.raises(ValueError):
        structural_holds(relation, {"x": True, "y": 0}, spec)
    with pytest.raises(ValueError):
        structural_holds(relation, {"x": 2, "y": 0}, spec)
    with pytest.raises(ValueError, match="resource"):
        compile_relation("not " * 40 + "x == y", spec)


@pytest.mark.parametrize("expressions", [
    [], ["x + y == 1", "x >= 0", "y >= 0"],
    ["x + y == 1", "x + y == 2"],
    ["abs(x - y) <= 1", "x != y", "(x + y) % 3 == 0"],
    ["x == 9"], ["x * -2 <= y", "x < y or x == 0"],
])
@pytest.mark.skipif(importlib.util.find_spec("z3") is None, reason="optional solver extra not installed")
def test_conjunction_z3_matches_independent_finite_enumeration(expressions):
    spec = default_spec(low=-2, high=2)
    relations = [compile_relation(expression, spec) for expression in expressions]
    enum = check_consistency(spec, relations)
    z3 = check_consistency(spec, relations, backend="z3")
    assert enum["status"] == z3["status"]
    if z3["status"] == "SAT":
        assert all(structural_holds(relation, z3["witness"], spec) for relation in relations)
    else:
        by_id = {structural_relation_id(relation): relation for relation in relations}
        assert check_consistency(spec, [by_id[rid] for rid in z3["unsat_core"]])["status"] == "UNSAT"


@pytest.mark.skipif(importlib.util.find_spec("z3") is None, reason="optional solver extra not installed")
def test_exclusions_and_empty_conjunction_are_respected_by_both_backends():
    spec = default_spec(low=0, high=0)
    for backend in ("enumeration", "z3"):
        assert check_consistency(spec, [], backend=backend)["witness"] == {"x": 0, "y": 0}
        assert check_consistency(spec, [], backend=backend, excluded=[(0, 0)])["status"] == "UNSAT"
        with pytest.raises(ValueError):
            check_consistency(spec, [], backend=backend, excluded=[(True, 0)])


def test_structured_counterexamples_remove_ast_hypotheses_without_scalar_rewards():
    spec = default_spec(low=-2, high=2)
    relations = [compile_relation(text, spec) for text in ("x == y", "x + y == 0", "x < y")]
    def event(kind, event_id, x, y):
        return {"kind": kind, "evidence_id": event_id, "inputs": {"x": x, "y": y},
                "invariant": spec["invariant"], "signature": "integer-mismatch"}
    events = [event("FAILURE", "a", 1, 1), event("REFUTATION", "b", -1, 1)]
    result = filter_hypotheses(spec, relations, events)
    assert result["status"] == "HYPOTHESES_REMAIN"
    assert [item["relation"] for item in result["version_space"]] == relations[:1]
    assert result["contradictions"]
    conflicting = filter_hypotheses(spec, relations, events + [event("REFUTATION", "c", 1, 1)])
    assert conflicting["status"] == "INCONSISTENT_EVIDENCE"
    assert conflicting["version_space"] == []
    with pytest.raises(ValueError):
        filter_hypotheses(spec, relations, [dict(events[0], score=1)])
    with pytest.raises(ValueError, match="unique"):
        filter_hypotheses(spec, relations, [events[0], events[0]])


def test_hypothesis_filter_deduplicates_only_exact_canonical_ast_relations():
    spec = default_spec(low=-2, high=2)
    relations = [compile_relation(text, spec) for text in
                 ("x == y", "(x == y)", "y == x", "x + y == 0")]
    event = {"kind": "FAILURE", "evidence_id": "duplicate-case",
             "inputs": {"x": 1, "y": 1}, "invariant": spec["invariant"],
             "signature": "integer-mismatch"}
    result = filter_hypotheses(spec, relations, [event])
    assert result["input_count"] == 4
    assert result["unique_hypotheses"] == 3 and result["duplicate_hypotheses"] == 1
    # Reversed equality is semantically equivalent but has distinct canonical
    # syntax, so it remains separately reviewable rather than being guessed away.
    assert [row["relation"] for row in result["version_space"]] == [relations[0], relations[2]]
    assert len(result["contradictions"]) == 1


@pytest.mark.skipif(importlib.util.find_spec("z3") is None, reason="optional solver extra not installed")
def test_z3_unknown_is_preserved_and_missing_dependency_is_explicit(monkeypatch):
    import builtins
    import z3
    spec = default_spec(low=-1, high=1)
    relation = compile_relation("x == y", spec)
    original_solver = z3.Solver

    class UnknownSolver:
        def __init__(self):
            self.actual = original_solver()

        def __getattr__(self, name):
            return getattr(self.actual, name)

        def check(self):
            return z3.unknown

        def reason_unknown(self):
            return "test timeout"

    monkeypatch.setattr(z3, "Solver", UnknownSolver)
    result = check_consistency(spec, [relation], backend="z3")
    assert result["status"] == "UNKNOWN" and result["reason"] == "test timeout"
    assert result["witness"] is None and result["unsat_core"] == []
    original_import = builtins.__import__

    def no_z3(name, *args, **kwargs):
        if name == "z3":
            raise ImportError("simulated missing extra")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_z3)
    with pytest.raises(ValueError, match="requires"):
        check_consistency(spec, [relation], backend="z3")
    assert check_consistency(spec, [relation])["status"] == "SAT"
