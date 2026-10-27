"""E7 publication exercises the same offline draft/source verifier with E7 assets."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import zipfile

import pytest
from test_e5_publish import HEAD, OfflineGitHub


@pytest.fixture
def publication(tmp_path,monkeypatch):
    path = Path(__file__).resolve().parents[1]/"scripts/publish-e7.py"
    spec = importlib.util.spec_from_file_location("e7_publish_test",path)
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    publisher = entry._load_publisher()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("E5_RELEASE_SOURCE_SHA",raising=False)
    for key,value in {"GITHUB_REPOSITORY":publisher.REPO,"GITHUB_EVENT_NAME":"push",
                      "GITHUB_REF":"refs/heads/main","GITHUB_SHA":HEAD}.items():
        monkeypatch.setenv(key,value)
    (tmp_path/"pyproject.toml").write_text('[project]\nversion="0.7.0a1"\n',encoding="utf-8")
    files = {"tomolab/audit_fixture.py":b"def identity(value):\n    return value\n",
             "README.md":b"E7 public fixture.\n","README.ko.md":"E7 공개 자료.\n".encode(),
             "SECURITY.md":b"Trusted local callbacks only.\n"}
    for name,data in files.items():
        dest = tmp_path/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(data)
    dist = tmp_path/"dist"
    dist.mkdir()
    prefix = "antemortem_structural_lab-0.7.0a1"
    with zipfile.ZipFile(dist/(prefix+"-py3-none-any.whl"),"w") as archive:
        for name,data in files.items():
            archive.writestr(name if name.startswith("tomolab/") else prefix+".data/data/share/antemortem-structural-lab/"+name,data)
    with tarfile.open(dist/(prefix+".tar.gz"),"w:gz") as archive:
        for name,data in files.items():
            info = tarfile.TarInfo(prefix+"/"+name)
            info.size=len(data)
            archive.addfile(info,io.BytesIO(data))
    fake = OfflineGitHub(publisher,tmp_path)
    monkeypatch.setattr(publisher,"api",fake.api)
    monkeypatch.setattr(publisher,"command",fake.command)
    monkeypatch.setattr(publisher,"gh",fake.gh)
    monkeypatch.setattr(entry,"_load_publisher",lambda:publisher)
    def forbid(*args,**kwargs):
        raise AssertionError("real publication subprocesses are forbidden")
    monkeypatch.setattr(publisher.subprocess,"run",forbid)
    return entry,publisher,fake,tmp_path


def test_e7_current_main_annotated_draft_is_verified_before_publication(publication):
    entry,publisher,fake,root = publication
    entry.main()
    receipt = json.loads((root/"release-receipt.json").read_text(encoding="utf-8"))
    assert receipt["tag"]=="v0.7.0a1" and receipt["source_commit"]==receipt["ci_commit"]==HEAD
    assert receipt["draft_verified_before_publication"] is True
    assert receipt["publication_policy"]=="E7_CURRENT_MAIN_ONLY"
    assert receipt["publication_entrypoint_sha256"]==hashlib.sha256(Path(entry.__file__).read_bytes()).hexdigest()
    assert set(fake.assets)=={"antemortem_structural_lab-0.7.0a1-py3-none-any.whl","antemortem_structural_lab-0.7.0a1.tar.gz","SHA256SUMS.txt"}
    assert fake.events.index("download-draft")<fake.events.index("publish")<fake.events.index("download-public")


def test_e7_draft_hash_failure_never_publishes(publication):
    entry,publisher,fake,root = publication
    fake.download_failure="checksum"
    with pytest.raises(ValueError,match="checksum"):
        entry.main()
    assert "publish" not in fake.events and fake.release["draft"]


def test_e7_rejects_old_source_recovery_before_any_remote_operation(publication,monkeypatch):
    entry,publisher,fake,root = publication
    monkeypatch.setenv("E5_RELEASE_SOURCE_SHA","473092b529a6593a890a5efc7f492433d269371e")
    with pytest.raises(ValueError,match="current main"):
        entry.main()
    assert not fake.events and not fake.api_paths


def test_draft_visibility_only_retries_successful_empty_reads():
    path = Path(__file__).resolve().parents[1]/"scripts/publish-e7.py"
    spec = importlib.util.spec_from_file_location("e7_visibility",path)
    entry = importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
    reads = iter([None,None,{"id":7,"draft":True}]);sleeps=[]
    assert entry.created_draft_readback(lambda:next(reads),sleep=sleeps.append)["id"] == 7
    assert sleeps == [1,2]
    assert entry.created_draft_readback(lambda:None,sleep=lambda _:None) is None


def test_draft_visibility_does_not_retry_api_or_permission_errors():
    path = Path(__file__).resolve().parents[1]/"scripts/publish-e7.py"
    spec = importlib.util.spec_from_file_location("e7_visibility_error",path)
    entry = importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
    calls=[]
    def reject():
        calls.append(1)
        raise RuntimeError("API permission error")
    with pytest.raises(RuntimeError,match="permission"):
        entry.created_draft_readback(reject,sleep=lambda _:pytest.fail("API errors must not be retried"))
    assert len(calls) == 1
