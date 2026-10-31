"""Measurement contracts reject quality loss, hidden cost and consumed retries.

These unit fixtures contain authored counters and no Source/Oracle execution.
The separate registered public driver supplies actual process integration.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("e8r3_measurement", ROOT/"scripts/evaluate-e8r3.py")
measurement = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measurement)


@pytest.fixture
def declaration():
    return measurement.read(ROOT/"docs/E8_R3_PUBLIC_PROFILE_CONTRACT.json")


@pytest.fixture
def public_runs(declaration):
    rows = []
    for seed in declaration["seeds"]:
        for profile in measurement.PROFILES:
            rows.append({"profile": profile, "seed": seed, "status": "COMPLETE", "semantic_digest": str(seed),
                "actual_generation_processes": 1 if profile == "runtime" else 2,
                "actual_plan_requests": 1 if profile == "runtime" else 2,
                "fixed_source_calls": 0, "fixed_oracle_calls": 0,
                "archive_processing_calls": {"full_archive_replay": 0, "compilation": 0},
                "response_validation_status": "PASS", "equivalence_check_status": "PASS" if profile == "audit" else "NOT_RUN_IN_RUNTIME",
                "outer_process_wall_seconds": 1.0 if profile == "runtime" else 2.0})
    return rows


def test_registered_public_criteria_use_full_outer_wall_and_keep_cold_unknown(declaration, public_runs):
    result = measurement.assess_public(public_runs, declaration)
    assert result["status"] == "PASS"
    assert result["prepared_efficiency"] == "IMPROVED"
    assert result["cold_efficiency"] == "INCONCLUSIVE"
    assert not result["statistical_superiority_claimed"]


@pytest.mark.parametrize("field,value", [("semantic_digest", "changed-origin"),
    ("actual_generation_processes", 2), ("actual_plan_requests", 2),
    ("fixed_source_calls", 1), ("response_validation_status", "NOT_EXECUTED")])
def test_fast_output_with_semantic_or_boundary_loss_cannot_pass(declaration, public_runs, field, value):
    runtime = next(r for r in public_runs if r["profile"] == "runtime")
    runtime[field] = value
    runtime["outer_process_wall_seconds"] = 0.001
    result = measurement.assess_public(public_runs, declaration)
    assert result["status"] == "FAIL"
    assert result["prepared_efficiency"] == "INCONCLUSIVE"


def test_negligible_timing_improvement_is_not_declared_efficiency(declaration, public_runs):
    for row in public_runs:
        if row["profile"] == "runtime":
            row["outer_process_wall_seconds"] = 1.99
    result = measurement.assess_public(public_runs, declaration)
    assert result["status"] == "PASS"
    assert result["prepared_efficiency"] == "NO_IMPROVEMENT"


def test_actual_explicit_audit_success_enum_is_accepted_without_threshold_changes(declaration, public_runs):
    for row in public_runs:
        if row["profile"] == "audit":
            row["equivalence_check_status"] = "PASS_FULL_STRUCTURED_SEMANTICS"
    result = measurement.assess_public(public_runs, declaration)
    assert result["status"] == "PASS"
    assert result["prepared_efficiency"] == "IMPROVED"


def test_one_outlier_cannot_replace_preregistered_paired_wins(declaration, public_runs):
    for index, row in enumerate(r for r in public_runs if r["profile"] == "runtime"):
        row["outer_process_wall_seconds"] = 0.01 if index == 0 else 2.01
    assert measurement.assess_public(public_runs, declaration)["prepared_efficiency"] == "NO_IMPROVEMENT"


def test_semantic_projection_preserves_candidate_order_origin_and_contract():
    candidates = [{"inputs": {"a": [0.25]*4, "b": [0.5]*4}, "origin": "AUTHORED_ONE"},
                  {"inputs": {"a": [0.5]*4, "b": [0.25]*4}, "origin": "AUTHORED_TWO"}]
    generation = {"candidates": candidates, "attempts": 2, "wall_seconds": 1.0}
    result = {"generation": {"attempts": 2, "wall_seconds": 1.0}, "rows": [], "contract": {"lengths": [4]}}
    plans = [{"generation": generation, "execution_contract_digest": "authored-contract"}]
    before = measurement.digest(measurement.semantic_projection(result, plans))
    result["generation"]["wall_seconds"] = 8.0
    assert measurement.digest(measurement.semantic_projection(result, plans)) == before
    plans[0]["generation"]["candidates"] = candidates[::-1]
    assert measurement.digest(measurement.semantic_projection(result, plans)) != before
    plans[0]["generation"]["candidates"] = deepcopy(candidates)
    plans[0]["generation"]["candidates"][0]["origin"] = "OTHER"
    assert measurement.digest(measurement.semantic_projection(result, plans)) != before
    plans[0]["generation"]["candidates"] = deepcopy(candidates)
    result["contract"]["lengths"] = [4, 5]
    assert measurement.digest(measurement.semantic_projection(result, plans)) != before


def test_known_union_includes_shrink_and_later_observations_without_method_adaptation():
    old, shrink, later = "1"*64, "2"*64, "3"*64
    tokens, counts = measurement.known_union({"known_input_digests": [old]},
        {"runs": [{"rows": [{"phase": "native_shrink", "input_digest": shrink}]}]},
        {"complete_post_r2_source_functional_inputs": True, "input_digests": [later], "inputs": []},
        lambda p: p)
    assert tokens == sorted([old, shrink, later])
    assert counts["union"] == 3
    with pytest.raises(ValueError, match="completeness"):
        measurement.known_union({"known_input_digests": [old]}, {"runs": []}, {}, lambda p: p)


def test_exclusive_durable_receipts_preserve_first_start(tmp_path):
    target = tmp_path/"START.json"
    measurement.save(target, {"attempt": 1})
    with pytest.raises(FileExistsError):
        measurement.save(target, {"attempt": 2})
    assert measurement.read(target) == {"attempt": 1}


def test_public_source_redaction_removes_all_raw_points_and_oracle_outputs():
    raw = {"runs": [{"rows": [{"inputs": "PRIVATE", "actual": "PRIVATE", "expected": "PRIVATE"}],
        "shrinking": {"witness": "PRIVATE", "original_witness": "PRIVATE", "predicate_calls": 2},
        "status": "COMPLETE"}], "receipt_sha256": "private"}
    public = measurement.redact_source(raw)
    assert "PRIVATE" not in json.dumps(public)
    assert public["runs"][0]["shrinking"] == {"predicate_calls": 2}
    assert "receipt_sha256" not in public


def test_source_registration_preserves_policy_and_disallows_consumed_seeds(declaration):
    source = measurement.read(ROOT/"docs/E8_R3_SOURCE_CONTRACT.json")
    assert source["parameters"] == {"size": 32, "max_examples": 512, "pair_budget": 96, "shrink_budget": 16}
    assert source["verification_profile"] == "runtime"
    assert len(source["seeds"]) == len(set(source["seeds"])) == 6
    assert not set(source["seeds"]) & {13, 47, 89}
    assert not set(source["seeds"]) & set(declaration["seeds"])
    assert source["preserved_r2_verdict"] == "NO_ADDITIONAL_VALUE_OVER_DOMAIN_PRIOR"
    assert source["publication"]["pypi_uploads"] == 0


def test_source_cost_summary_separates_prepared_cold_and_confirmation_curves():
    declaration = measurement.read(ROOT/"docs/E8_R3_SOURCE_CONTRACT.json")
    runs, meters = [], []
    for index, method in enumerate(measurement.METHODS):
        points = [{"input_digest": str(index)*63+str(number), "phase": "fresh_generation",
            "known_development_input": False, "confirmed_failure": True, "actual": {"authored": 1}}
            for number in range(index)]
        runs.append({"method": method, "status": "COMPLETE", "rows": points,
            "mechanisms": {"AUTHORED": index} if index else {}, "target_calls": 3*index,
            "oracle_calls": 3*index, "known_input_replay_calls": 0,
            "first_evaluated_valid_inputs": index, "domain_rejections": 0, "generation": {},
            "oracle_errors": 0, "target_errors": 0, "replay_mismatches": 0,
            "primary_generation_executions": 1, "reference_generation_executions": 0,
            "r3": {"timing": {"end_to_end_wall": 0.25}, "first_confirmed_failure": None,
                "discovery_events": [{"seconds_since_api_entry": 0.2, "input_digest": row["input_digest"]} for row in points]}})
        meters.append({"method": method, "prepared_outer_wall_seconds": 1.0 if method == "D" else 2.0,
            "api_entry_offset_seconds": 0.5})
    result = measurement.summarize_source(runs, declaration, {"A": 0.0, "B": 0.0, "C": 0.1, "D": 16.0}, run_measurements=meters)
    assert result["summaries"]["D"]["prepared_total_seconds"] == 1.0
    assert result["summaries"]["D"]["prepared_api_wall_seconds"] == 0.25
    assert result["summaries"]["D"]["cold_total_seconds"] == 17.0
    assert result["added_value"]["B"] == {"prepared": "OBSERVED", "cold": "NOT_ESTABLISHED"}
    assert result["added_value"]["C"] == {"prepared": "OBSERVED", "cold": "NOT_ESTABLISHED"}
    assert result["curves"]["D"]["confirmed_fresh_inputs_at_fixed_seconds"][0] == {"seconds": 1, "prepared": 3, "cold": 0}
