"""Failure-first publication tests; all remote operations are mocked.

These authored archives and fake CI/registry replies do not execute a Source,
Oracle, research runner, GitHub write or PyPI upload.
"""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace
from urllib.error import HTTPError
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "a"*40
VERSION = "0.8.0a1"


@pytest.fixture
def publisher(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("product_publication_under_test", ROOT/"scripts/product-publication.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "urlopen", lambda *a, **k: pytest.fail("unmocked network request"))
    for name,value in dict(RELEASE_VERSION=VERSION, RELEASE_SHA=SOURCE,
        GITHUB_REPOSITORY=module.REPO, GITHUB_REF="refs/heads/main", GITHUB_SHA=SOURCE).items():
        monkeypatch.setenv(name, value)
    return module


def registry_manifest(module):
    return dict(repository=module.REPO, version=VERSION, source_sha=SOURCE, tag="v"+VERSION,
        packages={name:dict(sha256=hashlib.sha256(name.encode()).hexdigest(),size=len(name))
                  for name in sorted(module.package_names(VERSION))})


def registry_document(module, manifest, names=None):
    names = list(manifest["packages"]) if names is None else names
    return dict(info=dict(name=module.NAME, version=VERSION), urls=[dict(filename=name,
        digests=dict(sha256=manifest["packages"][name]["sha256"]),
        size=manifest["packages"][name]["size"], yanked=False) for name in names])


def ci_replies(module):
    run = dict(id=17, name=module.WORKFLOW, path=".github/workflows/tests.yml",
        head_sha=SOURCE, head_branch="main", status="completed", conclusion="success", event="push")
    jobs = [dict(id=i+1,name=name,status="completed",conclusion="success",head_sha=SOURCE)
            for i,name in enumerate(sorted(module.REQUIRED_JOBS))]
    return run,jobs


def fake_ci(monkeypatch, module, runs, jobs):
    calls=[]
    def api(path, **kwargs):
        calls.append((path,kwargs))
        if path.startswith("actions/runs?"):return dict(workflow_runs=runs)
        if path.startswith("actions/runs/") and "/jobs?" in path:return dict(jobs=jobs)
        pytest.fail("unexpected API operation: "+path)
    monkeypatch.setattr(module,"api",api)
    return calls


def test_exact_main_ci_requires_all_fourteen_reviewed_jobs(publisher, monkeypatch):
    run,jobs=ci_replies(publisher);calls=fake_ci(monkeypatch,publisher,[run],jobs)
    receipt=publisher.source_ci(SOURCE)
    assert len(receipt["required_jobs"])==len(publisher.REQUIRED_JOBS)==14
    assert receipt["source_sha"]==SOURCE and receipt["run_id"]==17
    assert all(not kwargs.get("method") for _,kwargs in calls)


@pytest.mark.parametrize("field,value", [("head_sha","b"*40),("head_branch","research"),
    ("event","pull_request"),("name","Different workflow"),("path",".github/workflows/other.yml"),
    ("status","in_progress"),("conclusion","failure")])
def test_other_commit_branch_event_or_unfinished_ci_cannot_authorize_publication(publisher,monkeypatch,field,value):
    run,jobs=ci_replies(publisher);run[field]=value;fake_ci(monkeypatch,publisher,[run],jobs)
    with pytest.raises(ValueError,match="CI|tests"):
        publisher.source_ci(SOURCE)


@pytest.mark.parametrize("change", ["missing","failed","duplicate"])
def test_incomplete_or_ambiguous_ci_jobs_are_blocked(publisher,monkeypatch,change):
    run,jobs=ci_replies(publisher)
    if change=="missing":jobs.pop()
    elif change=="failed":jobs[0]["conclusion"]="failure"
    else:jobs.append(deepcopy(jobs[0]))
    fake_ci(monkeypatch,publisher,[run],jobs)
    with pytest.raises(ValueError,match="CI|jobs"):
        publisher.source_ci(SOURCE)


@pytest.mark.parametrize("version", ["0.7.0a1","0.8.0","0.8.0.post1","0.8.0a0","../0.8.0a1"])
def test_historical_or_nonexperimental_versions_are_never_publication_inputs(publisher,monkeypatch,version):
    monkeypatch.setenv("RELEASE_VERSION",version)
    with pytest.raises(ValueError):publisher.inputs()


def test_alpha_input_is_not_hardcoded_to_one_minor_version(publisher,monkeypatch):
    monkeypatch.setenv("RELEASE_VERSION","12.34.56a7")
    assert publisher.inputs()==("12.34.56a7",SOURCE,"v12.34.56a7")


def test_lightweight_tag_cannot_replace_an_annotated_release_identity(publisher,monkeypatch):
    monkeypatch.setattr(publisher,"api",lambda *a,**k:dict(object=dict(type="commit",sha=SOURCE)))
    with pytest.raises(ValueError,match="annotated"):
        publisher.verify_tag("v"+VERSION,SOURCE)


@pytest.mark.parametrize("change", ["source","type","name"])
def test_existing_annotated_tag_cannot_be_retargeted(publisher,monkeypatch,change):
    record=dict(tag="v"+VERSION,object=dict(sha=SOURCE,type="commit",url="https://api.github.com/repos/"+publisher.REPO+"/git/commits/"+SOURCE))
    if change=="source":record["object"]["sha"]="b"*40
    elif change=="type":record["object"]["type"]="tree"
    else:record["tag"]="v9.9.9a1"
    monkeypatch.setattr(publisher,"api",lambda path,**k:dict(object=dict(type="tag",sha="c"*40))if path.startswith("git/ref/")else record)
    with pytest.raises(ValueError,match="immutable"):
        publisher.verify_tag("v"+VERSION,SOURCE)


def test_registry_version_collision_stops_before_any_tag_creation(publisher,monkeypatch):
    monkeypatch.setattr(publisher,"validate_source",lambda **k:(VERSION,SOURCE,"v"+VERSION))
    monkeypatch.setattr(publisher,"verify_tag",lambda *a,**k:False)
    monkeypatch.setattr(publisher,"request",lambda *a,**k:dict(info=dict(version=VERSION)))
    mutations=[]
    monkeypatch.setattr(publisher,"api",lambda *a,**k:mutations.append((a,k)))
    with pytest.raises(ValueError,match="PyPI version already exists"):
        publisher.create_tag()
    assert mutations==[]


def test_creating_a_new_tag_only_uses_annotated_object_and_new_ref(publisher,monkeypatch):
    monkeypatch.setattr(publisher,"validate_source",lambda **k:(VERSION,SOURCE,"v"+VERSION))
    seen=iter([False,True]);monkeypatch.setattr(publisher,"verify_tag",lambda *a,**k:next(seen))
    monkeypatch.setattr(publisher,"request",lambda *a,**k:None)
    calls=[]
    def api(path,**kwargs):
        calls.append((path,kwargs));return dict(sha="c"*40)
    monkeypatch.setattr(publisher,"api",api);publisher.create_tag()
    assert [x[0]for x in calls]==["git/tags","git/refs"]
    assert all(x[1]["method"]=="POST"for x in calls)
    assert calls[0][1]["data"]["object"]==SOURCE and calls[0][1]["data"]["type"]=="commit"
    assert calls[1][1]["data"]==dict(ref="refs/tags/v"+VERSION,sha="c"*40)


@pytest.mark.parametrize("state", ["absent","partial","complete"])
def test_registry_reports_only_genuinely_missing_exact_files(publisher,monkeypatch,state):
    manifest=registry_manifest(publisher);names=list(manifest["packages"])
    document=None if state=="absent"else registry_document(publisher,manifest,names[:1]if state=="partial"else names)
    monkeypatch.setattr(publisher,"request",lambda *a,**k:document)
    present,missing=publisher.registry(manifest)
    assert set(present).isdisjoint(missing)and set(present)|set(missing)==set(names)
    assert len(missing)=={"absent":2,"partial":1,"complete":0}[state]


@pytest.mark.parametrize("change", ["hash","size","yanked","extra","identity","version","duplicate"])
def test_conflicting_registry_state_is_never_skip_existing(publisher,monkeypatch,change):
    manifest=registry_manifest(publisher);document=registry_document(publisher,manifest)
    if change=="hash":document["urls"][0]["digests"]["sha256"]="0"*64
    elif change=="size":document["urls"][0]["size"]+=1
    elif change=="yanked":document["urls"][0]["yanked"]=True
    elif change=="extra":document["urls"].append(dict(filename="unapproved.whl"))
    elif change=="identity":document["info"]["name"]="other-project"
    elif change=="version":document["info"]["version"]="0.7.0a1"
    else:document["urls"].append(deepcopy(document["urls"][0]))
    monkeypatch.setattr(publisher,"request",lambda *a,**k:document)
    with pytest.raises(ValueError,match="registry|PyPI"):
        publisher.registry(manifest)


@pytest.mark.parametrize("status", [401,403,429,500])
def test_failed_http_is_one_attempt_without_auth_retry_or_token_output(publisher,monkeypatch,status):
    monkeypatch.setenv("GH_TOKEN","test-token-never-log");calls=[]
    def denied(request,**kwargs):
        calls.append(request);raise HTTPError(request.full_url,status,"denied",{},None)
    monkeypatch.setattr(publisher,"urlopen",denied)
    with pytest.raises(RuntimeError,match="no retry")as error:
        publisher.request("https://api.github.com/repos/"+publisher.REPO,github=True)
    assert len(calls)==1 and "test-token-never-log"not in str(error.value)


def test_missing_404_is_data_not_a_permission_retry(publisher,monkeypatch):
    calls=[]
    def absent(request,**kwargs):calls.append(request);raise HTTPError(request.full_url,404,"absent",{},None)
    monkeypatch.setattr(publisher,"urlopen",absent)
    assert publisher.request("https://pypi.org/pypi/fixture/json",missing=True)is None
    assert len(calls)==1


@pytest.mark.parametrize("url", ["http://files.pythonhosted.org/x","https://evil.example/x",
    "https://u:p@files.pythonhosted.org/x","https://files.pythonhosted.org/x#fragment"])
def test_registry_file_downloads_use_only_official_https_origin(publisher,url):
    with pytest.raises(ValueError,match="official"):
        publisher.official_file(url)


def authored_archives(module,*,wheel_extra=None,sdist_extra=None,description=None):
    root=module.ROOT;(root/"tomolab").mkdir(exist_ok=True);(root/"dist").mkdir(exist_ok=True)
    runtime={"tomolab/__init__.py":b"", "tomolab/cli.py":b"def main():\n    return 0\n",
             "tomolab/online_cli.py":b"p.add_argument('--method', default='A')\n"}
    for name,data in runtime.items():(root/name).write_bytes(data)
    readme="# Experimental 0.8.0a1 [qa] packaging fixture\n\n한국어 안내 → α; bounds −8..8.\n"
    (root/"README.md").write_text(readme,encoding="utf-8")
    body=readme if description is None else description
    metadata=("Metadata-Version: 2.4\nName: "+module.NAME+"\nVersion: "+VERSION+
        "\nDescription-Content-Type: text/markdown; charset=UTF-8\n\n"+body).encode("utf-8")
    prefix=module.NAME.replace("-","_")+"-"+VERSION
    with zipfile.ZipFile(root/"dist"/(prefix+"-py3-none-any.whl"),"w")as package:
        for name,data in {**runtime,prefix+".dist-info/METADATA":metadata,**(wheel_extra or {})}.items():package.writestr(name,data)
    with tarfile.open(root/"dist"/(prefix+".tar.gz"),"w:gz")as package:
        for name,data in {**runtime,"README.md":readme.encode(),"PKG-INFO":metadata,**(sdist_extra or {})}.items():
            entry=tarfile.TarInfo(prefix+"/"+name);entry.size=len(data);package.addfile(entry,io.BytesIO(data))
    return root/"dist"


def test_unicode_long_description_is_exact_utf8_not_email_ascii_replacement(publisher):
    publisher.package_source_binding(authored_archives(publisher),VERSION)


def test_changed_long_description_cannot_be_published(publisher):
    with pytest.raises(ValueError,match="long description"):
        publisher.package_source_binding(authored_archives(publisher,description="Different public product claims."),VERSION)


@pytest.mark.parametrize("kind", ["wheel","sdist"])
def test_both_archives_reject_extra_unreviewed_runtime_modules(publisher,kind):
    folder=authored_archives(publisher,**{kind+"_extra":{"tomolab/unreviewed.py":b"raise RuntimeError('not approved')\n"}})
    with pytest.raises(ValueError,match="runtime inventory"):
        publisher.package_source_binding(folder,VERSION)


@pytest.mark.parametrize("change", ["hash","extra_file","extra_directory"])
def test_upload_inventory_or_bytes_cannot_change_after_verification(publisher,change):
    folder=authored_archives(publisher)
    record=dict(packages={p.name:dict(sha256=publisher.sha(p.read_bytes()),size=p.stat().st_size)for p in folder.iterdir()})
    if change=="hash":next(folder.iterdir()).write_bytes(b"changed")
    elif change=="extra_file":(folder/"unapproved.whl").write_bytes(b"extra")
    else:(folder/"unapproved").mkdir()
    with pytest.raises(ValueError,match="distribution|upload directory"):
        publisher.verify_dist(folder,record)


def prepared_handoff(module,monkeypatch):
    """Fake trusted attestations, paired with real authored archive bytes."""
    folder=authored_archives(module);root=module.ROOT
    (root/"docs").mkdir();(root/"scripts").mkdir();(root/"verification").mkdir()
    (root/"pyproject.toml").write_text('[project]\nname="'+module.NAME+'"\nversion="'+VERSION+
        '"\n[project.urls]\nRepository="https://github.com/'+module.REPO+'"\n',encoding="utf-8")
    (root/"README.ko.md").write_text("A online-run → online-replay; D Source 선택 기능",encoding="utf-8")
    (root/"docs/MIGRATION_0_8.md").write_text("Preserve 0.7.0a1; experimental product 0.8.0a1",encoding="utf-8")
    auth=json.loads((ROOT/"docs/PRODUCT_RELEASE_AUTHORIZATION.json").read_text(encoding="utf-8"))
    module.write(root/"docs/PRODUCT_RELEASE_AUTHORIZATION.json",auth)
    module.write(root/"docs/E8_RELEASE_AUTHORIZATION.json",dict(status="NOT_AUTHORIZED_READINESS_BLOCKED"))
    for name in("ONLINE_PROFILE.json","HISTORICAL_PROFILE.json"):
        module.write(root/"docs"/name,dict(frozen_config=dict(allow_release=False),
            profile=dict(publication_authorized=False,final_evaluation_authorized=False)))
    module.write(root/"docs/HISTORICAL_RESULTS.json",dict(allow_release=False))
    (root/"scripts/check-product-release.py").write_bytes((ROOT/"scripts/check-product-release.py").read_bytes())
    record=registry_manifest(module)
    record["packages"]={p.name:dict(sha256=module.sha(p.read_bytes()),size=p.stat().st_size)for p in folder.iterdir()}
    record["authorization_sha256"]=module.sha((root/"docs/PRODUCT_RELEASE_AUTHORIZATION.json").read_bytes())
    module.write(root/"verification/release-manifest.json",record)
    ci=dict(status="PASS",repository=module.REPO,source_sha=SOURCE,workflow=module.WORKFLOW,
        event="push",head_branch="main",conclusion="success",run_id=17,
        required_jobs=[dict(name=n,conclusion="success")for n in sorted(module.REQUIRED_JOBS)])
    module.write(root/"verification/source-ci.json",ci)
    install=dict(schema="tomolab-product-installation-v1",status="PASS",source_sha=SOURCE,version=VERSION,
        wheel_sha256=next(v["sha256"]for n,v in record["packages"].items()if n.endswith(".whl")),
        sdist_sha256=next(v["sha256"]for n,v in record["packages"].items()if n.endswith(".tar.gz")),
        base_install_verified=True,qa_solver_verified=True,sdist_install_verified=True,
        readme_commands_verified=True,outside_checkout_verified=True,default_A_without_source_learning=True,
        dependency_installation="NORMAL_INDEX_INSTALL",registered_research_reexecuted=False,
        installations=[dict(artifact=k,distribution_version=VERSION,default_method="A",
            source_collection_calls=0,source_learning_rules=0,product_target_calls=3,product_oracle_calls=3,
            replay_status="REPRODUCED",module_origins=["lib/site-packages/tomolab/online_cli.py"])
            for k in("wheel","sdist")],
        checks=[dict(check="authored fixture, not actual installation",returncode=0,expected_success=True)])
    module.write(root/"verification/product-install.json",install)
    spec=importlib.util.spec_from_file_location("authored_handoff_gate",root/"scripts/check-product-release.py")
    gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
    approved=gate.evaluate(root,source_sha=SOURCE,actual_head=SOURCE,
        ci_receipt=root/"verification/source-ci.json",installation_receipt=root/"verification/product-install.json",
        required_jobs=sorted(module.REQUIRED_JOBS))
    module.write(root/"verification/product-gate.json",approved)
    monkeypatch.setattr(module,"git",lambda *a:SOURCE)
    def local_git_only(argv,**kwargs):
        assert argv==["git","rev-parse","HEAD"]
        return SimpleNamespace(stdout=SOURCE+"\n",returncode=0)
    monkeypatch.setattr(module.subprocess,"run",local_git_only)
    return record


@pytest.mark.parametrize("state", ["absent","partial","complete"])
def test_upload_handoff_copies_only_missing_verified_bytes_without_network_upload(publisher,monkeypatch,state):
    record=prepared_handoff(publisher,monkeypatch);names=list(record["packages"])
    document=None if state=="absent"else registry_document(publisher,record,names[:1]if state=="partial"else names)
    monkeypatch.setattr(publisher,"request",lambda *a,**k:document)
    output=[];monkeypatch.setattr(publisher,"output",lambda **k:output.append(k))
    publisher.upload_directory()
    copied=list((publisher.ROOT/"upload").iterdir())
    assert len(copied)=={"absent":2,"partial":1,"complete":0}[state]
    assert all(p.read_bytes()==(publisher.ROOT/"dist"/p.name).read_bytes()for p in copied)
    assert output==[dict(publish_required=state!="complete")]


@pytest.mark.parametrize("field", ["source_sha","version","assets","installation_receipt_sha256"])
def test_stale_product_approval_is_blocked_before_registry_or_any_upload(publisher,monkeypatch,field):
    prepared_handoff(publisher,monkeypatch)
    path=publisher.ROOT/"verification/product-gate.json";value=publisher.read(path)
    value[field]="stale-or-altered";publisher.write(path,value)
    monkeypatch.setattr(publisher,"registry",lambda *a:pytest.fail("stale approval reached registry"))
    with pytest.raises(ValueError,match="stale|altered|handoff"):
        publisher.upload_directory()
    assert not(publisher.ROOT/"upload").exists()


def test_copied_manifest_cannot_replace_the_product_user_approval(publisher,monkeypatch):
    record=prepared_handoff(publisher,monkeypatch)
    record["authorization_sha256"]="0"*64
    publisher.write(publisher.ROOT/"verification/release-manifest.json",record)
    with pytest.raises(ValueError,match="approval|handoff"):
        publisher.verified_handoff()
