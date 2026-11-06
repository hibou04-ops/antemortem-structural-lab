"""Exact history mapping must reject drift without relaxing publication checks."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from test_pypi_release import archives, verifier

ROOT = Path(__file__).resolve().parents[1]


def adapter():
    path = ROOT / "scripts/verify-historical-e7-release.py"
    spec = importlib.util.spec_from_file_location("historical_e7_adapter_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def document_fixture(module):
    files, original, rows = {}, {}, []
    for name in sorted(module.DOCUMENTS):
        old, new = ("Original " + name).encode(), ("Current " + name).encode()
        files[name] = new
        original["fixture/" + name] = old
        rows.append(dict(path=name, original_sha256=module.digest(old), rewritten_sha256=module.digest(new),
                         original_bytes=len(old), rewritten_bytes=len(new)))
    files["README.md"] = b"Unmapped document"
    return files, original, rows


def test_mapping_restores_only_the_ten_exact_original_document_views():
    module = adapter()
    files, original, rows = document_fixture(module)
    result = module.mapped_documents(files, original, rows, "fixture")
    assert {name for name in files if files[name] != result[name]} == module.DOCUMENTS
    assert result["README.md"] == files["README.md"]
    assert all(result[row["path"]] == original["fixture/" + row["path"]] for row in rows)
    assert all(files[row["path"]] != result[row["path"]] for row in rows)
    assert len(module.document_mapping()) == 10


@pytest.mark.parametrize("side", ["rewritten", "original"])
def test_changed_document_cannot_be_accepted_by_the_mapping(side):
    module = adapter()
    files, original, rows = document_fixture(module)
    name = rows[0]["path"]
    if side == "rewritten":
        files[name] += b"!"
    else:
        original["fixture/" + name] += b"!"
    with pytest.raises(ValueError, match=side + " document differs"):
        module.mapped_documents(files, original, rows, "fixture")


@pytest.mark.parametrize("change", ["missing", "duplicate", "runtime"])
def test_mapping_cannot_expand_or_change_its_reviewed_scope(change):
    module = adapter()
    files, original, rows = document_fixture(module)
    if change == "missing":
        rows.pop()
    elif change == "duplicate":
        rows[0] = rows[1]
    else:
        rows[0]["path"] = "tomolab/cli.py"
    with pytest.raises(ValueError, match="exactly the reviewed paths"):
        module.mapped_documents(files, original, rows, "fixture")


@pytest.mark.parametrize("changed", ["tag", "source"])
def test_local_ref_drift_is_rejected(changed, tmp_path):
    module = adapter()
    values = [module.REWRITTEN_TAG, module.REWRITTEN_SOURCE]
    values[0 if changed == "tag" else 1] = "0" * 40
    reads = iter(values)
    original = SimpleNamespace(TAG="v0.7.0a1", git=lambda *args: next(reads).encode())
    with pytest.raises(ValueError, match="tag object or source commit differs"):
        module.verify_local_refs(tmp_path, original)


@pytest.mark.parametrize("changed", ["tag", "source"])
def test_live_ref_drift_is_rejected(changed):
    module = adapter()
    api = "https://api.github.com/repos/fixture/repo"
    ref = {"object": {"sha": module.REWRITTEN_TAG, "type": "tag", "url": api + "/git/tags/" + module.REWRITTEN_TAG}}
    tag = {"object": {"sha": module.REWRITTEN_SOURCE, "type": "commit"}}
    (ref if changed == "tag" else tag)["object"]["sha"] = "0" * 40
    reads = iter([ref, tag])
    original = SimpleNamespace(TAG="v0.7.0a1", API=api, read_json=lambda url: next(reads))
    with pytest.raises(ValueError, match="remote rewritten E7"):
        module.verify_remote_refs(original)


def test_distribution_hash_is_checked_before_using_any_document(tmp_path):
    module = adapter()
    (tmp_path / "original.whl").write_bytes(b"changed artifact")
    calls = []
    def git(root, *args):
        calls.append(args)
        assert args[0] == "rev-parse", "Untrusted artifact must fail before source loading"
        return (module.REWRITTEN_SOURCE if args[1].endswith("^{commit}") else module.REWRITTEN_TAG).encode()
    original = SimpleNamespace(TAG="v0.7.0a1", PACKAGES={"original.whl": "0" * 64}, git=git)
    with pytest.raises(ValueError, match="original distribution hash"):
        module.verified_source(tmp_path, tmp_path, original)
    assert len(calls) == 2


@pytest.mark.parametrize("changed", ["revision", "verify-pypi-release.py", "check-public-scope.py"])
def test_untrusted_helper_cannot_be_imported(tmp_path, monkeypatch, changed):
    module = adapter()
    (tmp_path / "scripts").mkdir()
    for name in ("verify-pypi-release.py", "check-public-scope.py"):
        (tmp_path / "scripts" / name).write_bytes(b"changed" if name == changed else b"pinned")
    def git(args, **kwargs):
        if args[1] == "rev-parse":
            return (("0" * 40) if changed == "revision" else module.PUBLICATION_REVISION).encode()
        return b"pinned"
    monkeypatch.setattr(subprocess, "check_output", git)
    monkeypatch.setattr(module, "load_module", lambda *args: pytest.fail("helper imported before verification"))
    with pytest.raises(ValueError, match="revision differs|helper changed"):
        module.checked_verifier(tmp_path)


def product_fixture(root):
    product = {"tomolab/module_%02d.py" % i: b"# Authored preservation fixture.\n" for i in range(54)}
    product.update({"pyproject.toml": b"# Authored packaging fixture.\n",
                    "scripts/evaluate-e7.py": b"# No evaluation is executed.\n",
                    "docs/E7_EVALUATION_CONTRACT.json": b"{}\n"})
    manifest = dict(schema="tomolab-e7-code-freeze-v1", version="0.7.0a1", product_files=57,
                    product={name: hashlib.sha256(data).hexdigest() for name, data in product.items()})
    files = {**product, "docs/E7_CODE_FREEZE.json": json.dumps(manifest).encode(),
             "scripts/check-e7-freeze.py": (ROOT / "scripts/check-e7-freeze.py").read_bytes()}
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return files


def test_original_freeze_checker_still_runs_for_all_57_files(tmp_path):
    adapter().preserved_product(tmp_path, product_fixture(tmp_path), verifier())


@pytest.mark.parametrize("changed", ["source_product", "working_product", "manifest", "checker", "added_runtime"])
def test_original_freeze_check_rejects_product_manifest_and_checker_drift(tmp_path, changed):
    files = product_fixture(tmp_path)
    if changed == "source_product":
        files["tomolab/module_00.py"] += b"!"
    else:
        name = {"working_product": "tomolab/module_00.py", "manifest": "docs/E7_CODE_FREEZE.json",
                "checker": "scripts/check-e7-freeze.py", "added_runtime": "tomolab/unreviewed.py"}[changed]
        (tmp_path / name).write_bytes(b"changed")
    with pytest.raises(ValueError):
        adapter().preserved_product(tmp_path, files, verifier())


def test_unmapped_document_difference_reaches_original_package_rejection(tmp_path):
    module, original = adapter(), verifier()
    files, hashes = archives(tmp_path, original)
    mapped, source, rows = document_fixture(module)
    view = module.mapped_documents({**files, **mapped}, source, rows, "fixture")
    with pytest.raises(ValueError, match="wheel member differs from tagged public source"):
        original.verify_package_contents(tmp_path, view, expected_hashes=hashes)
