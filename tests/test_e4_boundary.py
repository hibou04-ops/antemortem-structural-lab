"""Public, authored protocol tests; no historical evaluation data is used."""
import io
import json

import pytest

from tomolab.mold import worker
from tomolab.mold.boundary import GENERATOR_FILES, GeneratorBoundary
from tomolab.mold.engine import MoldEngine
from tomolab.mold.protocol import MAX_MESSAGE, validate_request
from tomolab.mold.schema import default_spec


@pytest.mark.parametrize("field,value", [
    ("score", 0.95), ("target_source", "def hidden(): pass"),
    ("oracle_output", 999), ("private_path", "/private/answers"),
])
def test_forbidden_fields_rejected_before_transport(field, value):
    with GeneratorBoundary() as boundary:
        boundary.request("init", spec=default_spec(low=-1, high=1))
        before = boundary.receipt["validated_requests"]
        # No worker round trip may happen: the transport is replaced by a trap.
        class ForbiddenTransport:
            def write(self, data):
                raise AssertionError("forbidden payload reached transport")
        original = boundary.process.stdin
        boundary.process.stdin = ForbiddenTransport()
        try:
            with pytest.raises(ValueError, match="forbidden"):
                boundary.request("propose", **{field: value})
            assert boundary.receipt["validated_requests"] == before
        finally:
            boundary.process.stdin = original


def test_nested_private_fields_rejected_before_transport():
    spec = default_spec(low=-1, high=1)
    bad_spec = dict(spec, oracle_source="private reference")
    with pytest.raises(ValueError):
        validate_request({"action": "init", "spec": bad_spec})
    evidence = {"kind": "FAILURE", "evidence_id": "dev-1", "inputs": {"x": 0, "y": 0},
                "invariant": spec["invariant"], "signature": "integer-mismatch"}
    for key in ("actual", "expected", "model_score", "source"):
        with pytest.raises(ValueError):
            validate_request({"action": "observe", "evidence": dict(evidence, **{key: "hidden"})}, spec)


def test_transport_contains_only_public_spec_and_minimal_evidence():
    spec = default_spec(low=-1, high=1)
    with GeneratorBoundary() as boundary:
        lines = []
        original = boundary.process.stdin
        class RecordingTransport:
            def write(self, data):
                lines.append(json.loads(data))
                return original.write(data)
            def flush(self):
                return original.flush()
        boundary.process.stdin = RecordingTransport()
        try:
            boundary.request("init", spec=spec)
            point = boundary.request("propose")["inputs"]
            evidence = {"kind": "REFUTATION", "evidence_id": "dev-1", "inputs": point,
                        "invariant": spec["invariant"], "signature": "integer-mismatch"}
            boundary.request("observe", evidence=evidence)
            boundary.request("freeze")
            with pytest.raises(ValueError, match="frozen"):
                boundary.request("observe", evidence=dict(evidence, evidence_id="final-1"))
        finally:
            boundary.process.stdin = original
        assert lines == [{"action": "init", "spec": spec}, {"action": "propose"},
                         {"action": "observe", "evidence": evidence}, {"action": "freeze"}]
        assert set(GENERATOR_FILES).isdisjoint({"service.py", "property_testing.py", "boundary.py", "jev.py"})
        copied = {path.name for path in (boundary.root / "tomolab" / "mold").iterdir()}
        assert copied == set(GENERATOR_FILES)
        assert boundary.receipt["isolation"] == "LOGICAL_ISOLATION_ONLY"


def test_unverified_snapshot_extra_fields_rejected_before_transfer():
    spec = default_spec(low=-1, high=1)
    snapshot = MoldEngine(spec).freeze()
    snapshot["private_answer"] = "never transmit"
    with pytest.raises(ValueError):
        validate_request({"action": "transfer", "snapshot": snapshot, "spec": spec})


def test_worker_checks_protocol_independently(monkeypatch, capsys):
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO(json.dumps({"action": "init", "spec": default_spec(low=-1, high=1),
                                                                    "score": 1}) + "\n"))
    assert worker.main() == 0
    response = json.loads(capsys.readouterr().out)
    assert response["ok"] is False and "forbidden" in response["error"]


def test_worker_stops_on_oversized_line_without_reading_entire_stream(monkeypatch, capsys):
    class BoundedInput:
        def readline(self, size):
            assert size == MAX_MESSAGE + 1
            return "x" * size
    monkeypatch.setattr(worker.sys, "stdin", BoundedInput())
    assert worker.main() == 2
    assert "too large" in json.loads(capsys.readouterr().out)["error"]


def test_private_environment_not_inherited(monkeypatch):
    import tomolab.mold.boundary as module
    real_popen = module.subprocess.Popen
    captured = {}
    def capture(*args, **kwargs):
        captured.update(kwargs["env"])
        return real_popen(*args, **kwargs)
    monkeypatch.setenv("TOMOLAB_PRIVATE_SENTINEL", "not-for-generator")
    monkeypatch.setattr(module.subprocess, "Popen", capture)
    with GeneratorBoundary() as boundary:
        boundary.request("init", spec=default_spec(low=-1, high=1))
    assert "TOMOLAB_PRIVATE_SENTINEL" not in captured


def test_diagnostic_never_connects_to_external_service(monkeypatch, tmp_path, capsys):
    import socket
    sentinel = tmp_path / "public-sentinel.txt"
    sentinel.write_text("public dummy", encoding="utf-8")
    # Run only the diagnostic's authored test with isolated fake filesystem
    # writes; never let it write a probe into the actual generator source tree.
    from pathlib import Path
    original_write = Path.write_text
    def write(path, *args, **kwargs):
        if path.name == "write-probe":
            raise PermissionError("read-only code test")
        return original_write(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", write)
    monkeypatch.setattr(socket, "if_nameindex", lambda: [(1, "lo")])
    def forbidden_socket(*args, **kwargs):
        raise AssertionError("diagnostic attempted an external connection")
    monkeypatch.setattr(socket, "socket", forbidden_socket)
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO(json.dumps({"action": "diagnose", "host_sentinel": str(sentinel)}) + "\n"))
    assert worker.main() == 0
    response = json.loads(capsys.readouterr().out)
    assert response["ok"] is True
    assert response["result"]["non_loopback_interfaces"] == []
