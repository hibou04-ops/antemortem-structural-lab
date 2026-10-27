import importlib.util
from itertools import product
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest


def evaluator():
    path = Path(__file__).resolve().parents[1] / "scripts/evaluate-e6.py"
    spec = importlib.util.spec_from_file_location("e6_evaluation_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contract(module):
    return json.loads(module.CONTRACT.read_text(encoding="utf-8"))


def test_public_independent_models_match_declared_effects_including_disabled_noops():
    module = evaluator()
    from tomolab.discovery.temporal import simulate_trace, validate_temporal_contract
    for case in module.load_module(module.PUBLIC).CASES:
        if case["kind"] != "stateful":
            continue
        spec, _ = module.prepare(case)
        temporal = validate_temporal_contract(case["temporal_contract"], spec)
        actions = [row["name"] for row in temporal["actions"]]
        # This checks the independently authored model, not the mutant target.
        for length in range(4):
            for trace in product(product(actions, (-1, 0, 1)), repeat=length):
                replay = simulate_trace({"trace": list(trace)}, spec, temporal)
                assert replay["valid"], (case["case_id"], trace, replay)
                state = dict(case["initial"])
                for index, (action, argument) in enumerate(trace):
                    state = case["model_step"](state, action, argument)
                    assert state == replay["transitions"][index]["post"], (case["case_id"], trace)


def test_meter_distinguishes_whole_trace_and_real_transition_invocations():
    module = evaluator()
    case = module.load_module(module.PUBLIC).case_by_id("dev-multiplicity")
    config = contract(module)["development"]
    meter = module.Meter(case, config, time.perf_counter(), time.perf_counter() + 10)
    point = {"trace": [["insert", 1], ["insert", 0], ["remove", 1]]}
    assert meter.predicate(point)
    metrics, rows = meter.metrics()
    assert metrics["trace_evaluations"] == 1
    assert metrics["actual_model_transition_calls"] == metrics["actual_target_transition_calls"] == 3
    assert metrics["actual_primitive_invocations"] == metrics["first_failure_primitive_invocations"] == 6
    assert rows[0]["first_failure_index"] == 2
    assert meter.predicate(point)
    assert meter.metrics()[0]["duplicate_failure_rate"] == 0.5


def test_native_live_operations_are_never_memoized():
    module = evaluator()
    case = module.load_module(module.PUBLIC).case_by_id("dev-multiplicity")
    meter = module.Meter(case, contract(module)["development"], time.perf_counter(), time.perf_counter() + 10)
    make_target, make_model, operations, snapshot = meter.bindings()
    target, model = make_target(), make_model()
    for _ in range(2):
        operations["insert"]["model"](model, 0)
        operations["insert"]["target"](target, 0)
    assert snapshot(model)["count"] == snapshot(target)["count"] == 2
    assert meter.metrics()[0]["actual_primitive_invocations"] == 4


def test_native_factory_episodes_are_not_whole_trace_predicate_callbacks():
    module = evaluator()
    case = module.load_module(module.PUBLIC).case_by_id("dev-multiplicity")
    config = contract(module)["development"] | {"trace_callback_cap": 1}
    meter = module.Meter(case, config, time.perf_counter(), time.perf_counter() + 10)
    for _ in range(2):
        make_target, make_model, operations, _ = meter.bindings()
        target, model = make_target(), make_model()
        operations["insert"]["model"](model, 0)
        operations["insert"]["target"](target, 0)
    measured = meter.metrics()[0]
    assert measured["whole_trace_callbacks"] == 0
    assert measured["native_factory_episodes"] == 2
    assert measured["actual_primitive_invocations"] == 4


def test_projection_failure_is_evaluator_error_not_a_finding():
    module = evaluator()
    public = module.load_module(module.PUBLIC).case_by_id("dev-multiplicity")
    def broken_projection(state):
        raise ValueError("broken projector")
    case = dict(public, project=broken_projection)
    meter = module.Meter(case, contract(module)["development"], time.perf_counter(), time.perf_counter() + 10)
    with pytest.raises(ValueError, match="broken projector"):
        meter.predicate({"trace": [["insert", 0]]})
    assert meter.metrics()[0]["confirmed_family"] is None


def test_crosshair_candidate_validation_does_not_swallow_oracle_projection_errors(tmp_path, monkeypatch):
    module = evaluator()
    import tomolab.discovery.symbolic as symbolic
    case = module.load_module(module.PUBLIC).case_by_id("dev-multiplicity")
    def broken_projection(state):
        raise ValueError("independent projection broke")
    meter = module.Meter(dict(case, project=broken_projection), contract(module)["development"],
                         time.perf_counter(), time.perf_counter() + 10)
    monkeypatch.setattr(symbolic, "check_contract", lambda *args, **kwargs: {
        "status": "SYMBOLIC_COUNTEREXAMPLE_CANDIDATE", "candidates": [{"trace": [["insert", 1]]}],
        "diagnostics": [], "tool_version": "test"})
    spec, _ = module.prepare(case)
    with pytest.raises(ValueError, match="independent projection broke"):
        module.crosshair(case, spec, tmp_path, meter, 1.0)
    assert meter.metrics()[0]["confirmed_family"] is None


def test_final_cli_cannot_substitute_a_different_baseline_after_freeze(tmp_path):
    module = evaluator()
    frozen_root = tmp_path / "frozen-baseline"
    replacement = tmp_path / "replacement-baseline"
    module.save(tmp_path / "FINAL_FREEZE.json", {"baseline_root": str(frozen_root)})
    args = SimpleNamespace(state_dir=tmp_path, phase="final", case=None, baseline_root=replacement)
    with pytest.raises(ValueError, match="match the frozen baseline"):
        module.run_phase(args)
    assert not list(tmp_path.glob("final-consumed-*.jsonl"))


def test_clean_project_control_oracle_preserves_case_and_punctuation_semantics():
    module = evaluator()
    case = module.load_module(module.PUBLIC).case_by_id("control-normalization")
    for length in range(4):
        for letters in product("AaB .\t\n", repeat=length):
            value = "".join(letters)
            assert case["target"](value) == case["oracle"](value)


def test_budget_abort_is_not_caught_as_an_ordinary_target_exception():
    module = evaluator()
    case = module.load_module(module.PUBLIC).case_by_id("dev-multiplicity")
    config = contract(module)["development"] | {"actual_target_transition_cap": 0}
    meter = module.Meter(case, config, time.perf_counter(), time.perf_counter() + 10)
    with pytest.raises(module.EvaluationStop, match="TRANSITION_BUDGET"):
        meter.predicate({"trace": [["insert", 0]]})
    assert not meter.metrics()[0]["confirmed_family"]
    assert not issubclass(module.EvaluationStop, Exception)


def test_partial_or_changed_final_family_grid_is_rejected():
    module = evaluator()
    cases = module.load_module(module.PUBLIC).CASES
    config = contract(module)
    module.validate_suite(cases, config)
    with pytest.raises(ValueError, match="exactly once"):
        module.validate_suite(cases[:-1], config)
    with pytest.raises(ValueError, match="incomplete"):
        module.validate_grid([], cases, config["final"]["methods"], config["seeds"])
    partial = [{"method": "E6-frozen", "family_id": "snapshot-restoration", "seed": 13}]
    assert module.verdict(partial, config)["status"] == "INCONCLUSIVE"


def test_private_benchmark_labels_do_not_change_generator_initialization():
    module = evaluator()
    from tomolab.discovery.temporal_protocol import validate_request
    for case in module.load_module(module.PUBLIC).CASES:
        spec, ir = module.prepare(case)
        altered = dict(case, family_id="hidden-other-family", expected_fault=not case["expected_fault"], case_id="hidden-private-case")
        assert module.prepare(altered) == (spec, ir)
        assert module.source_case_id(altered) == case["case_id"]
        packet = {"action": "init", "spec": spec, "public_ir": ir}
        if case["kind"] == "stateful":
            packet["temporal_contract"] = case["temporal_contract"]
            packet = validate_request(packet)
        encoded = module.canonical(packet)
        assert case["family_id"] not in encoded
        assert case["case_id"] not in encoded
        assert "expected_fault" not in encoded


def test_false_alert_by_any_required_baseline_invalidates_the_final_comparison():
    module = evaluator()
    config = contract(module)
    rows = []
    for case in module.load_module(module.PUBLIC).CASES:
        for method in config["final"]["methods"]:
            for seed in config["seeds"]:
                unsupported = method == "NativeStateful-frozen" and case["kind"] == "static"
                rows.append({"case_id": case["case_id"], "family_id": case["family_id"], "method": method,
                    "seed": seed, "expected_fault": case["expected_fault"], "status": "NOT_COMPARABLE" if unsupported else "COMPLETE",
                    "confirmed_family": case["family_id"] if case["expected_fault"] else None,
                    "control_false_alert": False, "wall_seconds": 1 if method == "E6-frozen" else 2,
                    "first_failure_primitive_invocations": 2 if method == "E6-frozen" else 4})
    assert module.verdict(rows, config)["status"] == "EFFICIENCY_IMPROVED_ONLY"
    control = next(row for row in rows if row["method"] == "NativeHypothesis-frozen" and not row["expected_fault"])
    control["control_false_alert"] = True
    assert module.verdict(rows, config)["status"] == "INCONCLUSIVE"


def test_consumed_final_ledger_and_existing_receipt_are_not_overwritten(tmp_path):
    module = evaluator()
    manifest = {"private_suite_sha256": "a" * 64, "sha256": "b" * 64}
    ledger = module.consume_final_once(tmp_path, manifest)
    original = ledger.read_bytes()
    with pytest.raises(FileExistsError):
        module.consume_final_once(tmp_path, manifest)
    assert ledger.read_bytes() == original
    (tmp_path / "result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError):
        module.run_worker({"folder": str(tmp_path)})


def test_lower_calls_without_lower_total_wall_is_not_efficiency():
    module = evaluator()
    config = contract(module)
    rows = []
    for family in config["families"]:
        for method in ("E6", "E5", "NativeHypothesis", "NativeStateful"):
            rows.append({"method": method, "family_id": family, "seed": 13, "expected_fault": True,
                         "status": "COMPLETE", "confirmed_family": family,
                         "first_failure_primitive_invocations": 2 if method == "E6" else 4,
                         "wall_seconds": 3 if method == "E6" else 2})
    assert module.verdict(rows, config)["status"] == "NO_IMPROVEMENT"


def test_infrastructure_failure_on_clean_control_is_inconclusive():
    module = evaluator()
    rows = [{"method": "E6", "status": "ERROR", "expected_fault": False}]
    assert module.verdict(rows, contract(module))["status"] == "INCONCLUSIVE"
