"""Reviewed external execution through fresh, inspected OCI containers only.

The host stages bytes and parses JSON; it never imports upstream code. The
existing historical launcher is reused with bounded host-side CLI capture.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sysconfig
import tempfile
import threading
import time
import uuid

from .online_observe import _equal
from .online_schema import input_identity, validate_input
from .schema import canonical, digest, keys
from .harvester_review import validate_review_bundle, _sha

MAX_SOURCE_BYTES = 256 * 1024
MAX_OUTPUT_BYTES = 256 * 1024
BUNDLE_SCHEMA = "tomolab-harvester-source-bundle-v1"
EXECUTION_SCHEMA = "tomolab-harvester-execution-v1"
REPRODUCTION_SCHEMA = "tomolab-harvester-reproduction-v1"
VARIANTS = ("buggy", "fixed", "oracle")
FILE_NAMES = ("buggy", "fixed", "oracle", "reset")
RUNTIME_FILES = ("historical.py", "discovery/schema.py", "discovery/online_schema.py", "discovery/online_observe.py")


class ExecutionOutputLimit(RuntimeError):
    def __init__(self, message, output=b"", stderr=b""):
        super().__init__(message)
        self.output,self.stderr = output,stderr


def _source(value):
    if type(value) is bytes:
        value = value.decode("utf-8")
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= MAX_SOURCE_BYTES:
        raise ValueError("bounded source bytes required")
    return value


def _function(value):
    if type(value) is not str or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value) is None:
        raise ValueError("one explicit callable export identifier required")
    return value


def make_source_bundle(buggy_source, fixed_source, oracle_source, reset_source, *,
                       buggy_function="implementation", fixed_function="implementation",
                       oracle_function="reference", reset_function="reset"):
    files = {}
    for name, source, fn in zip(FILE_NAMES, (buggy_source, fixed_source, oracle_source, reset_source),
                              (buggy_function, fixed_function, oracle_function, reset_function)):
        text = _source(source)
        files[name] = dict(source=text, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), function=_function(fn))
    value = dict(schema=BUNDLE_SCHEMA, files=files)
    value["bundle_digest"] = digest(value)
    return validate_source_bundle(value)


def validate_source_bundle(bundle, *, review=None):
    keys(bundle, ("schema", "files", "bundle_digest"))
    if bundle["schema"] != BUNDLE_SCHEMA:
        raise ValueError("unsupported external source bundle")
    keys(bundle["files"], FILE_NAMES)
    for name, row in bundle["files"].items():
        keys(row, ("source", "sha256", "function"))
        _source(row["source"]); _function(row["function"]); _sha(row["sha256"])
        if hashlib.sha256(row["source"].encode("utf-8")).hexdigest() != row["sha256"]:
            raise ValueError("external source bundle hash mismatch")
    if bundle["bundle_digest"] != digest({k:v for k,v in bundle.items() if k != "bundle_digest"}):
        raise ValueError("external source bundle content digest mismatch")
    if review is not None:
        expected = dict(buggy=review["implementation_sha256"], fixed=review["fixed_implementation_sha256"],
                        oracle=review["oracle_sha256"], reset=review["reset_adapter_sha256"])
        if any(bundle["files"][name]["sha256"] != expected[name] for name in FILE_NAMES):
            raise ValueError("source bundle does not match reviewed implementation/Oracle/reset")
        if any(bundle["files"][name]["function"] != review["exports"][name] for name in FILE_NAMES):
            raise ValueError("source bundle callable exports differ from the reviewed semantics")
    return deepcopy(bundle)


def _bounded_run(arguments, *, timeout=60):
    """Bound both stdout and stderr before allocation can grow without limit."""
    process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    messages = queue.Queue(maxsize=16)
    stopped = threading.Event()
    def send(value):
        while not stopped.is_set():
            try:
                messages.put(value,timeout=0.1)
                return
            except queue.Full:
                continue
    def reader(stream, channel):
        try:
            while True:
                block = stream.read(8192)
                if not block:
                    break
                send((channel, block))
                if stopped.is_set():
                    break
        finally:
            send((channel, None))
            stream.close()
    threads = [threading.Thread(target=reader, args=(stream, channel), daemon=True)
               for stream, channel in ((process.stdout, "stdout"), (process.stderr, "stderr"))]
    for thread in threads:
        thread.start()
    blocks, total, done = dict(stdout=[], stderr=[]), 0, 0
    started = time.monotonic()
    try:
        while done < 2:
            remaining = timeout - (time.monotonic()-started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(arguments, timeout,
                    output=b"".join(blocks["stdout"]), stderr=b"".join(blocks["stderr"]))
            try:
                channel, block = messages.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue
            if block is None:
                done += 1
                continue
            total += len(block)
            if total > MAX_OUTPUT_BYTES:
                raise ExecutionOutputLimit("bounded Docker CLI output limit exceeded",
                    output=b"".join(blocks["stdout"]),stderr=b"".join(blocks["stderr"]))
            blocks[channel].append(block)
        code = process.wait(timeout=max(0.01, timeout-(time.monotonic()-started)))
        return subprocess.CompletedProcess(arguments, code,
            b"".join(blocks["stdout"]).decode("utf-8", errors="replace"),
            b"".join(blocks["stderr"]).decode("utf-8", errors="replace"))
    finally:
        stopped.set()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=1)


def _launcher():
    root = Path(__file__).resolve().parents[2]
    source = root / "scripts/check-historical-container.py"
    installed = Path(sysconfig.get_path("data")) / "share/antemortem-structural-lab/scripts/check-historical-container.py"
    path = source if source.is_file() else installed
    if not path.is_file():
        raise RuntimeError("reviewed OCI launcher is unavailable; no host fallback")
    # Only a bundled first-party launcher is imported, never a harvested file.
    spec = importlib.util.spec_from_file_location("_tomolab_harvester_launcher_"+uuid.uuid4().hex, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._run = _bounded_run
    return module


RUNNER = r'''"""Fixed first-party entry point; all external imports remain inside OCI."""
import contextlib
import hashlib
import importlib.util
import inspect
import io
import json
from pathlib import Path
import sys
sys.path.insert(0, "/app/runtime")
from tomolab.historical import require_reviewed_container
from tomolab.discovery.online_observe import _capture
from tomolab.discovery.schema import digest

class BoundedText(io.StringIO):
    def write(self, value):
        if self.tell()+len(value) > 16384:
            raise OSError("external diagnostic output exceeded bound")
        return super().write(value)

def load(row, name):
    path = Path("/app/sources")/(name+".py")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise ValueError("external bytes differ from reviewed source")
    spec = importlib.util.spec_from_file_location("harvest_"+name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    fn = getattr(module, row["function"])
    if not inspect.isfunction(fn) or inspect.iscoroutinefunction(fn) or inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn):
        raise ValueError("one reviewed synchronous non-generator function required")
    return fn

request = json.loads(Path("/app/request.json").read_text(encoding="utf-8"))
boundary = require_reviewed_container()
boundary["execution_scope"] = "REVIEWED_HARVESTER_FUNCTIONS_ONLY"
variant = request["variant"]
entered = reset_calls = 0
reset_success = False
capture = None
diagnostics = BoundedText()
try:
    with contextlib.redirect_stdout(diagnostics), contextlib.redirect_stderr(diagnostics):
        fn = load(request["files"][variant], variant)
        reset = load(request["files"]["reset"], "reset")
        reset_calls = 1
        reset_success = reset() is True
        if reset_success:
            entered = 1
            capture, _, _ = _capture(fn, request["input"], tracing=False)
        else:
            capture = dict(kind="unknown", reason="RESET_NOT_VERIFIED")
except BaseException as error:
    capture = dict(kind="execution_error", exception_type=type(error).__module__+"."+type(error).__qualname__)
result = dict(schema="tomolab-harvester-container-result-v1", variant=variant,
    input_digest=request["input_digest"], selected_sha256=request["files"][variant]["sha256"],
    reset_sha256=request["files"]["reset"]["sha256"], reset_success=reset_success,
    external_entry_count=entered, external_reset_calls=reset_calls, capture=capture,
    semantic_digest=digest(capture), boundary=boundary,
    diagnostic_output_sha256=hashlib.sha256(diagnostics.getvalue().encode()).hexdigest())
print(json.dumps(result, ensure_ascii=True, allow_nan=False, separators=(",", ":")))
'''


def _stage(path, bundle, point, variant):
    runtime = path / "runtime/tomolab"
    (runtime / "discovery").mkdir(parents=True)
    (runtime / "__init__.py").write_text("", encoding="utf-8")
    (runtime / "discovery/__init__.py").write_text("", encoding="utf-8")
    package = Path(__file__).resolve().parents[1]
    manifest = {}
    for relative in RUNTIME_FILES:
        raw = (package / relative).read_bytes()
        (runtime / relative).write_bytes(raw)
        manifest[relative] = hashlib.sha256(raw).hexdigest()
    manifest["runner.py"] = hashlib.sha256(RUNNER.encode("utf-8")).hexdigest()
    sources = path / "sources"
    sources.mkdir()
    for name, row in bundle["files"].items():
        (sources / (name+".py")).write_bytes(row["source"].encode("utf-8"))
    (path / "runner.py").write_text(RUNNER, encoding="utf-8", newline="\n")
    request = dict(schema="tomolab-harvester-container-request-v1", variant=variant,
        input=deepcopy(point), input_digest=input_identity(point),
        files={name:{key:row[key] for key in ("sha256", "function")} for name,row in bundle["files"].items()})
    (path / "request.json").write_text(canonical(request)+"\n", encoding="utf-8", newline="\n")
    return digest(manifest)


def _save(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical(value)+"\n"); stream.flush(); os.fsync(stream.fileno())


def _validate_boundary(boundary):
    if type(boundary) is not dict or set(boundary) != {"inspection","runtime"}:
        raise PermissionError("one host inspection and observed runtime boundary required")
    inspection,runtime = boundary["inspection"],boundary["runtime"]
    if type(inspection) is not dict or type(runtime) is not dict:
        raise PermissionError("actual OCI boundary data required")
    expected = dict(network="none",read_only_root=True,user="65534:65534",cap_drop=["ALL"],
        no_new_privileges=True,pids_limit=64,memory_bytes=512*1024*1024,cpus=1,
        binds=[dict(destination="/app",read_only=True),dict(destination="/output",read_only=False),
               dict(destination="/boundary",read_only=True)],
        tmpfs="/tmp:rw,noexec,nosuid,size=64m,mode=1777")
    keys(inspection,set(expected)|{"status","container_id","image_id","inspected_before_start"})
    keys(runtime,("schema","status","operating_system","uid","gid","effective_capabilities",
        "no_new_privileges","interfaces","mounts","filesystem_probes","network_route_probes","binding",
        "binding_digest","sent_network_bytes","execution_scope","host_inspection_required","protection"))
    if len(canonical(boundary).encode()) > 65536:
        raise PermissionError("bounded actual OCI inspection receipt required")
    if inspection.get("status") != "PASS" or inspection.get("inspected_before_start") is not True:
        raise PermissionError("host must inspect the fresh container before first start")
    for name,value in expected.items():
        if inspection.get(name) != value or type(inspection.get(name)) is not type(value):
            raise PermissionError("actual inspected OCI controls differ")
    container_id,image_id = inspection.get("container_id"),inspection.get("image_id")
    if type(container_id) is not str or re.fullmatch("[a-f0-9]{64}",container_id) is None or type(image_id) is not str or re.fullmatch("sha256:[a-f0-9]{64}",image_id) is None:
        raise PermissionError("exact OCI container/image identities required")
    binding = dict(expected,container_id=container_id,image_id=image_id)
    if (runtime.get("schema") != "tomolab-reviewed-historical-boundary-v1" or runtime.get("status") != "PASS"
            or runtime.get("protection") != "CONTAINER_BOUNDARY_NOT_HOSTILE_HOST_PROTECTION"
            or runtime.get("operating_system") != "Linux" or runtime.get("uid") != 65534 or runtime.get("gid") != 65534
            or runtime.get("effective_capabilities") != 0 or runtime.get("no_new_privileges") is not True
            or runtime.get("interfaces") != ["lo"] or runtime.get("sent_network_bytes") != 0
            or runtime.get("execution_scope") != "REVIEWED_HARVESTER_FUNCTIONS_ONLY"
            or runtime.get("host_inspection_required") is not True
            or runtime.get("binding") != binding or runtime.get("binding_digest") != digest(binding)):
        raise PermissionError("runtime kernel boundary and host inspection must agree")
    for name in ("uid","gid","effective_capabilities","sent_network_bytes"):
        if type(runtime[name]) is not int:
            raise PermissionError("kernel observations require exact integer types")
    mounts = runtime["mounts"]
    expected_mounts = {"/":"ro","/app":"ro","/boundary":"ro","/output":"rw","/tmp":"rw"}
    keys(mounts,expected_mounts)
    for point,mode in expected_mounts.items():
        row = mounts[point]
        keys(row,("point","options","filesystem","super_options"))
        if row["point"] != point or type(row["filesystem"]) is not str or not 1 <= len(row["filesystem"]) <= 256:
            raise PermissionError("observed kernel mount identity differs")
        for name in ("options","super_options"):
            if type(row[name]) is not list or len(row[name]) > 64 or any(type(v) is not str or len(v)>512 for v in row[name]):
                raise PermissionError("bounded actual kernel mount options required")
        if mode not in row["options"]:
            raise PermissionError("observed kernel mount access differs")
    if mounts["/tmp"]["filesystem"] != "tmpfs" or not {"rw","noexec","nosuid"} <= set(mounts["/tmp"]["options"]):
        raise PermissionError("observed temporary filesystem differs")
    probes = runtime["network_route_probes"]
    if type(probes) is not list or len(probes)!=2 or {row.get("family") for row in probes if type(row) is dict} != {"IPv4","IPv6"}:
        raise PermissionError("both actual no-route network probes required")
    for row in probes:
        keys(row,("family","outcome","errno","sent_bytes"))
        if row["outcome"] != "NO_EXTERNAL_ROUTE" or type(row["errno"]) is not int or row["errno"] <= 0 or type(row["sent_bytes"]) is not int or row["sent_bytes"] != 0:
            raise PermissionError("observed network route was not blocked")
    writes = runtime["filesystem_probes"]
    if type(writes) is not list or len(writes) != 4:
        raise PermissionError("actual permitted and denied filesystem probes required")
    by_directory = {row.get("directory"):row for row in writes if type(row) is dict}
    if set(by_directory) != {"/output","/tmp","/","/app"}:
        raise PermissionError("filesystem probes omit a protected or writable authority")
    for point,row in by_directory.items():
        if point in ("/output","/tmp"):
            keys(row,("directory","outcome"))
            if row["outcome"] != "OWNED_PROBE_CREATED_AND_REMOVED":
                raise PermissionError("output/tmp writable probe failed")
        else:
            keys(row,("directory","outcome","errno"))
            if row["outcome"] != "WRITE_DENIED" or type(row["errno"]) is not int or row["errno"] <= 0:
                raise PermissionError("protected filesystem write was not denied")
    return deepcopy(boundary)


def execute_reviewed_case(candidate, review, source_bundle, *, variant, input, image,
                          output_directory, allow_external_execution=False, trusted_review=False,
                          timeout=30):
    if allow_external_execution is not True or trusted_review is not True:
        raise PermissionError("explicit external execution opt-in and accountable review required")
    review = validate_review_bundle(candidate, review)
    bundle = validate_source_bundle(source_bundle, review=review)
    if variant not in VARIANTS or not validate_input(input, review["contract"]):
        raise ValueError("reviewed variant and input contract required")
    if type(timeout) is not int or not 1 <= timeout <= 90:
        raise ValueError("external call timeout must be in [1,90] seconds")
    output = Path(output_directory).resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError("external execution output must be a fresh path")
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    receipt = dict(schema=EXECUTION_SCHEMA, candidate_id=candidate["candidate_id"],
        metadata_digest=candidate["metadata_digest"], review_digest=review["review_digest"],
        bundle_digest=bundle["bundle_digest"], variant=variant, input=deepcopy(input), input_digest=input_identity(input),
        selected_sha256=bundle["files"][variant]["sha256"], oracle_sha256=review["oracle_sha256"],
        reset_sha256=review["reset_adapter_sha256"], status="HOLD_EXECUTION", reasons=[],
        capture=None, semantic_digest=None, reset_success=False, external_target_calls=0,
        external_oracle_calls=0, external_reset_calls=0, call_count_status="NO_EXTERNAL_ENTRY_VERIFIED",
        boundary=None, runtime_digest=None, cost=dict(wall_seconds=0.0),
        host_external_code_imported=False, fresh_container_per_call=True)
    try:
        launcher = _launcher()
        with tempfile.TemporaryDirectory(prefix="tomolab-harvester-minimal-") as temporary:
            staging = Path(temporary)
            receipt["runtime_digest"] = _stage(staging, bundle, input, variant)
            launch = launcher.docker_execute(image,
                ["python", "-I", "/app/runner.py"], output, timeout=timeout, repository=staging)
            raw = (output / "container.stdout.log").read_bytes()
            if len(raw) > MAX_OUTPUT_BYTES:
                raise ExecutionOutputLimit("external result exceeds protocol ceiling")
            result = json.loads(raw)
            keys(result, ("schema", "variant", "input_digest", "selected_sha256", "reset_sha256",
                "reset_success", "external_entry_count", "external_reset_calls", "capture", "semantic_digest",
                "boundary", "diagnostic_output_sha256"))
            if result["schema"] != "tomolab-harvester-container-result-v1" or result["variant"] != variant or result["input_digest"] != receipt["input_digest"] or result["selected_sha256"] != receipt["selected_sha256"] or result["reset_sha256"] != receipt["reset_sha256"]:
                raise ValueError("external result differs from reviewed request")
            if launch.get("status") != "PASS" or launch.get("inspection",{}).get("inspected_before_start") is not True or result["boundary"].get("status") != "PASS" or result["boundary"].get("protection") != "CONTAINER_BOUNDARY_NOT_HOSTILE_HOST_PROTECTION":
                raise PermissionError("actual inspected OCI boundary is required")
            _validate_boundary(dict(inspection=launch["inspection"],runtime=result["boundary"]))
            if type(result["external_entry_count"]) is not int or not 0 <= result["external_entry_count"] <= 1 or type(result["external_reset_calls"]) is not int or not 0 <= result["external_reset_calls"] <= 1 or type(result["reset_success"]) is not bool:
                raise ValueError("actual external entry counters required")
            if result["semantic_digest"] != digest(result["capture"]):
                raise ValueError("external semantic result digest mismatch")
            _validate_capture(result["capture"])
            receipt.update(status="COMPLETE", capture=result["capture"], semantic_digest=result["semantic_digest"],
                reset_success=result["reset_success"], external_target_calls=result["external_entry_count"] if variant != "oracle" else 0,
                external_oracle_calls=result["external_entry_count"] if variant == "oracle" else 0,
                external_reset_calls=result["external_reset_calls"], call_count_status="ACTUAL_CONTAINER_ENTRY_COUNTERS",
                boundary=dict(inspection=launch["inspection"], runtime=result["boundary"]))
            if not receipt["reset_success"] or receipt["capture"]["kind"] in ("execution_error", "unknown"):
                receipt["status"] = "HOLD_EXECUTION"
                receipt["reasons"] = ["RESET_OR_EXTERNAL_EXECUTION_UNRESOLVED"]
    except (Exception, subprocess.TimeoutExpired) as error:
        output.mkdir(exist_ok=True)
        receipt["reasons"] = [type(error).__name__]
        if isinstance(error,(ExecutionOutputLimit,subprocess.TimeoutExpired)):
            for name,value in (("partial.stdout.log",getattr(error,"output",None)),("partial.stderr.log",getattr(error,"stderr",None))):
                if value is not None:
                    raw = value if isinstance(value,bytes) else value.encode("utf-8",errors="replace")
                    with (output/name).open("xb") as stream:
                        stream.write(raw[:MAX_OUTPUT_BYTES]);stream.flush();os.fsync(stream.fileno())
        # A started container may have entered code before timeout/protocol loss.
        # Never replace that uncertainty with zero actual function calls.
        if (output / "host-inspection.json").is_file():
            receipt.update(external_target_calls=None, external_oracle_calls=None, external_reset_calls=None,
                           call_count_status="UNKNOWN_AFTER_CONTAINER_START")
    receipt["cost"]["wall_seconds"] = time.perf_counter()-started
    receipt["sha256"] = digest(receipt)
    _save(output / "harvester-execution.json", receipt)
    return validate_execution_receipt(candidate, review, receipt)


def _validate_capture(capture):
    if type(capture) is not dict or capture.get("kind") not in ("return", "exception", "execution_error", "unknown"):
        raise ValueError("bounded typed external capture required")
    if len(canonical(capture).encode()) > 128 * 1024:
        raise ValueError("external capture exceeds bound")
    if capture["kind"] == "return":
        keys(capture, ("kind", "value"))
        _unsnapshot(capture["value"])
    elif capture["kind"] in ("exception", "execution_error"):
        keys(capture, ("kind", "exception_type"))
        if type(capture["exception_type"]) is not str or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,199}", capture["exception_type"]) is None:
            raise ValueError("bounded external exception identity required")
    else:
        keys(capture, ("kind", "reason"))
        if type(capture["reason"]) is not str or not 1 <= len(capture["reason"]) <= 200:
            raise ValueError("explicit unresolved external reason required")


def _unsnapshot(value, depth=0):
    if depth > 8:
        raise ValueError("external output nesting exceeds bound")
    keys(value, ("type", "value"))
    kind, item = value["type"], value["value"]
    if kind == "none" and item is None:
        return None
    if kind in ("bool", "int", "str") and type(item).__name__ == kind:
        if kind == "str" and len(item) > 65536 or kind == "int" and item.bit_length() > 4096:
            raise ValueError("external scalar output exceeds bound")
        return item
    if kind == "float":
        if type(item) is float and math.isfinite(item):
            return item
        if item in ("NAN", "POS_INF", "NEG_INF"):
            return dict(NAN=math.nan, POS_INF=math.inf, NEG_INF=-math.inf)[item]
    if kind in ("list", "tuple") and type(item) is list and len(item) <= 4096:
        result = [_unsnapshot(row, depth+1) for row in item]
        return tuple(result) if kind == "tuple" else result
    if kind == "dict" and type(item) is dict and len(item) <= 4096 and all(type(key) is str for key in item):
        return {key:_unsnapshot(row, depth+1) for key,row in item.items()}
    raise ValueError("unsupported external JSON output capture")


def validate_execution_receipt(candidate, review, receipt):
    validate_review_bundle(candidate, review)
    fields = ("schema", "candidate_id", "metadata_digest", "review_digest", "bundle_digest", "variant", "input",
        "input_digest", "selected_sha256", "oracle_sha256", "reset_sha256", "status", "reasons", "capture",
        "semantic_digest", "reset_success", "external_target_calls", "external_oracle_calls", "external_reset_calls",
        "call_count_status", "boundary", "runtime_digest", "cost", "host_external_code_imported", "fresh_container_per_call", "sha256")
    keys(receipt, fields)
    if receipt["schema"] != EXECUTION_SCHEMA or receipt["candidate_id"] != candidate["candidate_id"] or receipt["metadata_digest"] != candidate["metadata_digest"] or receipt["review_digest"] != review["review_digest"]:
        raise ValueError("external execution receipt identity mismatch")
    if receipt["host_external_code_imported"] is not False or receipt["fresh_container_per_call"] is not True:
        raise PermissionError("external code may execute only in a fresh OCI container")
    if receipt["variant"] not in VARIANTS or receipt["input_digest"] != input_identity(receipt["input"]) or not validate_input(receipt["input"], review["contract"]):
        raise ValueError("external variant/input identity mismatch")
    expected = dict(buggy=review["implementation_sha256"], fixed=review["fixed_implementation_sha256"], oracle=review["oracle_sha256"])
    if receipt["selected_sha256"] != expected[receipt["variant"]] or receipt["oracle_sha256"] != review["oracle_sha256"] or receipt["reset_sha256"] != review["reset_adapter_sha256"]:
        raise ValueError("external reviewed implementation/Oracle/reset identity mismatch")
    _sha(receipt["bundle_digest"])
    if receipt["runtime_digest"] is not None:
        _sha(receipt["runtime_digest"])
    if receipt["status"] not in ("COMPLETE", "HOLD_EXECUTION") or type(receipt["reset_success"]) is not bool:
        raise ValueError("invalid external execution status")
    for name in ("external_target_calls", "external_oracle_calls", "external_reset_calls"):
        if receipt[name] is not None and (type(receipt[name]) is not int or not 0 <= receipt[name] <= 1):
            raise ValueError("bounded actual external counters required")
    if receipt["capture"] is not None:
        _validate_capture(receipt["capture"])
        if receipt["semantic_digest"] != digest(receipt["capture"]):
            raise ValueError("external capture digest mismatch")
    elif receipt["semantic_digest"] is not None:
        raise ValueError("missing external capture cannot have semantic identity")
    if receipt["status"] == "COMPLETE":
        _sha(receipt["runtime_digest"])
        if receipt["call_count_status"] != "ACTUAL_CONTAINER_ENTRY_COUNTERS" or receipt["reset_success"] is not True or receipt["capture"] is None or receipt["capture"]["kind"] not in ("return", "exception"):
            raise ValueError("complete external call lacks actual reset/capture/counter evidence")
        target, oracle = (0,1) if receipt["variant"] == "oracle" else (1,0)
        if (receipt["external_target_calls"],receipt["external_oracle_calls"],receipt["external_reset_calls"]) != (target,oracle,1):
            raise ValueError("complete external call must execute exactly its selected callable once")
        _validate_boundary(receipt["boundary"])
    if type(receipt["reasons"]) is not list or len(receipt["reasons"]) > 16 or any(type(v) is not str or len(v) > 200 for v in receipt["reasons"]):
        raise ValueError("bounded explicit execution hold reasons required")
    keys(receipt["cost"], ("wall_seconds",))
    seconds = receipt["cost"]["wall_seconds"]
    if type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("actual external wall time required")
    if receipt["sha256"] != digest({k:v for k,v in receipt.items() if k != "sha256"}):
        raise ValueError("external execution receipt digest mismatch")
    return deepcopy(receipt)


def _comparison(target, oracle, contract):
    if target["kind"] in ("execution_error", "unknown") or oracle["kind"] in ("execution_error", "unknown"):
        return "UNKNOWN"
    comparison = contract.get("comparison", {})
    if oracle["kind"] == "exception" and oracle["exception_type"] not in comparison.get("expected_exceptions", []):
        return "UNKNOWN"
    if target["kind"] == oracle["kind"] == "return":
        return "PASS" if _equal(target["value"], oracle["value"], comparison) else "FAILURE"
    if target["kind"] == oracle["kind"] == "exception" and comparison.get("exception_policy", "match_type") == "match_type":
        return "PASS" if target["exception_type"] == oracle["exception_type"] else "FAILURE"
    return "FAILURE"


def make_reproduction_receipt(candidate, review, buggy_receipts, fixed_receipts):
    """Each repeat is {target: single-call receipt, oracle: single-call receipt}."""
    review = validate_review_bundle(candidate, review)
    value = dict(schema=REPRODUCTION_SCHEMA, candidate_id=candidate["candidate_id"],
        metadata_digest=candidate["metadata_digest"], review_digest=review["review_digest"],
        buggy=deepcopy(buggy_receipts), fixed=deepcopy(fixed_receipts), status="HOLD_EXECUTION", reasons=[],
        external_target_calls=0, external_oracle_calls=0, external_reset_calls=0,
        unknown_external_call_records=0, wall_seconds=0.0)
    derived = _derive_reproduction(candidate, review, value)
    value.update(derived)
    value["sha256"] = digest(value)
    return validate_reproduction_receipt(candidate, review, value)


def _derive_reproduction(candidate, review, receipt):
    reasons, points, environments = [], set(), set()
    seen_receipts,seen_containers = set(),set()
    counts = dict(external_target_calls=0, external_oracle_calls=0, external_reset_calls=0,
                  unknown_external_call_records=0, wall_seconds=0.0)
    for branch, expected_variant, expected_status in (("buggy","buggy","FAILURE"),("fixed","fixed","PASS")):
        repeats = receipt[branch]
        if type(repeats) is not list or len(repeats) > 3:
            raise ValueError("at most three actual reproduction repeats required")
        if len(repeats) != 3:
            reasons.append("INCOMPLETE_"+branch.upper()+"_REPETITION")
        semantics = []
        for repeat in repeats:
            keys(repeat, ("target", "oracle"))
            target = validate_execution_receipt(candidate, review, repeat["target"])
            oracle = validate_execution_receipt(candidate, review, repeat["oracle"])
            if target["variant"] != expected_variant or oracle["variant"] != "oracle" or target["input_digest"] != oracle["input_digest"]:
                raise ValueError("reproduction branch or corresponding input identity mismatch")
            points.add(target["input_digest"])
            for record in (target,oracle):
                if record["sha256"] in seen_receipts:
                    reasons.append("DUPLICATE_EXTERNAL_CALL_RECEIPT")
                    continue
                seen_receipts.add(record["sha256"])
                if record["status"] == "COMPLETE":
                    container_id = record["boundary"]["inspection"]["container_id"]
                    if container_id in seen_containers:
                        reasons.append("REUSED_CONTAINER_CANNOT_PROVE_FRESH_REPETITION")
                        counts["unknown_external_call_records"] += 1
                        continue
                    seen_containers.add(container_id)
                    environments.add((record["bundle_digest"],record["runtime_digest"],record["boundary"]["inspection"]["image_id"]))
                if any(record[name] is None for name in ("external_target_calls", "external_oracle_calls", "external_reset_calls")):
                    counts["unknown_external_call_records"] += 1
                for name in ("external_target_calls", "external_oracle_calls", "external_reset_calls"):
                    if record[name] is not None:
                        counts[name] += record[name]
                counts["wall_seconds"] += record["cost"]["wall_seconds"]
            if target["status"] != "COMPLETE" or oracle["status"] != "COMPLETE":
                reasons.append("EXTERNAL_EXECUTION_UNRESOLVED")
                continue
            if _comparison(target["capture"],oracle["capture"],review["contract"]) != expected_status:
                reasons.append("BUGGY_FAILURE_FIXED_PASS_NOT_REPRODUCED")
            semantics.append((target["semantic_digest"],oracle["semantic_digest"]))
        if len(semantics) != 3 or len(set(semantics)) != 1:
            reasons.append("REPETITION_SEMANTICS_NOT_EXACTLY_REPRODUCIBLE")
    if len(points) != 1:
        reasons.append("BUGGY_FIXED_REPRODUCTION_INPUT_MISMATCH")
    if len(environments) != 1:
        reasons.append("FROZEN_BUNDLE_RUNTIME_IMAGE_IDENTITY_MISMATCH")
    return dict(counts, status="REPRODUCED" if not reasons else "HOLD_EXECUTION", reasons=sorted(set(reasons)))


def validate_reproduction_receipt(candidate, review, receipt):
    keys(receipt, ("schema", "candidate_id", "metadata_digest", "review_digest", "buggy", "fixed", "status", "reasons",
        "external_target_calls", "external_oracle_calls", "external_reset_calls", "unknown_external_call_records", "wall_seconds", "sha256"))
    if receipt["schema"] != REPRODUCTION_SCHEMA or receipt["candidate_id"] != candidate["candidate_id"] or receipt["metadata_digest"] != candidate["metadata_digest"] or receipt["review_digest"] != review["review_digest"]:
        raise ValueError("reproduction receipt identity mismatch")
    derived = _derive_reproduction(candidate, review, receipt)
    if any(receipt[key] != value for key,value in derived.items()):
        raise ValueError("reproduction status or costs differ from actual call evidence")
    if receipt["sha256"] != digest({k:v for k,v in receipt.items() if k != "sha256"}):
        raise ValueError("reproduction receipt content digest mismatch")
    return deepcopy(receipt)


class OCIReviewedCallable:
    """One wrapper entry -> one fresh container -> one selected external call."""
    def __init__(self, candidate, review, source_bundle, *, variant, image, workspace,
                 allow_external_execution=False, trusted_review=False, timeout=30):
        self.candidate = deepcopy(candidate)
        self.review = validate_review_bundle(candidate, review)
        self.bundle = validate_source_bundle(source_bundle, review=review)
        if variant not in VARIANTS:
            raise ValueError("one reviewed external callable variant required")
        self.variant, self.image, self.workspace = variant, image, Path(workspace)
        self.allowed, self.trusted, self.timeout = allow_external_execution, trusted_review, timeout
        self.ledger = dict(wrapper_entries=0, container_attempts=0, external_target_calls=0,
            external_oracle_calls=0, external_reset_calls=0, unresolved_call_receipts=0, wall_seconds=0.0, receipts=[])

    def reset(self):
        # No external code lives on the host. Each __call__ starts a new
        # inspected container, and its reviewed reset executes INSIDE it.
        return self.allowed is True and self.trusted is True

    def __call__(self, point):
        self.ledger["wrapper_entries"] += 1
        if self.allowed is not True or self.trusted is not True:
            raise PermissionError("explicit reviewed external execution opt-in required")
        self.ledger["container_attempts"] += 1
        self.workspace.mkdir(parents=True, exist_ok=True)
        output = self.workspace/("call-"+uuid.uuid4().hex)
        receipt = execute_reviewed_case(self.candidate,self.review,self.bundle,variant=self.variant,input=point,
            image=self.image,output_directory=output,allow_external_execution=True,trusted_review=True,timeout=self.timeout)
        self.ledger["receipts"].append(receipt)
        if any(receipt[name] is None for name in ("external_target_calls", "external_oracle_calls", "external_reset_calls")):
            self.ledger["unresolved_call_receipts"] += 1
        for name in ("external_target_calls", "external_oracle_calls", "external_reset_calls"):
            if receipt[name] is not None:
                self.ledger[name] += receipt[name]
        self.ledger["wall_seconds"] += receipt["cost"]["wall_seconds"]
        if receipt["status"] != "COMPLETE":
            raise OSError("external OCI execution is unresolved; see preserved private receipt")
        capture = receipt["capture"]
        if capture["kind"] == "return":
            return _unsnapshot(capture["value"])
        exception = capture["exception_type"]
        module, _, name = exception.rpartition(".")
        remote = type(name or "RemoteException", (Exception,), {"__module__":module or "external"})
        raise remote("reviewed external exception; raw details remain private")
