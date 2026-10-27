"""Public integration measurements on newly authored pure Python fixtures.

Development and final fixtures are separate. The final plan is frozen before
final calls and no final labels return to the generator. This is reproducible
software QA, not a blind or real-world generalization benchmark.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tomolab.mold.property_testing import run_properties
from tomolab.mold.schema import default_spec, digest
from tomolab.mold.service import plan_mold
from tomolab.mold.structural import compile_relation, check_consistency, filter_hypotheses


def reference(x, y):
    return x + y


def development_threshold(x, y):
    return x + y + (1 if x >= 3 else 0)


def final_negative_residue(x, y):
    return x + y + (2 if x < 0 and (2 * x - y) % 5 == 2 else 0)


def final_clean(x, y):
    return x + y


def evaluate():
    code = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "tomolab").rglob("*.py"))}
    freeze_hash = digest(code)
    spec = default_spec("e4-public-development", -8, 8)
    dev = run_properties(development_threshold, reference, spec, budget=48, max_examples=128,
                         shrink_budget=96, seed=103, trusted_execution=True)
    assert dev["snapshot"]["frozen"] is True
    assert dev["metrics"]["duplicate_candidates"] == 0
    assert dev["metrics"]["oracle_calls"] <= dev["metrics"]["hard_call_limit"]
    assert dev["subjective_assessment"]["used_for_verdict"] is False
    expressions = ["x >= 3", "x < 0", "x + y == 0", "abs(x - y) <= 2"]
    relations = [compile_relation(expression, spec) for expression in expressions]
    filtered = filter_hypotheses(spec, relations, dev["evidence"])
    consistency = []
    for expressions in (["x >= 3", "x < 0"],
                        ["x < 0", "(2 * x - y) % 5 == 2"],
                        ["abs(x - y) <= 2", "x + y >= 3"]):
        predicates = [compile_relation(expression, spec) for expression in expressions]
        before = time.perf_counter()
        enum = check_consistency(spec, predicates)
        z3 = check_consistency(spec, predicates, backend="z3")
        assert enum["status"] == z3["status"]
        consistency.append({"expressions": expressions, "enumeration": enum, "z3": z3,
                            "wall_seconds": time.perf_counter() - before})
    final = []
    for name, function in (("negative-residue", final_negative_residue), ("clean", final_clean)):
        final_spec = {**spec, "task_id": "e4-public-final-" + name}
        plan = plan_mold(dev["snapshot"], final_spec, budget=64, seed=211)
        assert plan["final_feedback_allowed"] is False
        plan_hash = digest(plan)
        before = time.perf_counter()
        failures = 0
        for candidate in plan["candidates"]:
            point = candidate["inputs"]
            failures += function(point["x"], point["y"]) != reference(point["x"], point["y"])
        elapsed = time.perf_counter() - before
        assert digest(plan) == plan_hash
        points = [digest(p["inputs"]) for p in plan["candidates"]]
        final.append({"fixture": name, "candidate_count": len(points),
                      "unique_candidates": len(set(points)), "duplicate_candidate_rate": 1 - len(set(points)) / len(points),
                      "oracle_calls": len(points), "mismatches": failures,
                      "calls_per_observed_mismatch": len(points) / failures if failures else None,
                      "wall_seconds": elapsed, "feedback_calls": 0,
                      "plan_sha256": plan_hash, "snapshot_sha256": plan["snapshot"]["receipt"]["sha256"]})
    assert next(row for row in final if row["fixture"] == "clean")["mismatches"] == 0
    code_after = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in code}
    assert digest(code_after) == freeze_hash
    return {"schema": "tomolab-e4-integration-evaluation-v1", "status": "PASS",
            "source_freeze_sha256": freeze_hash, "code_sha256": code,
            "fixtures": "NEW_PUBLIC_PURE_PYTHON_FUNCTIONS", "old_holdouts_reused": False,
            "blinding": "NOT_BLIND", "generalization": "NOT_ESTABLISHED",
            "development": {key: dev[key] for key in ("status", "metrics", "timing", "shrink", "oracle_verdict", "subjective_assessment")},
            "ast_hypotheses": {"initial": len(relations), "remaining": len(filtered["version_space"]),
                               "status": filtered["status"]},
            "consistency": consistency, "final": final,
            "information_boundary": {"final_labels_sent": 0, "post_freeze_mutation": False,
                                     "isolation": dev["isolation"],
                                     "scope": "typed transport checks; Docker isolation checked separately in CI"}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate()
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
