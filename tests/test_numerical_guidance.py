"""Authored development fixtures; no private examples or held-out execution."""
from copy import deepcopy
import inspect
import math

import pytest

from tomolab.discovery.numerical_guidance import (
    FAMILIES, FailureGuidanceRecipe, calibrate_recipe, domain_guard,
    generate_numerical_candidates, input_features, public_input_contract,
    numerical_input_digest, shrink_numerical_failure,
)
from tomolab.discovery.schema import digest


def authored_recipe():
    # Membership labels exercise allocation only. These authored rows are not
    # Source validation or assertions that a target actually fails on them.
    rows = [{"inputs": {"a": [-0.5, 0.0, 0.5], "b": [0.1]*3}, "status": "FAILURE"},
            {"inputs": {"a": [-0.5, 0.0, 0.5], "b": [-0.5, 0.5, 0.0]}, "status": "REFUTATION"}]
    return calibrate_recipe(rows, source_evidence_refs=["authored-calibration"], archive_digest="a"*64).to_dict()


def test_source_domain_preserves_constants_and_rejects_near_constant_nonconstant():
    assert domain_guard({"a": [0.1]*3, "b": [0.1]*3})
    assert domain_guard({"a": [0.25]*3, "b": [-0.5, 0, 0.5]})
    near = {"a": [0.1, 0.1, math.nextafter(0.1, 1.0)], "b": [-0.5, 0, 0.5]}
    assert not domain_guard(near)
    assert domain_guard(near, public_input_contract("NEAR_CONSTANT_DIAGNOSTIC"))


@pytest.mark.parametrize("point", [
    {"a": [0.1]*3, "b": [0, 1, 2]},
    {"a": [0.1]*3, "b": [0.1]*4},
    {"a": [0.1]*2, "b": [0.1]*2},
    {"a": [True]*3, "b": [0.1]*3},
    {"a": [float("nan")]*3, "b": [0.1]*3},
    {"a": [float("inf")]*3, "b": [0.1]*3},
    {"a": [0.1]*3, "b": [0.1]*3, "answer": "OK"},
])
def test_invalid_inputs_never_become_normal_training_examples(point):
    assert not domain_guard(point)


def test_input_features_distinguish_exact_constant_and_rounded_residual():
    decimal = input_features({"a": [0.1]*3, "b": [-0.5, 0, 0.5]})
    binary = input_features({"a": [0.25]*3, "b": [-0.5, 0, 0.5]})
    assert decimal["a"]["all_identical"] and decimal["a"]["exact_degenerate"]
    # CPython versions may center the decimal differently; the feature must
    # report the actual public arithmetic instead of asserting a fixed label.
    assert decimal["a"]["centering_residual_nonzero"] == (sum([0.1]*3)/3 != 0.1)
    assert binary["a"]["rounded_centered_ss"] == 0
    assert binary["a"]["max_ulp"] > 0


def test_source_allocation_uses_failures_and_preserves_normal_counterevidence():
    recipe = authored_recipe()
    assert recipe["origin_type"] == "SOURCE_CALIBRATED_GUIDANCE"
    assert recipe["provenance"]["prior"]["origin_type"] == "HAND_SPECIFIED_PRIOR"
    assert recipe["development_validation"]["origin_type"] == "OBSERVED_VALIDATION_RESULT"
    weights = recipe["parameter_strategy"]["weights"]
    assert max(weights.values()) == 16
    assert recipe["known_counterevidence"]["normal_observations"] == 1
    # The compact recipe contains neither the calibration input nor outputs.
    text = repr(recipe)
    assert "actual_result" not in text and "oracle_result" not in text
    assert "[-0.5, 0.0, 0.5]" not in text


def test_out_of_domain_and_oracle_error_rows_are_quarantined_not_negative():
    recipe = authored_recipe()
    rows = [{"inputs": {"a": [-0.5, 0, 0.5], "b": [0.1]*3}, "status": "FAILURE"},
            {"inputs": {"a": [-0.5, 0, 0.5], "b": [0.5, 0, -0.5]}, "status": "REFUTATION"},
            {"inputs": {"a": [0.1]*3, "b": [0, 1, 2]}, "status": "REFUTATION"},
            {"inputs": {"a": [0.1]*3, "b": [0.1]*3}, "status": "ORACLE_ERROR"}]
    result = calibrate_recipe(rows, source_evidence_refs=["authored-calibration"], archive_digest="a"*64).to_dict()
    assert result["parameter_strategy"] == recipe["parameter_strategy"]
    assert result["known_counterevidence"]["quarantined_observations"] == 2


def test_unlabelled_or_only_failure_calibration_cannot_claim_source_support():
    with pytest.raises(ValueError, match="failure and normal"):
        calibrate_recipe([{"inputs": {"a": [0.1]*3, "b": [0.1]*3}, "status": "FAILURE"}],
                         source_evidence_refs=["authored"], archive_digest="a"*64)


@pytest.mark.parametrize("change", [
    lambda r: r.update(secret_oracle_output={"answer": 0}),
    lambda r: r["parameter_strategy"]["weights"].update(Y_CONSTANT_RESIDUAL=15),
    lambda r: r["permitted_transformations"].append("__import__('os')"),
    lambda r: r["comparison_contract"].update(absolute_tolerance=1.0),
    lambda r: r["provenance"].update(oracle_outputs_included=True),
    lambda r: r["development_validation"].update(status="PASS_AFTER_VALIDATION"),
])
def test_recipe_tampering_or_hidden_answers_are_rejected(change):
    recipe = authored_recipe(); change(recipe)
    with pytest.raises(ValueError):
        FailureGuidanceRecipe.from_dict(recipe)


def test_immutable_recipe_serialization_cannot_be_modified_through_returned_dict():
    frozen = FailureGuidanceRecipe.from_dict(authored_recipe())
    copy = frozen.to_dict(); copy["parameter_strategy"]["weights"].clear()
    assert set(frozen.to_dict()["parameter_strategy"]["weights"]) == set(FAMILIES)


def test_b_and_d_share_public_prior_while_d_changes_only_family_allocation():
    recipe = authored_recipe()
    b = generate_numerical_candidates("B", recipe=recipe, size=6, max_examples=128, seed=109)
    d = generate_numerical_candidates("D", recipe=recipe, size=6, max_examples=128, seed=109)
    assert b["target_calls"] == d["oracle_calls"] == 0
    assert b["candidates"] and d["candidates"]
    assert all(domain_guard(row["inputs"]) for row in b["candidates"]+d["candidates"])
    assert all(row["origin"] == "HAND_SPECIFIED_PRIOR" for row in b["candidates"])
    assert all(row["origin"] == "SOURCE_CALIBRATED_GUIDANCE" for row in d["candidates"])
    assert {row["transform"] for row in b["candidates"]+d["candidates"]} <= set(FAMILIES)


def test_generation_is_deterministic_and_rejects_old_inputs_by_digest():
    recipe = authored_recipe()
    first = generate_numerical_candidates("D", recipe=recipe, size=6, max_examples=128, seed=113)
    second = generate_numerical_candidates("D", recipe=recipe, size=6, max_examples=128, seed=113)
    assert first["candidates"] == second["candidates"]
    old = [digest(row["inputs"]) for row in first["candidates"]]
    fresh = generate_numerical_candidates("D", recipe=recipe, size=6, max_examples=128, seed=113, excluded_digests=old)
    assert not set(old) & {digest(row["inputs"]) for row in fresh["candidates"]}
    assert fresh["existing_input_rejections"] > 0


def test_replay_and_generic_transformation_are_accounted_separately():
    known = {"a": [-0.5, 0, 0.5], "b": [0.1]*3}
    result = generate_numerical_candidates("C", replay_inputs=[known], size=4, max_examples=64,
                                           seed=127, excluded_digests=[digest(known)])
    assert result["explicit_replays"] == 1
    assert result["candidates"][0]["origin"] == "KNOWN_INPUT_REPLAY"
    assert any(row["origin"] == "SOURCE_REPLAY_GENERIC_TRANSFORMATION" for row in result["candidates"][1:])
    assert len({digest(row["inputs"]) for row in result["candidates"]}) == len(result["candidates"])


def test_numeric_input_identity_uses_actual_float_values_not_json_spelling():
    integer_point = {"a": [-1, 0, 1], "b": [0.25]*3}
    float_point = {"a": [-1.0, 0.0, 1.0], "b": [0.25]*3}
    assert digest(integer_point) != digest(float_point)
    assert numerical_input_digest(integer_point) == numerical_input_digest(float_point)


def test_validation_length_axis_is_explicit_and_never_implicitly_broadened():
    recipe = authored_recipe()
    contract = public_input_contract(lengths=[4, 5, 6])
    batch = generate_numerical_candidates("B", recipe=recipe, contract=contract, size=4, max_examples=64, seed=131)
    assert all(len(row["inputs"]["a"]) in (4, 5, 6) for row in batch["candidates"])
    with pytest.raises(ValueError, match="applicability"):
        generate_numerical_candidates("D", recipe=recipe, contract=public_input_contract("NEAR_CONSTANT_DIAGNOSTIC"))


def test_generator_signature_accepts_no_oracle_or_target_and_requires_calibrated_d():
    parameters = inspect.signature(generate_numerical_candidates).parameters
    assert "oracle" not in parameters and "target" not in parameters
    with pytest.raises(ValueError, match="frozen Source"):
        generate_numerical_candidates("D")
    with pytest.raises(TypeError):
        generate_numerical_candidates("B", oracle=lambda _: True)


def test_native_shrink_is_bounded_and_returns_only_observed_failure():
    calls = []
    def authored_predicate(point):
        calls.append(deepcopy(point))
        return point["a"][0] >= 0.5
    result = shrink_numerical_failure(authored_predicate, method="B", budget=32, seed=137)
    assert result["predicate_calls"] == len(calls) <= 32
    assert result["witness_mode"] == "FRESH_NATIVE_FIND_AND_SHRINK"
    if result["witness"] is not None:
        assert result["witness"] in calls and result["witness"]["a"][0] >= 0.5
    assert result["shrinking"] in ("NATIVE_COMPLETED", "INCOMPLETE_OR_NO_WITNESS")


def test_initial_witness_shrink_reproduces_then_preserves_structure_and_domain():
    initial = {"a": [-0.5, 0.0, 0.5, -0.5, 0.0], "b": [0.1]*5}
    calls = []
    def authored_predicate(point):
        calls.append(deepcopy(point))
        return len(set(point["b"])) == 1 and len(set(point["a"])) > 1
    result = shrink_numerical_failure(authored_predicate, initial_witness=initial, budget=64, seed=139)
    assert calls[0] == initial and result["initial_witness_reproduced"] is True
    assert result["initial_witness_digest"] == numerical_input_digest(initial)
    assert result["witness_mode"] == "INITIAL_WITNESS_TRANSFORMS"
    assert len(calls) == result["predicate_calls"] <= 64
    assert all(domain_guard(p) for p in calls)
    assert all(len(set(p["b"])) == 1 and len(set(p["a"])) > 1 for p in calls)
    assert result["witness"] in calls
    assert len(result["witness"]["a"]) <= len(initial["a"])


def test_initial_failure_is_retained_when_native_shrink_budget_is_exhausted():
    initial = {"a": [-0.5, 0.0, 0.5], "b": [0.1]*3}
    calls = []
    def authored_predicate(point):
        calls.append(point)
        return True
    result = shrink_numerical_failure(authored_predicate, initial_witness=initial, budget=1, seed=149)
    assert result["witness"] == initial and result["initial_witness_preserved"] is True
    assert result["predicate_calls"] == len(calls) == 1
    assert result["stop"] == "RESOURCE_BUDGET"
    assert result["shrinking"] == "INCOMPLETE_OR_NO_WITNESS"


def test_initial_witness_must_reproduce_and_out_of_domain_never_calls_predicate():
    initial = {"a": [-0.5, 0.0, 0.5], "b": [0.1]*3}
    calls = []
    def normal_predicate(point):
        calls.append(point)
        return False
    with pytest.raises(ValueError, match="did not reproduce"):
        shrink_numerical_failure(normal_predicate, initial_witness=initial, budget=4)
    assert len(calls) == 1
    with pytest.raises(ValueError, match="declared shrink domain"):
        shrink_numerical_failure(normal_predicate, initial_witness={"a": [2.0]*3, "b": [0.1]*3})
    assert len(calls) == 1
