"""Actual E7 Docker access control and evidence-qualified execution gate."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from tomolab.discovery.knowledge_boundary import KnowledgeBoundary


def main():
    with tempfile.TemporaryDirectory(prefix="e7-host-dummy-") as folder:
        marker = Path(folder)/"public-dummy"
        marker.write_text("public E7 diagnostic only", encoding="utf-8")
        os.environ["TOMOLAB_PRIVATE_SENTINEL"] = "public-dummy-not-a-secret"
        try:
            with KnowledgeBoundary(backend="docker") as generator:
                control = generator.request("diagnose", host_sentinel=str(marker))
                receipt = generator.receipt
                network = subprocess.check_output(["docker","inspect",generator.name,"--format","{{.HostConfig.NetworkMode}}"],text=True).strip()
            assert control == {"host_read": False, "code_write": False, "non_loopback_interfaces": [],
                               "uid": 65534, "private_env_present": False}, control
            assert network == "none"
        finally:
            os.environ.pop("TOMOLAB_PRIVATE_SENTINEL", None)
    command = [sys.executable, "-X", "utf8", "-m", "tomolab", "knowledge-demo", "--backend", "docker",
               "--budget", "16", "--guidance-budget", "4", "--pool-size", "16", "--shrink-budget", "16",
               "--time-budget", "45"]
    completed = subprocess.run(command,capture_output=True,text=True,encoding="utf-8",check=True,timeout=150)
    result = json.loads(completed.stdout)
    assert result["status"] == "COUNTEREXAMPLE_FOUND"
    assert result["gate"]["status"] == "QUALIFIED_FOR_PROBING"
    assert result["snapshot"]["frozen"]
    assert result["metrics"]["guided_prefix_calls"] > 0
    assert result["counterexample"]["replay"] == "MATCHED_TWICE"
    assert result["final_feedback_allowed"] is False
    assert result["isolation"] == "CONTAINER_BOUNDARY"
    print(json.dumps({"status": "PASS", "access_control": control, "boundary": receipt,
        "network_mode": network, "external_connectivity": "NOT_TESTED_NO_THIRD_PARTY_PROBE",
        "qualified_claims": len(result["gate"]["claims"]), "actual_calls": result["metrics"]["actual_primitive_invocations"],
        "target_execution": "TRUSTED_HOST_CODE", "scope": "AUTHORED_FUNCTIONAL_FIXTURE_NOT_RESEARCH"},indent=2))


if __name__ == "__main__":
    main()
