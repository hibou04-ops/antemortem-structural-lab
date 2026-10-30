"""Host budget/phase accounting uses authored callbacks, never research runs."""
from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from tomolab.discovery import numerical_service as service
from tomolab.discovery import numerical_source as source
from tomolab.discovery.numerical_guidance import numerical_input_digest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bundle():
    folder = ROOT/"examples/numerical"
    return {"artifact":json.loads((folder/"source-guide.json").read_text()),
            "approval_receipt":json.loads((folder/"source-approval.json").read_text())}


@pytest.fixture
def authored_callbacks(monkeypatch):
    points = [{"a":[0.5]*4,"b":[0.25]*4}, {"a":[0.25]*4,"b":[0.5]*4}]
    def generate(*args, **kwargs):
        return {"candidates":[{"inputs":p,"origin":"AUTHORED_TEST", "transform":"AUTHORED", "recipe_id":None} for p in points]}
    monkeypatch.setattr(service,"generate_numerical_candidates",generate)
    monkeypatch.setattr(source,"target_result",lambda p:{"authored":1})
    monkeypatch.setattr(source,"oracle_result",lambda p:{"authored":2})
    monkeypatch.setattr(source,"compare_results",lambda a,b:a==b)
    monkeypatch.setattr(source,"classify_mechanism",lambda *a:"AUTHORED_COUNTER_MISMATCH")
    return points


def run(bundle, **options):
    return service.run_numerical_method(bundle,expected_digest=bundle["artifact"]["artifact_digest"],
        method=options.pop("method","B"),pair_budget=options.pop("pair_budget",12),shrink_budget=0,**options)


def test_each_new_failure_is_confirmed_with_two_separately_paid_replays(bundle,authored_callbacks):
    result = run(bundle)
    assert result["status"] == "COMPLETE"
    assert result["confirmed_new_failure_inputs"] == 2
    assert result["target_calls"] == result["oracle_calls"] == 6
    assert result["first_new_failure_target_calls"] == 1
    assert result["phase_counts"]["new_failure_replay"]["source_oracle_pairs"] == 4
    assert result["guide_unchanged"] and not result["allow_release"]


def test_total_call_cap_and_known_identity_rejection_are_enforced(bundle,authored_callbacks):
    result = run(bundle,pair_budget=3,excluded_digests=[numerical_input_digest(authored_callbacks[0])])
    assert result["confirmed_new_failure_inputs"] == 1
    assert result["target_calls"] == result["oracle_calls"] == 3
    assert result["first_evaluated_valid_inputs"] == 1


def test_oracle_error_is_recorded_and_never_becomes_a_normal_training_label(bundle,authored_callbacks,monkeypatch):
    def broken(point):
        raise ValueError("authored Oracle failure")
    monkeypatch.setattr(source,"oracle_result",broken)
    result = run(bundle)
    assert result["status"] == "ABORTED_EXECUTION_ERROR"
    assert result["oracle_errors"] == 1 and result["target_calls"] == 0
    assert result["oracle_calls"] == 1
    assert result["rows"][0]["status"] == "ORACLE_ERROR"
    assert "failed" not in result["rows"][0]


@pytest.mark.parametrize("which",["oracle_result","target_result"])
def test_nonfinite_result_is_quarantined_in_a_serializable_error_receipt(bundle,authored_callbacks,monkeypatch,which):
    monkeypatch.setattr(source,which,lambda p:{"computable":True,"value":float("nan")})
    result = run(bundle)
    assert result["status"] == "ABORTED_EXECUTION_ERROR"
    assert "failed" not in result["rows"][0]
    json.dumps(result,allow_nan=False)


def test_c_pays_for_known_replay_without_counting_it_as_a_new_failure(bundle,authored_callbacks):
    result = run(bundle,method="C",replay_inputs=[authored_callbacks[0]])
    assert result["initial_known_replays"] == result["known_input_replay_calls"] == 3
    assert result["confirmed_new_failure_inputs"] == 1
    assert result["first_new_failure_target_calls"] == 4


@pytest.mark.parametrize("value",[float("nan"),float("inf"),-1])
def test_invalid_preparation_costs_fail_before_any_callbacks(bundle,value):
    with pytest.raises(ValueError,match="preparation"):
        run(bundle,setup_seconds=value)


def test_comparison_counts_distinct_input_union_across_seeds(bundle,authored_callbacks):
    # Two trials intentionally yield the same authored rows. They are two
    # confirmations but only two distinct inputs per method, never four.
    result = service.run_numerical_comparison(bundle,
        expected_digest=bundle["artifact"]["artifact_digest"],seeds=(13,47),
        pair_budget=32,shrink_budget=0,size=2,max_examples=8,
        replay_inputs=[{"a":[0.1]*3,"b":[0.1]*3}])
    for method in ("A","B","C"):
        summary = result["summaries"][method]
        assert summary["confirmed_new_failure_inputs"] == 2
        assert summary["confirmed_new_failure_inputs_trial_sum"] == 4
        assert summary["unique_fresh_generation_valid_inputs"] == 2
    assert result["allow_release"] is False
    accounting = result["input_counting"]
    assert accounting["trial_sum_is_not_distinct_count"]
    assert accounting["batch_distinct_confirmed_new_failure_inputs"] >= 2
    assert accounting["actual_first_evaluations_across_entire_batch"] == sum(
        accounting["actual_first_evaluations_across_all_methods_and_shrink_by_execution_order"].values())


def test_cli_requires_explicit_execution_before_source_callback(monkeypatch,capsys):
    from tomolab.cli import main
    def forbidden(*args,**kwargs):
        raise AssertionError("Source callback reached without execution opt-in")
    monkeypatch.setattr(source,"target_result",forbidden)
    folder = ROOT/"examples/numerical"
    with pytest.raises(SystemExit) as error:
        main(["numerical-run","--guide",str(folder/"source-guide.json"),
            "--approval",str(folder/"source-approval.json"),
            "--expected-digest-file",str(folder/"source-guide.sha256")])
    assert error.value.code == 2
