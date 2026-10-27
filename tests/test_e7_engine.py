from copy import deepcopy

import pytest

from tomolab.discovery.knowledge import KnowledgeArchive, make_observation
from tomolab.discovery.knowledge_engine import KnowledgeEngine, plan_knowledge
from tomolab.discovery.knowledge_service import run_knowledge, run_knowledge_stateful
from tomolab.discovery.schema import digest


def spec(name="value"):
    return {"schema":"tomolab-discovery-spec-v1","task_id":"boundary-"+name,
        "inputs":[{"name":name,"role":"operand","type":{"kind":"int","min":-3,"max":3}}],
        "contract":{"id":"bounded-maximum","operation":"bounded-identity","preconditions":[],
            "invariants":["reference"],"state_model":"stateless","graph_signature":"UNKNOWN"}}


def origin(index=1):
    return {"project":f"authored-project-{index}","lineage":f"authored-lineage-{index}",
        "revision":f"revision-{index}","oracle_id":f"independent-reference-{index}",
        "semantics":"bounded-identity-v1","implementation_sha256":str(index)*64,
        "oracle_sha256":str(index+4)*64,"independence_id":f"reviewed-{index}"}


def event(value, failed, eid="event", name="value"):
    return {"kind":"FAILURE" if failed else "REFUTATION","evidence_id":eid,
        "inputs":{name:value},"invariant":"reference","category":"mismatch",
        "signature":"reference-comparison"}


def qualified_archive():
    archive=KnowledgeArchive.from_failure_log(spec(),
        [event(3,True,"source-failure"),event(0,False,"source-clean")],origin())
    for x,failed in ((3,True),(0,False)):
        envelope=make_observation(spec("alternate"),event(x,failed,f"contrast-{x}","alternate"),origin(2))
        archive.observe(envelope,trusted_observation=True)
    return archive.freeze()


def test_cold_engine_and_service_never_initialize_pool_solver_or_worker(monkeypatch):
    import tomolab.discovery.knowledge_engine as module
    import tomolab.discovery.knowledge_boundary as boundary
    def forbidden(*args,**kwargs):
        raise AssertionError("unqualified search started a knowledge resource")
    monkeypatch.setattr(module,"generate_pool",forbidden)
    monkeypatch.setattr(boundary,"KnowledgeBoundary",forbidden)
    engine=KnowledgeEngine(spec(),budget=8)
    assert engine.native_pool is None and engine.solver is None
    assert engine.metrics["native_pool_builds"]==0
    counts={"target":0,"oracle":0}
    def target(value):counts["target"]+=1;return value
    def oracle(value):counts["oracle"]+=1;return value
    result=run_knowledge(target,oracle,spec(),budget=16,shrink_budget=0,trusted_execution=True)
    assert result["status"]=="NOT_REFUTED_WITHIN_BUDGET"
    assert result["worker_started"] is False
    assert result["metrics"]["guided_prefix_calls"]==0
    assert counts["target"]==counts["oracle"]==result["metrics"]["oracle_calls"]
    assert result["snapshot"]["metrics"]["native_pool_builds"]==0


def test_independent_qualified_structure_changes_actual_order_and_preserves_native_fraction():
    archive=qualified_archive()
    baseline=KnowledgeEngine(spec("target"),target_provenance=origin(3),budget=6,pool_size=16)
    engine=KnowledgeEngine(spec("target"),archive=archive,target_provenance=origin(3),budget=6,pool_size=16)
    first=engine.propose()
    native_first=baseline.propose()["inputs"]
    assert native_first=={"target":0}
    assert first["inputs"]!=native_first
    assert first["source"]=="QUALIFIED_STRUCTURAL_PROBE" and first["claim_ids"]
    points=[first]
    while (point:=engine.propose()) is not None:points.append(point)
    assert len({digest(p["inputs"]) for p in points})==len(points)==6
    assert engine.metrics["native_candidates"]>=3
    assert engine.metrics["guided_candidates"]<=3
    assert engine.metrics["prediction_cache_hits"]>0
    assert engine.metrics["oracle_calls"]==engine.metrics["target_calls"]==0


def test_wrong_semantics_and_missing_independent_evidence_keep_native_path():
    archive=qualified_archive();wrong=origin(3);wrong["semantics"]="different-operation"
    engine=KnowledgeEngine(spec("target"),archive=archive,target_provenance=wrong,budget=6)
    assert not engine.qualified and engine.propose()["source"]=="NATIVE_HYPOTHESIS"
    pending=KnowledgeArchive.from_failure_log(spec(),[event(3,True),event(0,False,"clean")],origin())
    pending.freeze()
    assert not KnowledgeEngine(spec(),archive=pending.snapshot(),target_provenance=origin(3)).qualified


def test_cold_path_validates_provenance_before_any_reviewed_function_call():
    invalid=origin();invalid["actual_state"]={"secret":1}
    with pytest.raises(ValueError):KnowledgeEngine(spec(),target_provenance=invalid)
    called=[]
    with pytest.raises(ValueError):
        run_knowledge(lambda value:called.append(value),lambda value:value,spec(),
                      target_provenance=invalid,trusted_execution=True)
    assert called==[]


def test_target_counterevidence_removes_claims_and_archive_is_not_rewritten():
    archive=qualified_archive();engine=KnowledgeEngine(spec("target"),archive=archive,
        target_provenance=origin(3),budget=6,pool_size=8)
    point=engine.propose()
    observed=make_observation(spec("target"),event(point["inputs"]["target"],False,"counter","target"),origin(3))
    count=len(engine.active);response=engine.observe(observed)
    assert response["refuted_claim_ids"] and len(engine.active)<count
    assert engine.archive==archive and engine.refutations
    assert engine.observe(observed)["status"]=="IDEMPOTENT"
    changed=deepcopy(observed);changed["origin"]["revision"]="changed"
    changed["receipt_sha256"]=digest({k:v for k,v in changed.items() if k!="receipt_sha256"})
    with pytest.raises(ValueError,match="provenance"):engine.observe(changed)


def test_frozen_plans_and_snapshot_semantic_replay_reject_rehashed_tampering():
    archive=qualified_archive();plan=plan_knowledge(archive,spec("target"),target_provenance=origin(3),budget=6,pool_size=12)
    assert plan["candidates"] and all(p["frozen"] for p in plan["candidates"])
    assert plan["final_feedback_allowed"] is False and plan["oracle_calls"]==plan["target_calls"]==0
    snap=plan["snapshot"]
    restored=KnowledgeEngine.from_snapshot(snap)
    assert restored.snapshot()==snap
    with pytest.raises(ValueError,match="frozen"):restored.propose()
    with pytest.raises(ValueError,match="frozen"):restored.observe({})
    bad=deepcopy(snap);bad["active_claim_ids"]=[]
    bad["receipt"]["sha256"]=digest({k:v for k,v in bad.items() if k!="receipt"})
    with pytest.raises(ValueError,match="semantic replay"):KnowledgeEngine.from_snapshot(bad)
    bad=deepcopy(snap);bad["metrics"]["guided_candidates"]+=1
    bad["receipt"]["sha256"]=digest({k:v for k,v in bad.items() if k!="receipt"})
    with pytest.raises(ValueError,match="counter differs"):KnowledgeEngine.from_snapshot(bad)
    bad=deepcopy(snap);bad["frozen"]=False
    bad["receipt"]["sha256"]=digest({k:v for k,v in bad.items() if k!="receipt"})
    with pytest.raises(ValueError,match="semantic replay"):KnowledgeEngine.from_snapshot(bad)


def test_qualified_ast_claim_uses_actual_incremental_solver_witness():
    from tomolab.discovery.analysis import analyze_source
    def context(name):
        ir=analyze_source(f"def implementation({name}: int) -> int:\n    if {name} == 0:\n        return 1\n    return 0\n",roles={name:"operand"})
        value=spec(name);value["contract"]["graph_signature"]=ir["graph_signature"]
        return value,ir
    s,ir=context("value")
    archive=KnowledgeArchive.from_failure_log(s,[event(0,True,"f"),event(1,False,"n")],origin(),public_ir=ir)
    other,other_ir=context("alternate")
    for value,failed in [(0,True),(1,False)]:
        archive.observe(make_observation(other,event(value,failed,f"ind-{value}","alternate"),origin(2),public_ir=other_ir),trusted_observation=True)
    archive.freeze();target,target_ir=context("target")
    engine=KnowledgeEngine(target,archive=archive.snapshot(),target_provenance=origin(3),public_ir=target_ir,budget=8)
    point=engine.propose()
    assert point["source"]=="QUALIFIED_Z3_WITNESS" and point["inputs"]=={"target":0}
    assert engine.metrics["solver_calls"]==engine.metrics["solver_sat"]==1
    assert engine.solver.metrics["pushes"]==engine.solver.metrics["pops"]==1


def test_qualified_service_executes_narrow_feedback_freeze_native_shrink_and_two_replays():
    archive=qualified_archive();counts={"target":0,"oracle":0}
    def target(target):counts["target"]+=1;return target+int(target==3)
    def oracle(target):counts["oracle"]+=1;return target
    result=run_knowledge(target,oracle,spec("target"),archive=archive,target_provenance=origin(3),
        budget=16,shrink_budget=16,guidance_budget=4,pool_size=16,trusted_execution=True)
    assert result["worker_started"] and result["proposals"][0]["inputs"]!={"target":0}
    assert result["proposals"][0]["source"].startswith("QUALIFIED_")
    assert result["snapshot"]["frozen"] and result["counterexample"]["replay"]=="MATCHED_TWICE"
    assert result["status"]=="COUNTEREXAMPLE_FOUND"
    assert counts["target"]==counts["oracle"]==result["metrics"]["oracle_calls"]<=34
    assert result["metrics"]["guided_prefix_calls"]<=4
    assert result["metrics"]["generator_feedback_calls"]==len(result["observations"])
    assert all(set(e["evidence"])=={"kind","evidence_id","inputs","invariant","category","signature"} for e in result["observations"])
    assert result["final_feedback_allowed"] is False
    assert result["timing"]["shrink_seconds"] is None


def test_trust_and_oracle_errors_fail_closed_before_any_false_finding():
    with pytest.raises(PermissionError):run_knowledge(lambda value:value,lambda value:value,spec())
    def broken(value):raise RuntimeError("oracle-invalid")
    with pytest.raises(RuntimeError,match="oracle-invalid"):
        run_knowledge(lambda value:value,broken,spec(),trusted_execution=True)
    called=[]
    with pytest.raises(ValueError,match="time budget"):
        run_knowledge(lambda value:called.append(value),broken,spec(),time_budget=float("nan"),trusted_execution=True)
    assert called==[]


def test_native_stateful_fallback_uses_actual_RBS_machine_and_meters_replay():
    from test_e6_efficiency import stack_contract
    from test_e6_service import Subject,callbacks
    s,c=stack_contract();counts={}
    result=run_knowledge_stateful(lambda:Subject(True),Subject,callbacks(counts),
        snapshot=lambda obj:obj.snapshot(),spec=s,temporal_contract=c,budget=64,
        shrink_budget=64,guidance_budget=8,time_budget=10,trusted_execution=True,pool_size=12)
    assert result["worker_started"] is False and result["native"]["schema"]=="tomolab-native-temporal-v1"
    assert result["counterexample"]["replay"]=="MATCHED_TWICE"
    assert counts["model"]==counts["target"]==result["metrics"]["model_calls"]
    assert result["metrics"]["native_search_and_shrink_calls"]<=128
    assert result["evidence"] and all("first_failure_index" in e for e in result["evidence"])


def test_rejected_qualified_prefix_is_never_executed_or_sent_as_refutation():
    archive=qualified_archive();actual=[];expected=[]
    def target(target):actual.append(target);return target
    def oracle(target):expected.append(target);return target
    result=run_knowledge(target,oracle,spec("target"),archive=archive,target_provenance=origin(3),
        budget=16,shrink_budget=0,guidance_budget=4,pool_size=16,trusted_execution=True,
        input_accepts=lambda inputs:inputs["target"]<0)
    rejected=[r for r in result["precondition_rejections"] if r["phase"]=="guided_prefix"]
    assert rejected and all(r["status"]=="PRECONDITION_REJECTED" for r in rejected)
    assert all(r["oracle_calls"]==r["target_calls"]==0 and r["observed_failure"] is None for r in rejected)
    assert actual==expected and all(value<0 for value in actual)
    assert all(e["inputs"]["target"]<0 for e in result["evidence"])
    assert all(e["evidence"]["inputs"]["target"]<0 for e in result["observations"])
    assert result["metrics"]["generator_feedback_calls"]==len(result["observations"])
    assert len(actual)==result["metrics"]["oracle_calls"]
    assert result["metrics"]["guided_prefix_attempts"]<=4
    assert result["input_precondition"]["execution"]=="TRUSTED_HOST_ONLY_NOT_TRANSMITTED"


def test_native_rejections_consume_bounded_attempts_but_not_oracle_calls_or_clean_evidence():
    calls=[]
    result=run_knowledge(lambda value:calls.append(value),lambda value:calls.append(value),spec(),
        budget=8,shrink_budget=0,trusted_execution=True,input_accepts=lambda inputs:False)
    assert calls==[] and result["evidence"]==result["records"]==result["observations"]==[]
    assert result["metrics"]["oracle_calls"]==result["metrics"]["target_calls"]==0
    assert 0<result["metrics"]["native_predicate_attempts"]<=8
    assert result["native"]["predicate_calls"]==result["metrics"]["native_predicate_attempts"]
    assert result["native"]["oracle_calls"]==result["native"]["target_calls"]==0
    assert result["native"]["unique_evaluated_inputs"]==0
    assert all(r["failed"] is None and r["execution_status"]=="PRECONDITION_REJECTED"
               and r["oracle_calls"]==r["target_calls"]==0 for r in result["native"]["records"])
    assert result["timing"]["input_precondition_seconds"]>=0


def test_guard_errors_nonbool_and_noncallable_fail_before_reviewed_callbacks():
    calls=[]
    def target(value):calls.append("target");return value
    def oracle(value):calls.append("oracle");return value
    def broken(inputs):raise RuntimeError("precondition-invalid")
    with pytest.raises(RuntimeError,match="precondition-invalid"):
        run_knowledge(target,oracle,spec(),input_accepts=broken,trusted_execution=True)
    with pytest.raises(ValueError,match="exact bool"):
        run_knowledge(target,oracle,spec(),input_accepts=lambda inputs:1,trusted_execution=True)
    with pytest.raises(ValueError,match="reviewed callable"):
        run_knowledge(target,oracle,spec(),input_accepts=False,trusted_execution=True)
    assert calls==[]


def test_guard_receives_copy_and_cannot_modify_actual_arguments():
    seen=[]
    def guard(inputs):inputs["value"]=999;return True
    def target(value):seen.append(value);return value
    result=run_knowledge(target,lambda value:value,spec(),budget=8,shrink_budget=0,
                         input_accepts=guard,trusted_execution=True)
    assert seen and all(-3<=value<=3 for value in seen)
    assert result["metrics"]["precondition_rejected_attempts"]==0
    assert result["native"]["oracle_calls"]==result["native"]["predicate_calls"]==len(seen)


def test_opaque_stateful_guard_is_rejected_before_factories_actions_or_guard_execution():
    from test_e6_efficiency import stack_contract
    s,c=stack_contract();called=[]
    def factory():called.append("factory");return object()
    def model():called.append("model");return object()
    def guard(inputs):called.append("guard");return True
    with pytest.raises(ValueError,match="public EFSM preconditions"):
        run_knowledge_stateful(factory,model,{},snapshot=lambda obj:{},spec=s,
            temporal_contract=c,input_accepts=guard,trusted_execution=True)
    assert called==[]
