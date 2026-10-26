"""Executable container access-control check with a harmless host sentinel."""
import json
import os
from pathlib import Path
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
            assert result == {"host_read": False, "code_write": False, "network_connected": False,
                              "uid": 65534, "private_env_present": False}, result
            receipt = generator.receipt
        spec = json.loads((EXAMPLES / "mold/spec.json").read_text(encoding="utf-8"))
        run = run_mold(EXAMPLES / "mold/target.py", EXAMPLES / "mold/oracle.py", spec,
                       budget=24, backend="docker", trusted_execution=True)
        assert run["target_calls"] == 24 and run["isolation"] == "CONTAINER_BOUNDARY"
        print(json.dumps({"status": "PASS", "access_probes": result, "boundary": receipt,
                          "end_to_end_calls": run["target_calls"]}, indent=2))


if __name__ == "__main__":
    main()
