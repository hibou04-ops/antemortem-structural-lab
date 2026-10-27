from copy import deepcopy
import sqlite3

import pytest

from tomolab.discovery.analysis import analyze_source
from tomolab.discovery.engine import DiscoveryEngine, transfer
from tomolab.discovery.features import measurements, holds
from tomolab.discovery.hypothesis_adapter import generate_pool, native_find
from tomolab.discovery.schema import canonical, decode_inputs, digest, normalize_evidence, validate_inputs, validate_spec
from tomolab.discovery.stateful import run_stateful
from tomolab.discovery.store import FailureStore


INTEGER = {"kind":"int","min":-10,"max":10}


def spec(type_=None, name="value", ir=None):
    return {"schema":"tomolab-discovery-spec-v1","task_id":"development-test",
            "inputs":[{"name":name,"role":"operand","type":deepcopy(type_ or INTEGER)}],
            "contract":{"id":"arithmetic-v1","operation":"arithmetic","preconditions":[],
                        "invariants":["reference"],"state_model":"stateless",
                        "graph_signature":ir["graph_signature"] if ir else "UNKNOWN"}}


def evidence(point, i, failure=True, signature="positive"):
    return {"kind":"FAILURE" if failure else "REFUTATION","evidence_id":f"dev-{i}",
            "inputs":point,"invariant":"reference","category":"mismatch","signature":signature}


def feed(engine, points):
    for i,point in enumerate(points):
        proposed=engine.propose()["inputs"]
        assert proposed==point
        engine.observe(evidence(point,i,point["value"]>0))


def test_native_typed_pool_reproducible_all_six_types_and_tuple_decode():
    kinds=[INTEGER,{"kind":"float","min":-2,"max":2},
           {"kind":"str","alphabet":" a0","min_size":0,"max_size":5},
           {"kind":"list","items":INTEGER,"min_size":0,"max_size":4},
           {"kind":"dict","keys":["a","b"],"values":INTEGER,"min_size":0,"max_size":2},
           {"kind":"tuple","items":[INTEGER,{"kind":"str","alphabet":"ab","min_size":0,"max_size":3}]}]
    contract=spec()
    contract["inputs"]=[{"name":f"arg{i}","role":f"role{i}","type":t} for i,t in enumerate(kinds)]
    first=generate_pool(contract,seed=173,size=30)
    assert first==generate_pool(contract,seed=173,size=30)
    assert len(first)>15 and len({canonical(x) for x in first})==len(first)
    for point in first:
        validate_inputs(point,contract)
        decoded=decode_inputs(point,contract)
        assert type(decoded["arg1"]) is float and type(decoded["arg5"]) is tuple


@pytest.mark.parametrize("bad",[True,11,float("nan"),"1"])
def test_strict_public_input_bounds(bad):
    with pytest.raises(ValueError):
        validate_inputs({"value":bad},spec())


def test_evidence_rejects_unbounded_or_unapproved_channels():
    valid=evidence({"value":0},0)
    for patch in ({"source":"private code"},{"category":"hidden-answer"},{"signature":"a\ntrace"},{"invariant":"undeclared"}):
        with pytest.raises(ValueError):
            normalize_evidence(dict(valid,**patch),spec())


def test_hypothesis_native_find_shrinks_and_meters_every_actual_call():
    called=[]
    def oracle(point):
        called.append(point)
        return point["value"]>=7
    receipt=native_find(spec({"kind":"int","min":0,"max":1000}),oracle,budget=200,seed=4)
    assert receipt["witness"]=={"value":7}
    assert receipt["shrinking"]=="NATIVE_COMPLETED"
    assert receipt["oracle_calls"]==len(called)==len(receipt["records"])
    assert receipt["oracle_calls"]<=200
    stopped=native_find(spec(),lambda point:False,budget=3,seed=4)
    assert stopped["oracle_calls"]==3 and stopped["stop"] in {"RESOURCE_BUDGET","NO_WITNESS_WITHIN_SEARCH"}
    assert stopped["witness"] is None


def test_native_find_does_not_turn_oracle_errors_into_findings():
    def invalid(point):
        raise RuntimeError("broken oracle")
    with pytest.raises(RuntimeError,match="broken oracle"):
        native_find(spec(),invalid,budget=10)


def test_version_space_counterevidence_preserves_distinct_observed_families():
    pool=[{"value":i} for i in (-5,5,0,-1,1,9,-9)]
    engine=DiscoveryEngine(spec(),strategy="hypothesis",_pool=pool)
    for i in range(3):
        point=engine.propose()["inputs"]
        engine.observe(evidence(point,i,point["value"]!=0,"negative" if point["value"]<0 else "positive"))
    snapshot=engine.snapshot()
    assert len(snapshot["groups"])==2
    assert snapshot["contradictions"]
    assert all(group["remaining"] for group in snapshot["groups"].values())
    for family,group in snapshot["groups"].items():
        for rid in group["remaining"]:
            for point in pool[:3]:
                expected=point["value"]<0 if family.endswith("negative") else point["value"]>0
                assert holds(snapshot["relations"][rid],measurements(point,engine.spec))==expected
    assert {c["family_id"] for c in snapshot["constraints"]}==set(snapshot["groups"])
    assert all(c["uncertainty"]["probability"] is None for c in snapshot["constraints"])


def test_active_learning_and_diversity_have_separate_objectives():
    pool=[{"value":i} for i in (0,5,-5,2,-2,9,-9,1,-1)]
    engine=DiscoveryEngine(spec(),_pool=pool)
    first=engine.propose()["inputs"]
    engine.observe(evidence(first,0,True,"zero-region"))
    assert engine.propose()["reason"]=="constraint-guided"
    query=engine.propose()
    assert query["objective"]=="hypothesis-identification"
    assert 0<query["positive_votes"]<query["competing_count"]
    assert engine.propose()["objective"]=="coverage"


def test_no_feedback_before_proposal_or_after_freeze_and_conflicting_evidence_abstains():
    engine=DiscoveryEngine(spec(),_pool=[{"value":0},{"value":1}])
    with pytest.raises(ValueError,match="proposed"):
        engine.observe(evidence({"value":1},0))
    point=engine.propose()["inputs"]
    engine.observe(evidence(point,0))
    engine.observe(evidence(point,1,False))
    assert engine.status=="INCONSISTENT_EVIDENCE"
    assert all(not g["remaining"] for g in engine.groups.values())
    engine.freeze()
    with pytest.raises(ValueError,match="frozen"):
        engine.observe(evidence(point,2))


def test_frozen_snapshot_replay_and_rehashed_derived_state_tampering_rejected():
    engine=DiscoveryEngine(spec(),_pool=[{"value":i} for i in (0,1,-1,2,-2,3)])
    point=engine.propose()["inputs"]
    engine.observe(evidence(point,0))
    snapshot=engine.freeze()
    restored=DiscoveryEngine.from_snapshot(snapshot)
    assert restored.snapshot()==snapshot
    assert [restored.propose() for _ in range(3)]==[engine.propose() for _ in range(3)]
    corrupt=deepcopy(snapshot)
    corrupt["version"]+=1
    corrupt["receipt"]["sha256"]=digest({k:v for k,v in corrupt.items() if k!="receipt"})
    with pytest.raises(ValueError,match="derived state"):
        DiscoveryEngine.from_snapshot(corrupt)


def test_typed_transfer_uses_actual_public_ir_and_retains_uncertainty():
    source_ir=analyze_source("def source(value: int) -> int:\n    return value + 1\n","source",{"value":"operand"})
    target_ir=analyze_source("def target(renamed: int) -> int:\n    return renamed + 2\n","target",{"renamed":"operand"})
    source=DiscoveryEngine(spec(ir=source_ir),public_ir=source_ir,strategy="hypothesis",
                           _pool=[{"value":i} for i in (-2,2,0,1,-1)])
    feed(source,[{"value":-2},{"value":2},{"value":0}])
    snapshot=source.freeze()
    target_spec=spec(name="renamed",ir=target_ir)
    result=transfer(snapshot,target_spec,target_ir=target_ir,budget=3,pool_size=30)
    assert result["gate"]["status"]=="APPLICABLE_FOR_PROBING"
    assert result["gate"]["failure_recurrence"]=="UNKNOWN"
    assert result["gate"]["excluded_coordinate_constraints"]>0
    for family in result["snapshot"]["prior"]:
        assert all(r["value"]==0 for r in family["relations"] if r["term"]["kind"]=="value")
    assert result["snapshot"]["prior"] and all("renamed" in x["inputs"] for x in result["candidates"])
    DiscoveryEngine.from_snapshot(result["snapshot"])
    abstention=transfer(snapshot,target_spec,budget=3,pool_size=30)
    assert abstention["gate"]["status"]=="UNKNOWN" and not abstention["snapshot"]["prior"]
    changed=deepcopy(target_spec)
    changed["inputs"][0]["type"]["max"]=20
    assert transfer(snapshot,changed,target_ir=target_ir,budget=3,pool_size=30)["gate"]["status"]=="UNKNOWN"


def test_database_append_only_chain_duplicate_rolls_back_and_tamper_detected(tmp_path):
    path=tmp_path/"failures.sqlite3"
    with FailureStore(path) as store:
        first=store.append("e1",{"kind":"FAILURE","inputs":{"x":1}})
        second=store.append("e2",{"kind":"REFUTATION"})
        assert second["previous_sha256"]==first["sha256"]
        with pytest.raises(sqlite3.IntegrityError):
            store.append("e2",{})
        assert store.verify()["records"]==2
        with pytest.raises(sqlite3.IntegrityError,match="append-only"):
            store.connection.execute("UPDATE evidence SET payload='{}' WHERE seq=1")
        store.connection.rollback()
        # Owner-level tampering is outside access protection but remains detectable
        # unless the owner rewrites the complete chain and trusted head receipt.
        store.connection.execute("DROP TRIGGER evidence_no_update")
        store.connection.execute("UPDATE evidence SET payload='{}' WHERE seq=1")
        store.connection.commit()
        with pytest.raises(ValueError,match="chain invalid"):
            store.verify()


def state_operations(broken=False):
    def append(state,value):
        state.append(value)
    def broken_append(state,value):
        state.insert(0,value)
    return {"append":{"arguments":INTEGER,"target":broken_append if broken else append,"model":append}}


def test_native_state_machine_checks_transitions_shrinks_and_is_reproducible():
    first=run_stateful(list,list,state_operations(True),snapshot=list,budget=300,seed=5,max_examples=30,steps=6)
    second=run_stateful(list,list,state_operations(True),snapshot=list,budget=300,seed=5,max_examples=30,steps=6)
    assert first["status"]=="COUNTEREXAMPLE_FOUND"
    assert len(first["witness"])==2
    assert first["oracle_calls"]<=300
    assert [r["trace"] for r in first["records"]]==[r["trace"] for r in second["records"]]
    normal=run_stateful(list,list,state_operations(),snapshot=list,budget=10,seed=5,max_examples=30,steps=6)
    assert normal["oracle_calls"]==10 and normal["witness"] is None


def test_state_machine_oracle_assertion_is_not_reported_as_a_counterexample():
    def broken_snapshot(state):
        raise AssertionError("oracle projection broken")
    with pytest.raises(AssertionError,match="oracle projection broken"):
        run_stateful(list,list,state_operations(),snapshot=broken_snapshot,budget=10,seed=5,max_examples=2,steps=2)
