"""Authored controller fixtures. No harvested module executes in these tests."""
from copy import deepcopy
import hashlib
import itertools
import json
import subprocess

import pytest

from tomolab.discovery import real_qualification as qualification
from tomolab.discovery import harvester_execution as execution
from tomolab.discovery.schema import digest
from test_harvester_execution import mock_launcher, bundle_fixture
from test_harvester_review import candidate_fixture, review_fixture, CONTRACT

IMAGE = "sha256:" + "a" * 64


def test_default_registers_plan_before_any_network_or_external_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(qualification, "_download", lambda *a, **kw: pytest.fail("default must not download"))
    monkeypatch.setattr(execution, "_launcher", lambda: pytest.fail("default must not invoke Docker"))
    result = qualification.run_public_qualification(tmp_path / "once", image=IMAGE)
    assert result["summary"]["status"] == "HOLD_EXECUTION"
    assert result["receipt"]["execution_attempts"] == 0
    assert result["receipt"]["unknown_external_call_records"] == 0
    assert result["receipt"]["metadata_digest"] == qualification.ORIGINAL_METADATA_DIGEST
    plan = json.loads((tmp_path / "once/public/execution-plan.json").read_bytes())
    assert plan["sha256"] == digest({k:v for k,v in plan.items() if k != "sha256"})
    assert len(plan["schedule"]) == 12
    assert plan["resource_caps"]["target_calls"] == plan["resource_caps"]["oracle_calls"] == 6
    assert result["summary"]["policy_updates"] == 0
    with pytest.raises(FileExistsError):
        qualification.run_public_qualification(tmp_path / "once", image=IMAGE)


@pytest.mark.parametrize("authority", [1, "yes", {}, None])
def test_truthy_authority_cannot_create_execution_workspace(tmp_path, authority):
    with pytest.raises(PermissionError):
        qualification.run_public_qualification(tmp_path / "never", image=IMAGE, allow_external_execution=authority)
    assert not (tmp_path / "never").exists()


@pytest.mark.parametrize("image", ["python:3.12", "sha256:" + "A" * 64, "sha256:" + "a" * 63, "--privileged", "sha256:" + "a" * 64 + " x"])
def test_mutable_or_argv_like_image_is_rejected_before_any_io(tmp_path, image):
    with pytest.raises(ValueError):
        qualification.run_public_qualification(tmp_path / "never", image=image)
    assert not (tmp_path / "never").exists()


@pytest.mark.parametrize("text,expected", [("", ""), ("a", "a"), ("a#a", "a#a"), ("##", "##"), ("abba", "abba"), ("babad", "bab"), ("cbbd", "bb")])
def test_authored_exhaustive_oracle_preserves_characters_and_earliest_ties(text, expected):
    assert qualification.reference(text) == expected


def test_authored_oracle_satisfies_definition_on_small_complete_domain():
    for length in range(6):
        for chars in itertools.product("ab#", repeat=length):
            text = "".join(chars)
            result = qualification.reference(text)
            assert result in text and result == result[::-1]
            for start in range(len(text)):
                for end in range(start + 1, len(text) + 1):
                    part = text[start:end]
                    if part == part[::-1]:
                        assert len(result) >= len(part)
                        if len(result) == len(part):
                            assert text.index(result) <= start


def restoration_fixture():
    """Authored bytes with the same benign module shape; no upstream body."""
    candidate = candidate_fixture()
    sources = ['"""Authored source data."""\nfrom __future__ import annotations\ndef longest_palindrome(text):\n    return text + "a"\n',
               '"""Authored source data."""\nfrom __future__ import annotations\ndef longest_palindrome(text):\n    return text\n']
    payloads = {}
    for i, (row, source) in enumerate(zip(candidate["source_blobs"], sources)):
        raw = source.encode()
        row.update(text=source, sha256=hashlib.sha256(raw).hexdigest(), git_blob_sha=hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest())
        payloads["source" + str(i)] = raw
    payloads["license"] = candidate["license"]["text"].encode()
    patch = "Authored inert test patch data"
    candidate["test_evidence"] = dict(paths=["tests/fixture.py"], patches=[dict(path="tests/fixture.py", sha256=hashlib.sha256(patch.encode()).hexdigest(), text=patch)])
    payloads["files"] = json.dumps([dict(filename="tests/fixture.py", patch=patch)]).encode()
    candidate["metadata_digest"] = digest({k:v for k,v in candidate.items() if k != "metadata_digest"})
    projection = deepcopy(candidate)
    for row in projection["source_blobs"]:
        row.pop("text")
    projection["license"].pop("text")
    for row in projection["test_evidence"]["patches"]:
        row.pop("text")
    return candidate, projection, payloads


def test_safe_projection_restores_exact_original_digest_without_importing_source():
    candidate, projection, payloads = restoration_fixture()
    restored = qualification._restore_candidate(projection, payloads)
    assert restored == candidate
    assert all("text" not in row for row in projection["source_blobs"])


def test_restoration_cannot_silently_refresh_discovery_time_or_metadata():
    candidate, projection, payloads = restoration_fixture()
    projection["discovered_at"] = "2026-11-02T00:00:00Z"
    with pytest.raises(ValueError, match="digest"):
        qualification._restore_candidate(projection, payloads)


@pytest.mark.parametrize("role", ["source0", "source1", "license", "files"])
def test_tampered_pinned_body_cannot_be_rebound_to_original_metadata(role):
    candidate, projection, payloads = restoration_fixture()
    if role == "files":
        payloads[role] = b"[]"
    else:
        payloads[role] += b"altered"
    with pytest.raises(ValueError):
        qualification._restore_candidate(projection, payloads)


def install_authored_controller_fixture(monkeypatch):
    # This is a controller-only mocked path. Its authored sum fixture is
    # intentionally unrelated to the real pinned public palindrome source.
    calls = mock_launcher(monkeypatch)
    monkeypatch.setattr(qualification, "WITNESS", [1, 1])
    monkeypatch.setattr(qualification, "CONTRACT", CONTRACT)
    monkeypatch.setattr(qualification, "_prepare_case", lambda *a: (candidate_fixture(), review_fixture(), bundle_fixture()))
    class FixtureAdapter:
        def __init__(self, deadline):
            self.deadline = deadline
        def factory(self):
            return execution._launcher()
        def evidence(self):
            return dict(status="PASS", create_attempted=True, cleanup=[dict(status="PASS", removed=True, absence_verified=True)], cli_calls=[])
    monkeypatch.setattr(qualification, "_DeadlineLauncher", FixtureAdapter)
    return calls


def test_authored_mocked_controller_has_twelve_fresh_single_function_calls(tmp_path, monkeypatch):
    calls = install_authored_controller_fixture(monkeypatch)
    def preparation(*args):
        assert (tmp_path / "fixture/public/execution-plan.json").is_file()
        return candidate_fixture(), review_fixture(), bundle_fixture()
    monkeypatch.setattr(qualification, "_prepare_case", preparation)
    result = qualification.run_public_qualification(tmp_path / "fixture", image=IMAGE, allow_external_execution=True)
    assert result["summary"]["status"] == "REPRODUCED"
    assert len(calls) == 12
    assert result["receipt"]["actual_known_counts"] == dict(external_target_calls=6, external_oracle_calls=6, external_reset_calls=12)
    reproduction = result["receipt"]["reproduction"]
    assert len({row[which]["boundary"]["inspection"]["container_id"] for branch in ("buggy", "fixed") for row in reproduction[branch] for which in ("target", "oracle")}) == 12
    assert result["summary"]["m0"].startswith("HOLD")
    assert result["summary"]["allow_release"] is False


def test_first_unknown_call_stops_without_replacement_or_counting_it_as_zero(tmp_path, monkeypatch):
    install_authored_controller_fixture(monkeypatch)
    attempts = []
    def failed(*args, **kwargs):
        attempts.append(kwargs["variant"])
        raise RuntimeError("authored mock protocol loss after possible entry")
    monkeypatch.setattr(execution, "execute_reviewed_case", failed)
    result = qualification.run_public_qualification(tmp_path / "failed", image=IMAGE, allow_external_execution=True)
    assert attempts == ["buggy"]
    assert result["summary"]["status"] == "HOLD_EXECUTION"
    assert result["summary"]["unknown_external_call_records"] == 1
    assert result["receipt"]["automatic_retries"] == 0
    assert result["receipt"]["reproduction"] is None


def test_deadline_reserve_forbids_entering_a_new_container(tmp_path, monkeypatch):
    install_authored_controller_fixture(monkeypatch)
    now = [0.0]
    monkeypatch.setattr(qualification.time, "monotonic", lambda: now[0])
    def preparation(deadline, *args):
        now[0] = deadline - 24
        return candidate_fixture(), review_fixture(), bundle_fixture()
    monkeypatch.setattr(qualification, "_prepare_case", preparation)
    monkeypatch.setattr(execution, "execute_reviewed_case", lambda *a, **kw: pytest.fail("no deadline budget"))
    result = qualification.run_public_qualification(tmp_path / "deadline", image=IMAGE, allow_external_execution=True)
    assert result["receipt"]["execution_attempts"] == 0
    assert "CONTROLLER_ENTRY_DEADLINE_RESERVE" in result["summary"]["reasons"]


def test_deadline_adapter_bounds_cli_and_verifies_cleanup(monkeypatch):
    monkeypatch.setattr(qualification.time, "monotonic", lambda: 100.0)
    calls = []
    def run(arguments, *, timeout):
        calls.append((arguments, timeout))
        return subprocess.CompletedProcess(arguments, 0, "", "")
    monkeypatch.setattr(execution, "_bounded_run", run)
    adapter = qualification._DeadlineLauncher(120)
    with pytest.raises(subprocess.TimeoutExpired):
        adapter.run(["docker", "create", "fixture"])
    assert calls == []
    adapter.run(["docker", "rm", "--force", "tomolab-historical-" + "a" * 32], timeout=30)
    assert [value for _, value in calls] == [20, 5]
    assert adapter.evidence()["status"] == "PASS"


def test_unverified_cleanup_is_unknown_even_if_rm_returned_success(monkeypatch):
    monkeypatch.setattr(qualification.time, "monotonic", lambda: 100.0)
    def run(arguments, *, timeout):
        return subprocess.CompletedProcess(arguments, 0, "still-present" if arguments[1] == "container" else "", "")
    monkeypatch.setattr(execution, "_bounded_run", run)
    adapter = qualification._DeadlineLauncher(120)
    adapter.create_attempted = True
    with pytest.raises(RuntimeError):
        adapter.run(["docker", "rm", "--force", "tomolab-historical-" + "a" * 32])
    assert adapter.evidence()["status"] == "UNKNOWN"
