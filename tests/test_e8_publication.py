"""Data-only publication gates; never contact GitHub or run a publisher."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT/"scripts"/(name+".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True)+"\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def approved_fixture(tmp_path):
    # These are authored policy attestations, not actual research evidence.
    checker = load("check-e8-freeze")
    paths = checker.expected_files(ROOT)
    for name in paths:
        destination = tmp_path/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if name == "pyproject.toml":
            destination.write_text('[project]\nversion="0.8.0a1"\n', encoding="utf-8")
        elif name.startswith("scripts/") and (ROOT/name).is_file():
            shutil.copyfile(ROOT/name, destination)
        else:
            destination.write_text("# authored fixture\n", encoding="utf-8")
    product = {name:hashlib.sha256((tmp_path/name).read_bytes()).hexdigest() for name in checker.expected_files(tmp_path)}
    manifest = dict(schema="tomolab-e8-code-freeze-v1", version="0.8.0a1",
        scope="IMPLEMENTATION_BYTES_NOT_RESEARCH_VERDICT", product_files=len(product), product=product)
    frozen_sha = save(tmp_path/"docs/E8_CODE_FREEZE.json", manifest)
    ready_sha = save(tmp_path/"docs/E8_READINESS_PUBLIC.json", dict(status="PASS", evidence_scope="REVIEWED_REAL_PROJECT",
        source_corroboration_linkage="VERIFIED", qualified_guidance=1))
    result = dict(comparison_status="COMPLETE", final_attempts=1, full_grid=True, methods=["A","B","C","D"],
        generator_feedback=0, required_errors=0, control_false_alerts=0, readiness_receipt_sha256=ready_sha,
        product_manifest_sha256=frozen_sha, verdict="NO_IMPROVEMENT")
    result_sha = save(tmp_path/"docs/E8_FINAL_RESULTS.json", result)
    auth = dict(schema="tomolab-e8-release-authorization-v1", status="AUTHORIZED", source_corroboration_linkage="VERIFIED",
        comparison_status="COMPLETE", qualified_guidance=1, readiness_receipt_sha256=ready_sha,
        comparison_receipt_sha256=result_sha, product_manifest_sha256=frozen_sha)
    save(tmp_path/"docs/E8_RELEASE_AUTHORIZATION.json", auth)
    return tmp_path, auth, result, manifest


def test_current_e8_is_blocked_before_loading_mutating_publisher(monkeypatch):
    gate = load("check-e8-release-eligibility")
    result = gate.evaluate(ROOT)
    assert not result["allow_release"] and "no-qualified-guidance" in result["reasons"]
    publisher = load("publish-e8")
    original = publisher.load
    calls = []
    def guarded(name, path):
        calls.append(path.name)
        assert path.name == "check-e8-release-eligibility.py"
        return original(name, path)
    monkeypatch.setattr(publisher, "load", guarded)
    with pytest.raises(PermissionError, match="E8 release blocked"):
        publisher.main()
    assert calls == ["check-e8-release-eligibility.py"]


def test_valid_reviewed_attestations_allow_no_improvement_release(approved_fixture):
    root, _, _, _ = approved_fixture
    assert load("check-e8-release-eligibility").evaluate(root)["allow_release"]


@pytest.mark.parametrize("field,value", [("full_grid",False), ("control_false_alerts",1),
    ("generator_feedback",1), ("final_attempts",2), ("methods",["B","C"]), ("required_errors",1)])
def test_invalid_comparison_is_rejected_even_when_file_hash_is_updated(approved_fixture, field, value):
    root, auth, result, _ = approved_fixture
    result[field] = value
    auth["comparison_receipt_sha256"] = save(root/"docs/E8_FINAL_RESULTS.json",result)
    save(root/"docs/E8_RELEASE_AUTHORIZATION.json",auth)
    assert not load("check-e8-release-eligibility").evaluate(root)["allow_release"]


def test_rehashed_empty_product_and_changed_code_fail_closed(approved_fixture):
    root, auth, _, manifest = approved_fixture
    (root/"tomolab/discovery/qualified_comparison.py").write_text("# changed\n",encoding="utf-8")
    assert not load("check-e8-release-eligibility").evaluate(root)["allow_release"]
    manifest.update(product={},product_files=0)
    auth["product_manifest_sha256"] = save(root/"docs/E8_CODE_FREEZE.json",manifest)
    save(root/"docs/E8_RELEASE_AUTHORIZATION.json",auth)
    assert not load("check-e8-release-eligibility").evaluate(root)["allow_release"]


@pytest.mark.parametrize("value", [{}, [], None, {"schema":"untrusted", "status":"AUTHORIZED"}])
def test_missing_or_malformed_publication_evidence_is_not_permission(tmp_path, value):
    save(tmp_path/"docs/E8_RELEASE_AUTHORIZATION.json", value)
    assert not load("check-e8-release-eligibility").evaluate(tmp_path)["allow_release"]


def test_private_e8_paths_and_source_leaks_are_rejected():
    checker = load("check-public-scope")
    for name in ("research/e8/raw.json", "e8-evidence/raw.json", "e8-evaluation/final.json", "known-positive-private/test.py"):
        with pytest.raises(ValueError):
            checker.inspect(name,b"{}")
    checker.inspect("tomolab/discovery/development_evidence.py",b"# public implementation")
