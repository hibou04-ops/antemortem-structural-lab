"""Adversarial checks of evidence authority, separate from the evaluation gold."""
from copy import deepcopy

import pytest

from research.c1.authority import adjudicate, analyze, contract_hash


def contract(claim=None, obligation=None, **changes):
    result = {
        "schema": "c1-contract-v1", "id": "unit", "claim_text": "x is nonnegative",
        "variables": {"x": {"type": "int", "min": -2, "max": 2}},
        "claim": [">=", "x", 0] if claim is None else claim,
        "obligation": [">=", "x", 0] if obligation is None else obligation,
        "assumptions": [], "exceptions": [], "quantifier": "forall",
        "time": {"kind": "state", "horizon": 0},
        "evidence_scope": {"kind": "finite", "description": "all x in [-2,2]"},
        "interpretation": {"status": "reviewed", "source": "synthetic unit-test anchor"},
    }
    result.update(changes)
    return result


@pytest.mark.parametrize("claim,obligation,expected", [
    ([">=", "x", 0], [">", "x", -1], "EQUIVALENT"),
    ([">", "x", 0], [">=", "x", 0], "NECESSARY_ONLY"),
    ([">=", "x", 0], [">", "x", 0], "SUFFICIENT_ONLY"),
    ([">", "x", 0], ["<", "x", 0], "INCOMPARABLE"),
])
def test_relation_orientation(claim, obligation, expected):
    result = analyze(contract(claim, obligation))
    assert result["relation"] == expected
    assert result["checked_states"] == 5
    assert result["admissible_states"] == 5
    assert result["formal_anchor_only"]


def test_obligation_violation_does_not_automatically_refute_claim():
    stronger = contract([">=", "x", 0], [">", "x", 0])
    unsafe = adjudicate(stronger, {"status": "FAIL", "witness": {"x": 0}})
    assert unsafe["evidence_valid"]
    assert unsafe["status"] == "UNKNOWN"
    assert unsafe["reason"] == "OBLIGATION_FAILURE_LACKS_C_IMPLIES_O"


def test_necessary_obligation_supports_refutation_but_not_proof():
    c = contract([">", "x", 0], [">=", "x", 0])
    assert adjudicate(c, {"status": "FAIL", "witness": {"x": -1}})["status"] == "REFUTED"
    c["assumptions"] = [[">=", "x", 0]]
    result = adjudicate(c, {"status": "PASS_EXHAUSTIVE"})
    assert result["evidence_valid"]
    assert result["status"] == "UNKNOWN"


def test_exhaustive_pass_requires_actual_pass_and_sufficient_obligation():
    c = contract([">=", "x", 0], [">", "x", 0], assumptions=[[">", "x", 0]])
    assert adjudicate(c, {"status": "PASS_EXHAUSTIVE"})["status"] == "PROVED_BOUNDED"
    c["assumptions"] = []
    result = adjudicate(c, {"status": "PASS_EXHAUSTIVE"})
    assert result["status"] == "UNKNOWN"
    assert result["reason"] == "EXHAUSTIVE_OBLIGATION_PASS_NOT_REPRODUCED"


@pytest.mark.parametrize("assumptions,exceptions", [
    ([[">", "x", 0], ["<", "x", 0]], []), ([], [True]),
])
def test_empty_admissible_support_never_grants_vacuous_authority(assumptions, exceptions):
    c = contract(assumptions=assumptions, exceptions=exceptions)
    result = analyze(c)
    assert result["relation"] == "UNKNOWN"
    assert result["premise_satisfiable"] is False
    assert result["c_implies_o"] is None
    assert adjudicate(c, {"status": "PASS_EXHAUSTIVE"})["status"] == "UNKNOWN"


@pytest.mark.parametrize("witness", [{"x": 99}, {"x": True}, {}, {"x": -1, "y": 0}])
def test_invalid_witnesses(witness):
    result = adjudicate(contract(), {"status": "FAIL", "witness": witness})
    assert result["status"] == "UNKNOWN"
    assert not result["evidence_valid"]


def test_witness_must_obey_premises_and_exceptions():
    c = contract(assumptions=[[">=", "x", -1]], exceptions=[["==", "x", -1]])
    for x in [-2, -1]:
        assert not adjudicate(c, {"status": "FAIL", "witness": {"x": x}})["evidence_valid"]
    assert analyze(c)["admissible_states"] == 3


def test_witness_must_reproduce_obligation_violation():
    result = adjudicate(contract(), {"status": "FAIL", "witness": {"x": 1}})
    assert result["status"] == "UNKNOWN"
    assert result["reason"] == "WITNESS_DOES_NOT_VIOLATE_OBLIGATION"


def test_existential_cannot_be_refuted_by_one_failure():
    c = contract(quantifier="exists")
    result = adjudicate(c, {"status": "FAIL", "witness": {"x": -1}})
    assert result["evidence_valid"] and result["status"] == "UNKNOWN"
    assert result["reason"] == "SINGLE_FAILURE_CANNOT_REFUTE_EXISTENTIAL"
    assert adjudicate(c, {"status": "PASS_EXHAUSTIVE"})["status"] == "PROVED_BOUNDED"


def test_mixed_quantifiers_do_not_inherit_pointwise_authority():
    c = contract(obligation_quantifier="exists")
    assert analyze(c)["relation"] == "UNKNOWN"
    assert analyze(c)["reason"] == "MIXED_QUANTIFIERS"


def test_boolean_states_and_single_transition():
    c = contract(
        ["implies", "before", "after"], ["or", ["not", "before"], "after"],
        variables={"before": {"type": "bool"}, "after": {"type": "bool"}},
        time={"kind": "transition", "horizon": 1},
    )
    assert analyze(c)["relation"] == "EQUIVALENT"
    assert adjudicate(c, {"status": "FAIL", "witness": {"before": True, "after": False}})["status"] == "REFUTED"
    c["time"]["horizon"] = 2
    assert analyze(c)["relation"] == "OUT_OF_SCOPE"


@pytest.mark.parametrize("status,expected", [("ambiguous", "AMBIGUOUS"), ("out_of_scope", "OUT_OF_SCOPE")])
def test_unreviewed_interpretations_never_gain_authority(status, expected):
    c = contract(interpretation={"status": status, "source": "unresolved wording"})
    assert analyze(c)["relation"] == expected
    assert adjudicate(c, {"status": "FAIL", "witness": {"x": -1}})["status"] == "UNKNOWN"


@pytest.mark.parametrize("expr", [
    ["__import__", "os"], ["eval", "x"], ["==", "x", True],
    [">", True, False], ["and", True, 1], ["==", "undeclared", 0],
    ["+", "x", 1], ["not", True, False], ["and", True],
])
def test_untrusted_or_mistyped_dsl_is_rejected(expr):
    result = analyze(contract(obligation=expr))
    assert result["relation"] == "UNKNOWN"


def test_large_state_space_is_rejected_before_enumeration():
    c = contract(variables={"x": {"type": "int", "min": 0, "max": 100_000}})
    result = analyze(c)
    assert result["reason"] == "STATE_SPACE_LIMIT"
    assert result["checked_states"] == 0


def test_combined_expression_and_state_work_is_bounded():
    c = contract(variables={"x": {"type": "int", "min": 0, "max": 99_999}},
                 assumptions=[[">=", "x", 0]] * 30)
    result = analyze(c)
    assert result["reason"] == "EXHAUSTIVE_WORK_LIMIT"
    assert result["checked_states"] == 0


def test_deep_expressions_and_huge_integer_arithmetic_fail_closed():
    expression = True
    for _ in range(35):
        expression = ["not", expression]
    assert analyze(contract(obligation=expression))["reason"] == "EXPRESSION_RESOURCE_LIMIT"
    huge = ["*", ["*", 1_000_000_000, 1_000_000_000],
            ["*", ["*", 1_000_000_000, 1_000_000_000], 1_000_000_000]]
    result = analyze(contract(obligation=["==", huge, 1]))
    assert result["relation"] == "UNKNOWN"
    assert result["reason"] == "ARITHMETIC_RESOURCE_LIMIT"
    assert result["c_implies_o"] is None


def test_unknown_contract_fields_do_not_silently_drop_conditions():
    c = contract()
    c["assumptons"] = [[">", "x", 0]]
    assert analyze(c)["reason"] == "UNKNOWN_CONTRACT_FIELDS"


def test_hash_binds_evidence_to_contract_and_rejects_tampering():
    c = contract()
    evidence = {"status": "FAIL", "witness": {"x": -1}, "contract_sha256": contract_hash(c)}
    assert adjudicate(c, evidence)["status"] == "REFUTED"
    changed = deepcopy(c)
    changed["claim_text"] = "a changed interpretation"
    result = adjudicate(changed, evidence)
    assert result["status"] == "UNKNOWN"
    assert result["reason"] == "EVIDENCE_CONTRACT_MISMATCH"


def test_sampled_pass_never_proves_and_invalid_evidence_does_not_raise():
    for evidence in [{"status": "PASS_SAMPLED"}, {"status": "FAIL"}, None, []]:
        assert adjudicate(contract(), evidence)["status"] == "UNKNOWN"
