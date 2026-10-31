"""Real subprocess access boundary, including Hypothesis implicit constants.

Canaries below are authored harmless test data. The subprocess has logical
separation and a code allowlist; these tests do not claim OS filesystem denial.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import types

import pytest

from tomolab.discovery.online_boundary import OnlineBoundary, GENERATOR_FILES, bounded_message
from tomolab.discovery.online_observe import inspect_target, observe
from tomolab.discovery.schema import canonical


CONTRACT = dict(kind="int", low=-100_000_000_000, high=100_000_000_000)


def public_identity(point):
    return point


def configuration(method="B"):
    return dict(contract=deepcopy(CONTRACT), structure=inspect_target(public_identity, CONTRACT),
        method=method, seed=103, budget=12, shrink_budget=0, mold=None,
        replays=[], max_seconds=10.0, _started=time.perf_counter())


def evaluator(oracle=public_identity):
    history = []
    def execute(point, *, phase, reference):
        row = observe(public_identity, oracle, point, CONTRACT)
        match = None if reference is None else (type(reference) is int and 0 <= reference < len(history)
            and row.get("semantic_digest") == history[reference].get("semantic_digest"))
        history.append(row)
        return dict(feedback=row["feedback"], target_calls=row["target_calls"],
            oracle_calls=row["oracle_calls"], cost=row["cost"],
            observation_id=len(history)-1, reference_match=match)
    return execute, history


def recursive_keys(value):
    if isinstance(value, dict):
        return set(value).union(*(recursive_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(recursive_keys(item) for item in value))
    return set()


class RecordingTransport:
    def __init__(self, original):
        self.original, self.messages = original, []
    def write(self, data):
        self.messages.append(json.loads(data))
        return self.original.write(data)
    def flush(self):
        return self.original.flush()


def test_worker_allowlist_and_actual_import_inventory_exclude_evaluator_and_oracle():
    execute, history = evaluator()
    with OnlineBoundary() as boundary:
        copied = {p.name for p in (boundary.root/"tomolab/discovery").iterdir()}
        assert copied == set(GENERATOR_FILES)
        assert not {"online_observe.py", "online_learning.py", "online_benchmark.py", "evaluation_usage.py"} & copied
        result, metadata = boundary.run(configuration(), execute)
        modules = set(metadata["imported_modules"])
        assert not {"tomolab.discovery.online_observe", "tomolab.discovery.online_learning",
            "tomolab.discovery.online_benchmark", "benchmarks.online", "tomolab.online_cli", __name__} & modules
        assert metadata["rpc_evaluations"] == len(history) == result["target_calls"]
        assert metadata["worker_exit_code"] == 0
        assert boundary.receipt["isolation"] == "LOGICAL_ISOLATION_ONLY"


def test_online_transport_contains_only_public_configuration_and_limited_feedback():
    execute, _ = evaluator()
    with OnlineBoundary() as boundary:
        original = boundary.process.stdin
        recorder = RecordingTransport(original)
        boundary.process.stdin = recorder
        try:
            boundary.run(configuration(), execute)
        finally:
            boundary.process.stdin = original
        assert recorder.messages[0]["action"] == "run"
        assert all(row["action"] == "feedback" for row in recorder.messages[1:])
        forbidden = {"actual", "expected", "private_outcome", "private_outcomes",
            "semantic_digest", "oracle_source", "oracle_path", "target_source", "model_score"}
        assert not recursive_keys(recorder.messages) & forbidden


@pytest.mark.parametrize("location", ["configuration", "structure", "contract"])
def test_forbidden_fields_are_rejected_before_the_parent_pipe(location):
    config = configuration()
    container = config if location == "configuration" else config[location]
    container["oracle_source"] = "private evaluator code must never cross"
    class NoWrite:
        def write(self, data):
            pytest.fail("private request reached the worker transport")
        def flush(self):
            pass
    with OnlineBoundary() as boundary:
        original = boundary.process.stdin
        boundary.process.stdin = NoWrite()
        try:
            with pytest.raises(ValueError):
                boundary.run(config, lambda *_args, **_kwargs: pytest.fail("target was called"))
        finally:
            boundary.process.stdin = original


def test_private_nested_feedback_is_rejected_before_transport():
    execute, _ = evaluator()
    def forbidden(point, **kwargs):
        row = execute(point, **kwargs)
        row["feedback"]["expected"] = "private Oracle output"
        return row
    with OnlineBoundary() as boundary:
        original = boundary.process.stdin
        recorder = RecordingTransport(original)
        boundary.process.stdin = recorder
        try:
            with pytest.raises(ValueError):
                boundary.run(configuration(), forbidden)
            assert len(recorder.messages) == 1
        finally:
            boundary.process.stdin = original


def test_existing_transport_bound_is_not_increased():
    from tomolab.mold.protocol import MAX_MESSAGE
    assert MAX_MESSAGE == 8_000_000
    with pytest.raises(ValueError, match="8,000,000"):
        bounded_message(dict(action="run", data="x"*MAX_MESSAGE))


def test_host_only_oracle_literal_cannot_change_native_candidate_stream(tmp_path):
    source = tmp_path/"private_oracle_canary.py"
    module_name = "_online_private_oracle_canary"
    previous = sys.modules.get(module_name)
    streams = []
    try:
        for value in (91_827_364_501, -81_726_354_409):
            source.write_text(f"CANARY = {value}\ndef reference(point):\n    return point\n", encoding="utf-8")
            # Compile explicitly to avoid cache timestamp granularity affecting
            # this boundary test; the module is loaded only in the host.
            module = types.ModuleType(module_name)
            module.__file__ = str(source)
            exec(compile(source.read_text(), str(source), "exec"), module.__dict__)
            sys.modules[module_name] = module
            execute, _ = evaluator(module.reference)
            with OnlineBoundary() as boundary:
                result, metadata = boundary.run(configuration("A"), execute)
                assert module_name not in metadata["imported_modules"]
                streams.append([row["input_digest"] for row in result["observations"]])
        assert streams[0] == streams[1] and streams[0]
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous


def test_private_path_is_not_read_and_private_environment_is_not_inherited(monkeypatch, tmp_path):
    import tomolab.mold.boundary as shared
    canary = tmp_path/"host_only_private_oracle_canary.py"
    canary.write_text("CANARY = 48123192711\ndef reference(point):\n    return point\n", encoding="utf-8")
    module_name = "_online_host_only_path_canary"
    module = types.ModuleType(module_name)
    module.__file__ = str(canary)
    exec(compile(canary.read_text(), str(canary), "exec"), module.__dict__)
    monkeypatch.setitem(sys.modules, module_name, module)
    path_hash = hashlib.sha256(os.path.normcase(os.path.abspath(canary)).encode()).hexdigest()
    real_popen, captured = shared.subprocess.Popen, {}
    def monitored(command, *args, **kwargs):
        captured.update(env=dict(kwargs["env"]), cwd=kwargs["cwd"], command=list(command))
        command = list(command)
        index = command.index("-c")+1
        bootstrap = command[index]
        # Diagnostic hook sees actual open events; only a digest of the private
        # pathname enters this diagnostic bootstrap, never a generation field.
        hook = ("import sys,os,hashlib,atexit\n"
            "def _boundary_audit(event,args):\n"
            " if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):\n"
            "  value=os.fsdecode(args[0]); token=hashlib.sha256(os.path.normcase(os.path.abspath(value)).encode()).hexdigest()\n"
            f"  if token=={path_hash!r}: os.write(2,b'AUDIT_CANARY_OPEN\\n')\n"
            "sys.addaudithook(_boundary_audit)\n"
            "atexit.register(lambda:os.write(2,b'AUDIT_PROBE_COMPLETE\\n'))\n")
        command[index] = hook+bootstrap
        return real_popen(command, *args, **kwargs)
    monkeypatch.setenv("TOMOLAB_PRIVATE_SENTINEL", "not-for-online-generator")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setattr(shared.subprocess, "Popen", monitored)
    execute, _ = evaluator(module.reference)
    with OnlineBoundary() as boundary:
        _, metadata = boundary.run(configuration(), execute)
        assert module_name not in metadata["imported_modules"]
        deadline = time.monotonic()+2
        while "AUDIT_PROBE_COMPLETE" not in "".join(boundary.errors) and time.monotonic() < deadline:
            time.sleep(0.01)
        audit = "".join(boundary.errors)
        assert "AUDIT_PROBE_COMPLETE" in audit and "AUDIT_CANARY_OPEN" not in audit
        assert "TOMOLAB_PRIVATE_SENTINEL" not in captured["env"]
        assert "PYTHONPATH" not in captured["env"]
        assert "-I" in captured["command"] and Path(captured["cwd"]) == boundary.root
