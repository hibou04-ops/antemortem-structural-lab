import json
from pathlib import Path
import subprocess
import sys

import pytest

from tomolab.mold.boundary import GeneratorBoundary, GENERATOR_FILES
from tomolab.mold.service import run_mold, plan_mold
from tomolab.cli import EXAMPLES


def specification():
    return json.loads((EXAMPLES / "mold/spec.json").read_text(encoding="utf-8"))


def test_boundary_excludes_oracle_and_rejects_reward_field():
    assert "service.py" not in GENERATOR_FILES
    with GeneratorBoundary() as worker:
        assert not (worker.root / "tomolab/mold/service.py").exists()
        worker.request("init", spec=specification())
        with pytest.raises(ValueError, match="forbidden"):
            worker.request("observe", evidence={}, score=1)
        worker.request("freeze")
        with pytest.raises(ValueError):
            worker.request("observe", evidence={})


def test_complete_run_and_mapped_plan():
    result = run_mold(EXAMPLES / "mold/target.py", EXAMPLES / "mold/oracle.py", specification(),
                      budget=32, trusted_execution=True)
    assert result["target_calls"] == result["oracle_calls"] == 32
    assert result["isolation"] == "LOGICAL_ISOLATION_ONLY"
    assert result["status"] == "COUNTEREXAMPLES_FOUND"
    assert all(set(row) == {"kind", "evidence_id", "inputs", "invariant", "signature"}
               for row in result["evidence"])
    new_spec = json.loads((EXAMPLES / "mold/renamed-spec.json").read_text(encoding="utf-8"))
    planned = plan_mold(result, new_spec, budget=16)
    assert planned["gate"]["status"] == "APPLICABLE_FOR_PROBING"
    assert len(planned["candidates"]) == 16
    assert planned["final_feedback_allowed"] is False
    assert all(set(p["inputs"]) == {"amount", "increment"} for p in planned["candidates"])


def test_local_target_opt_in_and_separate_oracle():
    target = EXAMPLES / "mold/target.py"
    with pytest.raises(PermissionError):
        run_mold(target, EXAMPLES / "mold/oracle.py", specification())
    with pytest.raises(ValueError, match="separately"):
        run_mold(target, target, specification(), trusted_execution=True)
    result = subprocess.run([sys.executable, "-m", "tomolab", "mold-run", str(target),
                             "--oracle-file", str(EXAMPLES / "mold/oracle.py"),
                             "--spec", str(EXAMPLES / "mold/spec.json")], capture_output=True)
    assert result.returncode == 2 and b"allow-local-execution" in result.stderr


def test_bad_spec_rejected_before_target_import(tmp_path):
    marker = tmp_path / "imported"
    target = tmp_path / "target.py"
    target.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8")
    with pytest.raises(ValueError):
        run_mold(target, EXAMPLES / "mold/oracle.py", {"secret": "not allowed"}, trusted_execution=True)
    assert not marker.exists()


def test_role_order_controls_evaluator_arguments_and_not_array_order(tmp_path):
    target = tmp_path / "target.py"
    oracle = tmp_path / "oracle.py"
    target.write_text("def implementation(left,right):\n    return left-right+(left==1 and right==0)\n", encoding="utf-8")
    oracle.write_text("def reference(left,right):\n    return left-right\n", encoding="utf-8")
    spec = specification()
    spec["operation"] = "integer-subtraction"
    for var in spec["variables"]:
        var["low"], var["high"] = 0, 1
    spec["variables"].reverse()
    result = run_mold(target, oracle, spec, budget=4, trusted_execution=True)
    assert [row["inputs"] for row in result["failures"]] == [{"x": 1, "y": 0}]


def test_oversized_budget_rejected_before_source_import(tmp_path):
    target = tmp_path / "target.py"
    target.write_text("raise AssertionError('must not import')\n", encoding="utf-8")
    spec = specification()
    for var in spec["variables"]:
        var["low"], var["high"] = 0, 1
    with pytest.raises(ValueError, match="budget exceeds"):
        run_mold(target, EXAMPLES / "mold/oracle.py", spec, budget=5, trusted_execution=True)
