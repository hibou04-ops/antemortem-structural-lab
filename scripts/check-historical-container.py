"""Create, inspect, then execute a reviewed historical phase inside Docker.

No image is pulled automatically. The caller must first build/review the image.
Host output remains append-only/new-directory data; containers are disposable.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
MEMORY_BYTES = 512 * 1024 * 1024


def _run(arguments, *, timeout=60):
    return subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", timeout=timeout)


def _write_new(path, text):
    with path.open("x",encoding="utf-8") as stream:
        stream.write(text);stream.flush();os.fsync(stream.fileno())


def verify_inspection(value, *, image_id, repository, output, boundary):
    """Inspect authoritative Docker state before any reviewed code starts."""
    if not isinstance(value, dict):
        raise ValueError("Docker inspection object required")
    host, config = value.get("HostConfig", {}), value.get("Config", {})
    if (value.get("Image") != image_id or host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True or config.get("User") != "65534:65534"
            or set(host.get("CapDrop") or []) != {"ALL"}
            or set(host.get("SecurityOpt") or []) != {"no-new-privileges"}
            or host.get("PidsLimit") != 64 or host.get("Memory") != MEMORY_BYTES
            or host.get("NanoCpus") != 1_000_000_000):
        raise PermissionError("Docker resource/user/network/privilege boundary differs")
    mounts = value.get("Mounts", [])
    expected = {"/app": (str(repository.resolve()), False), "/output": (str(output.resolve()), True),
                "/boundary": (str(boundary.resolve()),False)}
    if len(mounts) != 3 or {row.get("Destination") for row in mounts} != set(expected):
        raise PermissionError("exactly repository RO, dedicated output RW and host context RO binds are allowed")
    for row in mounts:
        source, writable = expected[row["Destination"]]
        if row.get("Type") != "bind" or row.get("Source") != source or row.get("RW") is not writable:
            raise PermissionError("Docker bind source or access mode differs")
    temporary = host.get("Tmpfs", {})
    if set(temporary) != {"/tmp"}:
        raise PermissionError("a dedicated /tmp tmpfs is required")
    flags = set(temporary["/tmp"].split(","))
    if not {"rw", "noexec", "nosuid", "size=64m", "mode=1777"} <= flags:
        raise PermissionError("temporary filesystem restrictions differ")
    if value.get("State", {}).get("Status") != "created":
        raise PermissionError("inspection must precede the first container start")
    return dict(status="PASS", container_id=value["Id"], image_id=image_id,
        network="none", read_only_root=True, user="65534:65534", cap_drop=["ALL"],
        no_new_privileges=True, pids_limit=64, memory_bytes=MEMORY_BYTES, cpus=1,
        binds=[dict(destination=name,read_only=not writable) for name,(_,writable) in expected.items()],
        tmpfs="/tmp:rw,noexec,nosuid,size=64m,mode=1777", inspected_before_start=True)


def docker_execute(image, command, outputdir, *, timeout=900, repository=ROOT):
    """Run a caller-reviewed fixed command after inspecting the actual container."""
    if (not isinstance(image,str) or not 1<=len(image)<=256 or image.startswith("-") or any(c.isspace() for c in image)
            or not isinstance(command, (list,tuple)) or not 1<=len(command)<=64
            or any(type(arg) is not str or len(arg)>8192 or any(ord(c)<32 for c in arg) for arg in command)
            or type(timeout) is not int or not 1 <= timeout <= 1800):
        raise ValueError("a fixed argv and bounded timeout are required")
    repository = Path(repository).resolve(strict=True)
    output = Path(outputdir).resolve()
    if output == repository or repository.is_relative_to(output) or output.is_relative_to(repository/".git"):
        raise ValueError("dedicated output must not expose or replace the repository authority")
    output.mkdir(parents=True, exist_ok=False)
    # The non-root container may write only this newly created dedicated bind.
    output.chmod(0o777)
    image_result = _run(["docker","image","inspect",image,"--format","{{.Id}}"])
    image_id = image_result.stdout.strip()
    if (image_result.returncode or not image_id.startswith("sha256:") or len(image_id) != 71
            or any(c not in "0123456789abcdef" for c in image_id[7:])):
        raise RuntimeError("reviewed Docker image unavailable; no automatic pull or weaker fallback")
    name = "tomolab-historical-"+uuid.uuid4().hex
    boundary_temp=tempfile.TemporaryDirectory(prefix="tomolab-boundary-context-")
    boundary=Path(boundary_temp.name).resolve()
    boundary.chmod(0o755)
    create = ["docker","create","--name",name,"--network=none","--read-only",
        "--cap-drop=ALL","--security-opt=no-new-privileges","--user=65534:65534",
        "--pids-limit=64","--memory=512m","--cpus=1",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=64m,mode=1777","--workdir=/app",
        "--mount",f"type=bind,src={repository},dst=/app,readonly",
        "--mount",f"type=bind,src={output},dst=/output",
        "--mount",f"type=bind,src={boundary},dst=/boundary,readonly",
        "--env","PYTHONDONTWRITEBYTECODE=1","--env","TMPDIR=/tmp",
        "--env","HYPOTHESIS_STORAGE_DIRECTORY=/tmp/.hypothesis",image_id,*command]
    started=time.perf_counter(); inspection=None; completed=None
    try:
        created=_run(create)
        if created.returncode:
            raise RuntimeError("Docker create failed: "+created.stderr[-2000:])
        raw=_run(["docker","inspect",name])
        if raw.returncode:
            raise RuntimeError("Docker inspection failed before start")
        objects=json.loads(raw.stdout)
        if not isinstance(objects,list) or len(objects)!=1:
            raise RuntimeError("one Docker inspection object required")
        inspection=verify_inspection(objects[0],image_id=image_id,repository=repository,output=output,boundary=boundary)
        context={key:inspection[key] for key in ("container_id","image_id","network","read_only_root","user",
            "cap_drop","no_new_privileges","pids_limit","memory_bytes","cpus","binds","tmpfs")}
        context["schema"]="tomolab-reviewed-container-context-v1"
        context_path=boundary/"context.json"
        with context_path.open("x",encoding="utf-8") as stream:
            json.dump(context,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        context_path.chmod(0o444)
        with (output/"host-inspection.json").open("x",encoding="utf-8") as stream:
            json.dump(inspection,stream,indent=2);stream.flush();os.fsync(stream.fileno())
        try:
            completed=_run(["docker","start","--attach",name],timeout=timeout)
        except subprocess.TimeoutExpired as error:
            def decoded(value):
                return value.decode("utf-8",errors="replace") if isinstance(value,bytes) else value or ""
            _write_new(output/"container.stdout.log",decoded(error.stdout))
            _write_new(output/"container.stderr.log",decoded(error.stderr))
            _write_new(output/"container-launch.json",json.dumps(dict(
                schema="tomolab-historical-container-launch-v1",status="FAILED_TIMEOUT",
                inspection=inspection,wall_seconds=time.perf_counter()-started,
                timeout_seconds=timeout,automatic_retries=0,host_command=command,
                partial_phase_output_retained=True,cleanup="FORCE_REMOVE_DISPOSABLE_CONTAINER"),indent=2))
            raise RuntimeError("reviewed historical phase timed out; retained output and no retry") from error
        _write_new(output/"container.stdout.log",completed.stdout)
        _write_new(output/"container.stderr.log",completed.stderr)
        state=_run(["docker","inspect",name])
        final=json.loads(state.stdout)[0] if state.returncode==0 else {}
        code=final.get("State",{}).get("ExitCode")
        receipt=dict(schema="tomolab-historical-container-launch-v1",status="PASS" if completed.returncode==0 and code==0 else "FAILED",
            inspection=inspection,process_exit=completed.returncode,container_exit=code,
            oom_killed=final.get("State",{}).get("OOMKilled"),wall_seconds=time.perf_counter()-started,
            automatic_retries=0,host_command=command)
        with (output/"container-launch.json").open("x",encoding="utf-8") as stream:
            json.dump(receipt,stream,indent=2);stream.flush();os.fsync(stream.fileno())
        if receipt["status"] != "PASS":
            raise RuntimeError("reviewed historical phase failed; retained output and no retry")
        return receipt
    finally:
        _run(["docker","rm","--force",name],timeout=30)
        boundary_temp.cleanup()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image",required=True)
    parser.add_argument("--output-directory",type=Path,required=True)
    parser.add_argument("--timeout",type=int,default=900)
    parser.add_argument("--phase",choices=("preflight","study","wheel"))
    parser.add_argument("command",nargs=argparse.REMAINDER)
    args=parser.parse_args()
    command=args.command[1:] if args.command[:1]==["--"] else args.command
    if args.phase:
        if command:
            parser.error("choose a reviewed phase or an explicit reviewed argv, not both")
        command=(["python","-I","/app/scripts/check-historical-wheel.py","--output","/output/installed.json"]
                 if args.phase=="wheel" else ["python","-I","/app/scripts/run-historical-study.py",
                     "--phase",args.phase,"--output-directory","/output"])
    print(json.dumps(docker_execute(args.image,command,args.output_directory,timeout=args.timeout),indent=2))


if __name__=="__main__":
    main()
