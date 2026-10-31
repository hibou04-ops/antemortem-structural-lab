"""Authored truth-table regression; no project Target or Oracle is called."""
from copy import deepcopy

import pytest

from test_discovery_engine import evidence, spec
from tomolab.discovery.engine import DiscoveryEngine, transfer
from tomolab.discovery.features import holds, measurements, relation_id, relation_truth
from tomolab.discovery.schema import canonical, digest
from tomolab.discovery.claim_semantics import (
    CLAIM_KINDS, DEFAULT_POLICY, EXACT, SUFFICIENT, NECESSARY, EMPIRICAL,
    SEMANTIC_VERSION, classify, kleene, normalize_policy, normalize_semantic_evidence,
    relation_prediction, semantic_claim_id, semantic_label, semantic_grammar,
)


def relation(kind="value", operator="eq", value=0):
    return {"term":{"kind":kind,"roles":["operand"]},"operator":operator,"value":value}


def compound(op, *args):
    return {"term":{"kind":"compound","roles":["operand"],"expression":{"op":op,"args":list(args)}},"operator":"eq","value":1}


def ready_engine(*, kinds=CLAIM_KINDS, pool=None):
    points=pool or [{"value":x} for x in (-1,0,1,2)]
    engine=DiscoveryEngine(spec(),_pool=points,pool_size=len(points),native_strategy=False,
        claim_kinds=kinds,semantic_policy=DEFAULT_POLICY)
    for _ in points:
        engine.propose()
    return engine


@pytest.mark.parametrize("predicted,observed,cell,refuted", [
    (True,True,"TP",set()),(True,False,"FP",{EXACT,SUFFICIENT}),
    (False,True,"FN",{EXACT,NECESSARY}),(False,False,"TN",set()),
    (None,True,"UNKNOWN",set()),(False,None,"UNKNOWN",set()),(None,None,"UNKNOWN",set()),
])
def test_shared_semantics_apply_the_three_refutation_directions(predicted, observed, cell, refuted):
    for kind in CLAIM_KINDS:
        value=classify(predicted,observed,kind)
        assert value["cell"]==cell and value["refutes"] is (kind in refuted)
    assert not classify(predicted,observed,EMPIRICAL)["refutes"]


def test_partial_condition_survives_front_engine_fn_but_not_fp():
    engine=ready_engine()
    engine.observe(evidence({"value":0},0))
    engine.observe(evidence({"value":2},1))
    family="reference/mismatch/positive"
    rid=relation_id(relation())
    group=engine.groups[family]["remaining_by_kind"]
    assert rid in group[SUFFICIENT] and rid in group[EMPIRICAL]
    assert rid not in group[EXACT] and rid not in group[NECESSARY]
    assert any(row["constraint_id"]==rid and row["claim_kind"]==EXACT and row["cell"]=="FN" and row["evidence_id"]=="dev-1" for row in engine.contradictions)
    # A true condition on a normal row refutes sufficiency without deleting
    # the original failure or the earlier directional counterevidence.
    engine.observe(evidence({"value":0},2,False))
    assert rid not in group[SUFFICIENT]
    assert len(engine.evidence)==3 and engine.inconsistent


def test_necessary_condition_allows_true_normal_and_sufficiency_does_not():
    engine=ready_engine()
    engine.observe(evidence({"value":0},0))
    engine.observe(evidence({"value":1},1,False))
    engine.observe(evidence({"value":-1},2,False))
    rid=relation_id(relation(operator="ge"))
    group=engine.groups["reference/mismatch/positive"]["remaining_by_kind"]
    assert rid in group[NECESSARY] and rid not in group[SUFFICIENT] and rid not in group[EXACT]
    assert any(row["constraint_id"]==rid and row["claim_kind"]==SUFFICIENT and row["cell"]=="FP" for row in engine.contradictions)


def test_censored_other_failure_family_is_unknown_and_explicit_negative_is_distinct():
    other=evidence({"value":1},0,signature="other")
    family="reference/mismatch/positive"
    assert semantic_label(other,family) is None
    assert semantic_label(dict(other,family_observations={family:False}),family) is False
    assert semantic_label(evidence({"value":1},1,False),family) is False
    invalid=dict(other,observation_status="INVALID_ORACLE")
    assert semantic_label(normalize_semantic_evidence(invalid,spec()),family) is None
    engine=ready_engine()
    engine.observe(invalid)
    assert engine.groups=={} and engine.status=="NO_FAILURE_EVIDENCE"
    with pytest.raises(ValueError,match="cannot supply"):
        normalize_semantic_evidence(dict(invalid,family_observations={family:False}),spec())


def test_undefined_aggregate_and_not_do_not_manufacture_support():
    container=spec({"kind":"list","items":{"kind":"int","min":-2,"max":2},"min_size":0,"max_size":3})
    atomic=relation("minimum","ge",0)
    point={"value":[]}
    assert holds(atomic,measurements(point,container)) is False  # preserved API
    assert relation_prediction(atomic,point,container) is None
    assert relation_truth(compound("not",atomic),point,container) is None
    ast={"op":"not","args":[{"op":"eq","left":{"op":"min","args":[{"var":"operand"}]},"right":0}]}
    ast_relation={"term":{"kind":"ast","roles":["operand"],"expression":ast},"operator":"eq","value":1}
    assert relation_prediction(ast_relation,point,container) is None
    assert kleene("and",[False,None]) is False and kleene("or",[True,None]) is True
    assert kleene("not",[None]) is None


def test_semantic_snapshot_is_distinct_replayable_and_kind_mutation_cannot_reuse_receipt():
    engine=ready_engine()
    for number,value in enumerate((0,2,1,-1)):
        engine.observe(evidence({"value":value},number,value in (0,2)))
    snapshot=engine.freeze()
    assert snapshot["schema"]=="tomolab-discovery-snapshot-v3" and snapshot["semantic_version"]==SEMANTIC_VERSION
    assert DiscoveryEngine.from_snapshot(snapshot).snapshot()==snapshot
    changed=deepcopy(snapshot);changed["claim_kinds"]=[SUFFICIENT]
    changed["receipt"]["sha256"]=digest({k:v for k,v in changed.items() if k!="receipt"})
    with pytest.raises(ValueError,match="inconsistent"):
        DiscoveryEngine.from_snapshot(changed)
    with pytest.raises(ValueError,match="kind-checked"):
        transfer(snapshot,spec(),budget=2,pool_size=4)


def test_legacy_snapshots_and_default_meaning_remain_exact():
    pool=[{"value":-1},{"value":0},{"value":1}]
    engine=DiscoveryEngine(spec(),_pool=pool,pool_size=3,native_strategy=False)
    for _ in pool:engine.propose()
    engine.observe(evidence({"value":0},0));engine.observe(evidence({"value":1},1))
    snapshot=engine.freeze()
    assert snapshot["schema"]=="tomolab-discovery-snapshot-v2"
    assert "semantic_version" not in snapshot and "claim_kinds" not in snapshot
    assert relation_id(relation()) not in engine.groups["reference/mismatch/positive"]["remaining"]
    assert DiscoveryEngine.from_snapshot(snapshot).snapshot()==snapshot


def test_kinds_versions_domain_and_oracle_scope_bind_new_claim_ids():
    scope={"implementation_scope":"authored","domain":[-1,1],"oracle_contract":"exact-json"}
    ids={semantic_claim_id(relation(),kind,"reference/mismatch/positive",scope) for kind in CLAIM_KINDS}
    assert len(ids)==4
    assert semantic_claim_id(relation(),EXACT,"reference/mismatch/positive",dict(scope,oracle_contract="tolerance")) not in ids
    assert semantic_claim_id(relation(),EXACT,"reference/mismatch/positive",dict(scope,domain=[0,1])) not in ids
    with pytest.raises(ValueError,match="semantic version"):
        normalize_policy({"semantic_version":"future-or-legacy"})
    with pytest.raises(ValueError):
        normalize_policy({"max_compound_relations":129})


def test_bounded_composition_keeps_syntax_but_shares_true_and_unknown_columns():
    pool=[{"value":-1},{"value":0},{"value":1}]
    measured,relations,true,unknown=semantic_grammar(pool,spec())
    assert len(relations)<=640 and len(measured)==3
    assert {r["term"]["expression"]["op"] for r in relations.values() if r["term"]["kind"]=="compound"}=={"and","or","not"}
    columns={}
    for rid in relations:columns.setdefault((true[rid],unknown[rid]),[]).append(rid)
    assert len(columns)<len(relations)
    engine=ready_engine(pool=pool)
    engine.observe(evidence({"value":0},0))
    active=engine._candidate_ids()
    assert len({(engine.masks[rid],engine.unknown_masks[rid]) for rid in active})==len(active)
    unstarted=DiscoveryEngine(spec(),_pool=pool,pool_size=3,native_strategy=False,
        claim_kinds=CLAIM_KINDS,semantic_policy=DEFAULT_POLICY)
    assert unstarted.propose()["empirical_guidance_adopted"] is False


def test_frozen_atomic_universe_is_not_regenerated_from_validation_values():
    pool=[{"value":-1},{"value":0},{"value":1}]
    seed=relation(value=5)
    engine=DiscoveryEngine(spec(),_pool=pool,pool_size=3,native_strategy=False,
        claim_kinds=CLAIM_KINDS,semantic_policy=DEFAULT_POLICY,seed_relations=[seed])
    assert engine.relations=={relation_id(seed):seed}
    snapshot=engine.freeze()
    assert snapshot["seed_relations"]==[seed]
    assert DiscoveryEngine.from_snapshot(snapshot).snapshot()==snapshot
    changed=deepcopy(snapshot);changed["seed_relations"][0]["value"]=4
    changed["receipt"]["sha256"]=digest({k:v for k,v in changed.items() if k!="receipt"})
    with pytest.raises(ValueError,match="inconsistent"):
        DiscoveryEngine.from_snapshot(changed)
    with pytest.raises(ValueError,match="explicit R1"):
        DiscoveryEngine(spec(),_pool=pool,pool_size=3,native_strategy=False,seed_relations=[seed])


def test_nonfinite_or_wrong_typed_measured_values_abstain_before_not():
    atom=relation()
    for value in (float("nan"),float("inf"),-float("inf"),"0",True):
        measured={canonical(atom["term"]):value}
        assert relation_prediction(atom,{"value":0},spec(),measured=measured) is None
        assert relation_prediction(compound("not",atom),{"value":0},spec(),measured=measured) is None


def test_frozen_ast_seed_preserves_unknown_aggregates_without_public_ir():
    container=spec({"kind":"list","items":{"kind":"int","min":-1,"max":1},"min_size":0,"max_size":2})
    predicate={"op":"not","args":[{"op":"eq","left":{"op":"min","args":[{"var":"operand"}]},"right":0}]}
    seed={"term":{"kind":"ast","roles":["operand"],"expression":predicate},"operator":"eq","value":1}
    engine=DiscoveryEngine(container,_pool=[{"value":[]},{"value":[1]}],pool_size=2,native_strategy=False,
        claim_kinds=[SUFFICIENT],semantic_policy=DEFAULT_POLICY,seed_relations=[seed])
    rid=relation_id(seed)
    assert engine.unknown_masks[rid]&1 and engine.masks[rid]&2
    with pytest.raises(ValueError,match="duplicate"):
        semantic_grammar([{"value":0}],spec(),seed_relations=[relation(),relation()])
