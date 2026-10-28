"""Distribution gates use authored archives and metadata; no remote publication."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
from urllib.error import HTTPError
import zipfile

import pytest


def verifier():
    path = Path(__file__).resolve().parents[1] / "scripts/verify-pypi-release.py"
    spec = importlib.util.spec_from_file_location("pypi_release_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def archives(folder, module, *, wheel_changes=None, source_changes=None):
    """Authored packaging fixture, unrelated to any research evaluation."""
    files = {"tomolab/__init__.py": b"", "tomolab/cli.py": b"def main():\n    return 0\n",
        "pyproject.toml": b'[project]\nname="antemortem-structural-lab"\nversion="0.7.0a1"\n',
        "README.md": b"Authored packaging fixture.\n", "README.ko.md": "작성한 포장 검사.\n".encode(),
        "docs/E7_CODE_FREEZE.json": b"{}\n"}
    metadata = b"Metadata-Version: 2.4\nName: antemortem-structural-lab\nVersion: 0.7.0a1\n\n"
    wheel = {name: data for name, data in files.items() if name.startswith("tomolab/")}
    info = module.PREFIX + ".dist-info/"
    wheel[info + "METADATA"] = metadata
    wheel[info + "entry_points.txt"] = b"[console_scripts]\ntomolab = tomolab.cli:main\n"
    for name in ("README.md", "README.ko.md"):
        wheel[module.PREFIX + ".data/data/share/antemortem-structural-lab/" + name] = files[name]
    wheel.update(wheel_changes or {})
    source = {**files, "PKG-INFO": metadata, **(source_changes or {})}
    wheel_path = folder / (module.PREFIX + "-py3-none-any.whl")
    with zipfile.ZipFile(wheel_path, "w") as package:
        for name, data in wheel.items():
            package.writestr(name, data)
    source_path = folder / (module.PREFIX + ".tar.gz")
    with tarfile.open(source_path, "w:gz") as package:
        for name, data in source.items():
            item = tarfile.TarInfo(module.PREFIX + "/" + name)
            item.size = len(data)
            package.addfile(item, io.BytesIO(data))
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (wheel_path, source_path)}
    return files, hashes


def test_tagged_source_and_distribution_metadata_are_both_checked(tmp_path):
    module = verifier()
    files, hashes = archives(tmp_path, module)
    result = module.verify_package_contents(tmp_path, files, expected_hashes=hashes)
    assert result["runtime_modules"] == 2
    changed = dict(files, **{"tomolab/cli.py": b"def different():\n    return 1\n"})
    with pytest.raises(ValueError, match="tagged public source"):
        module.verify_package_contents(tmp_path, changed, expected_hashes=hashes)


def test_filenames_cannot_mask_wrong_internal_version(tmp_path):
    module = verifier()
    info = module.PREFIX + ".dist-info/METADATA"
    files, hashes = archives(tmp_path, module, wheel_changes={info: b"Name: antemortem-structural-lab\nVersion: 0.8.0a1\n"})
    with pytest.raises(ValueError, match="Name or Version"):
        module.verify_package_contents(tmp_path, files, expected_hashes=hashes)


def test_new_runtime_module_or_private_payload_cannot_be_added(tmp_path):
    module = verifier()
    files, hashes = archives(tmp_path, module, wheel_changes={"tomolab/unreviewed.py": b"pass\n"})
    with pytest.raises(ValueError, match="module inventory"):
        module.verify_package_contents(tmp_path, files, expected_hashes=hashes)
    # The same scoped inspector also rejects private package members.
    files, hashes = archives(tmp_path, module, source_changes={"PRIVATE_source.json": b"{}"})
    with pytest.raises(ValueError, match="private path"):
        module.verify_package_contents(tmp_path, files, expected_hashes=hashes)


def test_public_hash_and_exact_upload_inventory_are_fail_closed(tmp_path):
    module = verifier()
    files, hashes = archives(tmp_path, module)
    wrong = {name: "0" * 64 for name in hashes}
    with pytest.raises(ValueError, match="file hash"):
        module.verify_package_contents(tmp_path, files, expected_hashes=wrong)
    (tmp_path / "unexpected-directory").mkdir()
    with pytest.raises(ValueError, match="exactly"):
        module.verify_package_contents(tmp_path, files, expected_hashes=hashes)


@pytest.mark.parametrize("name", ["../outside.py", "/absolute.py", "C:/outside.py", "a\\outside.py"])
def test_archive_member_paths_are_not_trusted(name):
    with pytest.raises(ValueError, match="unsafe"):
        verifier().safe_name(name)


def test_archive_links_and_duplicate_members_are_rejected(tmp_path):
    module = verifier()
    path = tmp_path / "fixture.tar.gz"
    with tarfile.open(path, "w:gz") as package:
        item = tarfile.TarInfo("fixture/link")
        item.type = tarfile.SYMTYPE
        item.linkname = "../outside"
        package.addfile(item)
    with pytest.raises(ValueError, match="links"):
        module.archive_files(path)
    path = tmp_path / "fixture.whl"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("same.py", b"one")
        with pytest.warns(UserWarning, match="Duplicate"):
            package.writestr("same.py", b"two")
    with pytest.raises(ValueError, match="duplicate"):
        module.archive_files(path)


def registry_document(module):
    return {"info": {"name": module.NAME}, "releases": {module.VERSION: [
        {"filename": name, "digests": {"sha256": sha}, "yanked": False} for name, sha in module.PACKAGES.items()]}}


def test_missing_project_does_not_mean_name_reservation_or_ownership():
    result = verifier().registry_state(None)
    assert result == {"status": "PROJECT_LOOKUP_404_NOT_NAME_RESERVATION", "publish_required": True}


def test_only_exact_existing_pypi_files_allow_idempotent_skip():
    module = verifier()
    document = registry_document(module)
    assert module.registry_state(document) == {"status": "ALREADY_PUBLISHED_IDENTICAL_FILES", "publish_required": False}
    for mutate in (lambda value: value["releases"][module.VERSION].pop(),
                   lambda value: value["releases"][module.VERSION][0]["digests"].update(sha256="0" * 64),
                   lambda value: value["releases"][module.VERSION][0].update(yanked=True)):
        bad = deepcopy(document)
        mutate(bad)
        with pytest.raises(ValueError, match="conflicting or incomplete"):
            module.registry_state(bad)


def test_public_release_metadata_is_bound_to_the_approved_tag_and_files():
    module = verifier()
    release = {"id": module.RELEASE_ID, "tag_name": module.TAG, "draft": False, "prerelease": True,
        "assets": [{"name": name, "digest": "sha256:" + sha, "browser_download_url": module.ASSETS + name}
        for name, sha in {**module.PACKAGES, "SHA256SUMS.txt": module.CHECKSUM_SHA256}.items()]}
    module.validate_release_metadata(release)
    release["tag_name"] = "v0.8.0a1"
    with pytest.raises(ValueError, match="approved public"):
        module.validate_release_metadata(release)


def test_wrong_tag_is_rejected_before_archive_loading_or_network(monkeypatch, tmp_path):
    module = verifier()
    calls = []
    def changed(root, *args):
        calls.append(args)
        return b"0" * 40
    monkeypatch.setattr(module, "git", changed)
    with pytest.raises(ValueError, match="immutable E7 tag"):
        module.source_files(tmp_path)
    assert len(calls) == 1


def test_api_authentication_errors_are_not_retried_or_treated_as_missing(monkeypatch):
    module = verifier()
    calls = []
    def denied(request, **kwargs):
        calls.append(request.full_url)
        raise HTTPError(request.full_url, 403, "Denied", {}, None)
    monkeypatch.setattr(module, "urlopen", denied)
    with pytest.raises(HTTPError):
        module.read_json("https://pypi.org/pypi/antemortem-structural-lab/json", missing=True)
    assert len(calls) == 1


def test_offline_files_cannot_emit_a_live_publish_gate(monkeypatch, tmp_path):
    module = verifier()
    monkeypatch.setattr(sys, "argv", ["verify", "--directory", str(tmp_path), "--receipt", str(tmp_path / "out.json"), "--github-output"])
    with pytest.raises(ValueError, match="live release and registry"):
        module.main()


def post_verifier():
    path = Path(__file__).resolve().parents[1] / "scripts/verify-public-pypi.py"
    spec = importlib.util.spec_from_file_location("public_pypi_installs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def public_version(module):
    return {"info": {"name": module.NAME, "version": module.VERSION}, "urls": [
        {"filename": name, "digests": {"sha256": sha}, "url": "https://files.pythonhosted.org/packages/fixture/" + name, "yanked": False}
        for name, sha in module.PACKAGES.items()]}


def test_post_publish_files_must_have_the_same_hashes_and_official_download_origin():
    release, post = verifier(), post_verifier()
    value = public_version(release)
    assert set(post.version_files(value, release)) == set(release.PACKAGES)
    value["urls"][0]["url"] = "https://example.invalid/other.whl"
    with pytest.raises(ValueError, match="official PyPI"):
        post.version_files(value, release)
    value = public_version(release)
    value["urls"][0]["digests"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="file hash"):
        post.version_files(value, release)


def test_only_not_yet_visible_reads_are_retried_after_publication():
    release, post = verifier(), post_verifier()
    value = public_version(release)
    partial = deepcopy(value)
    partial["urls"].pop()
    reads, sleeps = iter([None, partial, value]), []
    release.read_json = lambda *args, **kwargs: next(reads)
    urls, attempts = post.await_version(release, sleep=sleeps.append)
    assert len(urls) == 2 and sleeps == [1, 2]
    assert attempts == ["VERSION_OR_FILE_NOT_VISIBLE", "VERSION_OR_FILE_NOT_VISIBLE", "VISIBLE_AND_HASH_MATCHED"]


def test_post_publish_hash_conflict_or_api_error_is_never_retried():
    for conflict in ("hash", "api"):
        release, post = verifier(), post_verifier()
        value = public_version(release)
        value["urls"][0]["digests"]["sha256"] = "0" * 64
        calls = []
        def read(*args, **kwargs):
            calls.append(True)
            if conflict == "api":
                raise HTTPError("https://pypi.org/", 403, "Denied", {}, None)
            return value
        release.read_json = read
        with pytest.raises((ValueError, HTTPError)):
            post.await_version(release, sleep=lambda _: pytest.fail("only missing reads can be retried"))
        assert calls == [True]


def test_fresh_download_hash_failure_prevents_any_installation(monkeypatch, tmp_path):
    release, post = verifier(), post_verifier()
    monkeypatch.setattr(post, "urlopen", lambda *args, **kwargs: io.BytesIO(b"wrong file"))
    folder = tmp_path / "public-download"
    with pytest.raises(ValueError, match="fresh public PyPI file differs"):
        post.download_public_files(folder, post.version_files(public_version(release), release), release)
    assert not list(folder.iterdir())
