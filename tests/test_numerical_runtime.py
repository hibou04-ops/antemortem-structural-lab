"""R3 integration uses real clean generators and authored evaluator callbacks.

No assertion in this file executes the historical Source or its Oracle.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tomolab.discovery import compact_guidance, numerical_source
from tomolab.discovery.numerical_boundary import NumericalBoundary
from tomolab.discovery.numerical_guidance import numerical_input_digest, public_input_contract
from tomolab.discovery.numerical_response import (assert_equivalent_plans,
    validate_worker_response)
from tomolab.discovery.numerical_service import run_numerical_method
from tomolab.discovery.schema import digest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def bundle():
    folder = ROOT/"examples/numerical"
    return {"artifact": json.loads((folder/"source-guide.json").read_text()),
            "approval_receipt": json.loads((folder/"source-approval.json").read_text())}


@pytest.fixture(scope="module")
def received_plan(bundle):
    request = dict(action="plan", **bundle, expected_digest=bundle["artifact"]["artifact_digest"],
        seed=17, size=4, max_examples=64, excluded_digests=[], contract=public_input_contract(lengths=[4]))
    with NumericalBoundary() as worker:
        response = worker.request("plan", **{k:v for k,v in request.items() if k != "action"})
        snapshot = worker.request("snapshot")
    return request, response, snapshot


@pytest.fixture
def authored_evaluator(monkeypatch):
    calls = {"target": 0, "oracle": 0}
    def target(point):
        calls["target"] += 1
        return {"authored_value": 1}
    def oracle(point):
        calls["oracle"] += 1
        return {"authored_value": 2}
    monkeypatch.setattr(numerical_source, "target_result", target)
    monkeypatch.setattr(numerical_source, "oracle_result", oracle)
    monkeypatch.setattr(numerical_source, "compare_results", lambda a,b:a == b)
    monkeypatch.setattr(numerical_source, "classify_mechanism", lambda *args:"AUTHORED_COUNTER_MISMATCH")
    return calls


def test_received_plan_binds_actual_rows_request_and_freeze(received_plan):
    request, response, snapshot = received_plan
    generation = validate_worker_response(response, request, snapshot=snapshot)
    assert digest(generation["candidates"]) == response["candidate_digest"]
    stale = deepcopy(request)
    stale["seed"] += 1
    with pytest.raises(ValueError, match="request identity"):
        validate_worker_response(response, stale, snapshot=snapshot)


@pytest.mark.parametrize("mutation", ["extra", "digest", "contract", "freeze", "duplicate",
    "domain", "features", "provenance", "recipe", "partial"])
def test_response_tampering_is_rejected(received_plan, mutation):
    request, response, snapshot = deepcopy(received_plan)
    if mutation == "extra":
        response["executable_code"] = "print('never executed')"
    elif mutation == "digest":
        response["candidate_digest"] = "0"*64
    elif mutation == "contract":
        response["execution_contract_digest"] = "0"*64
    elif mutation == "freeze":
        response["learning_allowed"] = True
    elif mutation == "duplicate":
        response["generation"]["candidates"][1] = deepcopy(response["generation"]["candidates"][0])
    elif mutation == "domain":
        response["generation"]["candidates"][0]["inputs"]["a"][0] = 2.0
    elif mutation == "features":
        response["generation"]["candidates"][0]["features"]["length"] = 999
    elif mutation == "provenance":
        response["generation"]["candidates"][0]["origin"] = "AUTHORED_TEST"
    elif mutation == "recipe":
        response["generation"]["candidates"][0]["recipe_id"] = "unapproved"
    elif mutation == "partial":
        response["generation"]["stop"] = "TIMEOUT_PARTIAL"
    with pytest.raises(ValueError):
        validate_worker_response(response, request, snapshot=snapshot)


def test_self_rehashed_excluded_candidate_is_still_rejected(received_plan):
    request, response, snapshot = deepcopy(received_plan)
    request["excluded_digests"] = [numerical_input_digest(response["generation"]["candidates"][0]["inputs"])]
    snapshot["request_digest"] = digest({k:v for k,v in request.items() if k != "action"})
    with pytest.raises(ValueError, match="excluded"):
        validate_worker_response(response, request, snapshot=snapshot)


def test_full_semantic_comparison_preserves_order_and_origin(received_plan):
    _, response, _ = received_plan
    other = deepcopy(response)
    other["generation"]["wall_seconds"] += 100
    assert_equivalent_plans(response, other)
    other["generation"]["candidates"].reverse()
    with pytest.raises(ValueError, match="semantics differ"):
        assert_equivalent_plans(response, other)


def test_real_runtime_one_generation_and_audit_two_match(bundle, authored_evaluator, monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("runtime must not call the legacy reference helper")
    monkeypatch.setattr(compact_guidance, "host_candidate_plan", forbidden)
    options = dict(expected_digest=bundle["artifact"]["artifact_digest"], method="D",
        seed=17, size=3, max_examples=64, pair_budget=12, shrink_budget=0,
        contract=public_input_contract(lengths=[4]))
    runtime = run_numerical_method(bundle, verification_profile="runtime", **options)
    audit = run_numerical_method(bundle, verification_profile="audit", **options)
    assert runtime["status"] == audit["status"] == "COMPLETE"
    assert runtime["r3"]["candidate_semantic_digest"] == audit["r3"]["candidate_semantic_digest"]
    for run, reference_count in ((runtime, 0), (audit, 1)):
        assert run["primary_generation_executions"] == 1
        assert run["reference_generation_executions"] == reference_count
        assert run["response_validation_status"] == "PASS"
        trace = run["r3"]["generation_trace"]
        assert len(trace) == 1+reference_count
        assert len({row["process_id"] for row in trace}) == len(trace)
        assert all(row["boundary"]["validated_requests"] == 2 for row in trace)
        assert all(len(row["boundary"]["generator_sha256"]) == 5 for row in trace)
        first = run["r3"]["first_mismatch_observation"]
        confirmed = run["r3"]["first_confirmed_failure"]
        assert first["target_calls"] == first["oracle_calls"] == 1
        assert confirmed["target_calls"] == confirmed["oracle_calls"] == 3
        assert confirmed["seconds_since_api_entry"] >= first["seconds_since_api_entry"]
        assert len(run["r3"]["discovery_events"]) == run["confirmed_new_failure_inputs"]
        assert run["r3"]["timing"]["end_to_end_wall"] >= run["cost"]["current_execution_seconds"]
        assert run["r3"]["timing"]["receipt_io"] is None
    assert runtime["equivalence_check_status"] == "NOT_RUN_IN_RUNTIME"
    assert audit["equivalence_check_status"] == "PASS_FULL_STRUCTURED_SEMANTICS"


@pytest.mark.parametrize("method", ["A", "B", "C"])
def test_strict_baselines_need_no_guide_and_share_clean_boundary(method, authored_evaluator):
    replay = [{"a":[0.5]*3, "b":[0.25]*3}] if method == "C" else []
    result = run_numerical_method(None, method=method, verification_profile="runtime",
        seed=17, size=2, max_examples=64, pair_budget=12, shrink_budget=0,
        replay_inputs=replay, contract=public_input_contract(lengths=[4]))
    assert result["status"] == "COMPLETE", result.get("error")
    assert result["guide_digest"] is None
    assert result["artifact_validation_status"] == "NOT_APPLICABLE_BASELINE_NO_GUIDE"
    assert result["response_validation_status"] == "PASS"
    assert result["primary_generation_executions"] == 1
    assert result["reference_generation_executions"] == 0
    assert result["boundary"]["validated_requests"] == 2
    assert result["r3"]["generation_trace"][0]["action"] == "baseline"


def test_audit_disagreement_aborts_before_source_callbacks(bundle, authored_evaluator, monkeypatch):
    from tomolab.discovery import numerical_response
    def disagree(*args):
        raise ValueError("authored semantic disagreement")
    monkeypatch.setattr(numerical_response, "assert_equivalent_plans", disagree)
    result = run_numerical_method(bundle, expected_digest=bundle["artifact"]["artifact_digest"],
        verification_profile="audit", seed=17, size=2, max_examples=32,
        pair_budget=6, shrink_budget=0)
    assert result["status"] == "ABORTED_EXECUTION_ERROR"
    assert result["equivalence_check_status"] == "FAIL"
    assert result["reference_generation_executions"] == 1
    assert authored_evaluator == {"target": 0, "oracle": 0}


def test_runtime_worker_timeout_is_explicit_failure(authored_evaluator, monkeypatch):
    from tomolab.discovery import numerical_boundary
    class FailedBoundary(NumericalBoundary):
        def request(self, action, **fields):
            raise ValueError("authored worker timed out")
    monkeypatch.setattr(numerical_boundary, "NumericalBoundary", FailedBoundary)
    result = run_numerical_method(None, method="B", verification_profile="runtime",
        size=2, max_examples=8, pair_budget=6, shrink_budget=0)
    assert result["status"] == "ABORTED_EXECUTION_ERROR"
    assert result["response_validation_status"] == "NOT_COMPLETED_EXECUTION_ERROR"
    assert result["equivalence_check_status"] == "NOT_RUN_IN_RUNTIME"
    assert result["boundary"]["validated_requests"] == 0
    assert authored_evaluator == {"target": 0, "oracle": 0}


def test_reference_startup_failure_does_not_count_unstarted_generation(bundle, authored_evaluator, monkeypatch):
    from tomolab.discovery import numerical_boundary
    class FailSecondBoundary(NumericalBoundary):
        starts = 0
        def __init__(self, **options):
            type(self).starts += 1
            if type(self).starts == 2:
                raise ValueError("authored reference startup failure")
            super().__init__(**options)
    monkeypatch.setattr(numerical_boundary, "NumericalBoundary", FailSecondBoundary)
    result = run_numerical_method(bundle, expected_digest=bundle["artifact"]["artifact_digest"],
        verification_profile="audit", size=2, max_examples=32, pair_budget=6, shrink_budget=0)
    assert result["status"] == "ABORTED_EXECUTION_ERROR"
    assert result["equivalence_check_status"] == "FAIL"
    assert result["primary_generation_executions"] == 1
    assert result["reference_generation_executions"] == 0
    assert len(result["r3"]["generation_trace"]) == 1
    assert result["r3"]["generation_trace"][0]["plan_completed"] is True
    assert authored_evaluator == {"target": 0, "oracle": 0}


def test_baseline_audit_does_not_add_an_unnecessary_reference(authored_evaluator):
    result = run_numerical_method(None, method="B", verification_profile="audit",
        size=2, max_examples=32, pair_budget=6, shrink_budget=0)
    assert result["status"] == "COMPLETE"
    assert result["primary_generation_executions"] == 1
    assert result["reference_generation_executions"] == 0
    assert result["equivalence_check_status"] == "NOT_APPLICABLE_BASELINE_SINGLE_GENERATION"
