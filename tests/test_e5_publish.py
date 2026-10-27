"""Offline release gates: real archive/hash checks, no GitHub subprocesses."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace
import zipfile

import pytest


HEAD = "1" * 40
TAG_OBJECT = "2" * 40


class OfflineGitHub:
    def __init__(self, publish, root):
        self.publish, self.root = publish, root
        self.events, self.assets = [], {}
        self.release = self.ref = None
        self.resolved_head = HEAD
        self.download_failure = None
        self.tracked = ["tomolab/audit_fixture.py", "README.md", "README.ko.md", "SECURITY.md"]

    def api(self, path, missing=False):
        if path == "releases/tags/" + self.publish.TAG:
            return deepcopy(self.release)
        if path == "git/ref/tags/" + self.publish.TAG:
            return deepcopy(self.ref)
        if path == "git/tags/" + TAG_OBJECT:
            return {"object": {"type": "commit", "sha": self.resolved_head}}
        raise AssertionError("unexpected offline API path: " + path)

    def command(self, *args, check=True):
        if args == ("git", "ls-files", "-z"):
            return SimpleNamespace(stdout="\0".join(self.tracked) + "\0")
        if args[:2] == ("git", "-c") and "tag" in args:
            assert "-a" in args and args[-1] == HEAD and self.ref is None
            self.events.append("annotated-tag")
        elif args == ("git", "push", "origin", "refs/tags/" + self.publish.TAG):
            assert self.events[-1] == "annotated-tag"
            self.ref = {"object": {"type": "tag", "sha": TAG_OBJECT}}
            self.events.append("push-tag")
        else:
            raise AssertionError("unexpected offline command: " + repr(args))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def set_release(self, *, draft, annotated=True):
        self.ref = {"object": {"type": "tag", "sha": TAG_OBJECT}} if annotated else {
            "object": {"type": "commit", "sha": HEAD}}
        self.release = {"tag_name": self.publish.TAG, "prerelease": True, "draft": draft,
                        "html_url": "https://example.invalid/controlled-release", "assets": []}
        for path in (self.root / "dist").iterdir():
            self.assets[path.name] = path.read_bytes()
        manifest = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n"
                           for name, data in sorted(self.assets.items()))
        self.assets["SHA256SUMS.txt"] = manifest.encode("ascii")
        self._asset_metadata()

    def _asset_metadata(self):
        self.release["assets"] = [{"name": name, "digest": "sha256:" + hashlib.sha256(data).hexdigest()}
                                  for name, data in self.assets.items()]

    def gh(self, *args, check=True):
        action = args[:2]
        if action == ("release", "create"):
            assert self.ref["object"]["type"] == "tag"
            assert all(flag in args for flag in ("--verify-tag", "--prerelease", "--draft", "--latest=false"))
            self.release = {"tag_name": self.publish.TAG, "prerelease": True, "draft": True,
                            "html_url": "https://example.invalid/controlled-release", "assets": []}
            self.events.append("create-draft")
        elif action == ("release", "upload"):
            assert "--clobber" not in args
            for name in args[5:]:
                path = Path(name)
                assert path.name not in self.assets, "an existing remote asset would be overwritten"
                self.assets[path.name] = path.read_bytes()
            self._asset_metadata()
            self.events.append("upload-assets")
        elif action == ("release", "download"):
            draft = self.release["draft"]
            self.events.append("download-draft" if draft else "download-public")
            if draft and self.download_failure == "download":
                raise RuntimeError("controlled download failure")
            folder = Path(args[args.index("--dir") + 1])
            for name, data in self.assets.items():
                if draft and self.download_failure == "checksum" and name.endswith(".whl"):
                    data += b"controlled corruption"
                (folder / name).write_bytes(data)
        elif action == ("release", "edit"):
            assert all(flag in args for flag in ("--draft=false", "--prerelease", "--latest=false"))
            self.events.append("publish")
            self.release["draft"] = False
        else:
            raise AssertionError("unexpected offline GitHub command: " + repr(args))
        return SimpleNamespace(returncode=0, stdout="", stderr="")


@pytest.fixture
def publication(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / "scripts" / "publish-e5.py"
    module_spec = importlib.util.spec_from_file_location("e5_publish_under_test", script)
    publish = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(publish)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", publish.REPO)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_SHA", HEAD)
    (tmp_path / "pyproject.toml").write_text(f'[project]\nversion="{publish.VERSION}"\n', encoding="utf-8")
    sources = {"tomolab/audit_fixture.py": b"def identity(value):\n    return value\n",
               "README.md": b"Public release fixture.\n", "README.ko.md": "공개 테스트 자료.\n".encode(),
               "SECURITY.md": b"Only controlled local examples.\n"}
    for name, data in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    dist = tmp_path / "dist"
    dist.mkdir()
    prefix = f"antemortem_structural_lab-{publish.VERSION}"
    with zipfile.ZipFile(dist / (prefix + "-py3-none-any.whl"), "w") as archive:
        for name, data in sources.items():
            packaged = name if name.startswith("tomolab/") else (
                f"{prefix}.data/data/share/antemortem-structural-lab/" + name)
            archive.writestr(packaged, data)
    with tarfile.open(dist / (prefix + ".tar.gz"), "w:gz") as archive:
        for name, data in sources.items():
            member = tarfile.TarInfo(prefix + "/" + name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    fake = OfflineGitHub(publish, tmp_path)
    monkeypatch.setattr(publish, "api", fake.api)
    monkeypatch.setattr(publish, "command", fake.command)
    monkeypatch.setattr(publish, "gh", fake.gh)
    original_verify = publish.verify_source_assets

    def verify_source(folder):
        original_verify(folder)
        fake.events.append("verify-source")

    def forbid_subprocess(*args, **kwargs):
        raise AssertionError("real subprocesses are forbidden in publication tests")

    monkeypatch.setattr(publish, "verify_source_assets", verify_source)
    monkeypatch.setattr(publish.subprocess, "run", forbid_subprocess)
    return publish, fake, tmp_path


def test_initial_main_publishes_only_after_verified_draft(publication):
    publish, fake, root = publication
    publish.main()
    assert fake.events == ["annotated-tag", "push-tag", "create-draft", "upload-assets",
                           "download-draft", "verify-source", "publish", "download-public", "verify-source"]
    receipt = json.loads((root / "release-receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "PUBLISHED_AND_BYTE_VERIFIED"
    assert receipt["annotated_tag"] is True
    assert receipt["draft_verified_before_publication"] is True
    assert receipt["sha256"] == {name: hashlib.sha256(data).hexdigest() for name, data in fake.assets.items()}


@pytest.mark.parametrize("failure,error", [("download", RuntimeError), ("checksum", ValueError)])
def test_failed_draft_readback_never_publishes(publication, failure, error):
    publish, fake, root = publication
    fake.download_failure = failure
    with pytest.raises(error, match="download failure|checksum mismatch"):
        publish.main()
    assert "publish" not in fake.events
    assert fake.release["draft"] is True
    assert not (root / "release-receipt.json").exists()


def test_published_rerun_verifies_bytes_without_claiming_draft_provenance(publication):
    publish, fake, root = publication
    fake.set_release(draft=False)
    original = deepcopy(fake.assets)
    publish.main()
    assert fake.events == ["download-public", "verify-source", "download-public", "verify-source"]
    assert fake.assets == original
    receipt = json.loads((root / "release-receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "EXISTING_RELEASE_BYTE_VERIFIED"
    assert receipt["annotated_tag"] is True
    assert receipt["draft_verified_before_publication"] is not True


@pytest.mark.parametrize("annotated,wrong_commit", [(False, False), (True, True)])
def test_published_rerun_rejects_wrong_tag_without_mutation(publication, annotated, wrong_commit):
    publish, fake, root = publication
    fake.set_release(draft=False, annotated=annotated)
    if wrong_commit:
        fake.resolved_head = "3" * 40
    original = deepcopy(fake.assets)
    with pytest.raises(ValueError, match="annotated|tag differs"):
        publish.main()
    assert "publish" not in fake.events
    assert "upload-assets" not in fake.events
    assert fake.assets == original
    assert not (root / "release-receipt.json").exists()
