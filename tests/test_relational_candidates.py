"""Authored property and guard checks; no external repository execution."""
from copy import deepcopy

from hypothesis import given, settings, strategies as st
import pytest

from tomolab.discovery.relational_candidates import (MUTATORS, REQUIRED_TAGS,
    SIGNATURE_SCHEMA, extract_relational_signature, propose_relational_candidates,
    bounded_carryover_schedule)
from tomolab.discovery.online_schema import validate_input, input_identity
from tomolab.discovery.schema import digest

CONTRACT = dict(kind="sequence_int", low=-1000, high=1000, min_size=0,max_size=16)


def signature(operator, contract=CONTRACT):
    return dict(schema=SIGNATURE_SCHEMA,status="SUPPORTED_SYNTAX_ONLY",
        tags=sorted(REQUIRED_TAGS[operator]),constants=[0],source_sha256=digest("authored-syntax"),
        contract_sha256=digest(contract),scope="SYNTAX_ONLY_NOT_MECHANISM_OR_FRONTIER_PROOF",unknown_reasons=[])


@settings(max_examples=35,deadline=None)
@given(st.lists(st.integers(-20,20),max_size=12))
@pytest.mark.parametrize("operator", MUTATORS)
def test_proposals_are_pure_bounded_valid_novel_and_typed(operator,base):
    before=deepcopy(base)
    result=propose_relational_candidates(base,CONTRACT,signature(operator),mutator_id=operator)
    assert base==before
    assert 0<len(result["candidates"])<=3
    ids=[c["input_digest"] for c in result["candidates"]]
    assert len(ids)==len(set(ids))
    for row in result["candidates"]:
        assert validate_input(row["input"],CONTRACT)
        assert row["input_digest"]==input_identity(row["input"])!=input_identity(base)
        assert row["learned"] is False
    assert result["external_execution_authorized"] is False


def test_m1_length_value_relationship():
    row=propose_relational_candidates([2],CONTRACT,signature(MUTATORS[0]),mutator_id=MUTATORS[0])["candidates"][0]
    xs=row["input"]; n=len(xs)
    assert (xs[0],xs[1],xs[-1])==(n,-n,n-1)


def test_m1_bound_public_deficit_preserves_shifted_length_relation_without_claiming_a_flip():
    base=[1]; sig=signature(MUTATORS[0])
    fb=dict(schema="tomolab-authored-frontier-v1",authority="AUTHORED_FIXTURE_REVIEW",
        input_digest=input_identity(base),contract_sha256=digest(CONTRACT),structure_sha256=digest(sig),
        expression="first_value",operator="==",lhs=1,rhs=3)
    result=propose_relational_candidates(base,CONTRACT,sig,mutator_id=MUTATORS[0],frontier=fb)
    assert result["frontier_used"] and len(result["candidates"])<=3
    xs=next(r["input"] for r in result["candidates"] if r["relationship"]=="LENGTH_VALUE_DEFICIT_SHIFT")
    assert xs[0]==len(xs)+2 and xs[-1]==len(xs)-1+2


def test_m2_local_inversion_and_plateau_preserve_other_increases():
    rows=propose_relational_candidates([2],CONTRACT,signature(MUTATORS[1]),mutator_id=MUTATORS[1])["candidates"]
    terminal,plateau=rows[0]["input"],rows[1]["input"]
    assert all(a<b for a,b in zip(terminal[:-2],terminal[1:-1])) and terminal[-1]<terminal[-2]
    mid=len(plateau)//2
    assert plateau[mid]==plateau[mid-1]
    assert all(plateau[i]>plateau[i-1] for i in range(1,len(plateau)) if i!=mid)


@settings(max_examples=30,deadline=None)
@given(st.integers(-15,15),st.lists(st.integers(-10,10),max_size=8))
def test_m3_reviewed_aggregate_projection_is_exact_and_bound_to_anchor(k,base):
    sig=signature(MUTATORS[2])
    frontier=dict(schema="tomolab-authored-frontier-v1",authority="AUTHORED_FIXTURE_REVIEW",
        input_digest=input_identity(base),contract_sha256=digest(CONTRACT),structure_sha256=digest(sig),
        expression="sum_input",operator="==",lhs=sum(base),rhs=k)
    result=propose_relational_candidates(base,CONTRACT,sig,mutator_id=MUTATORS[2],frontier=frontier)
    assert result["frontier_used"]
    for row in result["candidates"]:
        assert sum(row["input"])==row["aggregate_target"]


def test_m4_cardinality_topology_and_midpoint_position():
    rows=propose_relational_candidates([3],CONTRACT,signature(MUTATORS[3]),mutator_id=MUTATORS[3])["candidates"]
    for row in rows[:2]:
        xs=row["input"]
        assert sorted([xs.count(v) for v in set(xs)])==[1,len(xs)-1]
    pivot=rows[1]["input"]
    assert pivot[len(pivot)//2]!=pivot[0]


@pytest.mark.parametrize("base",[(1,2),{"x":1},[True], [1.0]])
def test_unsupported_input_is_never_coerced_to_sequence_int(base):
    assert propose_relational_candidates(base,CONTRACT,signature(MUTATORS[0]))["status"]=="ABSTAIN"


def test_other_supported_contract_still_abstains_in_relational_grammar():
    contract=dict(kind="mapping")
    result=propose_relational_candidates({"a":1},contract,{})
    assert result["reasons"]==["UNSUPPORTED_RELATIONAL_CONTRACT"]


@pytest.mark.parametrize("guard",["unknown","missing","empty","nonpositive","short","bounds","seen"])
def test_abstention_and_negative_guards_do_not_create_counterevidence(guard):
    contract=deepcopy(CONTRACT); sig=signature(MUTATORS[0]); kwargs=dict(mutator_id=MUTATORS[0])
    if guard=="unknown": sig.update(status="PARTIAL",unknown_reasons=["UNKNOWN"])
    if guard=="missing": sig["tags"]=[]
    if guard=="empty": sig["tags"]=sorted(sig["tags"]+["ONLY_EMPTY_CHECK"])
    if guard=="nonpositive": kwargs["history"]=dict(gains=1,losses=1)
    if guard=="short": contract["max_size"]=3
    if guard=="bounds": contract.update(low=0,high=0)
    sig["contract_sha256"]=digest(contract)
    if guard=="seen": kwargs["seen"]=[r["input_digest"] for r in propose_relational_candidates([],contract,sig,**kwargs)["candidates"]]
    result=propose_relational_candidates([],contract,sig,**kwargs)
    assert result["status"]=="ABSTAIN" and not result["candidates"] and result["reasons"]
    assert result["learned"] is False


def test_frontier_private_fields_stale_identity_and_wrong_operands_are_rejected():
    base=[1,2]; sig=signature(MUTATORS[2])
    fb=dict(schema="tomolab-authored-frontier-v1",authority="AUTHORED_FIXTURE_REVIEW",
        input_digest=input_identity(base),contract_sha256=digest(CONTRACT),structure_sha256=digest(sig),
        expression="sum_input",operator="==",lhs=3,rhs=5)
    for patch in [dict(actual=1),dict(lhs=4),dict(input_digest="0"*64),dict(authority="GENERIC_CAST_INFERRED"),dict(rhs=True)]:
        with pytest.raises(ValueError):
            propose_relational_candidates(base,CONTRACT,sig,mutator_id=MUTATORS[2],frontier={**fb,**patch})


def empty_only(xs):
    if not xs:
        return -1
    return sum(xs)


def structural(xs):
    n=len(xs)
    return xs[n-1]+sum(xs) if n else 0


def test_syntax_is_inspected_without_target_execution_and_empty_guard_abstains():
    sig=extract_relational_signature(empty_only,CONTRACT)
    assert "ONLY_EMPTY_CHECK" in sig["tags"]
    assert propose_relational_candidates([],CONTRACT,sig)["status"]=="ABSTAIN"
    sig=extract_relational_signature(structural,CONTRACT)
    assert {"HAS_LEN_CALL","HAS_INDEX_SUBSCRIPT","HAS_ACCUMULATOR"}<=set(sig["tags"])
    assert sig["scope"]=="SYNTAX_ONLY_NOT_MECHANISM_OR_FRONTIER_PROOF"


def test_prefix_and_carryover_preserve_only_a_shorter_common_prefix_at_fixed_budget():
    baseline=[[0],[1],[2],[99]]
    result=bounded_carryover_schedule(baseline,{2:[-1]},budget=4,prefix_steps=2)
    common=[r["input"] for r in result["rows"] if r["origin"]=="COMMON"]
    assert [r["input"] for r in result["rows"][:2]]==baseline[:2]
    assert common==baseline[:3] and result["pending_common"]==[[99]]
    # A pure authored predicate at the baseline tail is a concrete loss
    # counterexample, without executing a new research Target.
    assert any(p==[99] for p in baseline)
    assert not any(r["input"]==[99] for r in result["rows"])
    assert result["total_calls"]==4 and result["full_budget_no_regression_guaranteed"] is False
