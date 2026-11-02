"""Install a candidate wheel outside checkout and run authored harvest recursion only."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import venv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    candidates = sorted((root / "dist").glob("*.whl"))
    artifact = args.artifact.resolve() if args.artifact else candidates[0] if len(candidates) == 1 else None
    if artifact is None or not artifact.is_file():
        raise ValueError("one exact candidate wheel is required")
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="tomolab-harvester-installed-") as folder:
        scratch = Path(folder)
        environment = scratch / "environment"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        install = subprocess.run([str(python), "-m", "pip", "install", str(artifact)+"[qa]"],
            cwd=scratch, capture_output=True, text=True, encoding="utf-8", timeout=240)
        if install.returncode:
            raise RuntimeError("candidate install failed: " + install.stderr[-1000:])
        workspace = scratch / "authored-example"
        run = subprocess.run([str(python), "-I", "-m", "tomolab", "harvest-demo",
            "--workspace", str(workspace), "--allow-local-execution"], cwd=scratch,
            capture_output=True, text=True, encoding="utf-8", timeout=180)
        if run.returncode:
            raise RuntimeError("installed example failed: " + run.stderr[-2000:])
        summary = json.loads((workspace / "summary.json").read_text(encoding="utf-8"))
        assert summary["executed_candidates"] == [[-1,-2],[1,1],[-1,-2]]
        assert [row["status"] for row in summary["resumed"]] == ["PASS","FAILURE","PASS"]
        assert len({row["process_id"] for row in summary["resumed"]}) == 3
        observed_changes = []
        for row in summary["resumed"]:
            execution = json.loads((workspace/(row["generation_id"]+"-online.json")).read_text(encoding="utf-8"))
            measured = execution["run"]
            scheduler = measured["scheduler"]
            assert execution["selector_digest"] == row["selector_digest"]
            assert execution["generation_digest"] == row["generation_digest"]
            assert measured["status"] == row["full_new_search_status"] == "COMPLETE"
            assert scheduler["allocation_policy"] == "STATIC_C_FLOOR_D_CIRCUIT_BREAKER_V3"
            assert scheduler["epsilon_static_floor"] == 0.5
            actual = scheduler["mixed_policy"]["actual"]
            assert actual == row["full_new_search_policy_calls"]
            for kind in ("target_calls", "oracle_calls"):
                assert actual["C"][kind] >= (measured["budget"]+1)//2
                assert actual["D"][kind] <= measured["budget"]//2
                assert measured[kind] == row["full_new_search_cost"][kind] == sum(actual[arm][kind] for arm in ("C","D"))
            changes = sum(bool(event.get("rule_id")) and event.get("source_selection",{}).get("source_changed_common",False)
                          for event in measured["events"])
            assert row["full_new_search_changed_common"] == scheduler["learned_changed_common_executions"] == changes
            observed_changes.append(changes)
            assert all(scheduler["actual"][lane] <= cap for lane,cap in scheduler["caps"].items())
        assert summary["fresh_search_changed_common"] == observed_changes
        check = subprocess.run([str(python), "-m", "pip", "check"], cwd=scratch,
            capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert check.returncode == 0, check.stdout
        receipt = dict(schema="tomolab-harvester-installed-check-v1", status="PASS",
            artifact=artifact.name, artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
            outside_checkout=True, isolated_python=True, fresh_environment=True,
            registered_candidates=summary["registered_candidates"], duplicates_skipped=summary["duplicates_skipped"],
            actual_candidates=summary["executed_candidates"],
            new_search_changed_common=summary["fresh_search_changed_common"],
            new_search_policy_calls=[row["full_new_search_policy_calls"] for row in summary["resumed"]],
            new_search_guidance_scope="ACTUAL_EXECUTED_COUNTS_NOT_PROMISED_BY_FIXED_SLOT",
            real_eligible=summary["real_eligible"], consumed_registry="PINNED_INSTALLED_SNAPSHOT_VALIDATED",
            process_restarts=3, pip_check="PASS", evidence_class="AUTHORED_SYNTHETIC_FIXTURE",
            real_research_calls=0, wall_seconds=time.perf_counter()-started)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=True, indent=2)
        stream.write("\n")
    print(json.dumps(receipt, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
