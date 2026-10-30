"""Verify R3 strict service profiles with actual bounded Docker workers.

Evaluator callbacks are authored fixtures. The historical Source and Oracle
are never executed; the full Source archive is never transmitted or replayed.
Docker must already be available. There is no weaker automatic fallback.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from tomolab.discovery import numerical_boundary, numerical_source
from tomolab.discovery.numerical_boundary import GENERATOR_FILES, NumericalBoundary
from tomolab.discovery.numerical_guidance import public_input_contract
from tomolab.discovery.numerical_service import run_numerical_method
from tomolab.discovery.schema import canonical, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--image", default="tomolab-e7-generator:local")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    folder = root/"examples/numerical"
    bundle = {"artifact":json.loads((folder/"source-guide.json").read_text(encoding="utf-8")),
              "approval_receipt":json.loads((folder/"source-approval.json").read_text(encoding="utf-8"))}
    expected = (folder/"source-guide.sha256").read_text(encoding="ascii").strip()
    assert bundle["artifact"]["artifact_digest"] == expected
    hashes = {name:hashlib.sha256((root/"tomolab/discovery"/name).read_bytes()).hexdigest()
              for name in GENERATOR_FILES}
    original_boundary = numerical_boundary.NumericalBoundary
    callback_names = ("target_result", "oracle_result", "compare_results", "classify_mechanism")
    original_callbacks = {name:getattr(numerical_source, name) for name in callback_names}
    controls = []
    calls = {"target":0, "oracle":0}
    traces = []
    previous_sentinel = os.environ.get("TOMOLAB_PRIVATE_SENTINEL")
    with tempfile.TemporaryDirectory(prefix="e8r3-public-sentinel-") as temporary:
        marker = Path(temporary)/"public-host-sentinel.txt"
        marker.write_text("Harmless public R3 boundary probe.", encoding="utf-8")
        os.environ["TOMOLAB_PRIVATE_SENTINEL"] = "authored-public-placeholder"

        class CheckedBoundary(NumericalBoundary):
            def __enter__(self):
                super().__enter__()
                try:
                    if self.backend == "docker":
                        control = self.request("diagnose", host_sentinel=str(marker))
                        assert control == {"host_read":False, "code_write":False,
                            "non_loopback_interfaces":[], "uid":65534,
                            "private_env_present":False, "forbidden_modules_loaded":[]}, control
                        network = subprocess.check_output(["docker", "inspect", self.name,
                            "--format", "{{.HostConfig.NetworkMode}}"], text=True, timeout=30).strip()
                        assert network == "none"
                        controls.append(dict(access=control, network_mode=network))
                except Exception:
                    self.close()
                    raise
                return self

            def request(self, action, **fields):
                result = super().request(action, **fields)
                if action in ("plan", "baseline"):
                    before = self.receipt["validated_requests"]
                    blocked = []
                    for forbidden in ("observe", "learn", action, "init"):
                        try:
                            super().request(forbidden, **(fields if forbidden == action else {}))
                        except ValueError:
                            blocked.append(forbidden)
                        else:
                            raise AssertionError("post-freeze change accepted")
                    assert self.receipt["validated_requests"] == before
                    traces.append(dict(action=action, backend=self.backend,
                        process_id=self.process.pid, generator_sha256=self.receipt["generator_sha256"],
                        blocked_before_transport=blocked))
                return result

        def target(point):
            calls["target"] += 1
            return {"authored_value":1}
        def oracle(point):
            calls["oracle"] += 1
            return {"authored_value":1}
        numerical_boundary.NumericalBoundary = CheckedBoundary
        numerical_source.target_result, numerical_source.oracle_result = target, oracle
        numerical_source.compare_results = lambda left,right:left == right
        numerical_source.classify_mechanism = lambda *values:"AUTHORED_NO_FAILURE"
        runs = []
        try:
            for profile, method in (("runtime","D"), ("audit","D"),
                                    ("runtime","A"), ("runtime","B"), ("runtime","C")):
                result = run_numerical_method(bundle if method == "D" else None,
                    expected_digest=expected if method == "D" else None,
                    method=method, verification_profile=profile, backend="docker", image=args.image,
                    seed=17, size=4, max_examples=64, pair_budget=12, shrink_budget=0,
                    contract=public_input_contract(lengths=[4,5,6]),
                    replay_inputs=[{"a":[0.5]*3,"b":[0.25]*3}] if method == "C" else [])
                assert result["status"] == "COMPLETE", result.get("error")
                assert result["boundary"]["isolation"] == "CONTAINER_BOUNDARY"
                assert result["boundary"]["full_archive_transmitted"] is False
                assert result["boundary"]["oracle_modules_transmitted"] is False
                assert result["boundary"]["generator_sha256"] == hashes
                assert result["response_validation_status"] == "PASS"
                assert result["primary_generation_executions"] == 1
                assert result["reference_generation_executions"] == int(profile == "audit")
                assert result["equivalence_check_status"] == (
                    "PASS_FULL_STRUCTURED_SEMANTICS" if profile == "audit" else "NOT_RUN_IN_RUNTIME")
                assert result["generation"]["oracle_calls"] == result["generation"]["target_calls"] == 0
                assert result["serialized_request_bytes"] <= 8_000_000
                runs.append(dict(method=method, profile=profile,
                    candidate_semantic_digest=result["r3"]["candidate_semantic_digest"],
                    verification=result["r3"], boundary=result["boundary"],
                    serialized_request_bytes=result["serialized_request_bytes"]))
        finally:
            numerical_boundary.NumericalBoundary = original_boundary
            for name, callback in original_callbacks.items():
                setattr(numerical_source, name, callback)
            if previous_sentinel is None:
                os.environ.pop("TOMOLAB_PRIVATE_SENTINEL", None)
            else:
                os.environ["TOMOLAB_PRIVATE_SENTINEL"] = previous_sentinel
    assert len(controls) == len(traces) == 6
    assert runs[0]["candidate_semantic_digest"] == runs[1]["candidate_semantic_digest"]
    report = dict(schema="tomolab-e8r3-container-verification-v1", status="PASS",
        scope="FUNCTIONAL_BOUNDARY_NOT_SOURCE_UTILITY_OR_PERFORMANCE_STUDY",
        approved_compact_guide=True, full_archive_transmitted=False,
        full_archive_docker_validation_claimed=False, generator_sha256=hashes,
        worker_modules=list(GENERATOR_FILES), authored_evaluator_calls=calls,
        actual_historical_source_calls=0, actual_historical_oracle_calls=0,
        external_connectivity="NOT_PROBED_CONFIG_AND_INTERFACES_CHECKED", controls=controls,
        actual_generation_traces=traces, runs=runs, allow_release=False, pypi_uploads=0)
    report["receipt_sha256"] = digest(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical(report)+"\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
