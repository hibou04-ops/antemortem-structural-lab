"""Actual authored supply-chain execution; never evidence of real transfer."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tomolab.harvester_demo import (AuthoredGitHubTransport, REPOSITORIES,
    _fixture_authority, run_demo)
from tomolab.discovery.harvester_github import GitHubRestClient, discover_batch, validate_candidate
from tomolab.discovery.harvester_learning import learn_from_harvest
from tomolab.discovery.harvester_registry import HarvestRegistry
from tomolab.discovery.recursive_store import GenerationStore
from tomolab.discovery.schema import digest


@pytest.fixture(scope="module")
def completed_demo(tmp_path_factory):
    workspace = tmp_path_factory.mktemp("harvester-integration")/"authored"
    return workspace, run_demo(workspace)


def test_http_candidate_registry_queue_duplicate_and_real_gate(completed_demo):
    workspace, summary = completed_demo
    assert summary["registered_candidates"] == summary["registry_candidates"] == 4
    assert summary["duplicates_skipped"] == 4 and summary["rerun_registered_new"] == 0
    assert summary["review_queue_count"] == 4
    assert summary["conditional_304_responses"] == 4
    assert summary["actual_network_calls"] == 0
    assert summary["real_eligible"] == summary["real_target_calls"] == summary["real_oracle_calls"] == 0
    registry = HarvestRegistry(workspace)
    assert len(registry.candidates()) == 4
    assert all(assessment["status"] != "DEVELOPMENT_ELIGIBLE" for assessment in registry.assessments().values())
    assert summary["evidence_class"] == "AUTHORED_SYNTHETIC_FIXTURE"


def test_harvested_source_receipt_generation_and_actual_restart_are_connected(completed_demo):
    workspace, summary = completed_demo
    registry = HarvestRegistry(workspace)
    candidates = registry.candidates()
    assert summary["executed_candidates"] == [[-1,-2],[1,1],[-1,-2]]
    assert summary["fixed_slot_learning_effect"] == "COMMON_LEARNED_COMMON_ACTUAL_EXECUTIONS"
    assert len({row["process_id"] for row in summary["resumed"]}) == 3
    generations = [row["generation"] for row in GenerationStore(workspace/"generations.jsonl").records()]
    assert [g["generation_id"] for g in generations] == ["G0","G1","G2"]
    assert [g["cost_ledger"]["target_calls"] for g in generations] == [0,14,28]
    assert [g["cost_ledger"]["oracle_calls"] for g in generations] == [0,14,28]
    assert generations[1]["parent_generation_digest"] == generations[0]["sha256"]
    assert generations[2]["parent_generation_digest"] == generations[1]["sha256"]
    observed_changes = []
    for row, generation in zip(summary["resumed"], generations):
        receipt = json.loads((workspace/(row["generation_id"]+"-online.json")).read_text(encoding="utf-8"))
        run, scheduler = receipt["run"], receipt["run"]["scheduler"]
        assert receipt["selector_digest"] == generation["selector"]["selector_digest"] == row["selector_digest"]
        assert receipt["generation_digest"] == generation["sha256"] == row["generation_digest"]
        assert row["full_new_search_status"] == run["status"] == "COMPLETE"
        assert row["full_new_search_allocation_policy"] == "STATIC_C_FLOOR_D_CIRCUIT_BREAKER_V3"
        assert row["full_new_search_epsilon_static_floor"] == 0.5
        changes = sum(bool(event.get("rule_id")) and
            event.get("source_selection", {}).get("source_changed_common", False) for event in run["events"])
        assert row["full_new_search_changed_common"] == changes == scheduler["learned_changed_common_executions"]
        observed_changes.append(changes)
        actual = row["full_new_search_policy_calls"]
        assert actual == scheduler["mixed_policy"]["actual"]
        for kind in ("target_calls", "oracle_calls"):
            assert actual["C"][kind] >= 36 and actual["D"][kind] <= 36
            assert row["full_new_search_cost"][kind] == run[kind] == sum(actual[arm][kind] for arm in ("C", "D"))
            assert run[kind] <= 72
        assert all(scheduler["actual"][lane] <= cap for lane, cap in scheduler["caps"].items())
    assert summary["fresh_search_changed_common"] == observed_changes
    assert summary["authored_development_cost"]["reset_calls"] == 24
    for wave in summary["wave_results"]:
        development = json.loads((workspace/(wave["generation_id"]+"-development.json")).read_text(encoding="utf-8"))
        receipts = {row["pair_receipt_sha256"]:row for row in development["receipts"]}
        for binding in wave["candidate_bindings"]:
            candidate = candidates[binding["candidate_id"]]
            receipt = receipts[binding["pair_receipt_sha256"]]
            assert candidate["metadata_digest"] == binding["candidate_metadata_digest"]
            assert any(blob["sha256"] == binding["implementation_sha256"] for blob in candidate["source_blobs"])
            assert receipt["identity"]["implementation_sha256"] == binding["implementation_sha256"]
            assert receipt["source_lineage_id"] == binding["source_lineage_id"]
    assert len([row for row in registry.records() if row["kind"] == "M0" and row["payload"]["phase"] == "COMPLETE"]) == 2
    assert len([row for row in registry.records() if row["kind"] == "LEARNING"]) == 2
    assert summary["generation_performance_improvement"] == summary["transfer_utility"] == "NOT_ESTABLISHED"


def test_fixture_source_authority_rejects_rehashed_external_code(tmp_path):
    client = GitHubRestClient(tmp_path/"cache",transport=AuthoredGitHubTransport())
    batch = discover_batch(client,REPOSITORIES,max_candidates=4,max_details=4,max_qualifications=4)
    candidate = deepcopy(batch["candidates"][0])
    buggy = next(blob for blob in candidate["source_blobs"] if blob["revision"] == candidate["buggy_revision"])
    buggy["text"] += "\n# unreviewed mutation"
    raw = buggy["text"].encode()
    buggy["sha256"] = hashlib.sha256(raw).hexdigest()
    buggy["git_blob_sha"] = hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    candidate["metadata_digest"] = digest({k:v for k,v in candidate.items() if k!="metadata_digest"})
    validate_candidate(candidate)  # A consistent hash is not fixture execution authority.
    with pytest.raises(PermissionError,match="reviewed authored callable"):
        _fixture_authority(candidate)


def test_fixture_experience_cannot_enter_real_harvest_learning_gate(completed_demo):
    workspace, summary = completed_demo
    registry = HarvestRegistry(workspace)
    development = json.loads((workspace/"G1-development.json").read_text(encoding="utf-8"))
    before = (workspace/"generations.jsonl").read_bytes()
    with pytest.raises(PermissionError):
        learn_from_harvest(workspace,list(registry.candidates()),development["receipts"],
            development["manifest"],workspace/"generations.jsonl",generation_id="FORBIDDEN-REAL",
            allow_reviewed_development=True)
    assert (workspace/"generations.jsonl").read_bytes() == before


def test_existing_demo_workspace_is_preserved(completed_demo):
    workspace, _ = completed_demo
    before = (workspace/"registry.jsonl").read_bytes()
    with pytest.raises(FileExistsError):
        run_demo(workspace)
    assert (workspace/"registry.jsonl").read_bytes() == before


def test_harvest_demo_cli_requires_explicit_local_opt_in(tmp_path):
    workspace = tmp_path/"must-not-execute"
    result = subprocess.run([sys.executable,"-m","tomolab","harvest-demo","--workspace",str(workspace)],
        capture_output=True,text=True)
    assert result.returncode != 0
    assert "allow-local-execution" in result.stderr
    assert not workspace.exists()
