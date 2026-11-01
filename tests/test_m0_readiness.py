"""Authored receipt chains exercise a read-only gate; external executions zero."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tomolab.discovery import harvester_execution as execution
from tomolab.discovery.harvester_github import candidate_identity
from tomolab.discovery.harvester_review import make_review, source_function_identity
from tomolab.discovery.m0_readiness import make_manifest, assess_m0_readiness
from tomolab.discovery.schema import digest
from test_harvester_review import candidate_fixture, blob, CONTRACT, ORACLE, RESET
from test_harvester_execution import mock_launcher


def signed(value, field):
    value[field] = digest({k: v for k, v in value.items() if k != field})
    return value


@pytest.fixture
def reviewed_material(tmp_path, monkeypatch):
    mock_launcher(monkeypatch)
    rows = []
    for index in range(4):
        candidate = candidate_fixture()
        repository = "authored/project" + str(index // 2)
        candidate.update(repository=repository, number=10 + index,
            candidate_id=candidate_identity(repository, 10 + index), source_url="https://github.com/" + repository + "/pull/" + str(10 + index))
        bodies = [
            "    return sum(point) + int(len(point) > 1 and len(set(point)) == 1)\n",
            "    total = sum(point)\n    if len(point) > 1 and len(set(point)) == 1:\n        total += 1\n    return total\n",
            "    total = 0\n    for value in point:\n        total += value\n    return total + int(len(point) > 1 and len(set(point)) == 1)\n",
            "    return sum([value for value in point]) + int(len(point) > 1 and len(set(point)) == 1)\n",
        ]
        buggy = "def implementation(point):\n" + bodies[index]
        fixed = "def implementation(point):\n    return sum(point) + 0 * " + str(index) + "\n"
        candidate["source_blobs"] = [blob(buggy, "module.py", candidate["buggy_revision"]), blob(fixed, "module.py", candidate["fixed_revision"])]
        signed(candidate, "metadata_digest")
        review = make_review(candidate, contract=CONTRACT,
            implementation_sha256=hashlib.sha256(buggy.encode()).hexdigest(), fixed_implementation_sha256=hashlib.sha256(fixed.encode()).hexdigest(),
            oracle_sha256=hashlib.sha256(ORACLE.encode()).hexdigest(), reset_adapter_sha256=hashlib.sha256(RESET.encode()).hexdigest(),
            function_identity=source_function_identity(candidate, path="module.py", function="implementation"),
            lineage=dict(source_lineage_id="authored-lineage-" + str(index), project_id=repository.replace("/", "."),
                mechanism_id="authored-mechanism-" + str(index % 2), independence_id="authored-unit-" + str(index)),
            review_ids=dict(contract_review_id="authored-contract", oracle_review_id="authored-oracle", reset_review_id="authored-reset",
                license_review_id="authored-license", reviewer_id="authored-reviewer"),
            oracle_independence_basis="Authored mechanical validator fixture only; no real-project semantic independence claim.")
        bundle = execution.make_source_bundle(buggy, fixed, ORACLE, RESET)
        pairs = {"buggy": [], "fixed": []}
        for variant in pairs:
            for repeat in range(3):
                receipts = {}
                for key, selected in [("target", variant), ("oracle", "oracle")]:
                    receipts[key] = execution.execute_reviewed_case(candidate, review, bundle, variant=selected, input=[1, 1],
                        image="sha256:" + "a" * 64, output_directory=tmp_path/(str(index) + variant + str(repeat) + key),
                        allow_external_execution=True, trusted_review=True)
                pairs[variant].append(receipts)
        reproduction = execution.make_reproduction_receipt(candidate, review, pairs["buggy"], pairs["fixed"])
        rows.append(dict(candidate=candidate, review=review, reproduction=reproduction))
    return rows


def test_four_complete_chains_only_prepare_preregistration_without_authorizing_execution(reviewed_material):
    manifest = make_manifest(CONTRACT, reviewed_material)
    original = deepcopy(manifest)
    result = assess_m0_readiness(manifest, trusted_review=True)
    assert result["status"] == "READY_FOR_PREREGISTRATION"
    assert result["counts"]["projects"] == result["counts"]["mechanisms"] == 2
    assert result["m0"] == "HOLD" and result["utility"] == result["oos"] == "NOT_ESTABLISHED"
    assert result["execution_authorized"] is False and result["registry_writes"] == result["target_calls"] == result["oracle_calls"] == 0
    assert manifest == original
    assert result == assess_m0_readiness(manifest, trusted_review=True)


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_insufficient_material_is_not_refilled_or_relabelled(reviewed_material, count):
    result = assess_m0_readiness(make_manifest(CONTRACT, reviewed_material[:count]), trusted_review=True)
    assert result["status"] == "HOLD" and result["counts"]["evidence_rows"] == count
    assert result["target_calls"] == result["oracle_calls"] == result["reset_calls"] == result["network_requests"] == 0


def test_missing_review_authority_and_missing_reproduction_hold(reviewed_material):
    result = assess_m0_readiness(make_manifest(CONTRACT, reviewed_material))
    assert result["status"] == "HOLD" and result["counts"]["reviewed_reproduced"] == 0
    rows = deepcopy(reviewed_material)
    rows[0]["reproduction"] = None
    result = assess_m0_readiness(make_manifest(CONTRACT, rows), trusted_review=True)
    assert result["status"] == "HOLD" and result["counts"]["reviewed_reproduced"] == 3


def test_duplicate_and_tampered_evidence_cannot_manufacture_four_units(reviewed_material):
    rows = deepcopy(reviewed_material)
    rows[-1] = deepcopy(rows[0])
    result = assess_m0_readiness(make_manifest(CONTRACT, rows), trusted_review=True)
    assert result["status"] == "HOLD" and result["counts"]["unique_candidates"] == 3
    rows = deepcopy(reviewed_material)
    rows[0]["reproduction"]["external_reset_calls"] = 0
    signed(rows[0]["reproduction"], "sha256")
    result = assess_m0_readiness(make_manifest(CONTRACT, rows), trusted_review=True)
    assert result["rows"][0]["status"] == "HOLD_INVALID_EVIDENCE"


def test_common_contract_is_exact_and_not_inferred_from_kind(reviewed_material):
    narrowed = dict(CONTRACT, high=3)
    result = assess_m0_readiness(make_manifest(narrowed, reviewed_material), trusted_review=True)
    assert result["status"] == "HOLD" and result["counts"]["reviewed_reproduced"] == 4
    assert result["counts"]["common_contract_candidates"] == 0


@pytest.mark.parametrize("field", ["independence_id", "source_lineage_id", "mechanism_id"])
def test_relabelled_units_cannot_satisfy_independence_gate(reviewed_material, field):
    rows = deepcopy(reviewed_material)
    for row in rows:
        row["review"]["lineage"][field] = "same-authored-unit"
        signed(row["review"], "review_digest")
    result = assess_m0_readiness(make_manifest(CONTRACT, rows), trusted_review=True)
    assert result["status"] == "HOLD"


@pytest.mark.parametrize("authority", [1, None, "true"])
def test_authority_is_an_exact_boolean(authority):
    with pytest.raises(ValueError):
        assess_m0_readiness(make_manifest(CONTRACT, []), trusted_review=authority)


def test_manifest_digest_rejects_mutation_and_cli_never_enters_a_target(tmp_path):
    manifest = make_manifest(CONTRACT, [])
    changed = deepcopy(manifest)
    changed["mold_digest"] = "a" * 64
    with pytest.raises(ValueError, match="identity"):
        assess_m0_readiness(changed, trusted_review=True)
    source, output = tmp_path/"input.json", tmp_path/"receipt.json"
    source.write_text(json.dumps(manifest), encoding="utf8")
    run = subprocess.run([sys.executable, "-m", "tomolab", "m0-readiness", "--manifest", str(source), "--output", str(output)], capture_output=True, timeout=20)
    assert run.returncode == 3, run.stderr
    receipt = json.loads(output.read_bytes())
    assert receipt["status"] == "HOLD" and receipt["network_requests"] == 0
    assert receipt["execution_authorized"] is False
