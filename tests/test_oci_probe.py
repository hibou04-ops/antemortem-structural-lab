"""First-party mocked Docker transcripts; these tests do not run a daemon."""
import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace

import pytest

from tomolab.discovery import oci_probe as probe
from tomolab.discovery import harvester_execution as execution
from tomolab.discovery.schema import canonical,digest
from test_harvester_execution import boundary_fixture, mock_launcher, bundle_fixture
from test_harvester_review import candidate_fixture, review_fixture

IMAGE="sha256:"+"a"*64
CID="b"*64


def cgroup():
    return dict(schema="tomolab-cgroup-v2-control-v1",unified_membership=True,cgroup2_mount=True,
                memory_max=str(512*1024*1024),pids_max="64",cpu_max="100000 100000")


def mocked_docker(monkeypatch,*,daemon_first=True,daemon_cleanup=True,remaining="",ps_code=0,mutate=None,rm_code=0):
    calls=[]; information=0
    def bounded(argv,*,timeout=60):
        nonlocal information
        calls.append((deepcopy(argv),timeout))
        phase=argv[1]
        if phase=="info":
            information+=1
            okay=daemon_first if information==1 else daemon_cleanup
            return subprocess.CompletedProcess(argv,0 if okay else 1,'"27.0.0"' if okay else "","")
        if phase=="create": return subprocess.CompletedProcess(argv,0,CID+"\n","")
        if phase=="ps": return subprocess.CompletedProcess(argv,ps_code,remaining,"")
        if phase=="rm": return subprocess.CompletedProcess(argv,rm_code,"","")
        if phase=="start": return subprocess.CompletedProcess(argv,0,"","")
        raise AssertionError("unexpected Docker command")
    launcher=SimpleNamespace()
    def docker_execute(image,command,output,*,timeout,repository):
        assert image==IMAGE and command==["python","-I","/app/probe.py"] and timeout==30
        names={p.relative_to(repository).as_posix() for p in repository.rglob("*") if p.is_file()}
        assert names=={"probe.py","runtime/tomolab/__init__.py","runtime/tomolab/discovery/__init__.py"}|{
            "runtime/tomolab/"+name for name in execution.RUNTIME_FILES}
        assert not any(part in names for part in ("sources/buggy.py","sources/oracle.py","request.json"))
        assert (repository/"probe.py").read_text(encoding="utf-8")==probe.PROBE_SOURCE
        launcher._run(["docker","create","--name","tomolab-historical-"+"c"*32],timeout=30)
        inspection,runtime=boundary_fixture()
        inspection["container_id"]=CID
        runtime["binding"]["container_id"]=CID
        runtime["binding_digest"]=digest(runtime["binding"])
        runtime["execution_scope"]=probe.SCOPE
        value=dict(schema=probe.SCHEMA,control_entries=1,external_target_calls=0,external_oracle_calls=0,
            source_sha256=probe.hashlib.sha256(probe.PROBE_SOURCE.encode()).hexdigest(),boundary=runtime,
            cgroup=cgroup(),reasons=[])
        if mutate: mutate(inspection,value)
        value["result_sha256"]=digest(value)
        output.mkdir()
        (output/"container.stdout.log").write_text(canonical(value),encoding="utf-8")
        (output/"host-inspection.json").write_text(canonical(inspection),encoding="utf-8")
        launcher._run(["docker","start","--attach","tomolab-historical-"+"c"*32],timeout=30)
        launcher._run(["docker","rm","--force","tomolab-historical-"+"c"*32],timeout=30)
        return dict(status="PASS",inspection=inspection)
    launcher.docker_execute=docker_execute
    monkeypatch.setattr(probe,"_bounded_run",bounded)
    monkeypatch.setattr(probe,"_launcher",lambda:launcher)
    return calls


@pytest.mark.parametrize("opt_in",[False,1,"yes",None])
def test_opt_in_is_exact_and_precedes_all_writes_and_processes(tmp_path,monkeypatch,opt_in):
    monkeypatch.setattr(probe,"_bounded_run",lambda *a,**k:pytest.fail("no process authorized"))
    with pytest.raises(PermissionError): probe.run_oci_probe(tmp_path/"never",image=IMAGE,allow_container_execution=opt_in)
    assert not (tmp_path/"never").exists()


@pytest.mark.parametrize("image",["python:latest","-bad","sha256:"+"A"*64,"sha256:"+"0"*63,{},None])
def test_image_must_be_an_exact_preexisting_sha_before_any_write_or_process(tmp_path,monkeypatch,image):
    monkeypatch.setattr(probe,"_bounded_run",lambda *a,**k:pytest.fail("no process authorized"))
    with pytest.raises(ValueError): probe.run_oci_probe(tmp_path/"never",image=image,allow_container_execution=True)
    assert not (tmp_path/"never").exists()


def test_valid_control_reuses_boundary_and_minimal_stage_and_verifies_cleanup(tmp_path,monkeypatch):
    calls=mocked_docker(monkeypatch)
    receipt=probe.run_oci_probe(tmp_path/"control",image=IMAGE,allow_container_execution=True)
    assert receipt["status"]=="PASS"
    assert receipt["control_entries"]==1 and receipt["external_target_calls"]==receipt["external_oracle_calls"]==0
    assert receipt["boundary"]["runtime"]["execution_scope"]==probe.SCOPE
    assert receipt["cgroup"]["status"]==receipt["cleanup"]["status"]=="PASS"
    assert receipt["cleanup"]["daemon_available"] is True and receipt["cleanup"]["query_succeeded"] is True
    assert receipt["cleanup"]["matching_containers"]==0
    assert any(argv[:4]==["docker","ps","-a","--no-trunc"] and "id="+CID in argv for argv,_ in calls)
    assert receipt["cost"]["docker_cli_calls"]==len(calls)
    assert receipt["host_fallback"] is receipt["automatic_image_pull"] is False
    raw=json.loads((tmp_path/"control/oci-probe.json").read_text(encoding="utf-8"))
    assert raw==receipt and raw["receipt_sha256"]==digest({k:v for k,v in raw.items() if k!="receipt_sha256"})
    with pytest.raises(FileExistsError): probe.run_oci_probe(tmp_path/"control",image=IMAGE,allow_container_execution=True)


def test_daemon_unavailable_is_hold_with_no_container_or_host_fallback(tmp_path,monkeypatch):
    calls=mocked_docker(monkeypatch,daemon_first=False)
    monkeypatch.setattr(probe,"_launcher",lambda:pytest.fail("must not stage or create container"))
    receipt=probe.run_oci_probe(tmp_path/"unavailable",image=IMAGE,allow_container_execution=True)
    assert receipt["status"]=="HOLD" and receipt["control_entries"]==0
    assert not receipt["container_create_attempted"] and receipt["runtime_manifest"] is None
    assert receipt["cleanup"]["status"]=="NOT_CREATED" and len(calls)==1
    assert (tmp_path/"unavailable/oci-probe.json").is_file()


@pytest.mark.parametrize("patch",[dict(unified_membership=False),dict(cgroup2_mount=False),dict(memory_max="max"),
    dict(memory_max="268435456"),dict(pids_max="max"),dict(cpu_max="max 100000"),dict(cpu_max="200000 100000"),
    dict(cpu_max="0 100000"),dict(cpu_max="100000 100000\n"),dict(memory_max=512*1024*1024)])
def test_unsupported_or_wrong_actual_cgroup_observations_fail_closed(patch):
    with pytest.raises((ValueError,PermissionError)): probe.validate_cgroup_observation({**cgroup(),**patch})


def test_cgroup_period_may_vary_but_ratio_must_still_be_exactly_one():
    assert probe.validate_cgroup_observation({**cgroup(),"cpu_max":"50000 50000"})["status"]=="PASS"


@pytest.mark.parametrize("failure",["daemon","remaining","query","protocol"])
def test_cleanup_requires_successful_daemon_and_empty_exact_id_query(tmp_path,monkeypatch,failure):
    calls=mocked_docker(monkeypatch,daemon_cleanup=failure!="daemon",
        remaining=CID+"\n" if failure=="remaining" else ("invalid\n" if failure=="protocol" else ""),
        ps_code=1 if failure=="query" else 0)
    receipt=probe.run_oci_probe(tmp_path/failure,image=IMAGE,allow_container_execution=True)
    assert receipt["status"]=="HOLD" and receipt["cleanup"]["status"]=="HOLD"
    assert receipt["control_entries"]==1 and "CLEANUP_NOT_VERIFIED" in receipt["reasons"]
    if failure=="daemon": assert not any(argv[1]=="ps" for argv,_ in calls)


@pytest.mark.parametrize("field,value",[("execution_scope","REVIEWED_HARVESTER_FUNCTIONS_ONLY"),
    ("interfaces",["lo","eth0"]),("effective_capabilities",1),("sent_network_bytes",1)])
def test_real_boundary_validator_is_reused_without_relaxing_kernel_controls(tmp_path,monkeypatch,field,value):
    mocked_docker(monkeypatch,mutate=lambda inspection,result:result["boundary"].update({field:value}))
    receipt=probe.run_oci_probe(tmp_path/field,image=IMAGE,allow_container_execution=True)
    assert receipt["status"]=="HOLD" and receipt["cleanup"]["status"]=="PASS"


def test_control_scope_is_allowed_only_as_explicit_narrow_validator_argument():
    inspection,runtime=boundary_fixture()
    boundary=dict(inspection=inspection,runtime=runtime)
    assert execution._validate_boundary(boundary)
    runtime["execution_scope"]=probe.SCOPE
    with pytest.raises(PermissionError): execution._validate_boundary(boundary)
    assert execution._validate_boundary(boundary,expected_execution_scope=probe.SCOPE)
    with pytest.raises(PermissionError): execution._validate_boundary(boundary,expected_execution_scope="ARBITRARY_EXECUTION")


def test_protocol_cannot_claim_external_entry_or_swap_first_party_source(tmp_path,monkeypatch):
    for index,patch in enumerate([dict(external_target_calls=1),dict(control_entries=True),dict(source_sha256="f"*64)]):
        mocked_docker(monkeypatch,mutate=lambda inspection,result,p=patch:result.update(p))
        receipt=probe.run_oci_probe(tmp_path/str(index),image=IMAGE,allow_container_execution=True)
        assert receipt["status"]=="HOLD" and receipt["control_entries"] is None


def test_fixed_container_source_is_parseable_and_has_no_external_loader():
    ast.parse(probe.PROBE_SOURCE)
    assert "require_reviewed_container()" in probe.PROBE_SOURCE
    assert all(path in probe.PROBE_SOURCE for path in ("memory.max","pids.max","cpu.max","/proc/self/cgroup"))
    assert "importlib" not in probe.PROBE_SOURCE and "sources/" not in probe.PROBE_SOURCE


def test_optional_trusted_host_factory_is_validated_before_any_output_or_launcher(tmp_path,monkeypatch):
    monkeypatch.setattr(execution,"_launcher",lambda:pytest.fail("no launcher should be reached"))
    with pytest.raises(ValueError,match="trusted host"):
        execution.execute_reviewed_case(candidate_fixture(),review_fixture(),bundle_fixture(),variant="buggy",input=[1,1],
            image="authored-image",output_directory=tmp_path/"absent",allow_external_execution=True,
            trusted_review=True,launcher_factory="not-a-host-callable")
    assert not (tmp_path/"absent").exists()


def test_optional_factory_selects_only_the_call_local_launcher_and_preserves_default_scope(tmp_path,monkeypatch):
    calls=mock_launcher(monkeypatch)
    instance=execution._launcher()
    monkeypatch.setattr(execution,"_launcher",lambda:pytest.fail("default launcher must not be selected"))
    invoked=[]
    def factory():
        invoked.append(True)
        return instance
    receipt=execution.execute_reviewed_case(candidate_fixture(),review_fixture(),bundle_fixture(),variant="buggy",input=[1,1],
        image="authored-image",output_directory=tmp_path/"factory",allow_external_execution=True,trusted_review=True,
        launcher_factory=factory)
    assert receipt["status"]=="COMPLETE" and len(invoked)==len(calls)==1
    assert receipt["boundary"]["runtime"]["execution_scope"]=="REVIEWED_HARVESTER_FUNCTIONS_ONLY"


def test_minimal_stages_are_readable_by_the_inspected_nonroot_container_uid(tmp_path):
    for name in ("control","reviewed"):
        stage=tmp_path/name
        stage.mkdir(mode=0o700)
        if name=="control": probe._stage(stage)
        else: execution._stage(stage,bundle_fixture(),[1,1],"buggy")
        # POSIX mode assertions are an actual staging invariant; Windows ACL
        # behavior is established only by the separate real runtime probe.
        if os.name=="posix":
            assert stat.S_IMODE(stage.stat().st_mode)==0o755
            for path in stage.rglob("*"):
                assert stat.S_IMODE(path.stat().st_mode)==(0o755 if path.is_dir() else 0o644)
        assert (stage/("probe.py" if name=="control" else "runner.py")).is_file()
