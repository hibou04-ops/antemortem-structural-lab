"""Authored fixtures test functionality and refusal, never real-project utility."""
import json
from copy import deepcopy

import pytest

from tomolab import structural_probe as probe
from tomolab.discovery.relational_candidates import extract_relational_signature,propose_relational_candidates
from tomolab.discovery.online_observe import inspect_target


def test_explicit_execution_opt_in_precedes_workspace_and_calls(tmp_path,monkeypatch):
    def forbidden(*a,**kw):
        raise AssertionError("must not execute")
    monkeypatch.setattr(probe,"run_online",forbidden)
    with pytest.raises(PermissionError): probe.run_probe(tmp_path/"absent")
    assert not (tmp_path/"absent").exists()


@pytest.mark.parametrize("point",[[],[0],[1],[-1],[0,0,0,0,0],[1,1,1,1,1]])
def test_authored_functions_agree_with_mathematical_references_on_trivial_inputs(point):
    for _,target,reference in probe._cases():
        original=deepcopy(point)
        assert target(point)==reference(point)
        assert point==original


def test_each_mechanism_has_a_valid_relation_candidate_and_actual_repeated_failure():
    for operator,target,oracle in probe._cases():
        signature=extract_relational_signature(target,probe.CONTRACT)
        result=propose_relational_candidates([1],probe.CONTRACT,signature,mutator_id=operator)
        pairs=[probe._measure_pair(target,oracle,[1],row["input"],reset=probe._reset_authored_fixture,
                structure=inspect_target(target,probe.CONTRACT)) for row in result["candidates"]]
        assert any(r["label"]=="gain" for r in pairs)
        for pair in pairs:
            assert pair["cost"]["target_calls"]==pair["cost"]["oracle_calls"]==6
            assert pair["cost"]["reset_calls"]==12
            assert pair["evidence_class"]=="DEVELOPMENT_SYNTHETIC_EXPOSED"


def test_reset_fail_oracle_error_and_nondeterminism_are_unknown_and_preserved():
    target,oracle=probe._length_target,probe._length_reference
    for reset in [lambda:False,lambda:(_ for _ in ()).throw(RuntimeError("authored reset"))]:
        pair=probe._measure_pair(target,oracle,[1],[4,-4,1,3],reset=reset,structure={})
        assert pair["label"]=="UNKNOWN" and pair["cost"]["target_calls"]==pair["cost"]["oracle_calls"]==0
        assert pair["cost"]["reset_calls"]==6 and pair["unknown_reasons"]
    def broken_reference(xs):
        raise ValueError("authored reference failure")
    pair=probe._measure_pair(target,broken_reference,[1],[4,-4,1,3],reset=probe._reset_authored_fixture,structure={})
    assert pair["label"]=="UNKNOWN"
    assert all(row["status"]=="ORACLE_ERROR" for rows in pair["branches"].values() for row in rows)
    state={"i":0}
    def unstable(xs):
        state["i"]+=1
        return state["i"]
    pair=probe._measure_pair(unstable,oracle,[1],[4,-4,1,3],reset=probe._reset_authored_fixture,structure={})
    assert pair["label"]=="UNKNOWN"


def test_native_probe_uses_actual_engine_counts_and_preserves_receipts(tmp_path):
    workspace=tmp_path/"probe"
    summary=probe.run_probe(workspace,allow_local_execution=True,budget=12)
    assert summary["evidence_class"]=="DEVELOPMENT_SYNTHETIC_EXPOSED"
    assert len(summary["cases"])==4
    assert 0<summary["actual"]["target_calls"]<=summary["caps"]["target_calls"]==96
    assert summary["actual"]["oracle_calls"]<=96
    assert summary["real_eligible"]==summary["external_target_calls"]==summary["learning_updates"]==summary["independent_oos_cases"]==0
    assert summary["utility"]=="NOT_ESTABLISHED" and summary["policy_no_regression"]=="NOT_GUARANTEED"
    totals=dict(target_calls=0,oracle_calls=0,reset_calls=0)
    for i,row in enumerate(summary["cases"],1):
        assert row["native_baseline"]["method"]=="E9_A"
        assert row["native_baseline"]["engine"]=="native @given + target"
        assert row["relational"]["engine"]=="NATIVE_HYPOTHESIS_GIVEN_TARGET_PUBLIC_STRATEGY"
        raw=json.loads((workspace/("case-"+str(i)+".json")).read_text(encoding="utf-8"))
        for name in totals:
            baseline=raw["native_baseline"].get(name,0)
            actual=raw["relational"]["actual"][name]
            totals[name]+=baseline+actual
        for receipt in raw["relational"]["receipts"]:
            assert receipt["receipt_sha256"]
            assert receipt["implementation_sha256"] and receipt["oracle_sha256"]
    assert totals==summary["actual"]
    assert json.loads((workspace/"summary.json").read_text(encoding="utf-8"))==summary
    with pytest.raises(FileExistsError): probe.run_probe(workspace,allow_local_execution=True,budget=12)
