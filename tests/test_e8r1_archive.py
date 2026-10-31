"""Authored data-only R1 archive checks; no project/Oracle callbacks execute."""
from copy import deepcopy

import pytest

from test_e7_knowledge import evidence, provenance, spec
from test_e8_evidence import ledger, record
from tomolab.discovery.claim_semantics import EXACT, SUFFICIENT, NECESSARY, EMPIRICAL, SEMANTIC_VERSION
from tomolab.discovery.knowledge import (KnowledgeArchive, SEMANTIC_SCHEMA, evaluate_claim, make_observation,
    normalize_observation, normalize_semantic_observation)
from tomolab.discovery.schema import digest

POLICY={"max_compound_relations":0}
ZERO={"term":{"kind":"value","roles":["operand"]},"operator":"eq","value":0}


def source(events=None,**kwargs):
    return KnowledgeArchive.from_failure_log(spec(),events or [evidence(0,True,"f0"),evidence(1,False,"n1")],
        provenance(),semantic_policy=POLICY,**kwargs)


def claim(archive,kind,relation=ZERO):
    return next(row for row in archive.claims() if row["claim_kind"]==kind and row["typed_relation"]==relation
                and row["family_id"]=="reference/mismatch/zero-discrepancy")


def observe(archive,x,failed,eid,origin=None):
    return archive.observe(make_observation(spec(),evidence(x,failed,eid),origin or provenance(2)),trusted_observation=True)


def test_same_expression_has_different_direction_and_identity_in_actual_archive():
    archive=source([evidence(0,True,"f0"),evidence(1,True,"f1"),evidence(2,False,"n2")])
    rows={kind:claim(archive,kind) for kind in (EXACT,SUFFICIENT,NECESSARY,EMPIRICAL)}
    assert len({row["claim_id"] for row in rows.values()})==4
    assert all(row["confusion"]=={"TP":1,"FP":0,"FN":1,"TN":1,"UNKNOWN":0} for row in rows.values())
    assert rows[EXACT]["source_claim_status"]==rows[NECESSARY]["source_claim_status"]=="CONTRADICTED"
    assert rows[SUFFICIENT]["source_claim_status"]=="OBSERVED_WITHIN_SOURCE"
    assert rows[SUFFICIENT]["counterevidence"]["source"]==[]
    assert rows[SUFFICIENT]["confusion_evidence"]["FN"]==["source:f1"]
    assert rows[EMPIRICAL]["source_claim_status"]=="EMPIRICAL_CANDIDATE" and rows[EMPIRICAL]["utility_status"]=="NOT_VALIDATED"
    assert all(row["transfer_validation_status"]=="NOT_EXECUTED_READINESS_BLOCKED" for row in rows.values())


def test_false_positive_refutes_sufficiency_but_is_allowed_by_necessity():
    relation={"term":{"kind":"value","roles":["operand"]},"operator":"le","value":1}
    archive=source([evidence(0,True,"f0"),evidence(1,False,"n1"),evidence(2,False,"n2")])
    assert claim(archive,SUFFICIENT,relation)["source_claim_status"]=="CONTRADICTED"
    necessary=claim(archive,NECESSARY,relation)
    assert necessary["source_claim_status"]=="OBSERVED_WITHIN_SOURCE" and necessary["source_statistics"]["FP"]==1


def test_old_exact_snapshot_bytes_stay_legacy_and_new_claims_keep_parent_links():
    old=KnowledgeArchive.from_failure_log(spec(),[evidence(0,True,"f0"),evidence(1,True,"f1"),evidence(2,False,"n2")],provenance())
    parent=old.freeze();before=deepcopy(parent)
    archive=source([evidence(0,True,"f0"),evidence(1,True,"f1"),evidence(2,False,"n2")],derived_from=parent)
    row=claim(archive,SUFFICIENT)
    legacy=next(c for c in parent["claims"] if c["typed_relation"]==ZERO)
    assert legacy["status"]=="CONTRADICTED" and row["source_claim_status"]=="OBSERVED_WITHIN_SOURCE"
    assert row["derived_from"]==[legacy["claim_id"]] and row["parent_archive_sha256"]==parent["receipt"]["sha256"]
    assert old.snapshot()==before and parent==before
    assert KnowledgeArchive.from_snapshot(parent).snapshot()==parent
    assert "claim_kind" not in parent["claims"][0]


def test_independent_negative_observation_blocks_transfer_without_falsifying_source():
    archive=source();observe(archive,0,False,"C-normal")
    row=claim(archive,SUFFICIENT)
    assert row["source_claim_status"]=="OBSERVED_WITHIN_SOURCE"
    assert row["corroboration_status"]=="CONTRADICTED" and row["counterevidence"]["source"]==[]
    archive.freeze()
    assert row["claim_id"] not in {c["claim_id"] for c in archive.qualify(spec(),target_provenance=provenance(3))["claims"]}
    assert row["claim_id"] in {c["claim_id"] for c in archive.source_guidance(spec(),target_provenance=provenance())["claims"]}


def test_inconsistent_corroboration_does_not_contaminate_source_claim_status():
    archive=source()
    observe(archive,0,True,"C-first")
    observe(archive,0,False,"C-conflicting")
    row=claim(archive,SUFFICIENT)
    assert row["source_claim_status"]=="OBSERVED_WITHIN_SOURCE"
    assert row["corroboration_status"]=="INCONSISTENT_EVIDENCE"
    assert row["inconsistent_evidence_by_scope"]["source"]==[]
    assert row["inconsistent_evidence_by_scope"]["corroboration"]
    archive.freeze()
    assert row["claim_id"] in {c["claim_id"] for c in archive.source_guidance(spec(),target_provenance=provenance())["claims"]}
    assert row["claim_id"] not in {c["claim_id"] for c in archive.qualify(spec(),target_provenance=provenance(3))["claims"]}


def test_same_independent_implementation_and_oracle_must_supply_both_contrasts():
    split=source();observe(split,0,True,"C-positive",provenance(2));observe(split,1,False,"C-negative",provenance(3))
    assert claim(split,SUFFICIENT)["corroboration_status"]=="NOT_ESTABLISHED"
    together=source();observe(together,0,True,"C-positive");observe(together,1,False,"C-negative")
    assert claim(together,SUFFICIENT)["corroboration_status"]=="SUPPORTED_WITHIN_SCOPE"
    together.freeze()
    assert claim(together,SUFFICIENT)["claim_id"] in {c["claim_id"] for c in together.qualify(spec(),target_provenance=provenance(4))["claims"]}
    assert not together.qualify(spec(),target_provenance=provenance(2))["claims"]


def test_empirical_trial_is_explicit_and_never_independent_qualification():
    archive=source();archive.freeze()
    baseline=archive.source_guidance(spec(),target_provenance=provenance())
    trial=archive.source_guidance(spec(),target_provenance=provenance(),allow_unvalidated_empirical=True)
    assert all(c["claim_kind"]!=EMPIRICAL for c in baseline["claims"])
    empirical=[c for c in trial["claims"] if c["claim_kind"]==EMPIRICAL]
    assert empirical and all(c["status"]=="EMPIRICAL_TEST_CANDIDATE" and not c["qualified"] for c in empirical)
    assert trial["independent_transfer_authorized"] is False
    assert not archive.source_guidance(spec(),target_provenance=provenance(2),allow_unvalidated_empirical=True)["claims"]


def test_censored_other_failure_family_is_unknown_not_negative():
    foreign=evidence(1,True,"other");foreign["signature"]="another-mechanism"
    archive=source([evidence(0,True,"f0"),foreign,evidence(2,False,"n2")])
    row=claim(archive,SUFFICIENT)
    assert row["confusion"]["UNKNOWN"]==1 and row["unknown_evidence"]==["source:other"]
    assert row["source_statistics"]["FP"]==0


def test_new_schema_replays_and_rehashed_kind_or_policy_cannot_reuse_authority():
    archive=source();snapshot=archive.freeze()
    assert snapshot["schema"]==SEMANTIC_SCHEMA
    assert KnowledgeArchive.from_snapshot(snapshot).snapshot()==snapshot
    bad=deepcopy(snapshot);bad["claims"][0]["claim_kind"]=NECESSARY if bad["claims"][0]["claim_kind"]!=NECESSARY else SUFFICIENT
    bad["receipt"]["sha256"]=digest({k:v for k,v in bad.items() if k!="receipt"})
    with pytest.raises(ValueError,match="derived state"):KnowledgeArchive.from_snapshot(bad)
    bad=deepcopy(snapshot);bad["semantic_policy"]["semantic_version"]="future-meaning"
    bad["receipt"]["sha256"]=digest({k:v for k,v in bad.items() if k!="receipt"})
    with pytest.raises(ValueError):KnowledgeArchive.from_snapshot(bad)


def test_new_source_validation_requires_frozen_parent_and_preserves_parent():
    relation={"term":{"kind":"value","roles":["operand"]},"operator":"le","value":0}
    archive=source([evidence(-1,True,"f"),evidence(1,False,"n")]);parent=archive.freeze();before=deepcopy(parent)
    with pytest.raises(ValueError,match="frozen"):
        archive.record_source_validation([make_observation(spec(),evidence(0,False,"new"),provenance())],frozen_before_sha256=parent["receipt"]["sha256"],trusted_observation=True)
    child=archive.fork("validation-generation")
    child.record_source_validation([make_observation(spec(),evidence(0,False,"new"),provenance())],
        frozen_before_sha256=parent["receipt"]["sha256"],trusted_observation=True,batch_receipt_sha256="a"*64)
    row=claim(child,SUFFICIENT,relation)
    assert row["source_validation_status"]==row["source_claim_status"]=="CONTRADICTED"
    assert row["source_validation_statistics"]["FP"]==1
    assert archive.snapshot()==parent==before
    snapshot=child.freeze();assert KnowledgeArchive.from_snapshot(snapshot).snapshot()==snapshot


def test_utility_needs_separate_source_batch_and_cost_benefit_not_survival():
    archive=source();parent=archive.freeze();child=archive.fork("utility-generation")
    cid=claim(archive,EMPIRICAL)["claim_id"]
    receipt=dict(schema="tomolab-e8r1-guidance-utility-v1",semantic_version=SEMANTIC_VERSION,
        source_archive_sha256=parent["receipt"]["sha256"],validation_scope="SOURCE_DEVELOPMENT_ONLY",
        comparison_contract_sha256="c"*64,batch_receipt_sha256="b"*64,claim_ids=[cid],
        baseline=dict(found=True,target_calls=8,oracle_calls=8,wall_seconds=2.0),
        guided=dict(found=True,target_calls=4,oracle_calls=4,wall_seconds=1.0),selection_changed=True,
        novel_guided_candidates=1,first_discovery_new_guided=True,
        batch_attribution="ASSOCIATED_METHOD_BATCH_NOT_INDIVIDUAL_RULE_CAUSAL_EFFECT",criteria=dict(max_wall_ratio=1.25,max_call_ratio=1.0))
    receipt["receipt_sha256"]=digest(receipt)
    with pytest.raises(ValueError,match="separately recorded"):
        child.record_guidance_utility(receipt,trusted_host=True)
    child.record_source_validation([make_observation(spec(),evidence(0,True,"new-actual-source-observation"),provenance())],
        frozen_before_sha256=parent["receipt"]["sha256"],trusted_observation=True,batch_receipt_sha256="b"*64)
    child.record_guidance_utility(receipt,trusted_host=True)
    assert claim(child,EMPIRICAL)["utility_status"]=="UTILITY_SUPPORTED"
    assert claim(child,EMPIRICAL)["corroboration_status"]=="NOT_ESTABLISHED"
    final=child.freeze();assert KnowledgeArchive.from_snapshot(final).snapshot()==final
    assert not child.qualify(spec(),target_provenance=provenance(3))["claims"]


def test_both_methods_miss_does_not_validate_empirical_utility():
    archive=source();parent=archive.freeze();child=archive.fork("no-utility")
    child.record_source_validation([make_observation(spec(),evidence(2,False,"additional-normal"),provenance())],
        frozen_before_sha256=parent["receipt"]["sha256"],trusted_observation=True,batch_receipt_sha256="b"*64)
    cid=claim(child,EMPIRICAL)["claim_id"]
    receipt=dict(schema="tomolab-e8r1-guidance-utility-v1",semantic_version=SEMANTIC_VERSION,
        source_archive_sha256=parent["receipt"]["sha256"],validation_scope="SOURCE_DEVELOPMENT_ONLY",comparison_contract_sha256="c"*64,
        batch_receipt_sha256="b"*64,claim_ids=[cid],baseline=dict(found=False,target_calls=8,oracle_calls=8,wall_seconds=2.0),
        guided=dict(found=False,target_calls=8,oracle_calls=8,wall_seconds=1.0),selection_changed=True,novel_guided_candidates=2,first_discovery_new_guided=False,
        batch_attribution="ASSOCIATED_METHOD_BATCH_NOT_INDIVIDUAL_RULE_CAUSAL_EFFECT",
        criteria=dict(max_wall_ratio=1.25,max_call_ratio=1.0))
    receipt["receipt_sha256"]=digest(receipt);child.record_guidance_utility(receipt,trusted_host=True)
    assert claim(child,EMPIRICAL)["utility_status"]=="NO_UTILITY_DEMONSTRATED"


def test_producer_neutral_evidence_reaches_new_semantics_without_legacy_filter():
    bundle=ledger()
    for row in [record("source-0",0,True),record("source-1",1,True),record("source-2",2,False)]:bundle.ingest(row,trusted_host=True)
    archive=bundle.build_knowledge_archive(semantic_policy=POLICY)
    sufficient=[c for c in archive.claims() if c["claim_kind"]==SUFFICIENT and c["source_statistics"]["FN"] and not c["counterevidence"]["source"]]
    assert sufficient and archive.snapshot()["source_observations"]==3
    assert all(evaluate_claim(c,{"value":0},archive.spec) in (True,False,None) for c in sufficient)


def test_partial_engine_snapshot_import_uses_explicit_semantics_on_restore():
    from tomolab.discovery.engine import DiscoveryEngine
    engine=DiscoveryEngine(spec(),semantic_policy=POLICY,_pool=[{"value":0},{"value":1},{"value":2}],pool_size=3,native_strategy=False)
    for point in engine.pool:
        index=engine._index[__import__('json').dumps(point,sort_keys=True,separators=(',',':'))]
        engine._seen.add(index);engine.seen.append(index)
        engine.observe(evidence(point["value"],point["value"]<2,"engine-"+str(point["value"])))
    archive=KnowledgeArchive.from_engine_snapshot(engine.freeze(),provenance())
    assert claim(archive,SUFFICIENT)["source_claim_status"]=="OBSERVED_WITHIN_SOURCE"
    snapshot=archive.freeze();assert KnowledgeArchive.from_snapshot(snapshot).snapshot()==snapshot


def test_shared_semantic_observation_preserves_unobserved_label_and_strict_boundary():
    value=make_observation(spec(),evidence(1,False,"unobserved-family"),provenance())
    value["evidence"]["observation_status"]="UNOBSERVED"
    value["receipt_sha256"]=digest({k:v for k,v in value.items() if k!="receipt_sha256"})
    assert normalize_semantic_observation(value)==value
    with pytest.raises(ValueError):normalize_observation(value)
    with pytest.raises(ValueError):normalize_semantic_observation(dict(value,hidden_answer=0))
    archive=source();archive.observe(value,trusted_observation=True)
    assert claim(archive,SUFFICIENT)["unknown_evidence"]==[value["receipt_sha256"]]


def test_source_gate_receipt_cache_does_not_share_claims_or_cross_changed_scope():
    archive=source();parent=archive.freeze()
    gate=archive.source_guidance(spec(),target_provenance=provenance())
    assert gate["source_archive_sha256"]==parent["receipt"]["sha256"]
    gate["claims"][0]["source_statistics"]["TP"]=999
    assert archive.snapshot()==parent
    archive.source["oracle_sha256"]="a"*64
    with pytest.raises(ValueError,match="bound R1"):
        archive.source_guidance(spec(),target_provenance=archive.source)


def test_fixed_event_cap_counts_source_corroboration_and_validation_rows_together():
    archive=KnowledgeArchive.from_failure_log(spec(),[evidence(0,True,"f0"),evidence(1,False,"n1")],provenance(),
        semantic_policy={"max_compound_relations":0,"max_events":3})
    observe(archive,0,True,"C-one")
    before=archive.snapshot()
    with pytest.raises(ValueError,match="bounded R1"):
        observe(archive,1,False,"C-two")
    assert archive.snapshot()==before
    parent=archive.freeze();child=archive.fork("cap-validation")
    with pytest.raises(ValueError,match="capacity"):
        child.record_source_validation([make_observation(spec(),evidence(2,False,"new"),provenance())],
            frozen_before_sha256=parent["receipt"]["sha256"],trusted_observation=True)


@pytest.mark.parametrize("claim_ids_empty",[False,True])
def test_native_or_known_replay_discovery_never_credits_trial_rules(claim_ids_empty):
    archive=source();parent=archive.freeze();child=archive.fork("native-discovery")
    child.record_source_validation([make_observation(spec(),evidence(2,False,"new-source-normal"),provenance())],
        frozen_before_sha256=parent["receipt"]["sha256"],trusted_observation=True,batch_receipt_sha256="b"*64)
    cid=claim(child,EMPIRICAL)["claim_id"]
    receipt=dict(schema="tomolab-e8r1-guidance-utility-v1",semantic_version=SEMANTIC_VERSION,
        source_archive_sha256=parent["receipt"]["sha256"],validation_scope="SOURCE_DEVELOPMENT_ONLY",comparison_contract_sha256="c"*64,
        batch_receipt_sha256="b"*64,claim_ids=[] if claim_ids_empty else [cid],
        baseline=dict(found=True,target_calls=8,oracle_calls=8,wall_seconds=2.0),
        guided=dict(found=True,target_calls=4,oracle_calls=4,wall_seconds=1.0),selection_changed=True,novel_guided_candidates=2,
        first_discovery_new_guided=False,batch_attribution="ASSOCIATED_METHOD_BATCH_NOT_INDIVIDUAL_RULE_CAUSAL_EFFECT",
        criteria=dict(max_wall_ratio=1.25,max_call_ratio=1.0))
    receipt["receipt_sha256"]=digest(receipt);child.record_guidance_utility(receipt,trusted_host=True)
    assert claim(child,EMPIRICAL)["utility_status"]==("NOT_VALIDATED" if claim_ids_empty else "NO_UTILITY_DEMONSTRATED")
    assert child.snapshot()["utility_journal"][-1]["guided"]["found"] is True
    assert len(child.snapshot()["utility_journal"])==1
