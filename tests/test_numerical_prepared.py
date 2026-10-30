"""Approval-context and prepared reuse tests, without Source or Oracle calls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tomolab.discovery import numerical_prepared as prepared
from tomolab.discovery.schema import digest


@pytest.fixture
def compiled():
    folder = Path(__file__).parents[1]/"examples/numerical"
    return dict(artifact=json.loads((folder/"source-guide.json").read_text()),
                approval_receipt=json.loads((folder/"source-approval.json").read_text()))


def test_prepared_reuse_does_not_replay_archive(tmp_path, compiled, monkeypatch):
    context = prepared.approval_context(compiled)
    directory = tmp_path/"guide"
    saved = prepared.save_prepared_guide(compiled, directory, expected_current_context=context)
    from tomolab.discovery import knowledge, compact_guidance
    def denied(*args, **kwargs):
        raise AssertionError("prepared execution must not replay, calibrate or compile")
    monkeypatch.setattr(knowledge.KnowledgeArchive, "from_snapshot", denied)
    monkeypatch.setattr(compact_guidance, "prepare_recipe_from_archive", denied)
    monkeypatch.setattr(compact_guidance, "compile_execution_artifact", denied)
    value = prepared.load_prepared_guide(directory, expected_digest=context["approved_artifact_digest"],
                                         expected_current_context=context)
    assert value["compiled"] == compiled
    assert saved["prepared_bytes"] < 1048576
    assert value["metrics"]["full_archive_validation_invocations"] == 0
    with pytest.raises(FileExistsError):
        prepared.save_prepared_guide(compiled, directory, expected_current_context=context)


@pytest.mark.parametrize("field", ["source_archive_content_digest", "source_validation_version",
    "semantic_contract_version", "recipe_identity_and_parameters_digest", "public_input_contract",
    "counterevidence_state_reference", "compiler_identity", "artifact_schema",
    "approved_artifact_digest", "source_approval_receipt_digest"])
def test_external_current_identity_change_invalidates_reuse(tmp_path, compiled, field):
    context = prepared.approval_context(compiled)
    directory = tmp_path/"guide"
    prepared.save_prepared_guide(compiled, directory, expected_current_context=context)
    changed = deepcopy(context)
    changed[field] = "CHANGED_CURRENT_AUTHORITY"
    with pytest.raises(ValueError, match="context"):
        prepared.load_prepared_guide(directory, expected_digest=context["approved_artifact_digest"],
                                     expected_current_context=changed)


def test_manifest_rehash_is_not_external_approval(tmp_path, compiled):
    context = prepared.approval_context(compiled)
    directory = tmp_path/"guide"
    prepared.save_prepared_guide(compiled, directory, expected_current_context=context)
    path = directory/"manifest.json"
    value = json.loads(path.read_text())
    value["approval_context"]["compiler_identity"] = "0"*64
    value["manifest_digest"] = digest({k:v for k,v in value.items() if k != "manifest_digest"})
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="context"):
        prepared.load_prepared_guide(directory, expected_digest=context["approved_artifact_digest"],
                                     expected_current_context=context)


def test_whole_prepared_bundle_limit_and_duplicate_keys(tmp_path, compiled):
    context = prepared.approval_context(compiled)
    directory = tmp_path/"guide"
    prepared.save_prepared_guide(compiled, directory, expected_current_context=context)
    path = directory/"manifest.json"
    original = path.read_bytes()
    path.write_bytes(b" "*(prepared.MAX_PREPARED_BYTES+1))
    with pytest.raises(ValueError, match="one MiB"):
        prepared.load_prepared_guide(directory, expected_digest=context["approved_artifact_digest"],
                                     expected_current_context=context)
    path.write_bytes(b'{"schema":"one","schema":"two"}')
    with pytest.raises(ValueError, match="duplicate"):
        prepared.load_prepared_guide(directory, expected_digest=context["approved_artifact_digest"],
                                     expected_current_context=context)
    path.write_bytes(original)


def test_preparation_keeps_original_validators_and_external_state(tmp_path, compiled, monkeypatch):
    from tomolab.discovery import compact_guidance
    calls = []
    recipe = compiled["artifact"]["bounded_recipe_parameters"][0]
    def calibrate(snapshot, *, contract):
        calls.append("prepare")
        return {"recipe":recipe}
    def compile(snapshot, recipes, contract):
        calls.append("compile")
        return compiled
    monkeypatch.setattr(compact_guidance, "prepare_recipe_from_archive", calibrate)
    monkeypatch.setattr(compact_guidance, "compile_execution_artifact", compile)
    archive = tmp_path/"archive.json"
    archive.write_text("{}")
    state = tmp_path/"trusted-current-state.json"
    result = prepared.prepare_approved_guide(archive, tmp_path/"guide", state)
    assert calls == ["prepare", "compile"]
    assert result["metrics"]["full_archive_validation_invocations"] == 2
    assert result["approval_context"] == prepared.read_approval_state(state)
    with pytest.raises(FileExistsError):
        prepared.prepare_approved_guide(archive, tmp_path/"guide", state)


def test_partial_directory_without_manifest_is_not_accepted(tmp_path, compiled):
    context = prepared.approval_context(compiled)
    directory = tmp_path/"partial"
    directory.mkdir()
    with pytest.raises(FileNotFoundError):
        prepared.load_prepared_guide(directory, expected_digest=context["approved_artifact_digest"],
                                     expected_current_context=context)
