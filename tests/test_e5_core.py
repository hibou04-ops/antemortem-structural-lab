from copy import deepcopy

import pytest

from tomolab.discovery.analysis import analyze_source
from tomolab.discovery.engine import DiscoveryEngine, transfer
from tomolab.discovery.predicates import predicate_holds, validate_predicate, validate_public_ir
from tomolab.discovery.schema import digest


def contract(source=None,name="value",low=0,high=100):
    source=source or f"def implementation({name}: int) -> int:\n    if {name} >= 73:\n        return {name} + 1\n    return {name}\n"
    ir=analyze_source(source,roles={name:"operand"})
    spec={"schema":"tomolab-discovery-spec-v1","task_id":"e5-core-development",
          "inputs":[{"name":name,"role":"operand","type":{"kind":"int","min":low,"max":high}}],
          "contract":{"id":"integer-identity-v1","operation":"identity","preconditions":[],"invariants":["reference"],
                      "state_model":"stateless","graph_signature":ir["graph_signature"]}}
    return spec,ir


def event(point,i,failed=True):
    return {"kind":"FAILURE" if failed else "REFUTATION","evidence_id":f"core-dev-{i}","inputs":point,
            "invariant":"reference","category":"mismatch","signature":"integer-mismatch"}


def test_public_ast_becomes_real_hypothesis_and_changes_first_query():
    spec,ir=contract("def implementation(value:int)->int:\n    if value % 7 == 2 and value >= 5:\n        return value + 1\n    return value\n")
    pool=[{"value":x} for x in (0,1,2,8,9,10,16)]
    baseline=DiscoveryEngine(spec,_pool=pool)
    integrated=DiscoveryEngine(spec,public_ir=ir,_pool=pool)
    assert baseline.propose()["inputs"]=={"value":0}
    proposal=integrated.propose()
    assert proposal["inputs"]=={"value":9}
    assert proposal["predicted_constraints"]
    assert any(integrated.relations[r]["term"]["kind"]=="ast" for r in proposal["predicted_constraints"])
    assert ir["constraint_graph"]["edges"]==[{"from":ir["constraint_graph"]["nodes"][0]["id"],"to":"operand","kind":"depends-on-role"}]


def test_failure_and_refutation_change_real_next_action_and_version_space():
    spec,ir=contract(high=100)
    pool=[{"value":x} for x in (0,73,90,25,99)]
    positive=DiscoveryEngine(spec,public_ir=ir,_pool=pool)
    negative=DiscoveryEngine(spec,public_ir=ir,_pool=pool)
    first=positive.propose()["inputs"]
    assert first==negative.propose()["inputs"]=={"value":73}
    update=positive.observe(event(first,0))
    negative.observe(event(first,0,False))
    assert update["version"]==1 and positive.history[0]["groups"][0]["eliminated"]>0
    assert positive.propose()["inputs"]!=negative.propose()["inputs"]
    remaining=next(iter(positive.groups.values()))["remaining"]
    assert any(positive.relations[r]["term"]["kind"]=="ast" for r in remaining)


def test_native_strategy_produces_and_selects_fresh_guarded_inputs():
    spec,ir=contract()
    engine=DiscoveryEngine(spec,public_ir=ir,pool_size=1,seed=31)
    initial=deepcopy(engine.pool)
    proposal=engine.propose()
    assert proposal["reason"]=="native-constraint-search"
    assert proposal["inputs"] not in initial
    assert proposal["inputs"]["value"]>=73
    assert engine.pool_events and engine.pool_events[0]["source"]=="NATIVE_HYPOTHESIS_STRATEGY"
    assert engine.query_metrics["native_attempts"]>0


def test_z3_witness_is_consumed_by_actual_selection_and_snapshot_roundtrip():
    spec,ir=contract()
    engine=DiscoveryEngine(spec,public_ir=ir,_pool=[{"value":0},{"value":1}],solver="z3")
    proposal=engine.propose()
    assert proposal["solver_check"]["status"]=="SAT"
    assert proposal["inputs"]==proposal["solver_check"]["witness"]
    assert proposal["inputs"]["value"]>=73
    assert proposal["reason"]=="smt-constraint-witness"
    assert engine.pool_events[0]["source"]=="Z3_CONSTRAINT"
    engine.observe(event(proposal["inputs"],0))
    snapshot=engine.freeze()
    assert snapshot["query_metrics"]["solver_calls"]==snapshot["query_metrics"]["solver_sat"]==1
    assert DiscoveryEngine.from_snapshot(snapshot).snapshot()==snapshot


def test_native_dynamic_history_snapshot_is_verified_without_oracle_calls():
    spec,ir=contract()
    engine=DiscoveryEngine(spec,public_ir=ir,pool_size=1,seed=15)
    first=engine.propose()["inputs"]
    engine.observe(event(first,0))
    snapshot=engine.freeze()
    restored=DiscoveryEngine.from_snapshot(snapshot)
    assert restored.snapshot()==snapshot
    bad=deepcopy(snapshot)
    bad["prospective"]=["D-forged"]
    bad["receipt"]["sha256"]=digest({k:v for k,v in bad.items() if k!="receipt"})
    with pytest.raises(ValueError,match="derived state"):
        DiscoveryEngine.from_snapshot(bad)


def test_declared_static_oracle_cost_changes_query_without_feedback():
    spec,ir=contract("def implementation(value:int)->int:\n    if value >= 0:\n        return value\n    return -value\n",high=10)
    pool=[{"value":x} for x in (0,1,2)]
    cheap=DiscoveryEngine(spec,public_ir=ir,_pool=pool,oracle_costs=[{"inputs":{"value":0},"cost":100},
                                                                      {"inputs":{"value":2},"cost":0.5}])
    neutral=DiscoveryEngine(spec,public_ir=ir,_pool=pool)
    assert cheap.propose()["inputs"]=={"value":2}
    assert neutral.propose()["inputs"]=={"value":0}
    with pytest.raises(ValueError,match="positive"):
        DiscoveryEngine(spec,_pool=pool,oracle_costs=[{"inputs":{"value":0},"cost":0}])


@pytest.mark.parametrize("channel",["oracle","source","target_source","score","final_answers"])
def test_ir_rejects_extra_channels_even_if_nested_graph_digest_recomputed(channel):
    spec,ir=contract()
    ir["graph"][channel]="forbidden"
    import hashlib,json
    ir["graph_signature"]=hashlib.sha256(json.dumps(ir["graph"],sort_keys=True,separators=(",",":")).encode()).hexdigest()
    with pytest.raises(ValueError):
        validate_public_ir(ir,spec)


def test_typed_ast_predicates_support_containers_and_reject_arbitrary_calls():
    source="def implementation(values:list[int])->int:\n    if len(values) > 2 and sum(values) < 0:\n        return 1\n    return 0\n"
    ir=analyze_source(source,roles={"values":"items"})
    spec={"schema":"tomolab-discovery-spec-v1","task_id":"e5-list-core","inputs":[{"name":"values","role":"items",
          "type":{"kind":"list","items":{"kind":"int","min":-5,"max":5},"min_size":0,"max_size":5}}],
          "contract":{"id":"count-v1","operation":"count","preconditions":[],"invariants":["reference"],"state_model":"stateless","graph_signature":ir["graph_signature"]}}
    assert predicate_holds(ir["predicates"][0],{"values":[-1,-2,0]},spec)
    assert not predicate_holds(ir["predicates"][0],{"values":[]},spec)
    with pytest.raises(ValueError):
        validate_predicate({"op":"__import__","args":["os"]},spec)
    rejected=analyze_source("def implementation(values:list[int])->int:\n    if custom(values):\n        return 1\n    return 0\n",roles={"values":"items"})
    assert rejected["predicates"]==[] and rejected["predicate_rejections"]


def test_float_predicate_uses_declared_python_float_semantics_for_json_integers():
    spec,ir=contract("def implementation(value:float)->float:\n    if value * value + 1 > value * value:\n        return value+1\n    return value\n",high=10**12)
    spec["inputs"][0]["type"]["kind"]="float"
    # JSON permits a numeric integer spelling, but evaluator decoding makes it
    # float. Exact-integer arithmetic would incorrectly predict True here.
    assert not predicate_holds(ir["predicates"][0],{"value":10**12},spec)


def trained_source():
    spec,ir=contract("def implementation(value:int)->int:\n    if value >= 3:\n        return value+1\n    return value\n",high=10)
    engine=DiscoveryEngine(spec,public_ir=ir,_pool=[{"value":x} for x in (0,3,5,8,1)])
    first=engine.propose()["inputs"]
    assert first=={"value":3}
    engine.observe(event(first,0))
    return spec,ir,engine.freeze()


def test_transfer_checks_guard_constants_and_retains_valid_role_correspondence():
    _,_,snapshot=trained_source()
    target,ir=contract("def implementation(renamed:int)->int:\n    if renamed >= 3:\n        return renamed+1\n    return renamed\n",name="renamed",high=10)
    good=transfer(snapshot,target,target_ir=ir,mapping={"value":"renamed"},budget=3,pool_size=20,native_strategy=False)
    assert good["gate"]["status"]=="APPLICABLE_FOR_PROBING"
    assert good["gate"]["failure_recurrence"]=="UNKNOWN"
    assert good["snapshot"]["frozen"] and good["snapshot"]["prior"]
    assert DiscoveryEngine.from_snapshot(good["snapshot"]).snapshot()==good["snapshot"]
    different=analyze_source("def implementation(renamed:int)->int:\n    if renamed >= 4:\n        return renamed+1\n    return renamed\n",roles={"renamed":"operand"})
    wrong=transfer(snapshot,target,target_ir=different,budget=3,pool_size=20,native_strategy=False)
    assert wrong["gate"]["status"]=="UNKNOWN" and not wrong["snapshot"]["prior"]
    assert any("predicate constants" in reason for reason in wrong["gate"]["reasons"])
    assert transfer(snapshot,target,target_ir=ir,mapping={"value":"wrong"},budget=3,pool_size=20,native_strategy=False)["gate"]["status"]=="UNKNOWN"


def test_existing_target_development_counterevidence_refutes_inapplicable_prior():
    _,_,snapshot=trained_source()
    target,ir=contract("def implementation(renamed:int)->int:\n    if renamed >= 3:\n        return renamed+1\n    return renamed\n",name="renamed",high=10)
    evidence=event({"renamed":3},99,False)
    result=transfer(snapshot,target,target_ir=ir,target_evidence=[evidence],budget=3,pool_size=20,native_strategy=False)
    assert result["gate"]["status"]=="UNKNOWN" and not result["snapshot"]["prior"]
    assert result["gate"]["target_contradictions"]
    assert result["gate"]["target_counterevidence_ids"]==[evidence["evidence_id"]]


def test_conflicting_evidence_removes_all_competing_models_and_blocks_feedback():
    spec,ir=contract()
    engine=DiscoveryEngine(spec,public_ir=ir,_pool=[{"value":73},{"value":0}])
    point=engine.propose()["inputs"]
    engine.observe(event(point,0))
    engine.observe(event(point,1,False))
    assert engine.status=="INCONSISTENT_EVIDENCE"
    assert all(not group["remaining"] for group in engine.groups.values())
    snapshot=engine.freeze()
    assert DiscoveryEngine.from_snapshot(snapshot).snapshot()==snapshot
    with pytest.raises(ValueError,match="frozen"):
        engine.observe(event(point,2))
