"""Optional independently encoded SMT comparison checks."""
import pytest

pytest.importorskip("z3", reason="optional pinned research dependency")

from research.c1 import smt_crosscheck


def fixture(claim, obligation, **changes):
    c = {"schema": "c1-contract-v1", "id": "smt-unit", "claim_text": "synthetic",
         "variables": {"x": {"type": "int", "min": -2, "max": 2}},
         "assumptions": [], "exceptions": [], "quantifier": "forall",
         "time": {"kind": "state", "horizon": 0},
         "interpretation": {"status": "reviewed", "source": "synthetic test"},
         "evidence_scope": {"kind": "finite", "description": "x in [-2,2]"},
         "claim": claim, "obligation": obligation}
    c.update(changes)
    return c


def test_stronger_obligation_has_real_separating_model():
    result = smt_crosscheck.solve_relation(fixture([">=", "x", 0], [">", "x", 0]))
    assert result["relation"] == "SUFFICIENT_ONLY"
    separating = result["queries"]["c_not_o"]
    assert separating["status"] == "sat"
    assert separating["witness"] == {"x": 0}
    assert separating["model_satisfies_query"]
    assert result["queries"]["o_not_c"]["status"] == "unsat"


def test_unsat_premises_never_grant_vacuous_implication():
    result = smt_crosscheck.solve_relation(fixture(True, False, assumptions=[[">", "x", 0], ["<", "x", 0]]))
    assert result["relation"] == "UNKNOWN"
    assert result["premise_satisfiable"] is False
    assert result["queries"]["premises"]["status"] == "unsat"


def test_exception_removes_separating_model():
    c = fixture([">=", "x", 0], [">", "x", 0], exceptions=[["==", "x", 0]])
    result = smt_crosscheck.solve_relation(c)
    assert result["relation"] == "EQUIVALENT"
    assert result["queries"]["c_not_o"]["status"] == "unsat"


def test_bool_integer_coercion_is_rejected_by_independent_visitor():
    result = smt_crosscheck.solve_relation(fixture(True, ["==", "x", True]))
    assert result["relation"] == "UNKNOWN"
    assert result["reason"] == "SMT_TYPE_MISMATCH"


def test_one_step_state_transition_boolean_logic():
    c = fixture(["implies", "before", "after"], ["or", ["not", "before"], "after"],
                variables={"before": {"type": "bool"}, "after": {"type": "bool"}},
                time={"kind": "transition", "horizon": 1})
    assert smt_crosscheck.solve_relation(c)["relation"] == "EQUIVALENT"


def test_solver_unknown_is_not_mapped_to_unsat(monkeypatch):
    monkeypatch.setattr(smt_crosscheck, "_solve", lambda *args: {
        "status": "unknown", "witness": None, "reason_unknown": "test timeout"})
    result = smt_crosscheck.solve_relation(fixture(True, False))
    assert result["relation"] == "UNKNOWN"
    assert result["c_implies_o"] is None
    assert result["reason"] == "SMT_UNKNOWN_PREMISES"


def test_public_development_crosscheck_never_reads_gold_or_holdout():
    report = smt_crosscheck.crosscheck_dev()
    assert report["cases"] == 46
    assert report["parity_pass"] == 46
    assert report["solver_unknown_cases"] == 0
