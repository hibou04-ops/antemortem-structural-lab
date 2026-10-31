"""Host inspection contract and fail-closed checks; no historical code runs here."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

from tomolab.historical import HistoricalBoundaryError, require_reviewed_container


ROOT=Path(__file__).resolve().parents[1]


def launcher():
    spec=importlib.util.spec_from_file_location("historical_container_launcher",ROOT/"scripts/check-historical-container.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def inspection(tmp_path):
    repository=tmp_path/"repo";repository.mkdir()
    output=tmp_path/"output";output.mkdir()
    boundary=tmp_path/"boundary";boundary.mkdir()
    image_id="sha256:"+"a"*64
    value=dict(Id="b"*64,Image=image_id,State=dict(Status="created"),Config=dict(User="65534:65534"),
        HostConfig=dict(NetworkMode="none",ReadonlyRootfs=True,CapDrop=["ALL"],
            SecurityOpt=["no-new-privileges"],PidsLimit=64,Memory=512*1024*1024,NanoCpus=1_000_000_000,
            Tmpfs={"/tmp":"rw,noexec,nosuid,size=64m,mode=1777"}),
        Mounts=[dict(Type="bind",Source=str(path.resolve()),Destination=destination,RW=writable)
            for path,destination,writable in ((repository,"/app",False),(output,"/output",True),(boundary,"/boundary",False))])
    return value,dict(image_id=image_id,repository=repository,output=output,boundary=boundary)


def test_actual_inspection_contract_includes_both_readonly_authorities(tmp_path):
    module=launcher();value,arguments=inspection(tmp_path)
    receipt=module.verify_inspection(value,**arguments)
    assert receipt["inspected_before_start"] is True
    assert receipt["binds"]==[dict(destination="/app",read_only=True),dict(destination="/output",read_only=False),dict(destination="/boundary",read_only=True)]


@pytest.mark.parametrize("field,value",[("NetworkMode","bridge"),("ReadonlyRootfs",False),
    ("CapDrop",[]),("SecurityOpt",[]),("PidsLimit",0),("Memory",0),("NanoCpus",0)])
def test_weak_or_unbounded_docker_configuration_is_rejected(tmp_path,field,value):
    module=launcher();state,arguments=inspection(tmp_path)
    state["HostConfig"][field]=value
    with pytest.raises(PermissionError):module.verify_inspection(state,**arguments)


@pytest.mark.parametrize("kind",["root_user","writable_app","writable_context","extra_mount","already_running","wrong_image"])
def test_identity_and_mount_access_are_not_authorized_by_labels(tmp_path,kind):
    module=launcher();state,arguments=inspection(tmp_path)
    if kind=="root_user":state["Config"]["User"]="0"
    elif kind=="writable_app":state["Mounts"][0]["RW"]=True
    elif kind=="writable_context":state["Mounts"][2]["RW"]=True
    elif kind=="extra_mount":state["Mounts"].append(dict(Type="bind",Source="/var/run/docker.sock",Destination="/socket",RW=True))
    elif kind=="already_running":state["State"]["Status"]="running"
    else:state["Image"]="sha256:"+"c"*64
    with pytest.raises(PermissionError):module.verify_inspection(state,**arguments)


def test_environment_flag_cannot_authorize_local_historical_code(monkeypatch):
    from tomolab import historical
    monkeypatch.setenv("TOMOLAB_ALLOW_HISTORICAL_EXECUTION","1")
    monkeypatch.setattr(historical.platform,"system",lambda:"Windows")
    with pytest.raises(HistoricalBoundaryError,match="CI Docker"):
        require_reviewed_container()


@pytest.mark.parametrize("command",[["python","-c","print('x')\n"],["python","bad\0name"],[]])
def test_invalid_command_is_rejected_without_a_docker_call(tmp_path,monkeypatch,command):
    module=launcher();calls=[]
    monkeypatch.setattr(module,"_run",lambda *a,**k:calls.append(a))
    with pytest.raises(ValueError):module.docker_execute("reviewed-image",command,tmp_path/"out")
    assert calls==[]


def test_bad_inspection_stdout_cannot_start_the_container(tmp_path,monkeypatch):
    module=launcher();calls=[];repo=tmp_path/"repo";repo.mkdir()
    def run(argv,**kwargs):
        calls.append(argv)
        if argv[:3]==["docker","image","inspect"]:
            return subprocess.CompletedProcess(argv,0,"sha256:"+"a"*64+"\n","")
        if argv[:2]==["docker","inspect"]:
            return subprocess.CompletedProcess(argv,0,"not-json","")
        return subprocess.CompletedProcess(argv,0,"created\n","")
    monkeypatch.setattr(module,"_run",run)
    with pytest.raises(ValueError):
        module.docker_execute("reviewed-image",["python","/app/reviewed.py"],tmp_path/"out",repository=repo)
    assert not any(argv[:2]==["docker","start"] for argv in calls)
    assert any(argv[:2]==["docker","rm"] for argv in calls)


@pytest.mark.parametrize("timeout",[False,True])
def test_context_is_durable_before_start_and_partial_timeout_is_preserved(tmp_path,monkeypatch,timeout):
    module=launcher();state,arguments=inspection(tmp_path)
    output=tmp_path/"fresh-output";calls=[];created=[];context_at_start=[]
    def run(argv,**kwargs):
        calls.append(argv)
        if argv[:3]==["docker","image","inspect"]:
            return subprocess.CompletedProcess(argv,0,arguments["image_id"]+"\n","")
        if argv[:2]==["docker","create"]:
            created.extend(argv)
            return subprocess.CompletedProcess(argv,0,state["Id"]+"\n","")
        if argv[:2]==["docker","inspect"]:
            copy=deepcopy(state)
            binds=[arg for index,arg in enumerate(created) if index and created[index-1]=="--mount"]
            paths={next(piece[4:] for piece in bind.split(",") if piece.startswith("dst=")):
                next(piece[4:] for piece in bind.split(",") if piece.startswith("src=")) for bind in binds}
            for row in copy["Mounts"]:row["Source"]=paths[row["Destination"]]
            if context_at_start:copy["State"]=dict(Status="exited",ExitCode=0,OOMKilled=False)
            return subprocess.CompletedProcess(argv,0,json.dumps([copy]),"")
        if argv[:2]==["docker","start"]:
            boundary_arg=next(arg for arg in created if "dst=/boundary" in arg)
            folder=Path(next(piece[4:] for piece in boundary_arg.split(",") if piece.startswith("src=")))
            context_at_start.append(json.loads((folder/"context.json").read_text()))
            assert context_at_start[-1]["container_id"]==state["Id"]
            assert (output/"host-inspection.json").is_file()
            if timeout:raise subprocess.TimeoutExpired(argv,kwargs["timeout"],output=b"partial phase\n",stderr=b"")
            return subprocess.CompletedProcess(argv,0,"phase complete\n","")
        return subprocess.CompletedProcess(argv,0,"","")
    monkeypatch.setattr(module,"_run",run)
    if timeout:
        with pytest.raises(RuntimeError,match="timed out"):
            module.docker_execute("reviewed-image",["python","/app/reviewed.py"],output,repository=arguments["repository"])
    else:
        receipt=module.docker_execute("reviewed-image",["python","/app/reviewed.py"],output,repository=arguments["repository"])
        assert receipt["status"]=="PASS"
    assert len(context_at_start)==1
    receipt=json.loads((output/"container-launch.json").read_text())
    assert receipt["status"]==("FAILED_TIMEOUT" if timeout else "PASS")
    assert receipt["automatic_retries"]==0
    assert sum(argv[:2]==["docker","start"] for argv in calls)==1
    assert any(argv[:2]==["docker","rm"] for argv in calls)
