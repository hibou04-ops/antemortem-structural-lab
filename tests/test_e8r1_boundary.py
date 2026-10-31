"""R1 public-only subprocess planning; authored data, no execution callbacks."""
from copy import deepcopy
import hashlib
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from test_e7_knowledge import evidence, provenance, spec
from tomolab.discovery.claim_semantics import SUFFICIENT, NECESSARY, EMPIRICAL
from tomolab.discovery.knowledge import KnowledgeArchive, make_observation
from tomolab.discovery.knowledge_boundary import KnowledgeBoundary, GENERATOR_FILES
from tomolab.discovery.knowledge_protocol import MAX_MESSAGE, validate_request, semantic_observation_mode
from tomolab.discovery.schema import canonical, digest

ROOT=Path(__file__).resolve().parents[1]
LEGACY_PUBLIC_FILES={
    "__init__.py","schema.py","features.py","predicates.py","engine.py",
    "hypothesis_adapter.py","solver.py","transfer.py","temporal.py",
    "temporal_engine.py","temporal_transfer.py","efficient.py",
    "knowledge.py","knowledge_engine.py","knowledge_protocol.py","knowledge_worker.py",
}
HOST_FILES={"knowledge_service.py","knowledge_store.py","development_evidence.py",
    "development_collector.py","evaluation_readiness.py","evaluation_usage.py",
    "qualified_comparison.py","analysis.py","native_stateful.py","knowledge_examples.py"}


def authored_archive():
    value=KnowledgeArchive.from_failure_log(spec(),[
        evidence(0,True,"authored-positive"),evidence(1,False,"authored-normal-1"),
        evidence(-1,False,"authored-normal-minus1")],provenance(),
        semantic_policy={"max_compound_relations":0},claim_kinds=[SUFFICIENT,NECESSARY,EMPIRICAL])
    return value.freeze()


def test_allowlist_adds_only_public_semantics_and_keeps_existing_limit():
    assert set(GENERATOR_FILES)==LEGACY_PUBLIC_FILES|{"claim_semantics.py"}
    assert len(GENERATOR_FILES)==17 and not HOST_FILES&set(GENERATOR_FILES)
    assert MAX_MESSAGE==8_000_000
    from tomolab.mold.protocol import MAX_MESSAGE as shared_limit
    assert shared_limit==MAX_MESSAGE


def test_legacy_request_capture_is_unchanged_and_source_options_are_explicit():
    message={"action":"init","spec":spec(),"budget":4,"pool_size":8}
    assert validate_request(message)==message
    for empirical in (False,True):
        source=dict(message,purpose="SOURCE_DEVELOPMENT",allow_unvalidated_empirical=empirical)
        assert validate_request(source)==source
    independent=dict(message,purpose="INDEPENDENT_TRANSFER",allow_unvalidated_empirical=False)
    assert validate_request(independent)==independent


@pytest.mark.parametrize("options",[
    {"purpose":"FINAL"},{"purpose":None},{"purpose":1},{"purpose":{"mode":"SOURCE_DEVELOPMENT"}},
    {"allow_unvalidated_empirical":True},{"purpose":"INDEPENDENT_TRANSFER","allow_unvalidated_empirical":True},
    {"purpose":"SOURCE_DEVELOPMENT","allow_unvalidated_empirical":1},
    {"purpose":"SOURCE_DEVELOPMENT","allow_unvalidated_empirical":"true"},
    {"purpose":"SOURCE_DEVELOPMENT","allow_unvalidated_empirical":None},
])
def test_invalid_purpose_or_trial_options_fail_before_archive_replay(monkeypatch,options):
    def forbidden(*_args,**_kwargs):
        pytest.fail("invalid execution purpose reached archive replay")
    monkeypatch.setattr(KnowledgeArchive,"from_snapshot",classmethod(forbidden))
    with pytest.raises(ValueError):
        validate_request({"action":"init","spec":spec(),"archive":{},**options})


def test_source_archive_and_options_are_captured_without_granting_transfer():
    value=authored_archive()
    message={"action":"plan","spec":spec(),"archive":value,"target_provenance":provenance(),
        "purpose":"SOURCE_DEVELOPMENT","allow_unvalidated_empirical":True,"budget":4,"pool_size":8}
    captured=validate_request(message)
    message["purpose"]="INDEPENDENT_TRANSFER"
    message["allow_unvalidated_empirical"]=False
    message["archive"]["claims"].clear()
    assert captured["purpose"]=="SOURCE_DEVELOPMENT" and captured["allow_unvalidated_empirical"] is True
    assert captured["archive"]["claims"] and captured["archive"]["final_feedback_allowed"] is False
    assert not any(c["status"]=="SUPPORTED_WITHIN_SCOPE" for c in captured["archive"]["claims"])


def test_invalid_options_and_private_fields_are_rejected_before_parent_pipe():
    class NoWrite:
        called=False
        def write(self,_value):
            self.called=True
            pytest.fail("invalid request reached worker transport")
    boundary=object.__new__(KnowledgeBoundary)
    boundary._request_lock=threading.Lock();boundary._spec=spec();boundary._temporal_contract=None
    boundary._target_provenance=provenance();boundary._frozen=False
    spy=NoWrite();boundary.process=SimpleNamespace(stdin=spy)
    for options in ({"purpose":"FINAL"},{"allow_unvalidated_empirical":True},
                    {"purpose":"SOURCE_DEVELOPMENT","actual_result":"private-answer"},
                    {"purpose":"SOURCE_DEVELOPMENT","oracle_source":"private-source"}):
        with pytest.raises(ValueError):boundary.request("init",spec=spec(),**options)
    assert not spy.called


def test_actual_small_r1_archive_plans_inside_public_only_subprocess():
    value=authored_archive();before=canonical(value)
    with KnowledgeBoundary(timeout=30) as boundary:
        result=boundary.request("plan",spec=spec(),archive=value,target_provenance=provenance(),
            purpose="SOURCE_DEVELOPMENT",allow_unvalidated_empirical=True,
            seed=23,budget=4,pool_size=8,guidance_budget=2)
        assert result["gate"]["status"]=="SOURCE_DEVELOPMENT_GUIDANCE"
        assert result["gate"]["independent_transfer_authorized"] is False
        assert result["gate"]["allow_unvalidated_empirical"] is True
        assert len(result["candidates"])==4
        assert result["snapshot"]["purpose"]=="SOURCE_DEVELOPMENT" and result["snapshot"]["frozen"]
        assert result["target_calls"]==result["oracle_calls"]==0 and result["final_feedback_allowed"] is False
        assert any(p["source"] in {"PARTIAL_CONDITION_PROBE","EMPIRICAL_GUIDANCE_EXPERIMENT"} for p in result["candidates"])
        assert sum(p["source"]!="NATIVE_HYPOTHESIS" for p in result["candidates"])<=2
        assert sum(p["source"]=="NATIVE_HYPOTHESIS" for p in result["candidates"])>=2
        assert set(boundary.code_hashes)==set(GENERATOR_FILES)
        copied=boundary.root/"tomolab/discovery"
        for name in GENERATOR_FILES:
            assert (copied/name).read_bytes()==(ROOT/"tomolab/discovery"/name).read_bytes()
            assert boundary.code_hashes[name]==hashlib.sha256((copied/name).read_bytes()).hexdigest()
        assert all(not (copied/name).exists() for name in HOST_FILES)
        assert boundary._frozen is True
        with pytest.raises(ValueError,match="frozen"):boundary.request("observe",evidence={})
    assert canonical(value)==before


@pytest.mark.parametrize("purpose,empirical",[("INDEPENDENT_TRANSFER",False),("SOURCE_DEVELOPMENT",True)])
def test_other_implementation_cannot_use_source_trial_as_transfer_authority(purpose,empirical):
    with KnowledgeBoundary(timeout=30) as boundary:
        result=boundary.request("plan",spec=spec(),archive=authored_archive(),target_provenance=provenance(3),
            purpose=purpose,allow_unvalidated_empirical=empirical,
            seed=23,budget=4,pool_size=8,guidance_budget=2)
    assert result["gate"]["claims"]==[]
    assert all(p["source"]=="NATIVE_HYPOTHESIS" for p in result["candidates"])
    assert result["target_calls"]==result["oracle_calls"]==0 and result["final_feedback_allowed"] is False


def extended_observation(point):
    value=make_observation(spec(),evidence(point["value"],False,"authored-invalid-oracle"),provenance())
    value["evidence"]["observation_status"]="INVALID_ORACLE"
    value["receipt_sha256"]=digest({k:v for k,v in value.items() if k!="receipt_sha256"})
    return value


def test_observation_semantics_require_initialized_mode_and_keep_strict_minimum():
    event=extended_observation({"value":0})
    request={"action":"observe","evidence":event}
    with pytest.raises(ValueError):validate_request(request,spec(),None,provenance())
    captured=validate_request(request,spec(),None,provenance(),semantic_mode=True)
    assert captured==request
    assert semantic_observation_mode({"spec":spec()}) is False
    assert semantic_observation_mode({"purpose":"SOURCE_DEVELOPMENT"}) is True
    assert semantic_observation_mode({"archive":authored_archive()}) is True
    with pytest.raises(ValueError,match="Boolean"):
        validate_request(request,spec(),None,provenance(),semantic_mode=1)
    with pytest.raises(ValueError):
        validate_request({"action":"init","spec":spec(),"semantic_mode":True})
    for field in ("actual_result","oracle_source","expected_result","model_score"):
        bad=deepcopy(event);bad["evidence"][field]="private"
        bad["receipt_sha256"]=digest({k:v for k,v in bad.items() if k!="receipt_sha256"})
        with pytest.raises(ValueError):
            validate_request({"action":"observe","evidence":bad},spec(),None,provenance(),semantic_mode=True)
    final=deepcopy(event);final["split"]="final"
    final["receipt_sha256"]=digest({k:v for k,v in final.items() if k!="receipt_sha256"})
    with pytest.raises(ValueError,match="final"):
        validate_request({"action":"observe","evidence":final},spec(),None,provenance(),semantic_mode=True)


def test_actual_r1_worker_observes_unknown_without_refutation_or_callbacks():
    with KnowledgeBoundary(timeout=30) as boundary:
        initialized=boundary.request("init",spec=spec(),archive=authored_archive(),target_provenance=provenance(),
            purpose="SOURCE_DEVELOPMENT",seed=23,budget=4,pool_size=8,guidance_budget=2)
        assert initialized["initialized"] and boundary._semantic_mode is True
        point=boundary.request("propose")
        result=boundary.request("observe",evidence=extended_observation(point["inputs"]))
        assert result["status"]=="OBSERVED" and result["refuted_claim_ids"]==[]
        frozen=boundary.request("freeze")
        assert frozen["frozen"] and frozen["final_feedback_allowed"] is False
        assert frozen["metrics"]["target_calls"]==frozen["metrics"]["oracle_calls"]==0
