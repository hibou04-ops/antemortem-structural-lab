"""Durable G0/G1/G2 lineage, replay rejection and a fresh Python reader."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tomolab.discovery.recursive_policy import initial_selector, update_selector, choose_candidate
from tomolab.discovery.recursive_store import (GenerationStore, make_generation,
    validate_generation, record_e7_linkage)
from tomolab.discovery.schema import canonical, digest
from test_recursive_policy import authored_mold, fixture_batch, CONTRACT


def generations():
    receipts, manifest = fixture_batch([("fixture-a", "gain"), ("fixture-b", "gain")])
    s0 = initial_selector(authored_mold()["artifact_digest"], input_contract_digest=digest(CONTRACT))
    g0 = make_generation("G0", s0)
    s1 = update_selector(s0, receipts, manifest)
    g1 = make_generation("G1", s1, parent=g0, development_manifest=manifest, paired_receipts=receipts)
    losses, manifest2 = fixture_batch([("fixture-a", "loss"), ("fixture-b", "loss")], run="wave-two")
    s2 = update_selector(s1, losses, manifest2)
    g2 = make_generation("G2", s2, parent=g1, development_manifest=manifest2, paired_receipts=losses)
    return g0, g1, g2


def resign(generation):
    generation["sha256"] = digest({k: v for k, v in generation.items() if k != "sha256"})
    return generation


def test_append_only_generations_preserve_parent_experience_cost_and_raw_receipts(tmp_path):
    g0, g1, g2 = generations()
    store = GenerationStore(tmp_path / "generations.jsonl")
    for generation in (g0, g1, g2):
        assert store.append(generation)["status"] == "COMMITTED"
    assert store.latest() == g2
    assert store.get("G0") == g0
    assert store.get("G1") == g1
    assert store.append(g1)["status"] == "ALREADY_COMMITTED"
    assert len(store.records()) == 3
    assert g2["parent_generation_digest"] == g1["sha256"]
    assert g1["parent_generation_digest"] == g0["sha256"]
    assert g2["selector"]["evidence"][:2] == g1["selector"]["evidence"]
    assert len(g1["new_paired_receipts"]) == len(g2["new_paired_receipts"]) == 2
    assert g0["cost_ledger"]["target_calls"] == 0
    assert g1["cost_ledger"]["target_calls"] == g1["cost_ledger"]["oracle_calls"] == 12
    assert g2["cost_ledger"]["target_calls"] == g2["cost_ledger"]["oracle_calls"] == 24
    assert g2["candidate_validation"]["default_adoption"] == "HOLD"
    assert g2["e7_linkage"] == {"status": "E7_LINKAGE_UNKNOWN"}


def test_new_python_process_restores_all_choices_and_selects_actual_candidate(tmp_path):
    store = GenerationStore(tmp_path / "generations.jsonl")
    g0, g1, g2 = generations()
    for generation in (g0, g1, g2):
        store.append(generation)
    script = """
import json, sys
from tomolab.discovery.recursive_store import GenerationStore
from tomolab.discovery.recursive_policy import choose_candidate
from tomolab.discovery.online_engine import OnlinePolicy
from tomolab.discovery.online_observe import inspect_target
from tomolab.discovery.schema import digest
store = GenerationStore(sys.argv[1])
mold = json.loads(sys.argv[2])
contract = json.loads(sys.argv[3])
results = []
for name in ('G0', 'G1', 'G2'):
    generation = store.get(name)
    policy = OnlinePolicy(contract, method='D', seed=7, budget=100,
        mold=mold, selector=generation['selector'],
        structure=inspect_target(sum, contract, mode='black_box'))
    policy.attempts = 2
    policy.last_feedback = dict(status='FAILURE', input_digest=digest([1,2]),
        coverage=[], branch_distance=None, contract_checked=digest(contract))
    proposal = policy.propose([1,2])
    results.append(dict(generation=name,input=proposal[0],rule_id=proposal[3]))
print(json.dumps(results))
"""
    process = subprocess.run([sys.executable, "-c", script, str(store.path),
        canonical(authored_mold()), canonical(CONTRACT)], capture_output=True, text=True, check=True)
    rows = json.loads(process.stdout)
    assert rows[0]["input"] == rows[2]["input"] == [1]
    assert rows[1]["input"] == [1, 1]
    assert rows[0]["rule_id"] is rows[2]["rule_id"] is None
    assert rows[1]["rule_id"] == authored_mold()["rules"][0]["rule_id"]


def test_conflicting_id_wrong_parent_missing_receipt_and_rollback_are_rejected(tmp_path):
    g0, g1, g2 = generations()
    store = GenerationStore(tmp_path / "generations.jsonl")
    store.append(g0); store.append(g1)
    wrong = deepcopy(g1)
    wrong["candidate_validation"]["reason"] = "conflicting same generation"
    with pytest.raises(ValueError, match="ID content conflict"):
        store.append(resign(wrong))
    wrong = deepcopy(g2); wrong["parent_generation_digest"] = "0" * 64
    with pytest.raises(ValueError, match="parent"):
        store.append(resign(wrong))
    wrong = deepcopy(g2); wrong["new_paired_receipts"] = []
    with pytest.raises(ValueError, match="every new experience"):
        store.append(resign(wrong))
    with pytest.raises(ValueError, match="complete raw paired"):
        make_generation("G2-no-raw", g2["selector"], parent=g1,
                        development_manifest=g2["consumed_development_manifest"])
    with pytest.raises(ValueError, match="discard prior"):
        make_generation("G2-rollback", g0["selector"], parent=g1)


def test_partial_record_tamper_and_schema_mismatch_preserve_existing_bytes(tmp_path):
    g0, g1, _ = generations()
    store = GenerationStore(tmp_path / "generations.jsonl")
    store.append(g0)
    original = store.path.read_bytes()
    store.path.write_bytes(original + b'{"schema":')
    partial = store.path.read_bytes()
    with pytest.raises(ValueError, match="incomplete"):
        store.append(g1)
    assert store.path.read_bytes() == partial
    store.path.write_bytes(original.replace(b'"G0"', b'"GX"', 1))
    with pytest.raises(ValueError, match="chain"):
        store.records()
    bad_version = deepcopy(g1); bad_version["selector"]["schema"] = "future-selector-v99"
    with pytest.raises(ValueError, match="unsupported selector"):
        validate_generation(resign(bad_version))


def test_generation_replays_raw_pair_labels_after_outer_hashes_are_recomputed():
    _, g1, _ = generations()
    bad = deepcopy(g1)
    bad["new_paired_receipts"][0]["label"] = "loss"
    pair = bad["new_paired_receipts"][0]
    pair["pair_receipt_sha256"] = digest({k: v for k, v in pair.items() if k != "pair_receipt_sha256"})
    with pytest.raises(ValueError, match="paired label"):
        validate_generation(resign(bad))
    bad = deepcopy(g1)
    bad["consumed_development_manifest"]["lineages"][0]["implementation_sha256"] = digest("unreviewed-code")
    manifest = bad["consumed_development_manifest"]
    manifest["manifest_digest"] = digest({k: v for k, v in manifest.items() if k != "manifest_digest"})
    with pytest.raises(ValueError):
        validate_generation(resign(bad))


def test_lock_conflict_is_explicit_and_never_removed_by_other_writer(tmp_path):
    g0, _, _ = generations()
    store = GenerationStore(tmp_path / "generations.jsonl")
    lock = store.path.with_name(store.path.name + ".lock")
    lock.write_text("owned-by-another-writer", encoding="utf-8")
    with pytest.raises(FileExistsError):
        store.append(g0)
    assert lock.read_text(encoding="utf-8") == "owned-by-another-writer"
    assert not store.path.exists()


def test_existing_e7_store_is_reused_without_inventing_claim_mapping(tmp_path):
    from tomolab.discovery.knowledge import KnowledgeArchive
    from tomolab.discovery.knowledge_store import KnowledgeStore
    folder = Path(__file__).parents[1] / "examples" / "knowledge"
    load = lambda name: json.loads((folder / name).read_text(encoding="utf-8"))
    archive = KnowledgeArchive.from_failure_log(load("source-spec.json"), load("source-failures.json"),
        load("source-provenance.json"), public_ir=load("source-ir.json"))
    parent = archive.freeze()
    knowledge_store = KnowledgeStore(tmp_path / "knowledge.jsonl")
    link = record_e7_linkage(knowledge_store, parent, record_id="selector-reviewed-e7-parent")
    assert link["status"] == "REVIEWED_E7_ARCHIVE_RECEIPT"
    assert knowledge_store.latest().snapshot() == parent
    fork = archive.fork("selector-linked-next-development")
    child = fork.freeze()
    child_link = record_e7_linkage(knowledge_store, child, record_id="selector-reviewed-e7-child")
    assert child_link["snapshot_sha256"] != link["snapshot_sha256"]
    assert child["journal"][:len(parent["journal"])] == parent["journal"]
    assert knowledge_store.latest().snapshot() == child
    g0 = make_generation("G0", initial_selector(authored_mold()["artifact_digest"]), e7_linkage=link)
    assert g0["e7_linkage"] == link
