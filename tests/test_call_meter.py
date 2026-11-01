"""Hard entry limits on authored callables; no external target/OCI/API run."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

import pytest

from tomolab.discovery.call_meter import (HardCallMeter,HardBudgetExhausted,ResetNotVerified,
    independent_arm_meters,parity_receipt)
from tomolab.discovery.online_engine import run_online
from tomolab.discovery.recursive_observe import execute_pairs
from tomolab.discovery.recursive_api import create_generation,update_generation,run_generation
from tomolab.discovery.recursive_store import GenerationStore
from tomolab.structural_probe import _measure_pair,run_probe
from test_recursive_observe import fixed_trace,gain_target,oracle as paired_oracle,CONTRACT as PAIR_CONTRACT
from test_recursive_policy import authored_mold,fixture_batch,CONTRACT


def prep():
    return dict(scope="AUTHORED_STATIC_TEST_PRIOR",target_calls=0,oracle_calls=0,
                prior_development_cost="SEPARATE_PRESERVED_GENERATION_LEDGER")


def callbacks():
    actual=dict(target=0,oracle=0,reset=0)
    def target(xs):
        actual["target"]+=1
        return sum(xs)
    def oracle(xs):
        actual["oracle"]+=1
        return sum(xs)
    def reset():
        actual["reset"]+=1
        return True
    return actual,target,oracle,reset


def test_atomic_asymmetric_budget_checks_precede_reset_and_both_callable_entries():
    actual,t,o,r=callbacks()
    meter=HardCallMeter(2,1,arm_id="C")
    meter.evaluate(t,o,[1],CONTRACT,reset=r,phase="native")
    with pytest.raises(HardBudgetExhausted): meter.evaluate(t,o,[2],CONTRACT,reset=r,phase="confirmation")
    assert actual==dict(target=1,oracle=1,reset=1)
    snap=meter.snapshot()
    assert (snap["target_calls_used"],snap["oracle_calls_used"],snap["fresh_reset_count"])==(1,1,1)
    assert snap["budget_blocked_requests"]==1 and snap["unknown_observations"]==0
    assert snap["events"][-1]["kind"]=="NO_EXECUTION_BUDGET_EXHAUSTED"
    assert snap["unused_target_calls"]==1 and snap["unused_oracle_calls"]==0


def test_concurrent_requests_cannot_overrun_one_atomic_pair_budget():
    actual,t,o,r=callbacks()
    meter=HardCallMeter(1,1,arm_id="threaded-authored-control")
    def request(index):
        try: meter.evaluate(t,o,[index],CONTRACT,reset=r);return "EXECUTED"
        except HardBudgetExhausted:return "NO_EXECUTION"
    with ThreadPoolExecutor(max_workers=5) as pool: results=list(pool.map(request,range(5)))
    assert results.count("EXECUTED")==1 and results.count("NO_EXECUTION")==4
    assert actual==dict(target=1,oracle=1,reset=1)


def test_reset_reentry_is_rejected_before_any_inner_or_outer_callable_entry():
    actual,t,o,r=callbacks();meter=HardCallMeter(1,1,arm_id="C")
    def reentrant_reset():
        actual["reset"]+=1
        meter.evaluate(t,o,[2],CONTRACT,reset=None,phase="forbidden_nested_reset")
        return True
    with pytest.raises(ResetNotVerified):meter.evaluate(t,o,[1],CONTRACT,reset=reentrant_reset)
    assert actual==dict(target=0,oracle=0,reset=1)
    snap=meter.snapshot()
    assert snap["target_calls_used"]==snap["oracle_calls_used"]==snap["fresh_reset_count"]==0
    assert snap["reset_calls_used"]==snap["reset_failures"]==snap["reentry_rejections"]==1
    # A failed measurement releases the active guard, while preserving error
    # evidence; it does not consume a fictitious successful pair.
    meter.evaluate(t,o,[3],CONTRACT,reset=None)
    assert meter.snapshot()["target_calls_used"]==meter.snapshot()["oracle_calls_used"]==1


def test_target_reentry_cannot_spend_outer_oracle_capacity_or_create_a_fake_failure():
    actual,t,o,r=callbacks();meter=HardCallMeter(2,1,arm_id="C")
    def outer_target(xs):
        actual["target"]+=1
        meter.evaluate(t,o,[2],CONTRACT,reset=None,phase="forbidden_nested_target")
        return sum(xs)
    observation=meter.evaluate(outer_target,o,[1],CONTRACT,reset=None)
    assert actual==dict(target=1,oracle=1,reset=0)
    assert observation["feedback"]["status"]=="EXECUTION_ERROR"
    snap=meter.snapshot()
    assert snap["target_calls_used"]==snap["oracle_calls_used"]==1 and snap["reentry_rejections"]==1
    assert snap["unknown_observations"]==1 and snap["unresolved_measurement_events"]==1


@pytest.mark.parametrize("violation",["reported_counter","missing_entries"])
def test_observer_counter_contract_violation_is_unknown_with_actual_entries_preserved(monkeypatch,violation):
    from tomolab.discovery import online_observe
    original=online_observe.observe
    def dishonest_observer(*args,**kwargs):
        if violation=="missing_entries":
            return dict(target_calls=0,oracle_calls=0,feedback=dict(status="PASS"))
        row=original(*args,**kwargs)
        row["target_calls"]=0
        return row
    monkeypatch.setattr(online_observe,"observe",dishonest_observer)
    actual,t,o,r=callbacks();meter=HardCallMeter(1,1,arm_id="C")
    with pytest.raises(ValueError,match="actual metered entries"):
        meter.evaluate(t,o,[1],CONTRACT,reset=r)
    expected=1 if violation=="reported_counter" else 0
    assert actual==dict(target=expected,oracle=expected,reset=1)
    snap=meter.snapshot()
    assert snap["target_calls_used"]==snap["oracle_calls_used"]==expected and snap["fresh_reset_count"]==1
    assert snap["unknown_observations"]==1
    assert snap["events"][-1]["status"]=="UNKNOWN_MEASUREMENT_ERROR" and snap["events"][-1]["unknown"] is True


@pytest.mark.parametrize("value",[True,1.0,-1,10001,"24"])
def test_budgets_are_exact_bounded_integers(value):
    with pytest.raises(ValueError): HardCallMeter(value,arm_id="C")


def test_invalid_input_and_unsupported_async_do_not_spend_or_reset():
    actual,t,o,r=callbacks();meter=HardCallMeter(24,arm_id="C")
    row=meter.evaluate(t,o,[True],CONTRACT,reset=r)
    assert row["feedback"]["status"]=="INVALID_INPUT" and actual==dict(target=0,oracle=0,reset=0)
    async def unsupported(xs): return xs
    with pytest.raises(ValueError): meter.evaluate(unsupported,o,[],CONTRACT,reset=r)
    assert actual==dict(target=0,oracle=0,reset=0)


def test_reset_failure_and_captured_oracle_exception_are_not_zero_filled():
    actual,t,o,r=callbacks();meter=HardCallMeter(24,arm_id="C")
    def bad_reset():
        actual["reset"]+=1
        raise RuntimeError("authored reset failure")
    with pytest.raises(ResetNotVerified):meter.evaluate(t,o,[1],CONTRACT,reset=bad_reset)
    assert actual==dict(target=0,oracle=0,reset=1)
    snap=meter.snapshot()
    assert snap["reset_calls_used"]==snap["reset_failures"]==1 and snap["fresh_reset_count"]==0
    def broken_oracle(xs):
        actual["oracle"]+=1
        raise ValueError("authored Oracle error")
    row=meter.evaluate(t,broken_oracle,[1],CONTRACT,reset=r)
    assert row["feedback"]["status"]=="ORACLE_ERROR"
    assert actual==dict(target=1,oracle=1,reset=2)
    other=HardCallMeter(24,arm_id="RELATIONAL")
    result=parity_receipt({"C":meter,"RELATIONAL":other},preparation_cost_ledger=prep())
    assert result["status"]=="HOLD_UNRESOLVED_OBSERVATION" and result["unresolved_events"]==2


def test_arms_have_equal_caps_but_independent_ledgers_and_keep_unused_budget():
    meters=independent_arm_meters(["C","RELATIONAL"],target_budget=24)
    empty=parity_receipt(meters,preparation_cost_ledger=prep())
    assert empty["status"]=="HOLD_NO_EVALUATIONS" and empty["measurements_present_in_all_arms"] is False
    actual,t,o,r=callbacks();meters["C"].evaluate(t,o,[1],CONTRACT,reset=r)
    assert meters["RELATIONAL"].snapshot()["target_calls_used"]==0
    result=parity_receipt(meters,preparation_cost_ledger=prep())
    assert result["identical_hard_caps"] is True and result["actual_calls_equal"] is False
    assert result["arms"]["C"]["unused_target_calls"]==23
    assert result["arms"]["RELATIONAL"]["unused_target_calls"]==24
    assert result["utility"]=="NOT_ESTABLISHED" and result["no_regression_guaranteed"] is False
    with pytest.raises(ValueError): parity_receipt({"C":meters["C"],"RELATIONAL":meters["C"]},preparation_cost_ledger=prep())
    with pytest.raises(ValueError): parity_receipt({"C":meters["C"],"RELATIONAL":HardCallMeter(48,arm_id="RELATIONAL")},preparation_cost_ledger=prep())


@pytest.mark.parametrize("method",list("ABCD"))
@pytest.mark.parametrize("budget",[24,48])
def test_every_online_arm_uses_actual_host_meter_and_same_fresh_reset_budget(method,budget):
    actual,t,o,r=callbacks();meter=HardCallMeter(budget,arm_id=method)
    mold=authored_mold() if method=="D" else None
    result=run_online(t,o,CONTRACT,method=method,mold=mold,budget=budget,shrink_budget=0,
        seed=47,max_seconds=15,mode="black_box",call_meter=meter,fresh_reset=r,hard_budget=True)
    assert result["status"]=="COMPLETE"
    assert result["target_calls"]==result["oracle_calls"]==actual["target"]==actual["oracle"]==budget
    assert actual["reset"]==result["fresh_reset_count"]==result["reset_calls"]==budget
    snap=result["hard_call_meter"]
    assert snap["target_calls_used"]==snap["oracle_calls_used"]==budget and snap["unused_target_calls"]==0
    assert sum(p["target_calls_used"] for p in snap["phases"].values())==budget
    assert all(event["feedback"].keys() <= {"status","input_digest","coverage","branch_distance","contract_checked","exception_type","exception_location"} for event in result["events"])


def test_singleton_domain_stops_early_instead_of_dummy_filling_the_budget():
    actual=dict(t=0,o=0,r=0)
    def target(x):actual["t"]+=1;return x
    def oracle(x):actual["o"]+=1;return x
    def reset():actual["r"]+=1;return True
    meter=HardCallMeter(24,arm_id="C")
    result=run_online(target,oracle,dict(kind="int",low=0,high=0),method="C",budget=24,shrink_budget=0,
        call_meter=meter,fresh_reset=reset,hard_budget=True,max_seconds=10)
    assert actual==dict(t=1,o=1,r=1)
    assert result["hard_call_meter"]["unused_target_calls"]==23 and result["unknown"]==0


def test_native_confirmation_and_shrinking_are_charged_in_the_same_arm_meter():
    actual=dict(t=0,o=0,r=0)
    def target(x):actual["t"]+=1;return x+1
    def oracle(x):actual["o"]+=1;return x
    def reset():actual["r"]+=1;return True
    meter=HardCallMeter(48,arm_id="C")
    result=run_online(target,oracle,dict(kind="int",low=-10,high=10),method="C",budget=48,shrink_budget=9,
        call_meter=meter,fresh_reset=reset,hard_budget=True,seed=47,max_seconds=15)
    snap=result["hard_call_meter"]
    assert actual["t"]==actual["o"]==actual["r"]==snap["target_calls_used"]<=48
    assert snap["phases"]["online_confirmation"]["target_calls_used"]>0
    assert any("shrink" in phase for phase in snap["phases"])


def test_paired_remeasurement_spends_remaining_budget_in_the_same_carrier_meter():
    config,trace=fixed_trace();meter=HardCallMeter(7,arm_id="C_DIAGNOSTIC")
    reset=lambda:True
    meter.evaluate(gain_target,paired_oracle,[-1,-2],PAIR_CONTRACT,reset=reset,phase="carrier")
    result=execute_pairs(trace,config=config["public"],identity=config["identity"],target=gain_target,
        oracle=paired_oracle,contract=PAIR_CONTRACT,structure=trace["reservations"][0]["state"]["structure"],
        reset=reset,tracing=False,call_meter=meter)
    assert result["status"]=="COMPLETE" and result["cost"]["target_calls"]==6
    snap=meter.snapshot()
    assert snap["target_calls_used"]==snap["oracle_calls_used"]==snap["fresh_reset_count"]==7
    assert snap["phases"]["carrier"]["target_calls_used"]==1
    assert snap["phases"]["paired_common"]["target_calls_used"]==snap["phases"]["paired_learned"]["target_calls_used"]==3


def test_paired_group_with_insufficient_remaining_budget_does_not_enter_or_invent_unknown_outcomes():
    config,trace=fixed_trace();meter=HardCallMeter(5,arm_id="C_DIAGNOSTIC")
    actual,t,o,r=callbacks()
    result=execute_pairs(trace,config=config["public"],identity=config["identity"],target=t,oracle=o,
        contract=PAIR_CONTRACT,structure=trace["reservations"][0]["state"]["structure"],reset=r,tracing=False,call_meter=meter)
    assert actual==dict(target=0,oracle=0,reset=0) and result["receipts"]==[]
    assert result["status"]=="HOLD_MEASUREMENT" and result["unknown_reasons"]==["HARD_BUDGET_EXHAUSTED_NO_EXECUTION"]
    assert meter.snapshot()["unknown_observations"]==0 and meter.snapshot()["budget_blocked_requests"]==1


def test_nondeterministic_paired_semantics_hold_without_erasing_actual_calls():
    state={"i":0}
    def unstable(xs):state["i"]+=1;return state["i"]
    def reference(xs):return 0
    def reset():return True
    meter=HardCallMeter(24,arm_id="RELATIONAL",reset_per_entry=True)
    receipt=_measure_pair(unstable,reference,[1],[2],reset=reset,structure={},call_meter=meter)
    assert receipt["label"]=="UNKNOWN" and receipt["cost"]["target_calls"]==receipt["cost"]["oracle_calls"]==6
    other=HardCallMeter(24,arm_id="C",reset_per_entry=True)
    result=parity_receipt({"RELATIONAL":meter,"C":other},preparation_cost_ledger=prep())
    assert result["status"]=="HOLD_UNRESOLVED_OBSERVATION" and result["arms"]["RELATIONAL"]["unresolved_measurement_events"]==1


def test_g0_g1_g2_restore_fixed_selectors_and_use_independent_evaluation_meters(tmp_path):
    mold=authored_mold();store=tmp_path/"generations.jsonl"
    create_generation(store,mold,CONTRACT)
    first,manifest=fixture_batch([("meter-fixture-a","gain"),("meter-fixture-b","gain")])
    update_generation(store,first,manifest,generation_id="G1",parent_id="G0")
    second,manifest2=fixture_batch([("meter-fixture-a","loss"),("meter-fixture-b","loss")],run="meter-wave-two")
    update_generation(store,second,manifest2,generation_id="G2",parent_id="G1")
    frozen=store.read_bytes()
    meters=independent_arm_meters(["G0","G1","G2"],target_budget=24)
    generations={r["generation"]["generation_id"]:r["generation"] for r in GenerationStore(store).records()}
    for name in meters:
        actual,t,o,r=callbacks()
        receipt=run_generation(store,mold,t,o,CONTRACT,generation_id=name,execution_id="meter-"+name,
            output=tmp_path/(name+".json"),allow_local_execution=True,budget=24,shrink_budget=0,mode="black_box",
            call_meter=meters[name],fresh_reset=r,hard_budget=True)
        assert receipt["run"]["hard_call_meter"]["arm_id"]==name
        assert receipt["training_cost_ledger"]==generations[name]["cost_ledger"]
        assert 0<actual["target"]==actual["oracle"]==actual["reset"]<=24
    assert store.read_bytes()==frozen
    parity=parity_receipt(meters,preparation_cost_ledger={"preserved_generation_cost_ledgers":{name:g["cost_ledger"] for name,g in generations.items()}})
    assert parity["status"]=="PASS" and parity["identical_hard_caps"]


@pytest.mark.parametrize("budget",[24,48])
def test_equal_cost_probe_is_actual_c_vs_prior_relational_with_all_calls_metered(tmp_path,budget):
    summary=run_probe(tmp_path/str(budget),allow_local_execution=True,budget=budget,equal_cost=True)
    assert summary["status"]=="FUNCTIONAL_COMPLETE" and summary["baseline_method"]=="E9_C"
    assert summary["relational_arm"]=="COMMON_PRIOR_RELATIONAL_NOT_SOURCE_LEARNED_D"
    assert summary["hard_budget_parity"]=="PASS" and summary["actual_call_spending_equal"] is True
    assert summary["actual"]==dict(target_calls=8*budget,oracle_calls=8*budget,reset_calls=16*budget)
    for i,row in enumerate(summary["cases"],1):
        assert row["native_baseline"]["method"]=="E9_C"
        parity=row["hard_call_parity"]
        for arm in parity["arms"].values():
            assert arm["target_budget"]==arm["oracle_budget"]==budget
            assert arm["target_calls_used"]==arm["oracle_calls_used"]==budget
            assert arm["fresh_reset_count"]==2*budget and arm["reset_per_entry"] is True
            assert arm["unknown_observations"]==arm["reset_failures"]==arm["unresolved_measurement_events"]==0
        raw=json.loads((tmp_path/str(budget)/("case-"+str(i)+".json")).read_text())
        assert raw["native_baseline"]["hard_call_meter"]["target_calls_used"]==budget
        assert raw["relational"]["hard_call_meter"]["target_calls_used"]==budget
    assert summary["utility"]=="NOT_ESTABLISHED" and summary["policy_no_regression"]=="NOT_GUARANTEED"


@pytest.mark.parametrize("role",["reset","target","oracle"])
@pytest.mark.parametrize("swallow",[False,True])
def test_all_callback_reentry_paths_preserve_hard_caps_and_unknown_evidence(role,swallow):
    from tomolab.discovery.call_meter import MeterReentryError
    actual,t,o,r=callbacks();meter=HardCallMeter(1,1,arm_id="nested-boundary")
    def nested(value=None):
        actual[role]+=1
        try:
            meter.evaluate(t,o,[2],CONTRACT,reset=r,phase="nested")
        except MeterReentryError:
            if not swallow:raise
        return True if role=="reset" else sum(value)
    if role=="reset":
        with pytest.raises(ResetNotVerified):meter.evaluate(t,o,[1],CONTRACT,reset=nested)
        assert actual==dict(target=0,oracle=0,reset=1)
    else:
        row=meter.evaluate(nested if role=="target" else t,nested if role=="oracle" else o,[1],CONTRACT,reset=r)
        assert row["feedback"]["status"]=="EXECUTION_ERROR"
        assert actual==dict(target=1,oracle=1,reset=1)
    snap=meter.snapshot()
    assert snap["reentry_rejections"]==snap["unresolved_measurement_events"]==1
    assert 0<=snap["target_calls_used"]<=1 and 0<=snap["oracle_calls_used"]<=1
    other=HardCallMeter(1,1,arm_id="other")
    assert parity_receipt({"nested-boundary":meter,"other":other},preparation_cost_ledger=prep())["status"]=="HOLD_UNRESOLVED_OBSERVATION"
