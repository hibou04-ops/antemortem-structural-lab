"""Install a candidate wheel outside checkout and run exposed authored structural probe only."""
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
    with tempfile.TemporaryDirectory(prefix="tomolab-qualification-installed-") as folder:
        scratch = Path(folder)
        environment = scratch / "environment"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        install = subprocess.run([str(python), "-m", "pip", "install", str(artifact)+"[qa]"],
            cwd=scratch, capture_output=True, text=True, timeout=240)
        if install.returncode:
            raise RuntimeError("candidate install failed: " + install.stderr[-1000:])
        workspace = scratch / "authored-example"
        run = subprocess.run([str(python), "-I", "-m", "tomolab", "structural-probe",
            "--workspace", str(workspace), "--allow-local-execution", "--budget", "24", "--equal-cost"], cwd=scratch,
            capture_output=True, text=True, timeout=180)
        if run.returncode not in (0,3):
            raise RuntimeError("installed example failed: " + run.stderr[-2000:])
        summary = json.loads((workspace / "summary.json").read_text(encoding="utf-8"))
        assert summary["evidence_class"] == "DEVELOPMENT_SYNTHETIC_EXPOSED"
        assert summary["status"] in ("FUNCTIONAL_COMPLETE", "HOLD_MEASUREMENT")
        assert len(summary["cases"]) == 4 and summary["external_target_calls"] == 0
        assert summary["learning_updates"] == 0 and summary["independent_oos_cases"] == 0
        assert summary["utility"] == "NOT_ESTABLISHED"
        assert summary["equal_cost_mode"] is True and summary["baseline_method"] == "E9_C"
        assert all(row["hard_call_parity"]["identical_hard_caps"] is True for row in summary["cases"])
        assert all(summary["actual"][k] <= summary["caps"][k] for k in summary["actual"])
        audit_help = subprocess.run([str(python), "-I", "-m", "tomolab", "transfer-audit", "--help"],
            cwd=scratch, capture_output=True, text=True, timeout=30)
        assert audit_help.returncode == 0
        check = subprocess.run([str(python), "-m", "pip", "check"], cwd=scratch,
            capture_output=True, text=True, timeout=30)
        assert check.returncode == 0, check.stdout
        triage_help = subprocess.run([str(python), "-I", "-m", "tomolab", "harvest-triage", "--help"],
            cwd=scratch, capture_output=True, text=True, timeout=30)
        assert triage_help.returncode == 0
        triage_input = scratch / "authored-docs-only.json"
        triage_output = scratch / "authored-docs-only-result.json"
        inert = dict(candidate_id="a"*64, metadata_digest="b"*64, repository="authored/installed-docs-only",
            buggy_revision="1"*40, fixed_revision="2"*40,
            files=[dict(path="docs/authored-installation-note.md", status="modified")],
            files_complete=True, expected_changed_files=1, source_pairs=[], uninspected_runtime_paths=[], reasons=[])
        triage_input.write_text(json.dumps(dict(schema="tomolab-prequalification-triage-input-v1",
            records=[inert], expected_candidate_ids=[inert["candidate_id"]])), encoding="utf-8")
        triage_run = subprocess.run([str(python), "-I", "-m", "tomolab", "harvest-triage",
            "--manifest", str(triage_input), "--output", str(triage_output)],
            cwd=scratch, capture_output=True, text=True, timeout=30)
        assert triage_run.returncode == 0
        triage = json.loads(triage_output.read_text(encoding="utf-8"))
        assert triage["status"] == "COMPLETE" and triage["denominator"] == 1
        assert triage["outcomes"] == {"EXCLUDE_DOC_OR_NON_CODE": 1}
        assert triage["qualified"] == triage["target_calls"] == triage["oracle_calls"] == triage["network_requests"] == 0
        assert triage["source_imported"] is False and triage["source_executed"] is False
        receipt = dict(schema="tomolab-qualification-installed-check-v1", status="PASS" if summary["status"] == "FUNCTIONAL_COMPLETE" and summary["hard_budget_parity"] == "PASS" else "HOLD_MEASUREMENT",
            installation_status="PASS",equal_cost_mode=True,baseline_method="E9_C",hard_budget_parity=summary["hard_budget_parity"],
            actual_call_spending_equal=summary["actual_call_spending_equal"],
            hard_call_meters=[row["hard_call_parity"] for row in summary["cases"]],
            harvest_triage_cli="PASS",triage_denominator=triage["denominator"],triage_qualified=triage["qualified"],
            triage_target_calls=triage["target_calls"],triage_oracle_calls=triage["oracle_calls"],
            triage_scope="AUTHORED_DOCS_ONLY_INSTALLATION_FIXTURE_NO_TARGET_EXECUTION",
            artifact=artifact.name, artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
            outside_checkout=True, isolated_python=True, fresh_environment=True,
            probe_status=summary["status"], evidence_class=summary["evidence_class"],
            native_cases=4, actual=summary["actual"], caps=summary["caps"],
            real_eligible=summary["real_eligible"], independent_oos_cases=0,
            external_target_calls=0, learning_updates=0, utility="NOT_ESTABLISHED",
            transfer_audit_cli="PASS", pip_check="PASS", wall_seconds=time.perf_counter()-started)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=True, indent=2)
        stream.write("\n")
    print(json.dumps(receipt, ensure_ascii=True, indent=2))
    return 0 if receipt["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
