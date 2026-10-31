"""Independent authored comparison fixtures; never real-project evaluation.

One complete execution of this file uses at most 52 primitive callback calls:
44 for an A-D batch, one Oracle-error call, seven clean/flaky/error calls.
All other checks are callback-free. Root separately authorizes rerun costs.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_e8_readiness import setup_data
from tomolab.discovery.evaluation_readiness import EvaluationReadiness
from tomolab.discovery.schema import digest
import tomolab.discovery.knowledge_engine as engine_module
import tomolab.discovery.qualified_comparison as comparison


CALL_COUNTS = {"target": 0, "oracle": 0}


def called(side):
    CALL_COUNTS[side] += 1
    assert sum(CALL_COUNTS.values()) <= 52, "authored comparison callback scope exceeded"


@pytest.fixture(scope="session", autouse=True)
def comparison_callback_scope(record_testsuite_property):
    yield
    record_testsuite_property("E8_comparison_authored_target_calls", CALL_COUNTS["target"])
    record_testsuite_property("E8_comparison_authored_oracle_calls", CALL_COUNTS["oracle"])
    record_testsuite_property("E8_comparison_authored_primitive_calls", sum(CALL_COUNTS.values()))
    record_testsuite_property("E8_comparison_real_project_calls", 0)


def fixed_pool(_spec, **_settings):
    return [{"value": 1}, {"value": 0}]


def readiness(tmp_path, monkeypatch):
    # This changes only a public, data-only candidate pool. No labels or
    # callbacks are given to either planner.
    monkeypatch.setattr(engine_module, "generate_pool", fixed_pool)
    monkeypatch.setattr(comparison, "generate_pool", fixed_pool)
    data = setup_data(tmp_path)
    return data, EvaluationReadiness(**data)


def evaluators(data, target=None, oracle=None):
    def forbidden(**_point):
        pytest.fail("a blocked or preflight-only path executed a callback")
    return {row["target_id"]: {
        "target": target or forbidden,
        "oracle": oracle or (lambda **_point: forbidden(**_point)),
        "implementation_sha256": row["provenance"]["implementation_sha256"],
        "oracle_sha256": row["provenance"]["oracle_sha256"],
    } for row in data["targets"]}


def test_execution_approval_blocked_readiness_and_fake_pass_never_call(tmp_path):
    with pytest.raises(PermissionError, match="explicit trusted"):
        comparison.compare_frozen(EvaluationReadiness(), {}, output=tmp_path/"unapproved.json")
    result = comparison.compare_frozen(EvaluationReadiness(), {}, output=tmp_path/"blocked.json", trusted_execution=True)
    assert result["status"] == "NOT_EXECUTED_READINESS_BLOCKED"
    assert result["target_calls"] == result["oracle_calls"] == 0
    assert not (tmp_path/"blocked.json").exists()
    with pytest.raises(TypeError, match="live EvaluationReadiness"):
        comparison.compare_frozen({"status": "PASS"}, {}, output=tmp_path/"fake.json", trusted_execution=True)


def test_prepare_freezes_all_four_methods_and_d_uses_only_public_roles(tmp_path, monkeypatch):
    data, ready = readiness(tmp_path, monkeypatch)
    before = digest(data["knowledge_snapshot"])
    prepared = comparison.prepare_comparison(ready)
    assert prepared["status"] == "PREPARED"
    assert len(prepared["plans"]) == 8
    assert {p["method"] for p in prepared["plans"]} == {"A", "B", "C", "D"}
    assert prepared["target_calls"] == prepared["oracle_calls"] == 0
    assert all(p["plan"]["final_feedback_allowed"] is False for p in prepared["plans"])
    assert all(c["frozen"] for p in prepared["plans"] for c in p["plan"]["candidates"])
    assert all(p["plan"]["candidates"][0]["source"] == "SOURCE_COUNTEREXAMPLE_ROLE_REPLAY"
               for p in prepared["plans"] if p["method"] == "D")
    assert digest(ready.get_execution_context()["knowledge_snapshot"]) == before
    target = deepcopy(data["targets"][0]); target["spec"]["inputs"][0]["name"] = "renamed"
    replay = comparison._simple_replay([
        {"record_id": "source", "spec": data["targets"][0]["spec"], "inputs": {"value": 0}}
    ], target, [{"renamed": 1}], 2)
    assert replay["candidates"][0]["inputs"] == {"renamed": 0}
    assert replay["target_calls"] == replay["oracle_calls"] == 0


def test_b_c_plan_mutation_is_rejected_before_any_callback(tmp_path, monkeypatch):
    data, ready = readiness(tmp_path, monkeypatch)
    original = ready.get_prepared_plans
    def changed():
        plans = original()
        plans[0]["plan"]["candidates"][0]["inputs"]["value"] = 2
        return plans
    monkeypatch.setattr(ready, "get_prepared_plans", changed)
    with pytest.raises(ValueError, match="plans differ"):
        comparison.compare_frozen(ready, evaluators(data), output=tmp_path/"changed.json", trusted_execution=True)


def test_saved_authorization_and_evaluator_hash_changes_are_rejected(tmp_path, monkeypatch):
    data, ready = readiness(tmp_path, monkeypatch)
    with pytest.raises(PermissionError, match="saved authorization differs"):
        comparison.compare_frozen(ready, evaluators(data), output=tmp_path/"saved.json",
                                  trusted_execution=True, expected_authorization={"status": "PASS"})
    batch = evaluators(data)
    batch[data["targets"][0]["target_id"]]["oracle_sha256"] = "0"*64
    with pytest.raises(PermissionError, match="evaluator identity"):
        comparison.compare_frozen(ready, batch, output=tmp_path/"hash.json", trusted_execution=True)


def test_same_callable_is_not_an_independent_oracle(tmp_path, monkeypatch):
    data, ready = readiness(tmp_path, monkeypatch)
    def forbidden(value):
        pytest.fail("identical callbacks reached execution")
    with pytest.raises(PermissionError, match="evaluator identity"):
        comparison.compare_frozen(ready, evaluators(data, forbidden, forbidden),
                                  output=tmp_path/"same.json", trusted_execution=True)


def test_started_identity_cannot_reopen_with_another_output(tmp_path, monkeypatch):
    data, ready = readiness(tmp_path, monkeypatch)
    usage = data["usage_ledger"]
    usage.claim(data["targets"], {"status": "PASS", "bindings": {"authority_id": usage.authority_id}},
                output=tmp_path/"already-started.json")
    result = comparison.compare_frozen(ready, evaluators(data), output=tmp_path/"alias.json", trusted_execution=True)
    assert result["status"] == "NOT_EXECUTED_READINESS_BLOCKED"
    assert "READINESS_BLOCKED_NO_APPLICABLE_TARGET" in result["readiness"]["blockers"]
    assert not (tmp_path/"alias.json").exists()


def test_a_d_batch_is_frozen_before_first_call_and_replays_share_budget(tmp_path, monkeypatch):
    data, ready = readiness(tmp_path, monkeypatch)
    prepared = []
    original_prepare = comparison.prepare_comparison
    def capture(value):
        result = original_prepare(value)
        prepared.append(deepcopy(result))
        return result
    monkeypatch.setattr(comparison, "prepare_comparison", capture)
    events = []
    batch = {}
    for row in data["targets"]:
        tid, positive = row["target_id"], row["evaluation_role"] == "POSITIVE_REPRODUCTION"
        def oracle(value, tid=tid):
            called("oracle")
            assert prepared and len(prepared[0]["plans"]) == 8
            assert {p["method"] for p in prepared[0]["plans"]} == {"A", "B", "C", "D"}
            assert all(c["frozen"] for p in prepared[0]["plans"] for c in p["plan"]["candidates"])
            events.append((tid, "oracle", value))
            return value
        def target(value, tid=tid, positive=positive):
            called("target"); events.append((tid, "target", value))
            return value + int(positive and value == 0)
        batch[tid] = {"target": target, "oracle": oracle,
                      "implementation_sha256": row["provenance"]["implementation_sha256"],
                      "oracle_sha256": row["provenance"]["oracle_sha256"]}
    before = digest(ready.get_execution_context()["knowledge_snapshot"])
    result = comparison.compare_frozen(ready, batch, output=tmp_path/"complete.json", trusted_execution=True,
                                       host_preflight_wall_seconds=0.125)
    assert result["comparison_status"] == "COMPLETE" and result["full_grid"] is True
    assert result["target_calls"] == result["oracle_calls"] == 22
    assert len(events) == 44
    assert all(r["target_calls"] <= 4 and r["oracle_calls"] <= 4 for r in result["rows"])
    positive = [r for r in result["rows"] if r["evaluation_role"] == "POSITIVE_REPRODUCTION"]
    assert len(positive) == 4 and all(r["found"] and r["replay_status"] == "MATCHED_TWICE" for r in positive)
    assert all(sum(x["phase"] == "independent-replay" for x in r["raw"]) == 2 for r in positive)
    assert all(not r["found"] and not r["control_false_alert"] for r in result["rows"] if r["evaluation_role"] == "CLEAN_CONTROL")
    assert result["generator_feedback"] == 0 and result["verdict"] == "FUNCTIONAL_ONLY_NOT_RESEARCH"
    costs = result["wall_accounting"]
    assert costs["host_preflight_wall_seconds"] == 0.125
    assert costs["host_through_result_assembly_wall_seconds"] == 0.125+costs["runner_through_result_assembly_wall_seconds"]
    assert digest(ready.get_execution_context()["knowledge_snapshot"]) == before


def test_oracle_error_aborts_before_target_and_consumes_batch(tmp_path, monkeypatch):
    data, ready = readiness(tmp_path, monkeypatch)
    decoded = []
    decode = comparison.decode_inputs
    def observed_decode(point, spec):
        decoded.append(deepcopy(point))
        return decode(point, spec)
    monkeypatch.setattr(comparison, "decode_inputs", observed_decode)
    def broken(value):
        called("oracle"); assert decoded
        raise ArithmeticError("authored independent reference error")
    result = comparison.compare_frozen(ready, evaluators(data, oracle=broken),
                                      output=tmp_path/"oracle-error.json", trusted_execution=True)
    assert result["comparison_status"] == "ABORTED_EXECUTION_ERROR"
    assert result["target_calls"] == 0 and result["oracle_calls"] == 1
    assert result["required_errors"] == 1 and result["rows"] == []
    state = data["usage_ledger"].inspect()
    assert state["consumed_tokens"] and not state["open_claim_ids"]
    retry = comparison.compare_frozen(ready, evaluators(data), output=tmp_path/"retry.json", trusted_execution=True)
    assert retry["status"] == "NOT_EXECUTED_READINESS_BLOCKED"


def test_clean_false_alert_and_nondeterministic_replay_are_not_findings(tmp_path, monkeypatch):
    data, _ = readiness(tmp_path, monkeypatch)
    data["targets"].reverse()  # Same predeclared batch; put a clean fixture first.
    ready = EvaluationReadiness(**data)
    oracle_calls, target_calls = [], []
    def oracle(value):
        called("oracle"); oracle_calls.append(value)
        if len(oracle_calls) > 3:
            raise ArithmeticError("authored stop after first clean row")
        return value
    def changing(value):
        called("target"); target_calls.append(value)
        return value + (0 if len(target_calls) == 2 else 1)
    result = comparison.compare_frozen(ready, evaluators(data, changing, oracle),
                                      output=tmp_path/"clean-flaky.json", trusted_execution=True)
    row = result["rows"][0]
    assert row["evaluation_role"] == "CLEAN_CONTROL"
    assert row["control_false_alert"] is True and row["found"] is False
    assert row["replay_status"] == "NONDETERMINISTIC_QUARANTINED"
    assert result["invalid_replay_rows"] == 1 and result["required_errors"] == 2
    assert result["control_false_alerts"] == 1
    assert result["oracle_calls"] == 4 and result["target_calls"] == 3
    assert all(not r["found"] for r in result["rows"])


def test_cooperative_wall_budget_aborts_before_first_callback(tmp_path, monkeypatch):
    data, ready = readiness(tmp_path, monkeypatch)
    state = {"executing": False, "clock_calls": 0}
    def clock():
        if not state["executing"]:
            return 0.0
        state["clock_calls"] += 1
        return 0.0 if state["clock_calls"] == 1 else 16.0
    monkeypatch.setattr(comparison, "time", SimpleNamespace(perf_counter=clock))
    usage = ready.get_usage_ledger()
    def execution_phase():
        state["executing"] = True
        return usage
    monkeypatch.setattr(ready, "get_usage_ledger", execution_phase)
    result = comparison.compare_frozen(ready, evaluators(data), output=tmp_path/"timeout.json", trusted_execution=True)
    assert result["comparison_status"] == "ABORTED_EXECUTION_ERROR"
    assert result["target_calls"] == result["oracle_calls"] == 0
    assert result["error"]["type"] == "TimeoutError"
    assert result["execution_timeout_policy"] == "COOPERATIVE_CHECKS_NOT_HOST_CALLBACK_PREEMPTION"


def test_finite_json_comparison_respects_declared_tolerance_and_bool_types():
    policy = {"absolute_tolerance": 1e-10, "relative_tolerance": 1e-8}
    assert comparison.equivalent({"x": [1.0, 2]}, {"x": [1.0+1e-12, 2]}, policy)
    assert not comparison.equivalent(True, 1, policy)
    assert not comparison.equivalent(1.0, 1.01, policy)
    with pytest.raises(ValueError):
        comparison.equivalent(float("nan"), 0, policy)
