"""Explicit, first-party OCI control probe; no external Target or Oracle.

The existing reviewed launcher and kernel boundary validator are reused. An
unavailable daemon, unsupported cgroup v2, or unverified cleanup stays HOLD.
"""
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time

from .harvester_execution import (_launcher, _bounded_run, _validate_boundary,
    _save, _stage_readable, RUNTIME_FILES, MAX_OUTPUT_BYTES)
from .schema import digest, keys

SCOPE = "FIRST_PARTY_BOUNDARY_CONTROL_PROBE"
SCHEMA = "tomolab-first-party-oci-control-v1"
MEMORY_BYTES = 512*1024*1024

# Fixed first-party code only. No harvested code, user program, expression, or
# module path is accepted by this control entry point.
PROBE_SOURCE = r'''"""Bundled first-party kernel control observer, executed only in OCI."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,"/app/runtime")
from tomolab.historical import require_reviewed_container
from tomolab.discovery.schema import digest

def bounded_text(path,limit=4096):
    with open(path,"r",encoding="utf-8") as stream:
        value=stream.read(limit+1)
    if len(value)>limit:
        raise ValueError("kernel observation exceeded control bound")
    return value.strip()

boundary=cgroup=None
reasons=[]
try:
    boundary=require_reviewed_container()
    boundary["execution_scope"]="FIRST_PARTY_BOUNDARY_CONTROL_PROBE"
    membership=bounded_text("/proc/self/cgroup").splitlines()
    mount_lines=bounded_text("/proc/self/mountinfo",262144).splitlines()
    mounted=any(" - cgroup2 " in line and len(line.split())>4 and line.split()[4]=="/sys/fs/cgroup" for line in mount_lines)
    cgroup=dict(schema="tomolab-cgroup-v2-control-v1",
        unified_membership=len(membership)==1 and membership[0].startswith("0::"),
        cgroup2_mount=mounted,memory_max=bounded_text("/sys/fs/cgroup/memory.max",64),
        pids_max=bounded_text("/sys/fs/cgroup/pids.max",64),
        cpu_max=bounded_text("/sys/fs/cgroup/cpu.max",64))
except Exception as error:
    reasons=[type(error).__name__]
value=dict(schema="tomolab-first-party-oci-control-v1",control_entries=1,
    external_target_calls=0,external_oracle_calls=0,
    source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    boundary=boundary,cgroup=cgroup,reasons=reasons)
value["result_sha256"]=digest(value)
print(json.dumps(value,ensure_ascii=True,allow_nan=False,separators=(",",":")))
'''


def _stage(path):
    runtime=path/"runtime/tomolab"
    (runtime/"discovery").mkdir(parents=True)
    manifest={}
    for relative in ("__init__.py","discovery/__init__.py"):
        (runtime/relative).write_bytes(b"")
        manifest["runtime/tomolab/"+relative]=hashlib.sha256(b"").hexdigest()
    package=Path(__file__).resolve().parents[1]
    for relative in RUNTIME_FILES:
        raw=(package/relative).read_bytes()
        (runtime/relative).write_bytes(raw)
        manifest["runtime/tomolab/"+relative]=hashlib.sha256(raw).hexdigest()
    raw=PROBE_SOURCE.encode("utf-8")
    (path/"probe.py").write_bytes(raw)
    manifest["probe.py"]=hashlib.sha256(raw).hexdigest()
    _stage_readable(path)
    return dict(files=manifest,runtime_digest=digest(manifest),source_sha256=manifest["probe.py"])


def validate_cgroup_observation(value):
    keys(value,("schema","unified_membership","cgroup2_mount","memory_max","pids_max","cpu_max"))
    if (value["schema"]!="tomolab-cgroup-v2-control-v1" or value["unified_membership"] is not True
        or value["cgroup2_mount"] is not True):
        raise PermissionError("observed unified cgroup v2 kernel authority required")
    if value["memory_max"]!=str(MEMORY_BYTES) or type(value["memory_max"]) is not str or value["pids_max"]!="64" or type(value["pids_max"]) is not str:
        raise PermissionError("observed memory.max/pids.max must match inspected limits")
    cpu=value["cpu_max"]
    if type(cpu) is not str or re.fullmatch(r"[1-9][0-9]{0,11} [1-9][0-9]{0,11}",cpu) is None:
        raise PermissionError("finite exact cpu.max quota and period required")
    quota,period=map(int,cpu.split())
    if quota!=period:
        raise PermissionError("observed cpu.max must limit to exactly one CPU")
    return dict(status="PASS",memory_bytes=MEMORY_BYTES,pids_limit=64,
                cpu_quota=quota,cpu_period=period,cpu_ratio_numerator=1,cpu_ratio_denominator=1,
                observation=value)


def _daemon(runner):
    result=runner(["docker","info","--format","{{json .ServerVersion}}"],timeout=10)
    if result.returncode!=0:
        return False
    try: version=json.loads(result.stdout)
    except (ValueError,TypeError): return False
    return type(version) is str and 1<=len(version)<=128


def _cleanup(runner,tracking):
    result=dict(status="HOLD",daemon_available=None,container_id=tracking["container_id"],
                query_succeeded=False,matching_containers=None)
    try:
        result["daemon_available"]=_daemon(runner)
        if not result["daemon_available"]:
            result["reason"]="DAEMON_UNAVAILABLE_CLEANUP_UNKNOWN"
            return result
        if not tracking["create_attempted"]:
            result.update(status="NOT_CREATED",reason="NO_CONTAINER_CREATE_ATTEMPT")
            return result
        cid=tracking["container_id"]
        if type(cid) is not str or re.fullmatch(r"[a-f0-9]{64}",cid) is None:
            result["reason"]="CREATED_CONTAINER_ID_UNKNOWN"
            return result
        query=runner(["docker","ps","-a","--no-trunc","--filter","id="+cid,"--format","{{.ID}}"],timeout=10)
        if query.returncode!=0:
            result["reason"]="CLEANUP_QUERY_FAILED"
            return result
        result["query_succeeded"]=True
        rows=query.stdout.splitlines()
        if any(re.fullmatch(r"[a-f0-9]{64}",row) is None for row in rows):
            result["reason"]="CLEANUP_QUERY_PROTOCOL_INVALID"
            return result
        result["matching_containers"]=len(rows)
        if rows:
            result["reason"]="DISPOSABLE_CONTAINER_STILL_PRESENT"
        else:
            result.update(status="PASS",reason="DAEMON_AND_EMPTY_EXACT_ID_QUERY_CONFIRMED")
    except Exception as error:
        result["reason"]="CLEANUP_"+type(error).__name__
    return result


def run_oci_probe(workspace,*,image,allow_container_execution=False):
    """Persist a fresh PASS/HOLD receipt, never auto-pull or run on the host."""
    if allow_container_execution is not True:
        raise PermissionError("explicit allow_container_execution=True required before writes or processes")
    if type(image) is not str or re.fullmatch(r"sha256:[a-f0-9]{64}",image) is None:
        raise ValueError("one exact pre-existing reviewed image SHA256 ID required")
    workspace=Path(workspace).resolve()
    workspace.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter()
    tracking=dict(create_attempted=False,container_id=None,start_attempted=False)
    receipt=dict(schema="tomolab-oci-control-probe-receipt-v1",status="HOLD",image_id=image,
        execution_scope=SCOPE,first_party_control_only=True,external_target_calls=0,external_oracle_calls=0,
        host_external_code_imported=False,host_fallback=False,automatic_image_pull=False,
        control_entries=0,daemon_available=None,container_create_attempted=False,container_start_attempted=False,
        boundary=None,cgroup=None,runtime_manifest=None,cleanup=dict(status="NOT_ATTEMPTED"),reasons=[],
        cost=dict(docker_cli_calls=0,wall_seconds=0.0))
    def runner(arguments,*,timeout=60):
        receipt["cost"]["docker_cli_calls"]+=1
        if arguments[:2]==["docker","create"]:
            tracking["create_attempted"]=True
        if arguments[:2]==["docker","start"]:
            tracking["start_attempted"]=True
            receipt["control_entries"]=None
        result=_bounded_run(arguments,timeout=timeout)
        if arguments[:2]==["docker","create"] and result.returncode==0:
            value=result.stdout.strip()
            if re.fullmatch(r"[a-f0-9]{64}",value): tracking["container_id"]=value
        return result
    try:
        receipt["daemon_available"]=_daemon(runner)
        if not receipt["daemon_available"]:
            receipt["reasons"].append("DAEMON_UNAVAILABLE_NO_CONTAINER_ATTEMPT")
        else:
            launcher=_launcher()
            launcher._run=runner
            output=workspace/"container"
            with tempfile.TemporaryDirectory(prefix="tomolab-first-party-control-") as temporary:
                stage=Path(temporary)
                receipt["runtime_manifest"]=_stage(stage)
                launch=launcher.docker_execute(image,["python","-I","/app/probe.py"],output,
                    timeout=30,repository=stage)
                raw=(output/"container.stdout.log").read_bytes()
                if len(raw)>MAX_OUTPUT_BYTES: raise ValueError("bounded control result required")
                result=json.loads(raw)
                keys(result,("schema","control_entries","external_target_calls","external_oracle_calls",
                    "source_sha256","boundary","cgroup","reasons","result_sha256"))
                if (result["schema"]!=SCHEMA or result["result_sha256"]!=digest({k:v for k,v in result.items() if k!="result_sha256"})
                    or result["source_sha256"]!=receipt["runtime_manifest"]["source_sha256"]
                    or type(result["control_entries"]) is not int or result["control_entries"]!=1
                    or type(result["external_target_calls"]) is not int or result["external_target_calls"]!=0
                    or type(result["external_oracle_calls"]) is not int or result["external_oracle_calls"]!=0):
                    raise ValueError("first-party control result identity or counters differ")
                receipt["control_entries"]=1
                if launch.get("status")!="PASS" or result["reasons"]!=[]:
                    raise PermissionError("control launch or observed runtime incomplete")
                boundary=dict(inspection=launch["inspection"],runtime=result["boundary"])
                receipt["boundary"]=_validate_boundary(boundary,expected_execution_scope=SCOPE)
                if launch["inspection"]["image_id"]!=image or tracking["container_id"]!=launch["inspection"]["container_id"]:
                    raise PermissionError("requested, created and inspected identities differ")
                receipt["cgroup"]=validate_cgroup_observation(result["cgroup"])
                receipt["status"]="PASS"
    except Exception as error:
        receipt["reasons"].append(type(error).__name__)
    finally:
        receipt["container_create_attempted"]=tracking["create_attempted"]
        receipt["container_start_attempted"]=tracking["start_attempted"]
        if receipt["daemon_available"] is True:
            receipt["cleanup"]=_cleanup(runner,tracking)
            if tracking["create_attempted"] and receipt["cleanup"]["status"]!="PASS":
                receipt["status"]="HOLD"
                receipt["reasons"].append("CLEANUP_NOT_VERIFIED")
        else:
            receipt["cleanup"]=dict(status="NOT_CREATED",reason="NO_CONTAINER_CREATE_ATTEMPT_DAEMON_UNAVAILABLE")
        receipt["cost"]["wall_seconds"]=time.perf_counter()-started
    receipt["receipt_sha256"]=digest(receipt)
    _save(workspace/"oci-probe.json",receipt)
    return receipt
