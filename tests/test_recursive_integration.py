"""Authored end-to-end execution, real process restart and API boundaries."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tomolab.discovery.recursive_api import create_generation, run_generation
from tomolab.discovery.recursive_store import GenerationStore
from tomolab.recursive_demo import CONTRACT, fixture_mold, gain_a, reference, run_demo


def test_real_development_update_store_process_restart_and_next_search(tmp_path):
    workspace = tmp_path / "authored"
    summary = run_demo(workspace)
    assert summary["choices"] == ["common", "learned", "common"]
    assert summary["executed_candidates"] == [[-1, -2], [1, 1], [-1, -2]]
    assert [row["status"] for row in summary["resumed"]] == ["PASS", "FAILURE", "PASS"]
    assert summary["resumed"][1]["full_new_search_changed_common"] >= 1
    assert len({row["process_id"] for row in summary["resumed"]}) == 3
    records = GenerationStore(workspace / "generations.jsonl").records()
    assert [row["generation"]["generation_id"] for row in records] == ["G0", "G1", "G2"]
    generations = [row["generation"] for row in records]
    assert generations[1]["parent_generation_digest"] == generations[0]["sha256"]
    assert generations[2]["parent_generation_digest"] == generations[1]["sha256"]
    assert [len(row["selector"]["evidence"]) for row in generations] == [0, 2, 4]
    assert [row["cost_ledger"]["target_calls"] for row in generations] == [0, 14, 28]
    assert summary["paired_target_calls"] == 24
    assert summary["carrier_cost"]["target_calls"] == 4
    assert all(row["candidate_validation"]["default_adoption"] == "HOLD" for row in generations)
    assert summary["real_utility"] == summary["generalization"] == "NOT_ESTABLISHED"
    assert (workspace / "functional-contract.json").exists()


def test_generation_api_refuses_execution_without_opt_in_and_mismatched_contract(tmp_path):
    mold = fixture_mold()
    store = tmp_path / "generations.jsonl"
    create_generation(store, mold, CONTRACT)
    calls = []
    def forbidden(point):
        calls.append(point)
        raise AssertionError("must not execute")
    with pytest.raises(PermissionError):
        run_generation(store, mold, forbidden, forbidden, CONTRACT,
            execution_id="no-opt-in", output=tmp_path / "no.json")
    with pytest.raises(ValueError, match="input contract"):
        run_generation(store, mold, forbidden, forbidden, dict(CONTRACT, high=9),
            allow_local_execution=True, execution_id="wrong-contract", output=tmp_path / "wrong.json")
    assert calls == []


def test_generation_execution_receipt_is_exclusive_and_bound_to_saved_selector(tmp_path):
    mold = fixture_mold()
    store = tmp_path / "generations.jsonl"
    generation = create_generation(store, mold, CONTRACT)
    output = tmp_path / "run.json"
    receipt = run_generation(store, mold, gain_a, reference, CONTRACT,
        allow_local_execution=True, execution_id="new-search", output=output,
        budget=24, shrink_budget=6, mode="black_box")
    assert receipt["generation_digest"] == generation["sha256"]
    assert receipt["selector_digest"] == generation["selector"]["selector_digest"]
    assert receipt["run"]["boundary"]["worker_lifecycle"] == "FRESH_PER_RUN"
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        run_generation(store, mold, gain_a, reference, CONTRACT,
            allow_local_execution=True, execution_id="overwrite", output=output)
    assert output.read_bytes() == before


def test_recursive_cli_requires_explicit_execution_opt_in(tmp_path):
    result = subprocess.run([sys.executable, "-m", "tomolab", "recursive-demo",
        "--workspace", str(tmp_path / "not-created")], capture_output=True, text=True)
    assert result.returncode != 0
    assert "allow-local-execution" in result.stderr
    assert not (tmp_path / "not-created").exists()
