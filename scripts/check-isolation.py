"""Executable container access-control check with a harmless host sentinel."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from tomolab.mold.boundary import GeneratorBoundary
from tomolab.mold.service import run_mold
from tomolab.cli import EXAMPLES


def main():
    with tempfile.TemporaryDirectory(prefix="private-oracle-sentinel-") as folder:
        sentinel = Path(folder) / "hidden-answer.txt"
        sentinel.write_text("public test sentinel, not an actual answer", encoding="utf-8")
        os.environ["TOMOLAB_PRIVATE_SENTINEL"] = "must-not-cross"
        with GeneratorBoundary(backend="docker") as generator:
            result = generator.request("diagnose", host_sentinel=str(sentinel))
            assert result == {"host_read": False, "code_write": False, "non_loopback_interfaces": [],
                              "uid": 65534, "private_env_present": False}, result
            configured = subprocess.run(["docker", "inspect", generator.name, "--format",
                                         "{{.HostConfig.NetworkMode}}"],
                                        capture_output=True, text=True, check=True, timeout=30).stdout.strip()
            assert configured == "none", configured
            receipt = generator.receipt
        spec = json.loads((EXAMPLES / "mold/spec.json").read_text(encoding="utf-8"))
        run = run_mold(EXAMPLES / "mold/target.py", EXAMPLES / "mold/oracle.py", spec,
                       budget=24, backend="docker", trusted_execution=True)
        assert run["target_calls"] == 24 and run["isolation"] == "CONTAINER_BOUNDARY"
        print(json.dumps({"status": "PASS", "access_probes": result, "boundary": receipt,
                          "network_check": {"docker_network_mode": configured,
                                            "non_loopback_interfaces": result["non_loopback_interfaces"],
                                            "external_connectivity": "NOT_TESTED_NO_EXTERNAL_CONNECTION_ATTEMPT"},
                          "end_to_end_calls": run["target_calls"]}, indent=2))


if __name__ == "__main__":
    main()
