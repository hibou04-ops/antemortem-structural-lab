"""Execute the real compact Source guide in the existing bounded Docker worker.

The 72 MB audit archive was replay-validated on the trusted host before this
public guide was compiled. This check executes that guide, not the archive.
No external network probes or target/Oracle execution occur inside the worker.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from tomolab.discovery.compact_guidance import MAX_ARTIFACT_BYTES, MAX_MESSAGE, host_candidate_plan
from tomolab.discovery.numerical_boundary import NumericalBoundary
from tomolab.discovery.numerical_guidance import public_input_contract
from tomolab.discovery.schema import canonical, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    folder = root/"examples/numerical"
    artifact = json.loads((folder/"source-guide.json").read_text(encoding="utf-8"))
    approval = json.loads((folder/"source-approval.json").read_text(encoding="utf-8"))
    expected_digest = (folder/"source-guide.sha256").read_text(encoding="ascii").strip()
    assert artifact["artifact_digest"] == expected_digest
    fields = dict(artifact=artifact, approval_receipt=approval, expected_digest=expected_digest,
        seed=17, size=16, max_examples=128, excluded_digests=[],
        contract=public_input_contract(lengths=[4, 5, 6]))
    artifact_bytes = len(canonical(artifact).encode("utf-8"))
    request_bytes = len(canonical(dict(action="plan", **fields)).encode("utf-8"))+1
    assert artifact_bytes <= MAX_ARTIFACT_BYTES and request_bytes <= MAX_MESSAGE
    tick = time.perf_counter()
    host = host_candidate_plan(**fields)
    assert host["reference_execution"] == "CLEAN_HOST_SUBPROCESS_REFERENCE"
    assert host["reference_boundary"]["full_archive_transmitted"] is False
    host_seconds = time.perf_counter()-tick
    with tempfile.TemporaryDirectory(prefix="e8r2-public-sentinel-") as temp:
        marker = Path(temp)/"public-host-sentinel.txt"
        marker.write_text("Harmless public numerical boundary probe.", encoding="utf-8")
        os.environ["TOMOLAB_PRIVATE_SENTINEL"] = "public-dummy-not-a-secret"
        try:
            tick = time.perf_counter()
            with NumericalBoundary(backend="docker") as worker:
                control = worker.request("diagnose", host_sentinel=str(marker))
                assert control == {"host_read": False, "code_write": False,
                    "non_loopback_interfaces": [], "uid": 65534,
                    "private_env_present": False, "forbidden_modules_loaded": []}, control
                network = subprocess.check_output(["docker", "inspect", worker.name,
                    "--format", "{{.HostConfig.NetworkMode}}"], text=True, timeout=30).strip()
                assert network == "none"
                result = worker.request("plan", **fields)
                assert result["generation"]["candidates"] == host["generation"]["candidates"]
                assert result["candidate_digest"] == host["candidate_digest"]
                assert result["execution_contract_digest"] == host["execution_contract_digest"]
                assert result["generation"]["oracle_calls"] == result["generation"]["target_calls"] == 0
                count = worker.receipt["validated_requests"]
                blocked = []
                for action, values in (("observe", {"evidence": {}}), ("learn", {}),
                                       ("plan", fields), ("init", {"spec": {}})):
                    try:
                        worker.request(action, **values)
                    except ValueError:
                        blocked.append(action)
                    else:
                        raise AssertionError("frozen guide accepted feedback or replacement parameters")
                assert worker.receipt["validated_requests"] == count
                frozen = worker.request("freeze")
                assert frozen["frozen"] and not frozen["learning_allowed"]
                assert frozen["candidate_digest"] == host["candidate_digest"]
                receipt = worker.receipt
            worker_seconds = time.perf_counter()-tick
        finally:
            os.environ.pop("TOMOLAB_PRIVATE_SENTINEL", None)
    # This is a public executable fixture of the actual Source-derived compact
    # guide. It does not rerun or disclose the private Source training rows.
    report = {"schema": "tomolab-e8r2-compact-container-verification-v1", "status": "PASS",
        "actual_source_guide": True, "source_archive_digest": artifact["source_archive_digest"],
        "artifact_digest": expected_digest, "host_approval_receipt_digest": approval["receipt_digest"],
        "artifact_bytes": artifact_bytes, "serialized_request_bytes": request_bytes,
        "artifact_limit_bytes": MAX_ARTIFACT_BYTES, "transport_limit_bytes": MAX_MESSAGE,
        "boundary": receipt, "access_control": control, "network_mode": network,
        "host_worker_candidates_identical": True, "candidate_digest": result["candidate_digest"],
        "host_reference_execution": host["reference_execution"],
        "host_reference_boundary": host["reference_boundary"],
        "ambient_host_module_constants_visible_to_generation": False,
        "candidate_count": len(result["generation"]["candidates"]),
        "post_freeze_actions_blocked_before_transport": blocked,
        "host_generation_seconds": host_seconds, "worker_startup_generation_shutdown_seconds": worker_seconds,
        "full_archive_sent_to_worker": False, "full_archive_docker_validation_claimed": False,
        "source_target_oracle_execution": "NONE_IN_THIS_CONTAINER_CHECK",
        "external_connectivity": "NOT_PROBED_NETWORK_CONFIG_AND_INTERFACES_CHECKED",
        "performance_scope": "FUNCTIONAL_BOUNDARY_CHECK_NOT_GUIDANCE_UTILITY_EVALUATION"}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
