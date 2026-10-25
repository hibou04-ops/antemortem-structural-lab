"""Run trusted C1 data evaluation in a separate isolated Python process.

This limits Python/environment contamination; it is not an OS security sandbox.
Use a dedicated virtual environment. No arbitrary module or target is accepted.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 300:
        parser.error("timeout must be between 1 and 300 seconds")
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Only OS startup variables. Provider keys and Python path variables are absent.
    allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE"}
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in allowed}
    with tempfile.TemporaryDirectory(prefix="c1-process-", dir=output.parent) as tmp:
        environment.update(TEMP=tmp, TMP=tmp, PYTHONIOENCODING="utf-8")
        bootstrap = (
            "import sys; sys.path.insert(0, sys.argv.pop(1)); "
            "from research.c1.evaluate import main; raise SystemExit(main())"
        )
        command = [str(args.python.resolve()), "-I", "-c", bootstrap, str(root),
                   "--output", str(output),
                   "--llm-direct", str(root / "research/c1/baselines/llm_direct.json"),
                   "--llm-self-review", str(root / "research/c1/baselines/llm_self_review.json")]
        result = subprocess.run(command, cwd=tmp, env=environment,
                                capture_output=True, timeout=args.timeout)
    receipt = {
        "schema": "c1-process-isolation-v1", "returncode": result.returncode,
        "separate_virtual_environment": True, "python_isolated_mode": True,
        "environment_policy": "OS startup allowlist; no provider credentials inherited",
        "trusted_json_fixtures_only": True, "arbitrary_target_execution": False,
        "timeout_seconds": args.timeout, "os_security_sandbox": False,
        "network_filter_enforced_by_runner": False,
        "scope": "Data-only interpreter; no C1 network/API calls. Not safe for hostile Python."
    }
    output.with_suffix(".isolation.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if result.stdout:
        print(result.stdout.decode("utf-8", errors="replace"))
    if result.stderr:
        print(result.stderr.decode("utf-8", errors="replace"))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
