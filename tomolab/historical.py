"""Execution gate for reviewed historical capsules inside the CI container.

This verifies observed kernel/container conditions. An environment flag or
self-computed JSON digest never grants permission to execute external code.
The host launcher additionally verifies Docker's actual inspect configuration.
"""
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import tempfile


class HistoricalBoundaryError(PermissionError):
    pass


def _mounts():
    rows = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        left, right = line.split(" - ", 1)
        fields, fs = left.split(), right.split()
        point = fields[4].replace("\\040", " ").replace("\\134", "\\")
        rows.append(dict(point=point, options=fields[5].split(","), filesystem=fs[0],
                         super_options=fs[2].split(",")))
    return rows


def _effective_mount(path, mounts):
    path = str(Path(path).resolve())
    matches = [row for row in mounts if path == row["point"] or
               path.startswith(row["point"].rstrip("/")+"/")]
    if not matches:
        raise HistoricalBoundaryError("mount observation unavailable")
    return max(matches, key=lambda row: len(row["point"]))


def require_reviewed_container():
    """Fail closed before loading/calling a historical project implementation.

    The only network probe is a UDP route lookup to documentation-only address
    ranges. No datagram is sent and no external service is scanned or contacted.
    All temporary file probes use disposable owned names and remove them.
    """
    if platform.system() != "Linux" or not Path("/.dockerenv").is_file():
        raise HistoricalBoundaryError("reviewed historical execution requires the CI Docker container")
    if os.getuid() != 65534 or os.geteuid() != 65534 or os.getgid() != 65534:
        raise HistoricalBoundaryError("historical code must run as uid/gid 65534")
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    if int(status.get("CapEff", "1").strip(), 16) != 0 or status.get("NoNewPrivs", "0").strip() != "1":
        raise HistoricalBoundaryError("zero effective capabilities and no-new-privileges are required")
    mounts = _mounts()
    observed = {name: _effective_mount(name, mounts) for name in ("/", "/app", "/output", "/boundary", "/tmp")}
    if (observed["/"]["point"] != "/" or "ro" not in observed["/"]["options"]
            or observed["/app"]["point"] != "/app" or "ro" not in observed["/app"]["options"]
            or observed["/output"]["point"] != "/output" or "rw" not in observed["/output"]["options"]
            or observed["/boundary"]["point"] != "/boundary" or "ro" not in observed["/boundary"]["options"]
            or observed["/tmp"]["point"] != "/tmp" or observed["/tmp"]["filesystem"] != "tmpfs"
            or not {"rw","noexec","nosuid"} <= set(observed["/tmp"]["options"])
            or Path("/tmp").stat().st_mode & 0o7777 != 0o1777):
        raise HistoricalBoundaryError("read-only root/repository, writable output and tmpfs are required")
    try:
        context_raw = Path("/boundary/context.json").read_bytes()
        if len(context_raw) > 65536:
            raise ValueError("oversized host boundary context")
        context = json.loads(context_raw)
    except (OSError, ValueError, TypeError) as error:
        raise HistoricalBoundaryError("read-only host inspection context is required") from error
    fields = {"schema", "container_id", "image_id", "network", "read_only_root", "user",
              "cap_drop", "no_new_privileges", "pids_limit", "memory_bytes", "cpus", "binds", "tmpfs"}
    expected_binds = [dict(destination="/app",read_only=True),dict(destination="/output",read_only=False),
                      dict(destination="/boundary",read_only=True)]
    hostname=socket.gethostname()
    if (not isinstance(context,dict) or set(context)!=fields
            or context["schema"]!="tomolab-reviewed-container-context-v1"
            or not isinstance(context["container_id"],str) or len(context["container_id"])!=64
            or any(c not in "0123456789abcdef" for c in context["container_id"])
            or len(hostname) not in (12,64) or not context["container_id"].startswith(hostname)
            or not isinstance(context["image_id"],str) or not context["image_id"].startswith("sha256:")
            or len(context["image_id"])!=71 or context["network"]!="none"
            or any(c not in "0123456789abcdef" for c in context["image_id"][7:])
            or context["read_only_root"] is not True or context["user"]!="65534:65534"
            or context["cap_drop"]!=["ALL"] or context["no_new_privileges"] is not True
            or type(context["pids_limit"]) is not int or context["pids_limit"]!=64
            or type(context["memory_bytes"]) is not int or context["memory_bytes"]!=512*1024*1024
            or type(context["cpus"]) is not int or context["cpus"]!=1 or context["binds"]!=expected_binds
            or context["tmpfs"]!="/tmp:rw,noexec,nosuid,size=64m,mode=1777"):
        raise HistoricalBoundaryError("actual container and read-only host approval differ")
    if any(row["point"].startswith("/app/") and "rw" in row["options"] for row in mounts):
        raise HistoricalBoundaryError("a writable submount exposes the reviewed repository")
    interfaces = sorted(name for _, name in socket.if_nameindex())
    if interfaces != ["lo"]:
        raise HistoricalBoundaryError("the historical container may expose only loopback")
    route_probes = []
    for family, address in ((socket.AF_INET, ("192.0.2.1", 9)),
                            (socket.AF_INET6, ("2001:db8::1", 9))):
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as stream:
                stream.connect(address)
        except OSError as error:
            if error.errno not in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EAFNOSUPPORT,
                                   errno.EPROTONOSUPPORT, errno.EADDRNOTAVAIL):
                raise HistoricalBoundaryError("unexpected network probe failure") from error
            route_probes.append(dict(family="IPv4" if family == socket.AF_INET else "IPv6",
                                     outcome="NO_EXTERNAL_ROUTE", errno=error.errno, sent_bytes=0))
        else:
            raise HistoricalBoundaryError("the historical container has an external route")
    write_probes = []
    for directory in ("/output", "/tmp"):
        descriptor, name = tempfile.mkstemp(prefix="boundary-probe-", dir=directory)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(b"reviewed-container-boundary\n"); stream.flush(); os.fsync(stream.fileno())
        finally:
            Path(name).unlink()
        write_probes.append(dict(directory=directory, outcome="OWNED_PROBE_CREATED_AND_REMOVED"))
    # Verify actual kernel denial on both root and repository. These probes
    # never modify existing files; unexpected success is removed and rejected.
    for directory in ("/", "/app"):
        try:
            descriptor, name = tempfile.mkstemp(prefix="boundary-denied-", dir=directory)
        except OSError as error:
            if error.errno not in (errno.EROFS, errno.EACCES, errno.EPERM):
                raise HistoricalBoundaryError("unexpected read-only filesystem probe failure") from error
            write_probes.append(dict(directory=directory, outcome="WRITE_DENIED", errno=error.errno))
        else:
            os.close(descriptor); Path(name).unlink()
            raise HistoricalBoundaryError("the historical root or repository accepted a write")
    stable_binding={key:context[key] for key in sorted(context) if key!="schema"}
    binding_digest=hashlib.sha256(json.dumps(stable_binding,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()
    return dict(schema="tomolab-reviewed-historical-boundary-v1", status="PASS",
        operating_system="Linux", uid=os.getuid(), gid=os.getgid(), effective_capabilities=0,
        no_new_privileges=True, interfaces=interfaces, mounts=observed,
        filesystem_probes=write_probes, network_route_probes=route_probes,
        binding=stable_binding, binding_digest=binding_digest,
        sent_network_bytes=0, execution_scope="REVIEWED_FIXED_HISTORICAL_FUNCTIONS_ONLY",
        host_inspection_required=True, protection="CONTAINER_BOUNDARY_NOT_HOSTILE_HOST_PROTECTION")


if __name__ == "__main__":
    print(json.dumps(require_reviewed_container(), sort_keys=True))
