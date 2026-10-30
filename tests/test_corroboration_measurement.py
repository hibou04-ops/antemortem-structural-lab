"""Authored receipt arithmetic only: no target library or Oracle execution."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("e8r4_measurement",ROOT/"scripts/evaluate-e8r4.py")
measurement=importlib.util.module_from_spec(spec)
spec.loader.exec_module(measurement)


@pytest.fixture
def declaration():
    return measurement.read(ROOT/"docs/E8_R4_EVALUATION_CONTRACT.json")


def authored(declaration,failures=None):
    failures=failures or {}
    runs=[];meters=[];plans=[]
    for index,label in enumerate(measurement.schedule(declaration)):
        count=failures.get((label["implementation_id"],label["method"]),0)
        rows=[dict(input_digest=str(i),confirmed_failure=True,
            comparison={"violation_category":"AUTHORED_CATEGORY"},
            normalized={"computability":"DEFINED"}) for i in range(count)]
        event=None if not count else dict(seconds_since_execution_api_entry=0.25,
            target_calls=3,oracle_calls=3,phase="fresh_generation")
        run=dict(status="COMPLETE",target_calls=max(1,count*3),oracle_calls=max(1,count*3),
            confirmed_contract_violation_inputs=count,rows=rows,first_confirmed_failure=event,
            oracle_errors=0,not_comparable=0,replay_mismatches=0,
            primary_generation_executions=1,reference_generation_executions=0)
        runs.append(dict(index=index,**label,run=run))
        meters.append(dict(index=index,api_entry_offset_seconds=0.1,
            execution_through_receipt_flush_seconds=1.0))
        plans.append(dict(index=index,planning_outer_seconds=2.0))
    return runs,meters,plans


def test_schedule_is_balanced_and_has_exactly_six_fresh_seed_runs_each(declaration):
    measurement.validate_declaration(declaration)
    rows=measurement.schedule(declaration)
    assert len(rows)==48
    for implementation in measurement.IMPLEMENTATIONS:
        for method in measurement.METHODS:
            assert [row["seed"] for row in rows if row["implementation_id"]==implementation and row["method"]==method]==declaration["seeds"]
    assert rows[:4]==[dict(implementation_id=measurement.IMPLEMENTATIONS[0],method=m,seed=1103) for m in "ABCD"]
    assert rows[8]["implementation_id"]==measurement.IMPLEMENTATIONS[1]


@pytest.mark.parametrize("field,value",[("seeds",[13,47,89,103,227,389]),("run_count",49),
    ("publication_authorized",True),("final_evaluation_authorized",True)])
def test_changed_registered_contract_is_rejected(declaration,field,value):
    declaration[field]=value
    with pytest.raises(ValueError):
        measurement.validate_declaration(declaration)


def test_all_negative_runs_have_no_made_up_first_failure_or_advantage(declaration):
    runs,meters,plans=authored(declaration)
    result=measurement.summarize_runs(runs,meters,plans,declaration)
    assert result["status"]=="COMPLETE"
    assert result["outcome"]=="NO_CONFIRMED_FAILURE_WITHIN_BUDGET"
    assert result["added_value_over_B"]==result["added_value_over_C"]=="NOT_IDENTIFIABLE_NO_CONFIRMED_FAILURE"
    for methods in result["summaries"].values():
        for row in methods.values():
            assert row["first_confirmed_failure"]==[None]*6
            assert row["fixed_budget_discoveries"]==0


def test_more_inputs_of_the_same_detection_do_not_create_breadth_advantage(declaration):
    implementation=measurement.IMPLEMENTATIONS[0]
    runs,meters,plans=authored(declaration,{(implementation,"B"):1,(implementation,"C"):1,(implementation,"D"):4})
    result=measurement.summarize_runs(runs,meters,plans,declaration)
    assert result["outcome"]=="CONFIRMED_CONTRACT_VIOLATIONS_WITHIN_BUDGET"
    assert result["added_value_over_B"]==result["added_value_over_C"]=="NO_ADDITIONAL_DETECTION_BREADTH_OBSERVED"
    row=result["summaries"][implementation]["D"]
    assert row["distinct_confirmed_violation_inputs"]==4
    assert row["mechanism_count"]=="REQUIRES_SEPARATE_MECHANISTIC_REVIEW_NOT_INPUT_OR_CATEGORY_COUNT"
    assert row["first_confirmed_failure"][0]["execution_run_outer_seconds"]==0.35
    assert row["first_confirmed_failure"][0]["prepaid_plan_plus_run_event_seconds"]==2.35


def test_single_guide_preparation_is_shared_over_exactly_twelve_actual_D_uses(declaration):
    runs,meters,plans=authored(declaration)
    result=measurement.summarize_runs(runs,meters,plans,declaration,
        shared_execution_seconds=8.0,shared_planning_seconds=8.0,
        preparation_costs={"shared_guide_preparation_seconds":20.0})
    for implementation in measurement.IMPLEMENTATIONS:
        base=result["summaries"][implementation]["B"]
        guided=result["summaries"][implementation]["D"]
        assert base["prepared_seconds"]==20.0
        assert guided["prepared_seconds"]==20.0
        assert guided["cold_measured_subtotal_seconds"]==30.0
        assert guided["D_guide_total_actual_reuse_count"]==12
        assert base["cold_measured_subtotal_seconds"]==20.0
    assert sum(result["summaries"][name]["D"]["guide_preparation_share_seconds"] for name in measurement.IMPLEMENTATIONS)==20.0


@pytest.mark.parametrize("seconds",[-1.0,float("nan"),float("inf"),True])
def test_unmeasured_or_invalid_cost_is_not_silently_zero(declaration,seconds):
    runs,meters,plans=authored(declaration)
    meters[0]["execution_through_receipt_flush_seconds"]=seconds
    with pytest.raises(ValueError):
        measurement.summarize_runs(runs,meters,plans,declaration)


def test_partial_batch_is_not_reported_as_completed_or_no_failure_proof(declaration):
    runs,meters,plans=authored(declaration)
    result=measurement.summarize_runs(runs[:2],meters[:2],plans,declaration)
    assert result["status"]=="PARTIAL"
    assert result["outcome"]=="INCONCLUSIVE_PARTIAL_EXECUTION"
    assert result["all_methods_no_failure"] is None
    assert result["added_value_over_B"]==result["added_value_over_C"]=="INCONCLUSIVE_PARTIAL_EXECUTION"


def test_actual_over_budget_run_cannot_contribute_discovery(declaration):
    runs,meters,plans=authored(declaration)
    runs[0]["run"]["target_calls"]=97
    with pytest.raises(ValueError):
        measurement.summarize_runs(runs,meters,plans,declaration)


def test_exclusive_receipts_preserve_first_consumption(tmp_path):
    file=tmp_path/"START.json"
    measurement.save(file,{"started":True})
    with pytest.raises(FileExistsError):
        measurement.save(file,{"started":False})
    assert measurement.read(file)=={"started":True}


def test_actual_entry_observer_restores_and_forwards_surrounding_and_nested_hooks():
    original=sys.getprofile()
    events=[]
    def previous(frame,event,arg):
        if event=="call" and frame.f_code.co_name=="authored_helper":
            events.append("called")
    def authored_helper():
        return 1
    try:
        sys.setprofile(previous)
        with measurement.NumericEntryCounter() as counter:
            authored_helper()
            forwarding=sys.getprofile()
            def nested(frame,event,arg):
                forwarding(frame,event,arg)
            sys.setprofile(nested)
            authored_helper()
            sys.setprofile(forwarding)
        assert sys.getprofile() is previous
        assert events==["called","called"]
        assert not any(counter.counts.values())
    finally:
        sys.setprofile(original)


@pytest.mark.parametrize("left,right,verdict",[
    (["one"],[],"ADDITIONAL_DETECTION_BREADTH_OBSERVED"),
    ([],["one"],"DETECTION_LOSS_OBSERVED"),
    (["one"],["two"],"MIXED_DETECTION_BREADTH_NO_OVERALL_SUPERIORITY")])
def test_detection_advantage_and_loss_are_separate(left,right,verdict):
    assert measurement.compare_detection(left,right)==verdict
