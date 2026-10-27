from copy import deepcopy
import json

import pytest

from tomolab.discovery.knowledge import (KnowledgeArchive, evaluate_claim, make_observation,
                                          normalize_observation, validate_provenance)
from tomolab.discovery.knowledge_store import KnowledgeStore
from tomolab.discovery.schema import digest


def spec(name="value"):
    return {"schema":"tomolab-discovery-spec-v1","task_id":"knowledge-"+name,
            "inputs":[{"name":name,"role":"operand","type":{"kind":"int","min":-3,"max":3}}],
            "contract":{"id":"zero-boundary","operation":"reciprocal","preconditions":[],
                        "invariants":["reference"],"state_model":"stateless","graph_signature":"UNKNOWN"}}


def provenance(number=1,**changes):
    result={"project":"project-"+str(number),"lineage":"lineage-"+str(number),
            "revision":"revision-"+str(number),"oracle_id":"oracle-"+str(number),
            "semantics":"reciprocal-zero-v1","implementation_sha256":str(number)*64,
            "oracle_sha256":str(number+4)*64,"independence_id":"review-"+str(number)}
    result.update(changes);return result


def evidence(value,failed,eid,name="value"):
    return {"evidence_id":eid,"kind":"FAILURE" if failed else "REFUTATION","inputs":{name:value},
            "invariant":"reference","category":"mismatch","signature":"zero-discrepancy"}


def source():
    return KnowledgeArchive.from_failure_log(spec(),[evidence(0,True,"source-0"),evidence(1,False,"source-1")],provenance())


def zero_claim(archive):
    return next(c for c in archive.claims() if c["typed_relation"]=={"term":{"kind":"value","roles":["operand"]},"operator":"eq","value":0})


def observe_contrast(archive,origin=None):
    origin=origin or provenance(2)
    for value,failed in [(0,True),(1,False)]:
        archive.observe(make_observation(spec("renamed"),evidence(value,failed,"ind-"+str(value),"renamed"),origin),trusted_observation=True)


def test_real_failure_log_reuses_version_space_and_retains_competing_refutations():
    archive=source()
    assert zero_claim(archive)["status"]=="HYPOTHESIS"
    assert any(c["status"]=="CONTRADICTED" for c in archive.claims())
    snapshot=archive.snapshot()
    assert snapshot["competing_groups"]
    assert all(c["competing_group"] in snapshot["competing_groups"] for c in snapshot["claims"])
    assert all("actual" not in c and "expected" not in c for c in snapshot["claims"])


def test_actual_independent_contrastive_receipts_qualify_role_renamed_probe():
    archive=source();observe_contrast(archive)
    assert zero_claim(archive)["status"]=="SUPPORTED_WITHIN_SCOPE"
    archive.freeze()
    gate=archive.qualify(spec("target"),target_provenance=provenance(3))
    assert gate["status"]=="QUALIFIED_FOR_PROBING"
    claim=next(c for c in gate["claims"] if c["claim_id"]==zero_claim(archive)["claim_id"])
    assert evaluate_claim(claim,{"target":0},spec("target")) is True
    assert evaluate_claim(claim,{"target":1},spec("target")) is False
    assert gate["final_feedback_allowed"] is False and gate["failure_recurrence"]=="UNKNOWN"


def test_support_requires_negative_control_and_both_independent_code_and_oracle():
    archive=source()
    event=make_observation(spec(),evidence(0,True,"only-positive"),provenance(2))
    archive.observe(event,trusted_observation=True)
    assert zero_claim(archive)["status"]=="HYPOTHESIS"
    for field in ["implementation_sha256","oracle_sha256","independence_id","lineage"]:
        another=source(); origin=provenance(2,**{field:provenance()[field]});observe_contrast(another,origin)
        assert zero_claim(another)["status"]=="HYPOTHESIS"


def test_strings_alone_are_not_independent_evidence_and_receipt_requires_host_approval():
    archive=source();origin={k:v for k,v in provenance(2).items() if k not in {"oracle_sha256","independence_id"}}
    event=make_observation(spec(),evidence(0,True,"new"),origin)
    with pytest.raises(PermissionError):archive.observe(event)
    archive.observe(event,trusted_observation=True)
    assert zero_claim(archive)["status"]=="HYPOTHESIS"


def test_single_counterexample_permanently_blocks_qualified_transfer_and_is_preserved():
    archive=source();observe_contrast(archive)
    archive.observe(make_observation(spec(),evidence(0,False,"disproof"),provenance(3)),trusted_observation=True)
    claim=zero_claim(archive)
    assert claim["status"]=="CONTRADICTED" and claim["contradicting_evidence"]
    assert claim["supporting_evidence"] and claim["independent_positive"]
    archive.freeze();gate=archive.qualify(spec(),target_provenance=provenance(2))
    assert claim["claim_id"] not in {c["claim_id"] for c in gate["claims"]}
    assert KnowledgeArchive.from_snapshot(archive.snapshot()).snapshot()==archive.snapshot()


def test_unknown_semantics_or_contract_rejects_transfer_and_retains_ignored_receipt():
    archive=source();observe_contrast(archive)
    bad=make_observation(spec(),evidence(0,False,"different-meaning"),provenance(3,semantics="different-operation"))
    archive.observe(bad,trusted_observation=True)
    assert zero_claim(archive)["status"]=="SUPPORTED_WITHIN_SCOPE"
    assert zero_claim(archive)["ignored_evidence"]
    archive.freeze()
    assert not archive.qualify(spec(),target_provenance=provenance(3,semantics="different-operation"))["claims"]
    changed=spec();changed["contract"]["operation"]="unrelated"
    assert not archive.qualify(changed,target_provenance=provenance(3))["claims"]


def test_coordinate_hypothesis_never_promoted_even_with_matching_independent_labels():
    archive=KnowledgeArchive.from_failure_log(spec(),[evidence(2,True,"f"),evidence(1,False,"n")],provenance())
    for x,failed in [(2,True),(1,False)]:
        archive.observe(make_observation(spec(),evidence(x,failed,"i-"+str(x)),provenance(2)),trusted_observation=True)
    coordinate=[c for c in archive.claims() if c["typed_relation"]=={"term":{"kind":"value","roles":["operand"]},"operator":"eq","value":2}][0]
    assert coordinate["coordinate_only"] and coordinate["status"]=="HYPOTHESIS"
    archive.freeze()
    assert coordinate["claim_id"] not in {c["claim_id"] for c in archive.qualify(spec(),target_provenance=provenance(3))["claims"]}


def test_unknown_raw_or_subjective_fields_and_final_split_are_rejected():
    event=make_observation(spec(),evidence(0,True,"f"),provenance(2))
    for extra in ["actual","expected","score","source","final_label"]:
        bad=deepcopy(event);bad[extra]=0;bad["receipt_sha256"]=digest({k:v for k,v in bad.items() if k!="receipt_sha256"})
        with pytest.raises(ValueError):normalize_observation(bad)
    event["split"]="final";event["receipt_sha256"]=digest({k:v for k,v in event.items() if k!="receipt_sha256"})
    with pytest.raises(ValueError,match="final feedback"):normalize_observation(event)


def test_frozen_learning_and_observing_fail_before_mutation():
    archive=source();before=archive.freeze()
    with pytest.raises(ValueError,match="frozen"):archive.learn([evidence(2,False,"new")])
    with pytest.raises(ValueError,match="frozen"):archive.observe(make_observation(spec(),evidence(2,False,"new"),provenance(2)),trusted_observation=True)
    assert archive.snapshot()==before


def test_rehashed_derived_status_and_journal_tamper_rejected():
    archive=source();snapshot=archive.freeze()
    bad=deepcopy(snapshot);bad["claims"][0]["status"]="QUALIFIED_FOR_PROBING"
    bad["receipt"]["sha256"]=digest({k:v for k,v in bad.items() if k!="receipt"})
    with pytest.raises(ValueError,match="derived state"):KnowledgeArchive.from_snapshot(bad)
    bad=deepcopy(snapshot);bad["journal"][0]["evidence"][0]["actual"]={"hidden":1}
    bad["receipt"]["sha256"]=digest({k:v for k,v in bad.items() if k!="receipt"})
    with pytest.raises(ValueError):KnowledgeArchive.from_snapshot(bad)


def test_evidence_idempotency_and_conflicting_id_fail_closed():
    archive=source();before=archive.snapshot()
    archive.learn([evidence(0,True,"source-0")]);assert before==archive.snapshot()
    with pytest.raises(ValueError,match="ID conflict"):archive.learn([evidence(1,True,"source-0")])
    event=make_observation(spec(),evidence(0,True,"observed"),provenance(2))
    archive.observe(event,trusted_observation=True);once=archive.snapshot();archive.observe(event,trusted_observation=True)
    assert archive.snapshot()==once
    bad=make_observation(spec(),evidence(0,False,"observed"),provenance(2))
    with pytest.raises(ValueError,match="ID conflict"):archive.observe(bad,trusted_observation=True)


def test_append_only_store_is_idempotent_and_retains_previous_snapshots(tmp_path):
    archive=source();store=KnowledgeStore(tmp_path/"knowledge.jsonl")
    first=store.append(archive.snapshot(),record_id="before-audit")
    original=(tmp_path/"knowledge.jsonl").read_bytes()
    assert store.append(archive.snapshot(),record_id="before-audit")["status"]=="ALREADY_COMMITTED"
    assert (tmp_path/"knowledge.jsonl").read_bytes()==original
    observe_contrast(archive);store.append(archive.freeze(),record_id="after-audit")
    assert (tmp_path/"knowledge.jsonl").read_bytes().startswith(original)
    assert len(store.records())==2 and store.latest().snapshot()==archive.snapshot()
    with pytest.raises(ValueError,match="ID conflict"):store.append(archive.snapshot(),record_id="before-audit")
    assert first["status"]=="COMMITTED"


def test_store_tamper_truncation_and_competing_writer_are_not_silently_repaired(tmp_path):
    path=tmp_path/"knowledge.jsonl";store=KnowledgeStore(path);store.append(source().snapshot(),record_id="a")
    original=path.read_bytes();path.write_bytes(original[:-1])
    with pytest.raises(ValueError,match="incomplete"):store.records()
    assert path.read_bytes()==original[:-1]
    path.write_bytes(original);row=json.loads(original);row["previous_sha256"]="f"*64;path.write_text(json.dumps(row)+"\n")
    with pytest.raises(ValueError,match="chain|rewritten"):store.records()
    path.write_bytes(original);path.with_name(path.name+".lock").write_text("another writer")
    with pytest.raises(FileExistsError):store.append(source().snapshot(),record_id="b")
    assert path.read_bytes()==original


def test_temporal_source_failure_uses_first_failed_transition_and_freezes():
    from test_e6_efficiency import stack_contract
    s,c=stack_contract()
    def temporal_event(trace,fail,eid):
        return {"kind":"FAILURE" if fail else "REFUTATION","evidence_id":eid,"inputs":{"trace":trace},
                "invariant":s["contract"]["invariants"][0],"category":"state_violation","signature":"size-mismatch",
                "first_failure_index":len(trace)-1 if fail else None}
    archive=KnowledgeArchive.from_failure_log(s,[temporal_event([["push",0],["pop",0]],True,"f"),temporal_event([["push",1]],False,"n")],provenance(),temporal_contract=c)
    assert any(v["typed_relation"]["term"]["kind"]=="temporal" for v in archive.claims())
    assert any(v["status"]=="HYPOTHESIS" for v in archive.claims())
    snapshot=archive.freeze();assert KnowledgeArchive.from_snapshot(snapshot).snapshot()==snapshot


def test_rehashed_thaw_does_not_bypass_terminal_freeze_journal():
    snapshot=source().freeze();snapshot["frozen"]=False
    snapshot["receipt"]["sha256"]=digest({k:v for k,v in snapshot.items() if k!="receipt"})
    with pytest.raises(ValueError,match="derived state"):KnowledgeArchive.from_snapshot(snapshot)


def test_contrastive_signs_from_two_always_single_label_implementations_do_not_qualify():
    archive=source()
    archive.observe(make_observation(spec(),evidence(0,True,"p"),provenance(2)),trusted_observation=True)
    archive.observe(make_observation(spec(),evidence(1,False,"n"),provenance(3)),trusted_observation=True)
    assert zero_claim(archive)["status"]=="HYPOTHESIS"
    assert not zero_claim(archive)["independent_contrastive_origins"]


def test_ast_membership_reuses_validated_predicate_not_source_literal_score():
    archive=source()
    relation={"term":{"kind":"ast","roles":["operand"],"expression":{"op":"eq","left":{"var":"operand"},"right":0}},"operator":"eq","value":1}
    claim={"typed_relation":relation}
    assert evaluate_claim(claim,{"value":0},spec()) is True
    assert evaluate_claim(claim,{"value":2},spec()) is False
    relation["value"]=0
    with pytest.raises(ValueError,match="AST predicate membership"):evaluate_claim(claim,{"value":0},spec())


def test_import_actual_frozen_e5_engine_snapshot_and_replay_archive():
    from tomolab.discovery.engine import DiscoveryEngine
    points=[{"value":0},{"value":1}]
    engine=DiscoveryEngine(spec(),_pool=points,native_strategy=False,pool_size=2)
    for n in [0,1]:
        engine._seen.add(n);engine.seen.append(n);engine.observe(evidence(n,n==0,"old-"+str(n)))
    archive=KnowledgeArchive.from_engine_snapshot(engine.freeze(),provenance())
    assert zero_claim(archive)["status"]=="HYPOTHESIS"
    frozen=archive.freeze();assert KnowledgeArchive.from_snapshot(frozen).snapshot()==frozen


def test_conflicting_failure_families_for_same_implementation_input_do_not_qualify():
    archive=source();observe_contrast(archive)
    changed=evidence(0,True,"other-family");changed["signature"]="different-mechanism"
    archive.observe(make_observation(spec("renamed"),{**changed,"inputs":{"renamed":0}},provenance(2)),trusted_observation=True)
    assert zero_claim(archive)["status"]=="CONTRADICTED"


def test_new_record_id_cannot_resurrect_archive_before_counterevidence(tmp_path):
    archive=source();observe_contrast(archive)
    old=archive.snapshot();store=KnowledgeStore(tmp_path/"knowledge.jsonl")
    store.append(old,record_id="supported")
    archive.observe(make_observation(spec(),evidence(0,False,"refuted"),provenance(3)),trusted_observation=True)
    store.append(archive.freeze(),record_id="contradicted")
    before=(tmp_path/"knowledge.jsonl").read_bytes()
    with pytest.raises(ValueError,match="rollback"):store.append(old,record_id="resurrected")
    assert (tmp_path/"knowledge.jsonl").read_bytes()==before
    assert zero_claim(store.latest())["status"]=="CONTRADICTED"


def test_validation_cache_reuses_only_exact_frozen_bytes_and_copies_state(monkeypatch):
    import tomolab.discovery.knowledge as module
    module._VALIDATED_ARCHIVES.clear()
    snapshot=source().freeze();original=KnowledgeArchive._restore_snapshot.__func__;calls=[]
    def restore(cls,value):
        calls.append(1);return original(cls,value)
    monkeypatch.setattr(KnowledgeArchive,"_restore_snapshot",classmethod(restore))
    first=KnowledgeArchive.from_snapshot(snapshot)
    first.source["revision"]="caller-mutated-copy"
    second=KnowledgeArchive.from_snapshot(snapshot)
    assert len(calls)==1 and second.snapshot()==snapshot
    bad=deepcopy(snapshot);bad["claims"][0]["status"]="QUALIFIED_FOR_PROBING"
    bad["receipt"]["sha256"]=digest({k:v for k,v in bad.items() if k!="receipt"})
    with pytest.raises(ValueError,match="derived state"):KnowledgeArchive.from_snapshot(bad)
    assert len(calls)==2
    monkeypatch.setattr(module,"VALIDATION_CACHE_VERSION","next-validator-version")
    assert KnowledgeArchive.from_snapshot(snapshot).snapshot()==snapshot and len(calls)==3
    assert KnowledgeArchive.from_snapshot(snapshot).snapshot()==snapshot and len(calls)==3


def test_validation_cache_does_not_memoize_mutable_development_or_boolean_counter_tamper(monkeypatch):
    import tomolab.discovery.knowledge as module
    module._VALIDATED_ARCHIVES.clear()
    live=source().snapshot()
    KnowledgeArchive.from_snapshot(live);KnowledgeArchive.from_snapshot(live)
    assert not module._VALIDATED_ARCHIVES
    frozen=source().freeze();frozen["source_observations"]=float(frozen["source_observations"])
    frozen["receipt"]["sha256"]=digest({k:v for k,v in frozen.items() if k!="receipt"})
    with pytest.raises(ValueError,match="derived state"):KnowledgeArchive.from_snapshot(frozen)
    assert not module._VALIDATED_ARCHIVES


def test_caller_mutation_between_cache_key_and_replay_cannot_resurrect_counterevidence(monkeypatch):
    import tomolab.discovery.knowledge as module
    archive=source();observe_contrast(archive)
    supported=KnowledgeArchive.from_snapshot(archive.snapshot()).freeze()
    archive.observe(make_observation(spec(),evidence(0,False,"race-refutation"),provenance(3)),trusted_observation=True)
    contradicted=archive.freeze();cid=zero_claim(archive)["claim_id"]
    assert next(c for c in supported["claims"] if c["claim_id"]==cid)["status"]=="SUPPORTED_WITHIN_SCOPE"
    caller=deepcopy(contradicted)
    module._VALIDATED_ARCHIVES.clear()
    original=KnowledgeArchive._restore_snapshot.__func__
    def mutate_caller_at_validation_boundary(cls,captured):
        caller.clear();caller.update(deepcopy(supported))
        return original(cls,captured)
    with monkeypatch.context() as patch:
        patch.setattr(KnowledgeArchive,"_restore_snapshot",classmethod(mutate_caller_at_validation_boundary))
        restored=KnowledgeArchive.from_snapshot(caller)
    assert restored.status(cid)=="CONTRADICTED"
    assert caller==supported  # The deterministic competing-writer schedule occurred.
    assert KnowledgeArchive.from_snapshot(deepcopy(contradicted)).status(cid)=="CONTRADICTED"
    assert KnowledgeArchive.from_snapshot(deepcopy(supported)).status(cid)=="SUPPORTED_WITHIN_SCOPE"


def test_explicit_fork_preserves_frozen_parent_and_actual_new_development_counterevidence(tmp_path):
    archive=source();observe_contrast(archive)
    parent=archive.freeze();parent_bytes=json.dumps(parent,sort_keys=True)
    child=archive.fork("generation-2")
    assert child.frozen is False and child.generation_id=="generation-2"
    assert child.snapshot()["journal"][:-1]==parent["journal"]
    assert child.snapshot()["journal"][-1]=={"action":"fork","generation_id":"generation-2","parent_sha256":parent["receipt"]["sha256"]}
    assert child.snapshot()["claims"]==parent["claims"]
    assert child.snapshot()["source_observations"]==parent["source_observations"]
    assert child.snapshot()["independent_observations"]==parent["independent_observations"]
    # A directly authored clean target and separate reference are actually run.
    def clean_target(value):return value+0
    def independent_reference(value):return value
    failed=clean_target(0)!=independent_reference(0)
    assert failed is False
    child.observe(make_observation(spec(),evidence(0,failed,"generation-2-clean"),provenance(3)),trusted_observation=True)
    assert zero_claim(child)["status"]=="CONTRADICTED"
    assert zero_claim(archive)["status"]=="SUPPORTED_WITHIN_SCOPE"
    assert json.dumps(archive.snapshot(),sort_keys=True)==parent_bytes
    frozen_child=child.freeze()
    assert KnowledgeArchive.from_snapshot(frozen_child).snapshot()==frozen_child
    store=KnowledgeStore(tmp_path/"generations.jsonl")
    store.append(parent,record_id="generation-1")
    old_bytes=(tmp_path/"generations.jsonl").read_bytes()
    store.append(frozen_child,record_id="generation-2")
    assert (tmp_path/"generations.jsonl").read_bytes().startswith(old_bytes)
    assert zero_claim(store.latest())["status"]=="CONTRADICTED"
    assert store.records()[0]["snapshot"]==parent
    with pytest.raises(ValueError,match="rollback"):store.append(parent,record_id="resurrect-generation-1")


def test_fork_requires_frozen_parent_unique_generation_id_and_keeps_existing_refutations():
    archive=source()
    with pytest.raises(ValueError,match="frozen parent"):archive.fork("generation-2")
    archive.freeze();child=archive.fork("generation-2")
    with pytest.raises(ValueError,match="frozen parent"):child.fork("generation-3")
    child.freeze()
    with pytest.raises(ValueError,match="already used"):child.fork("generation-2")
    with pytest.raises(ValueError,match="identifier"):child.fork("invalid generation id")
    grandchild=child.fork("generation-3")
    old_refuted={c["claim_id"] for c in archive.claims() if c["status"]=="CONTRADICTED"}
    assert old_refuted and old_refuted<={c["claim_id"] for c in grandchild.claims() if c["status"]=="CONTRADICTED"}


def test_fork_receipt_parent_generation_id_and_current_terminal_freeze_are_replayed():
    archive=source();archive.freeze();child=archive.fork("generation-2")
    live=child.snapshot()
    assert KnowledgeArchive.from_snapshot(live).snapshot()==live
    for field,value in [("parent_sha256","f"*64),("generation_id","renamed-without-matching-derived-id")]:
        bad=deepcopy(live);bad["journal"][-1][field]=value
        bad["receipt"]["sha256"]=digest({k:v for k,v in bad.items() if k!="receipt"})
        with pytest.raises(ValueError,match="fork|derived state"):KnowledgeArchive.from_snapshot(bad)
    bad=deepcopy(live);bad["journal"]=[r for r in bad["journal"] if r["action"]!="freeze"]
    bad["receipt"]["sha256"]=digest({k:v for k,v in bad.items() if k!="receipt"})
    with pytest.raises(ValueError,match="frozen parent"):KnowledgeArchive.from_snapshot(bad)
    bad=deepcopy(live);bad["frozen"]=True
    bad["receipt"]["sha256"]=digest({k:v for k,v in bad.items() if k!="receipt"})
    with pytest.raises(ValueError,match="derived state"):KnowledgeArchive.from_snapshot(bad)


def test_fork_cannot_accept_final_feedback_or_unreceipted_source_log_and_keeps_event_caps(monkeypatch):
    import tomolab.discovery.knowledge as module
    archive=source();observe_contrast(archive);archive.freeze()
    child=archive.fork("generation-2");before=child.snapshot()
    final=make_observation(spec(),evidence(0,False,"final-forbidden"),provenance(3))
    final["split"]="final";final["receipt_sha256"]=digest({k:v for k,v in final.items() if k!="receipt_sha256"})
    with pytest.raises(ValueError,match="final feedback"):child.observe(final,trusted_observation=True)
    with pytest.raises(ValueError,match="development observation receipts"):child.learn([evidence(0,False,"unreceipted")])
    assert child.snapshot()==before
    monkeypatch.setattr(module,"MAX_EVENTS",2)
    with pytest.raises(ValueError,match="observation cap"):child.observe(make_observation(spec(),evidence(0,False,"new-dev"),provenance(3)),trusted_observation=True)


def test_fork_preserves_unique_generation_ids_across_full_lineage_and_generation_cap(monkeypatch):
    import tomolab.discovery.knowledge as module
    archive=source();archive.freeze();child=archive.fork("generation-2");child.freeze()
    grandchild=child.fork("generation-3");grandchild.freeze()
    with pytest.raises(ValueError,match="already used"):grandchild.fork("generation-2")
    bad=deepcopy(grandchild.snapshot());forks=[r for r in bad["journal"] if r["action"]=="fork"]
    forks[-1]["generation_id"]=forks[0]["generation_id"]
    bad["receipt"]["sha256"]=digest({k:v for k,v in bad.items() if k!="receipt"})
    with pytest.raises(ValueError,match="already used"):KnowledgeArchive.from_snapshot(bad)
    monkeypatch.setattr(module,"MAX_GENERATIONS",2)
    with pytest.raises(ValueError,match="generation cap"):grandchild.fork("generation-4")
