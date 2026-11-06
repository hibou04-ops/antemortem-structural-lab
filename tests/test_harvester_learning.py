"""Real learning gates are separate from authored mechanism verification."""
import time
from copy import deepcopy
import pytest
from tomolab.discovery.harvester_learning import _DeadlineCallable, m0_verdict, run_harvest_m0
from tomolab.recursive_demo import fixture_mold,collect_fixture,gain_a,gain_b,reference,loss_a


def _host_measurement_fixture(receipt):
    from tomolab.discovery.recursive_observe import make_diagnostics,new_trace
    reservation=deepcopy(receipt["reservation"])
    cfg=make_diagnostics(fixture_mold(),experiment_contract_sha256=receipt["experiment_contract_sha256"],
        source_lineage_id=receipt["source_lineage_id"],project_id=receipt["project_id"],
        mechanism_id=receipt["mechanism_id"],run_id=reservation["run_id"],identity=receipt["identity"])
    trace=new_trace(cfg["public"])
    trace["reservations"]=[reservation]
    trace["slots"]=[dict(proposal_index=reservation["proposal_index"],common_digest=reservation["common_digest"],
        learned_digest=reservation["learned_digest"],source_state="APPLIED",reason="ELIGIBLE")]
    for name in ("shadow_proposals","common_validation_proposals","mold_lookups"):
        trace["cost"][name]=len(trace["slots"])
    host=dict(schema="tomolab-paired-host-result-v1",status="COMPLETE",receipts=[deepcopy(receipt)],
        cost=deepcopy(receipt["cost"]),slots=deepcopy(trace["slots"]),worker_instrumentation_cost=deepcopy(trace["cost"]),
        unknown_reasons=[],transport_calls_not_in_diagnostic_cost=True,
        scope="CONDITIONAL_LOCAL_PAIRS_NOT_POLICY_UTILITY_OR_GENERALIZATION")
    return dict(status="COMPLETE",diagnostic_trace=trace,paired_diagnostics=host),cfg


@pytest.fixture
def authored_pairs():
    mold=fixture_mold()
    lineages=["verdict-a","verdict-b","verdict-c","verdict-d"]
    receipts=[]
    for fn,lineage in zip((gain_a,gain_b,reference,loss_a),lineages):
        paired,_,_=collect_fixture(mold,fn,lineage,run_id="verdict-"+lineage)
        receipts.extend(paired["receipts"])
    return receipts,lineages


def test_local_signal_requires_all_four_resolved_lineages_and_two_gains(authored_pairs):
    receipts,lineages=authored_pairs
    assert m0_verdict(receipts,lineages)["status"]=="LOCAL_SIGNAL_OBSERVED"
    assert m0_verdict(receipts[:2],lineages)["status"]=="HOLD_MEASUREMENT"
    assert m0_verdict(receipts,lineages,within_budget=False)["status"]=="HOLD_MEASUREMENT"
    assert m0_verdict(receipts,lineages,unknown_external_calls=1)["status"]=="HOLD_MEASUREMENT"


def test_duplicate_m0_execution_cannot_manufacture_signal(authored_pairs):
    receipts,lineages=authored_pairs
    with pytest.raises(ValueError,match="duplicated M0"):
        m0_verdict(receipts+[receipts[0]],lineages)


def test_host_measurement_validation_failure_cannot_inherit_worker_complete_or_positive_signal(authored_pairs):
    from tomolab.discovery.harvester_learning import _m0_run_measurement
    receipts,lineages=authored_pairs
    run,cfg=_host_measurement_fixture(receipts[0])
    assert _m0_run_measurement(run,cfg)["status"]=="COMPLETE"
    original=deepcopy(run)
    run["paired_diagnostics"]=dict(schema="tomolab-paired-host-result-v1",status="HOLD_MEASUREMENT",
        receipts=[],cost=dict(target_calls=0,oracle_calls=0,reset_calls=0,wall_seconds=0.0),
        unknown_reasons=["ValueError:actual C candidate mismatched"])
    assert run["diagnostic_trace"]["status"]=="COMPLETE"
    measurement=_m0_run_measurement(run,cfg)
    assert measurement["status"]=="HOLD_MEASUREMENT"
    assert m0_verdict(receipts,lineages)["status"]=="LOCAL_SIGNAL_OBSERVED"
    assert m0_verdict(receipts,lineages,measurement_complete=measurement["status"]=="COMPLETE")["status"]=="HOLD_MEASUREMENT"
    assert original["paired_diagnostics"]["receipts"][0]==receipts[0]


def test_missing_reserved_host_receipt_is_not_complete_even_if_status_claims_complete(authored_pairs):
    from tomolab.discovery.harvester_learning import _m0_run_measurement
    run,cfg=_host_measurement_fixture(authored_pairs[0][0])
    run["paired_diagnostics"]["receipts"]=[]
    result=_m0_run_measurement(run,cfg)
    assert result["status"]=="HOLD_MEASUREMENT"
    assert result["reserved_pairs"]==1 and result["preserved_pairs"]==0


def test_retained_unknown_receipt_remains_measured_without_becoming_neutral(authored_pairs):
    from tomolab.discovery.harvester_learning import _m0_run_measurement
    from tomolab.discovery.schema import digest
    receipt=deepcopy(authored_pairs[0][0])
    receipt["branches"]["common"][0]["semantic_digest"]="0"*64
    receipt["label"]="UNKNOWN"
    receipt["unknown_reasons"]=["REPETITION_STATUS_OR_SEMANTICS_UNRESOLVED"]
    receipt["pair_receipt_sha256"]=digest({k:v for k,v in receipt.items() if k!="pair_receipt_sha256"})
    run,cfg=_host_measurement_fixture(receipt)
    run["paired_diagnostics"]["status"]="HOLD_MEASUREMENT"
    result=_m0_run_measurement(run,cfg)
    assert result["status"]=="COMPLETE" and result["preserved_unknown_pairs"]==1
    assert run["paired_diagnostics"]["receipts"][0]["label"]=="UNKNOWN"


def test_host_measurement_identity_and_integer_cost_accounting_are_exact(authored_pairs):
    from tomolab.discovery.harvester_learning import _m0_run_measurement
    from tomolab.discovery.schema import digest
    run,cfg=_host_measurement_fixture(authored_pairs[0][0])
    wrong=deepcopy(run)
    receipt=wrong["paired_diagnostics"]["receipts"][0]
    receipt["project_id"]="different-authored-project"
    receipt["pair_receipt_sha256"]=digest({k:v for k,v in receipt.items() if k!="pair_receipt_sha256"})
    assert _m0_run_measurement(wrong,cfg)["status"]=="HOLD_MEASUREMENT"
    wrong=deepcopy(run)
    wrong["paired_diagnostics"]["cost"]["target_calls"]-=1
    assert _m0_run_measurement(wrong,cfg)["status"]=="HOLD_MEASUREMENT"
    wrong=deepcopy(run)
    wrong["paired_diagnostics"]["cost"]["wall_seconds"]=0.0
    assert _m0_run_measurement(wrong,cfg)["status"]=="HOLD_MEASUREMENT"


def test_zero_eligible_reservations_are_preserved_without_inventing_a_pair(authored_pairs):
    from tomolab.discovery.harvester_learning import _m0_run_measurement
    run,cfg=_host_measurement_fixture(authored_pairs[0][0])
    trace=run["diagnostic_trace"]
    trace["reservations"],trace["slots"]=[],[]
    trace["cost"].update(shadow_proposals=0,common_validation_proposals=0,mold_lookups=0)
    host=run["paired_diagnostics"]
    host.update(status="HOLD_MEASUREMENT",receipts=[],slots=[],worker_instrumentation_cost=deepcopy(trace["cost"]),
        unknown_reasons=["NO_ELIGIBLE_RESERVATIONS"],cost=dict(target_calls=0,oracle_calls=0,reset_calls=0,wall_seconds=0.0))
    result=_m0_run_measurement(run,cfg)
    assert result["status"]=="COMPLETE" and result["reserved_pairs"]==result["preserved_pairs"]==0


def test_frozen_all_kind_mismatch_holds_before_registry_budget_or_any_container_entry(tmp_path,monkeypatch):
    import tomolab.discovery.harvester_learning as learning
    import tomolab.discovery.harvester_execution as execution
    from tomolab.discovery.schema import digest
    entered=[]
    def forbidden(*args,**kwargs):
        entered.append(True)
        raise AssertionError("unsupported kind must stop before this boundary")
    monkeypatch.setattr(learning,"HarvestRegistry",forbidden)
    monkeypatch.setattr(learning,"_reserve_research_budget",forbidden)
    monkeypatch.setattr(learning.subprocess,"run",forbidden)
    monkeypatch.setattr(execution,"OCIReviewedCallable",forbidden)
    contract=dict(schema="tomolab-harvester-m0-contract-v1",split="development",candidate_ids=["a","b","c","d"],
        input_contract=dict(kind="float",low=-4,high=4),mold_path="no-source-read.json",
        mold_digest=learning.FROZEN_MOLD_DIGEST,source_bundles={},image="sha256:"+"0"*64,
        replays=[],seed_repetitions=2,max_target_calls=1152,max_oracle_calls=1152,max_wall_seconds=1200)
    contract["experiment_contract_sha256"]=digest(contract)
    workspace=tmp_path/"not-created-for-unsupported-kind"
    result=run_harvest_m0(workspace,contract,allow_external_execution=True)
    assert result["m0"]=="HOLD_APPLICABILITY" and result["real_target_calls"]==result["real_oracle_calls"]==0
    assert not workspace.exists() and entered==[]


def test_shared_deadline_blocks_container_entry_and_preserves_attempt_cost():
    class AuthoredDelegate:
        def __init__(self):
            self.ledger={"wrapper_entries":0,"container_attempts":0}
            self.entered=False
        def reset(self):
            return True
        def __call__(self,point):
            self.entered=True
            raise AssertionError("deadline must prevent this external-boundary entry")
    delegate=AuthoredDelegate()
    wrapper=_DeadlineCallable(delegate,time.perf_counter()+1)
    assert wrapper.reset() is False
    with pytest.raises(OSError,match="deadline"):
        wrapper([1,2])
    assert delegate.entered is False
    assert delegate.ledger=={"wrapper_entries":1,"container_attempts":0}


def test_final_m0_contract_is_rejected_before_registry_or_execution(tmp_path):
    contract=dict(schema="tomolab-harvester-m0-contract-v1",split="final",candidate_ids=[],input_contract={},
        mold_path="none",mold_digest="0"*64,source_bundles={},image="sha256:"+"0"*64,
        replays=[],seed_repetitions=2,max_target_calls=1152,max_oracle_calls=1152,
        max_wall_seconds=1200,experiment_contract_sha256="0"*64)
    destination=tmp_path/"not-created"
    with pytest.raises(PermissionError,match="final"):
        run_harvest_m0(destination,contract,allow_external_execution=True)
    assert not destination.exists()


def test_replaying_consumed_harvest_experience_creates_no_generation_or_cost(tmp_path):
    import json
    from tomolab.harvester_demo import run_demo
    from tomolab.discovery.harvester_learning import _append_update
    from tomolab.discovery.harvester_registry import HarvestRegistry
    from tomolab.discovery.recursive_store import GenerationStore
    workspace=tmp_path/"authored-idempotent"
    run_demo(workspace)
    registry=HarvestRegistry(workspace)
    development=json.loads((workspace/"G1-development.json").read_text(encoding="utf-8"))
    receipts,manifest=development["receipts"],development["manifest"]
    receipt_ids={r["pair_receipt_sha256"] for r in receipts}
    m0=next(r["payload"] for r in registry.records() if r["kind"]=="M0" and
        set(r["payload"].get("paired_receipt_digests",[]))==receipt_ids)
    store=workspace/"generations.jsonl"
    generation_before=store.read_bytes()
    registry_before=registry.path.read_bytes()
    result=_append_update(registry,receipts,manifest,store,generation_id="duplicate-G3",m0_record=m0)
    assert result["update_status"]=="ALREADY_CONSUMED"
    assert result["generation_id"]=="G1" and result["additional_observation_cost"]==0
    assert store.read_bytes()==generation_before and registry.path.read_bytes()==registry_before
    assert [r["generation"]["generation_id"] for r in GenerationStore(store).records()]==["G0","G1","G2"]
