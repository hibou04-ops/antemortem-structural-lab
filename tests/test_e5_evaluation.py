import importlib.util
import json
from pathlib import Path
import time

import pytest


def evaluation_module():
    path = Path(__file__).resolve().parents[1] / "scripts/evaluate-e5.py"
    spec = importlib.util.spec_from_file_location("e5_evaluation_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def completed(method, family, seed=17, *, wall=2.0, calls=4, fault=True):
    return {"method": method, "phase": "final", "case_id": family, "family_id": family,
            "expected_fault": fault, "seed": seed, "status": "COMPLETE",
            "confirmed_family": family if fault else None, "control_false_alert": False,
            "first_failure_oracle_calls": calls if fault else None, "oracle_calls": calls,
            "wall_seconds": wall}


def test_efficiency_verdict_uses_wall_and_calls_and_support_strata():
    m = evaluation_module()
    rows = []
    for family in ("one", "two", "three"):
        rows += [completed("E5", family, wall=1, calls=2), completed("Hypothesis", family)]
    rows.append(completed("E4", "one"))
    assert m.verdict(rows)["status"] == "EFFICIENCY_IMPROVED_ONLY"
    # Lower Oracle-call count without lower total cost is not efficiency.
    for row in rows:
        if row["method"] == "E5":
            row["wall_seconds"] = 3
    assert m.verdict(rows)["status"] == "NO_IMPROVEMENT"


def test_duplicate_inputs_seeds_and_source_aware_calls_do_not_inflate_fault_count():
    m = evaluation_module()
    rows = [completed("Hypothesis", "one", seed=seed) for seed in (17, 43, 101)]
    rows.append(completed("CrossHair", "one", calls=1))
    summary = {row["method"]: row for row in m.summary(rows)}
    assert summary["Hypothesis"]["confirmed_unique_fault_families"] == 1
    assert summary["CrossHair"]["oracle_calls"] is None
    assert summary["CrossHair"]["independent_concrete_replay_calls"] == 1


def test_final_attempt_ledger_refuses_a_second_attempt(tmp_path):
    m = evaluation_module()
    manifest = {"private_suite_sha256": "a" * 64, "sha256": "b" * 64}
    path = m.consume_final_once(tmp_path, manifest)
    first = path.read_bytes()
    with pytest.raises(FileExistsError):
        m.consume_final_once(tmp_path, manifest)
    assert path.read_bytes() == first
    assert json.loads(first)["event"] == "FINAL_ATTEMPT_STARTED"


def test_source_drift_is_rejected_before_any_final_target_can_run(tmp_path, monkeypatch):
    m = evaluation_module()
    private = tmp_path / "withheld.py"
    private.write_text("# original fixture\n", encoding="utf-8")
    hashes = {"tomolab/example.py": "a" * 64}
    monkeypatch.setattr(m, "product_hashes", lambda: hashes)
    manifest = {"product": dict(hashes), "private_suite_path": str(private),
                "private_suite_sha256": m.file_sha(private), "source_molds": {}}
    manifest["sha256"] = m.digest(manifest)
    m.verify_freeze(tmp_path, manifest)
    hashes["tomolab/example.py"] = "c" * 64
    with pytest.raises(ValueError, match="freeze drifted"):
        m.verify_freeze(tmp_path, manifest)


def test_independent_meter_counts_actual_replays_and_canonical_outcomes():
    m = evaluation_module()
    module = m.load_module(m.PUBLIC_CASES)
    case = module.case_by_id("dev-add-order")
    spec, _ = m.prepared_case(case)
    meter = m.Meter(case, spec, 2, time.perf_counter(), time.perf_counter() + 10)
    assert meter.predicate({"x": 0, "y": 1}) is True
    assert meter.predicate({"x": 0, "y": 1}) is True
    metrics = meter.metrics()
    assert metrics["oracle_calls"] == metrics["target_calls"] == 2
    assert metrics["unique_failing_inputs"] == 1
    assert metrics["duplicate_failure_rate"] == 0.5
    with pytest.raises(m.EvaluationBudgetStop):
        meter.predicate({"x": 0, "y": 1})


def test_float_reference_does_not_create_a_negative_zero_false_finding():
    m = evaluation_module()
    cases = m.load_module(m.PUBLIC_CASES)
    case = cases.case_by_id("dev-absolute")
    spec, _ = m.prepared_case(case)
    meter = m.Meter(case, spec, 2, time.perf_counter(), time.perf_counter() + 10)
    assert meter.predicate({"value": -0.0}) is False
    assert meter.predicate({"value": -0.5}) is True


def test_timeouts_and_failed_controls_are_inconclusive():
    m = evaluation_module()
    cases = m.load_module(m.PUBLIC_CASES)
    case = cases.case_by_id("dev-add-order")
    spec, _ = m.prepared_case(case)
    meter = m.Meter(case, spec, 128, time.perf_counter(), time.perf_counter() - 1)
    with pytest.raises(m.EvaluationBudgetStop, match="WALL_TIMEOUT"):
        meter.predicate({"x": 0, "y": 1})
    rows = [completed("E5-frozen", family) for family in ("one", "two", "three")]
    rows += [completed("Hypothesis-strategy-plan", family) for family in ("one", "two", "three")]
    control = completed("E5-frozen", "control", fault=False)
    control["status"] = "WORKER_ERROR"
    assert m.verdict([*rows, control])["status"] == "INCONCLUSIVE"


def test_existing_result_is_never_reused_as_a_fresh_run(tmp_path):
    m = evaluation_module()
    (tmp_path / "result.json").write_text('{"status":"COMPLETE"}', encoding="utf-8")
    with pytest.raises(FileExistsError, match="already exists"):
        m.run_worker({"folder": str(tmp_path)})


def test_final_contract_rejects_partial_family_control_and_seed_selection():
    m = evaluation_module()
    contract = json.loads(m.CONTRACT.read_text(encoding="utf-8"))
    cases = m.load_module(m.PUBLIC_CASES).CASES
    m.validate_final_suite(cases, contract)
    with pytest.raises(ValueError, match="every family"):
        m.validate_final_suite(cases[:-1], contract)
    incomplete = [completed("E5-frozen", case["family_id"]) | {"case_id": case["case_id"]} for case in cases]
    with pytest.raises(ValueError, match="incomplete"):
        m.validate_final_records(incomplete, cases, ["E5-frozen"], [17, 43, 101])
    partial = []
    for family in ("one", "two", "three"):
        partial += [completed("E5-frozen", family, wall=1, calls=2), completed("Hypothesis-strategy-plan", family)]
    assert m.verdict(partial)["status"] == "INCONCLUSIVE"


def test_freeze_requires_all_preregistered_development_molds(tmp_path):
    m = evaluation_module()
    suite = tmp_path / "suite.py"
    suite.write_text("from benchmarks.e5_public_cases import CASES\n", encoding="utf-8")
    with pytest.raises(ValueError, match="all required public development"):
        m.freeze_state(tmp_path, suite)
