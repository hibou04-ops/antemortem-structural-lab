"""Authored data-only qualification fixtures; no external source is imported."""
from copy import deepcopy
import hashlib

import pytest

from tomolab.discovery.harvester_github import candidate_identity, validate_candidate
from tomolab.discovery.harvester_review import (assess_candidate, build_consumed_registry,
    candidate_profile, validate_candidate_profile, make_review, source_function_identity,
    static_source_review, validate_review_bundle)
from tomolab.discovery.schema import digest

BUGGY = "def implementation(point):\n    return sum(point) + int(len(point) > 1 and len(set(point)) == 1)\n"
FIXED = "def implementation(point):\n    return sum(point)\n"
ORACLE = "def reference(point):\n    total = 0\n    for value in point:\n        total += value\n    return total\n"
RESET = "def reset():\n    return True\n"
CONTRACT = dict(kind="sequence_int",low=-4,high=4,min_size=0,max_size=4)


def blob(text, path, revision):
    raw = text.encode()
    return dict(path=path,revision=revision,git_blob_sha=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest(),
                sha256=hashlib.sha256(raw).hexdigest(),text=text)


def candidate_fixture():
    buggy,fixed = "1"*40,"2"*40
    license = blob("Authored MIT license fixture; not an actual upstream license.","LICENSE",fixed)
    c = dict(candidate_id=candidate_identity("authored/project",7),repository="authored/project",
        source_url="https://github.com/authored/project/pull/7",number=7,title="authored qualification fixture",
        discovered_at="2026-11-01T00:00:00Z",stage="PROVENANCE_VERIFIED",issues=[],buggy_revision=buggy,fixed_revision=fixed,
        provenance=dict(public_repository=True,repository_id=7,merged=True,merge_commit_sha=fixed,
            proposed_buggy_first_parent=True,proposed_buggy_parent_sha=buggy,reported_base_sha=buggy,
            reported_head_sha="3"*40,detail_reserved=True,qualification_reserved=True,api_objects=[]),
        license=dict(license,spdx_id="MIT",status="ORIGINAL_BYTES_VERIFIED_NOT_LEGAL_REVIEW"),
        changed_files=[],test_evidence=dict(paths=[],patches=[]),
        source_blobs=[blob(BUGGY,"module.py",buggy),blob(FIXED,"module.py",fixed)],
        identity_support=dict(source_files_inspected=1,python_source_available=True,raw_sources_verified=True,
            consumption_status="NOT_REVIEWED",independence_status="NOT_ESTABLISHED"),unknown_reasons=[])
    c["metadata_digest"] = digest(c)
    return validate_candidate(c)


def review_fixture(candidate=None):
    candidate = candidate or candidate_fixture()
    return make_review(candidate,contract=CONTRACT,
        implementation_sha256=hashlib.sha256(BUGGY.encode()).hexdigest(),
        fixed_implementation_sha256=hashlib.sha256(FIXED.encode()).hexdigest(),
        oracle_sha256=hashlib.sha256(ORACLE.encode()).hexdigest(),reset_adapter_sha256=hashlib.sha256(RESET.encode()).hexdigest(),
        function_identity=source_function_identity(candidate,path="module.py",function="implementation"),
        lineage=dict(source_lineage_id="authored-lineage",project_id="authored.project",mechanism_id="authored-sum",
                     independence_id="authored-independent-unit"),
        review_ids=dict(contract_review_id="authored-contract",oracle_review_id="authored-oracle",
            reset_review_id="authored-reset",license_review_id="authored-license",reviewer_id="authored-reviewer"),
        oracle_independence_basis="Authored linear sum specification and independently written loop oracle; functional fixture only.")


def resign(value, key):
    value[key] = digest({k:v for k,v in value.items() if k != key})
    return value


def test_metadata_does_not_automatically_authorize_contract_or_oracle():
    c = candidate_fixture()
    a = assess_candidate(c)
    assert a["status"] == "HOLD_REVIEW"
    assert a["completed_stages"] == ["DISCOVERED","PROVENANCE_VERIFIED"]
    assert a["host_external_code_imported"] is False


def test_accountable_review_still_requires_actual_isolated_reproduction():
    c,r = candidate_fixture(),review_fixture()
    assert assess_candidate(c,review=r)["status"] == "HOLD_REVIEW"
    a = assess_candidate(c,review=r,trusted_review=True)
    assert a["status"] == "HOLD_EXECUTION"
    assert a["completed_stages"][-1] == "ORACLE_REVIEWED"


@pytest.mark.parametrize("field",["canonical_function_identity","cross_revision_function_key","normalized_ast_clone_sha256"])
def test_rehashed_function_identity_cannot_replace_actual_source_fingerprint(field):
    c,r = candidate_fixture(),review_fixture()
    r["function_identity"][field] = "f"*64
    resign(r,"review_digest")
    with pytest.raises(ValueError,match="fingerprints"):
        validate_review_bundle(c,r)


def test_final_feedback_and_oracle_copy_are_rejected_even_with_new_digest():
    c,r = candidate_fixture(),review_fixture()
    r["split"] = "final"
    with pytest.raises(PermissionError):
        validate_review_bundle(c,resign(r,"review_digest"))
    r = review_fixture(c)
    r["oracle_sha256"] = r["fixed_implementation_sha256"]
    with pytest.raises(ValueError,match="Oracle"):
        validate_review_bundle(c,resign(r,"review_digest"))


def test_static_parse_never_imports_upstream_top_level_side_effect(tmp_path):
    marker = tmp_path/"must-not-exist"
    source = "from pathlib import Path\nPath("+repr(str(marker))+").write_text('bad')\ndef selected(point):\n    return point\n"
    result = static_source_review(source)
    assert result["host_imported"] is False and result["functions"][0]["name"] == "selected"
    assert not marker.exists()


def test_known_upstream_consumption_is_blocked_across_url_case_alias():
    c = candidate_fixture()
    c["issues"] = ["https://github.com/MAHMOUD/BOLTONS/issues/475"]
    resign(c,"metadata_digest")
    assert assess_candidate(c)["status"] == "REJECTED"


def test_consumed_registry_is_nonempty_and_missing_sources_fail_closed(tmp_path):
    registry = build_consumed_registry()
    assert registry["tokens"] and any(row["path"] == "docs/E8_R4_CORR_USAGE.json" for row in registry["sources"])
    with pytest.raises(ValueError,match="unavailable"):
        build_consumed_registry(tmp_path)


def test_candidate_profile_uses_verified_file_refs_and_keeps_semantics_unknown():
    candidate = candidate_fixture()
    original = deepcopy(candidate)
    profile = candidate_profile(candidate)
    assert profile["candidate_id"] == candidate["candidate_id"]
    assert profile["metadata_digest"] == candidate["metadata_digest"]
    assert profile["language"] == "Python" and len(profile["language_evidence"]) == 2
    assert profile["library"] == "authored/project"
    assert profile["implementation_identity"]["references"][0]["sha256"] == candidate["source_blobs"][0]["sha256"]
    assert all(profile[name] == "UNKNOWN" for name in ("input_type","mechanism","input_contract_identity","oracle_identity"))
    assert profile["implementation_identity"]["selected_function_identity"] == "UNKNOWN"
    assert validate_candidate_profile(candidate,profile) == profile
    assert candidate == original


def test_candidate_title_cannot_invent_language_contract_mechanism_or_oracle():
    candidate = candidate_fixture()
    candidate["source_blobs"] = []
    candidate["title"] = "Python list bug with independent Oracle and arithmetic mechanism"
    resign(candidate,"metadata_digest")
    profile = candidate_profile(candidate)
    assert profile["language"] == "UNKNOWN" and profile["language_evidence"] == []
    assert profile["implementation_identity"]["status"] == "UNKNOWN"
    assert profile["input_type"] == profile["mechanism"] == profile["oracle_identity"] == "UNKNOWN"
    profile["input_type"] = "sequence_int"
    resign(profile,"sha256")
    with pytest.raises(ValueError,match="source-backed metadata"):
        validate_candidate_profile(candidate,profile)
