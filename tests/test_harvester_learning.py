"""Real learning gates are separate from authored mechanism verification."""
import time
import pytest
from tomolab.discovery.harvester_learning import _DeadlineCallable, m0_verdict, run_harvest_m0
from tomolab.recursive_demo import fixture_mold,collect_fixture,gain_a,gain_b,reference,loss_a


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
