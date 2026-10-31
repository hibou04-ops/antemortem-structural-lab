"""Authored functional diagnostics, never independent research projects."""
from copy import deepcopy

import pytest

from tomolab.discovery.online_engine import OnlinePolicy, run_online
from tomolab.discovery.online_learning import learn_mold
from tomolab.discovery.online_observe import observe, inspect_target
from tomolab.discovery.online_schema import input_identity
from tomolab.discovery.recursive_observe import (make_diagnostics, new_trace, observe_proposal,
    validate_trace, validate_pair_receipt, execute_pairs, validate_reservation, derive_label)
from tomolab.discovery.schema import digest

CONTRACT = dict(kind="sequence_int", low=-10, high=10, min_size=0, max_size=3)


def oracle(point):
    return point


def gain_target(point):
    return None if point and len(set(point)) == 1 else point


def loss_target(point):
    return None if point and any(x < 0 for x in point) and len(set(point)) > 1 else point


def make_mold():
    rows = [dict(input=p, status=s, contract=CONTRACT, source_identity="authored-fixture")
            for p,s in [([1,2], "PASS"),([1,1], "FAILURE")]]
    mold = learn_mold(rows, operator_grammar=["constantize"])
    return mold


def diagnostics(mold=None):
    return make_diagnostics(mold or make_mold(), experiment_contract_sha256=digest("authored-contract"),
        source_lineage_id="authored-lineage",project_id="authored-project",mechanism_id="authored-mechanism",
        run_id="authored-run",identity=dict(implementation_sha256=digest("target"),oracle_sha256=digest("oracle"),
            environment_sha256=digest("env"),reset_adapter_sha256=digest("reset"),purity_review_id="authored-pure-review"))


def fixed_trace():
    config=diagnostics()
    policy=OnlinePolicy(CONTRACT,method="C",seed=47,budget=63,structure=inspect_target(gain_target,CONTRACT,mode="black_box"))
    policy.attempts=2
    before=policy.state_digest()
    actual=deepcopy(policy).propose([1,2])
    trace=new_trace(config["public"])
    observe_proposal(policy,[1,2],actual,config=config["public"],trace=trace,
        seed=47,actual_calls_before=0,shadow_rule_state=None)
    assert policy.state_digest()==before
    assert len(trace["reservations"])==1
    return config,trace


def run_fixed(target=gain_target,reset=lambda:True):
    config,trace=fixed_trace()
    return execute_pairs(trace,config=config["public"],identity=config["identity"],target=target,oracle=oracle,
        contract=CONTRACT,structure=trace["reservations"][0]["state"]["structure"],reset=reset,tracing=False)


def test_same_anchor_separate_candidates_and_exact_cost():
    config,trace=fixed_trace()
    r=trace["reservations"][0]
    assert r["native_input"]==r["anchor_input"]==[1,2]
    assert r["common_input"]==[-1,-2]
    assert r["learned_input"]==[1,1]
    # Host transport is checked separately from post-worker pair costs.
    validate_trace(trace,config=config["public"],host_rows=[dict(input_digest=r["common_digest"],phase=r["phase"],target_calls=1)])
    result=run_fixed()
    assert result["cost"]["target_calls"]==result["cost"]["oracle_calls"]==6
    assert result["cost"]["reset_calls"]==6
    assert result["receipts"][0]["label"]=="gain"


@pytest.mark.parametrize("target,label",[(gain_target,"gain"),(loss_target,"loss"),(oracle,"neutral_pass"),(lambda p:None,"neutral_failure")])
def test_labels_come_from_actual_three_repeat_observations(target,label):
    receipt=run_fixed(target)["receipts"][0]
    assert receipt["label"]==label
    assert validate_pair_receipt(receipt)==receipt


def test_reset_failure_is_unknown_and_never_filled_with_pass():
    result=run_fixed(reset=lambda:False)
    assert result["receipts"][0]["label"]=="UNKNOWN"
    assert result["cost"]["target_calls"]==0
    assert result["cost"]["reset_calls"]==6
    assert result["status"]=="HOLD_MEASUREMENT"


def test_semantic_instability_stays_unknown_even_when_status_agrees():
    calls=[0]
    def unstable(point):
        calls[0]+=1
        return calls[0]
    assert run_fixed(unstable)["receipts"][0]["label"]=="UNKNOWN"


def test_partial_resource_limit_keeps_partial_cost_and_unknown():
    config,trace=fixed_trace()
    config["public"]["max_pair_calls"]=2
    result=execute_pairs(trace,config=config["public"],identity=config["identity"],target=gain_target,oracle=oracle,
        contract=CONTRACT,structure=trace["reservations"][0]["state"]["structure"],reset=lambda:True,tracing=False)
    assert result["cost"]["target_calls"]==2
    assert result["receipts"][0]["label"]=="UNKNOWN"
    assert "DIAGNOSTIC_RESOURCE_LIMIT" in result["receipts"][0]["unknown_reasons"]


def test_tampered_candidate_rejected_even_after_rehash():
    config,trace=fixed_trace()
    r=trace["reservations"][0]
    r["learned_input"]=[2,2]
    r["learned_digest"]=input_identity([2,2])
    r["reservation_id"]=digest({k:v for k,v in r.items() if k!="reservation_id"})
    with pytest.raises(ValueError,match="reconstruction"):
        validate_reservation(r,config=config["public"])


def test_final_feedback_and_unknown_raw_fields_rejected():
    receipt=run_fixed()["receipts"][0]
    receipt["split"]="final"
    receipt["pair_receipt_sha256"]=digest({k:v for k,v in receipt.items() if k!="pair_receipt_sha256"})
    with pytest.raises(PermissionError):
        validate_pair_receipt(receipt)
    receipt=run_fixed()["receipts"][0]
    receipt["branches"]["common"][0]["actual"]="private"
    receipt["pair_receipt_sha256"]=digest({k:v for k,v in receipt.items() if k!="pair_receipt_sha256"})
    with pytest.raises(ValueError,match="fields"):
        validate_pair_receipt(receipt)


def test_real_worker_diagnostics_preserve_common_state_feedback_and_budget():
    mold=make_mold()
    config=diagnostics(mold)
    args=dict(method="C",seed=47,budget=72,shrink_budget=9,max_seconds=30,mode="black_box")
    before=run_online(oracle,oracle,CONTRACT,**args)
    after=run_online(oracle,oracle,CONTRACT,diagnostics=config,diagnostic_reset=lambda:True,**args)
    assert before["status"]==after["status"]=="COMPLETE"
    assert before["observations"]==after["observations"]
    def events(result):
        return [{k:v for k,v in row.items() if k!="seconds"} for row in result["events"]]
    assert events(before)==events(after)
    assert before["scheduler"]==after["scheduler"]
    assert before["target_calls"]==after["target_calls"]
    assert after["paired_diagnostics"]["status"] in ("COMPLETE","HOLD_MEASUREMENT")
    assert after["diagnostic_trace"]["status"]=="COMPLETE"
    assert after["paired_diagnostics"]["receipts"]
    assert after["paired_diagnostics"]["cost"]["target_calls"]==6*len(after["paired_diagnostics"]["receipts"])
    assert not before.get("diagnostic_trace")
