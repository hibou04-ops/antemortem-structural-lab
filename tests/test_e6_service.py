from copy import deepcopy

import pytest

from tomolab.discovery.native_stateful import evaluate_temporal_trace, generate_stateful_plan, run_native_stateful
from tomolab.discovery.temporal import simulate_trace
from test_e6_efficiency import stack_contract


class Subject:
    def __init__(self, buggy=False):
        self.count = 0
        self.buggy = buggy

    def step(self, action, argument):
        if action == "push":
            self.count += 1
        elif not self.buggy or argument != 0:
            self.count -= 1

    def snapshot(self):
        return {"size":self.count}


def callbacks(counts=None):
    counts = {} if counts is None else counts
    def invoke(which, action):
        def call(subject, argument):
            counts[which] = counts.get(which, 0) + 1
            return subject.step(action, argument)
        return call
    return {action:{"target":invoke("target",action),"model":invoke("model",action)} for action in ("push","pop")}


def test_native_stateful_actual_callbacks_include_shrinking_and_valid_replay():
    spec, contract = stack_contract()
    counts = {}
    result = run_native_stateful(spec, contract, lambda:Subject(True), Subject, callbacks(counts),
        snapshot=lambda subject:subject.snapshot(), budget=256, steps=6, seed=7, time_budget=10, trusted_execution=True)
    assert result["status"] == "COUNTEREXAMPLE_FOUND"
    assert result["witness"] and len(result["witness"]) == 2
    assert counts["target"] == counts["model"] == result["model_transition_calls"] <= 256
    inputs = {"trace":result["witness"]}
    assert simulate_trace(inputs, spec, contract)["valid"]
    replay = evaluate_temporal_trace(spec, contract, lambda:Subject(True), Subject, callbacks(), inputs,
        snapshot=lambda subject:subject.snapshot(), trusted_execution=True)
    assert replay["failed"] and replay["first_failure_index"] == 1


def test_public_stateful_plan_has_no_callbacks_or_final_feedback():
    spec, contract = stack_contract()
    plan = generate_stateful_plan(spec, contract, seed=19, max_examples=12, steps=6, budget=48)
    assert plan["frozen"] and plan["candidates"]
    assert plan["target_calls"] == plan["oracle_calls"] == 0
    assert plan["final_feedback_allowed"] is False
    assert all(simulate_trace(point, spec, contract)["valid"] for point in plan["candidates"])


def test_oracle_errors_propagate_and_invalid_trace_never_calls_factories():
    spec, contract = stack_contract()
    called = []
    with pytest.raises(ValueError, match="precondition"):
        evaluate_temporal_trace(spec, contract, lambda:called.append(1), lambda:called.append(2), callbacks(),
            {"trace":[["pop",0]]}, snapshot=lambda subject:subject.snapshot(), trusted_execution=True)
    assert called == []
    operations = callbacks()
    def broken_model(subject, argument):
        raise RuntimeError("independent model failed")
    operations["push"]["model"] = broken_model
    with pytest.raises(RuntimeError, match="independent model"):
        run_native_stateful(spec, contract, Subject, Subject, operations,
            snapshot=lambda subject:subject.snapshot(), budget=8, steps=4, trusted_execution=True)


def test_native_stateful_control_and_hard_transition_budget():
    spec, contract = stack_contract()
    counts = {}
    result = run_native_stateful(spec, contract, Subject, Subject, callbacks(counts),
        snapshot=lambda subject:subject.snapshot(), budget=11, steps=6, trusted_execution=True)
    assert result["status"] == "NOT_REFUTED_WITHIN_BUDGET"
    assert result["target_transition_calls"] == counts["target"] == counts["model"] == 11


def test_native_registration_precedes_actual_callback_and_requires_trust():
    spec, contract = stack_contract()
    registered = []
    operations = callbacks()
    def target(subject, argument):
        assert registered and registered[-1]["trace"][-1] == ["push", argument]
        subject.step("push", argument)
    operations["push"]["target"] = target
    run_native_stateful(spec, contract, Subject, Subject, operations, snapshot=lambda subject:subject.snapshot(),
        budget=3, steps=1, trusted_execution=True, before_trace_callback=registered.append)
    with pytest.raises(PermissionError):
        run_native_stateful(spec, contract, lambda:pytest.fail("untrusted factory executed"), Subject, callbacks(),
            snapshot=lambda subject:subject.snapshot())


def test_real_temporal_service_learns_freezes_shrinks_and_counts_every_callback():
    from tomolab.discovery.temporal_service import run_temporal
    spec, contract = stack_contract()
    counts = {}
    result = run_temporal(lambda:Subject(True), Subject, callbacks(counts),
        snapshot=lambda subject:subject.snapshot(), spec=spec, temporal_contract=contract,
        budget=32, shrink_budget=128, seed=7, time_budget=15, pool_size=12, trusted_execution=True)
    assert result["status"] == "COUNTEREXAMPLE_FOUND"
    assert result["snapshot"]["frozen"] and result["final_feedback_allowed"] is False
    assert result["snapshot"]["temporal_metrics"]["activation_count"] == 1
    assert result["evidence"] and all(set(event) == {"kind","evidence_id","inputs","invariant","category","signature","first_failure_index"}
                                      for event in result["evidence"])
    assert result["metrics"]["target_transition_calls"] == counts["target"] == counts["model"]
    assert counts["target"] <= result["metrics"]["hard_transition_limit"]
    assert result["counterexample"]["replay"] == "MATCHED_TWICE"
    assert result["timing"]["worker_dispatch"]["requests"] > 0
    assert result["shrink"]["generator_feedback"] is False


def test_clean_service_keeps_native_generation_without_temporal_activation():
    from tomolab.discovery.temporal_service import run_temporal
    spec, contract = stack_contract()
    counts = {}
    result = run_temporal(lambda:Subject(False), Subject, callbacks(counts),
        snapshot=lambda subject:subject.snapshot(), spec=spec, temporal_contract=contract,
        budget=14, shrink_budget=0, seed=17, time_budget=10, pool_size=8, trusted_execution=True)
    assert result["status"] == "NOT_REFUTED_WITHIN_BUDGET"
    assert result["snapshot"]["temporal_metrics"]["activation_count"] == 0
    assert result["metrics"]["guided_trace_calls"] == 0
    assert counts["target"] == counts["model"] == result["metrics"]["target_transition_calls"] == 14


def test_real_learned_mold_plans_for_renamed_list_implementation_without_final_feedback():
    from tomolab.discovery.schema import digest
    from tomolab.discovery.stateful import trace_spec
    from tomolab.discovery.temporal_service import run_temporal
    from tomolab.discovery.temporal_transfer import transfer_temporal
    spec, contract = stack_contract()
    learned = run_temporal(lambda:Subject(True), Subject, callbacks(), snapshot=lambda subject:subject.snapshot(),
        spec=spec, temporal_contract=contract, budget=64, shrink_budget=0, pool_size=12, time_budget=10, trusted_execution=True)
    assert learned["status"] == "COUNTEREXAMPLE_FOUND"
    frozen_hash = digest(learned["snapshot"])
    renamed = trace_spec(["enqueue","dequeue"], {"kind":"int","min":-1,"max":1}, name="operations", max_steps=6)
    target_contract = deepcopy(contract)
    target_contract["state"][0]["name"] = "length"
    target_contract["actions"][0]["name"] = "enqueue"
    target_contract["actions"][1]["name"] = "dequeue"
    plan = transfer_temporal(learned["snapshot"], renamed, target_contract, budget=12, pool_size=16)
    assert plan["gate"]["status"] == "APPLICABLE_FOR_PROBING"

    class ListSubject:
        def __init__(self, buggy=False):
            self.items, self.buggy = [], buggy

    def insert(subject, argument):
        subject.items.append(argument)

    def remove(subject, argument):
        if not subject.buggy or argument != 0:
            subject.items.pop()

    operations = {"enqueue":{"target":insert,"model":insert},"dequeue":{"target":remove,"model":remove}}
    results = [evaluate_temporal_trace(renamed, target_contract, lambda:ListSubject(True), ListSubject,
        operations, proposal["inputs"], snapshot=lambda subject:{"size":len(subject.items)}, trusted_execution=True)
        for proposal in plan["candidates"]]
    assert any(result["failed"] for result in results)
    assert plan["final_feedback_allowed"] is False and plan["bug_recurrence"] == "UNKNOWN"
    assert digest(learned["snapshot"]) == frozen_hash


@pytest.mark.parametrize("public_plan", [False, True])
def test_hypothesis_wrapped_internal_budget_is_explicitly_incomplete(monkeypatch, public_plan):
    import tomolab.discovery.native_stateful as native
    from hypothesis.errors import FlakyStrategyDefinition
    from tomolab.discovery.hypothesis_adapter import BudgetExhausted
    from tomolab.discovery.temporal import apply_action, initial_state
    spec, contract = stack_contract()
    captured = {}

    def machine(spec, contract, argument_type, **callbacks_):
        captured.update(callbacks_)
        return lambda: None

    def runner(factory, settings):
        subject = captured["start"]()
        transition = apply_action(initial_state(contract), "push", 0, 0, None, contract, spec)
        captured["step"](subject, [["push",0]], transition)
        try:
            captured["check"]()
        except BudgetExhausted as stop:
            raise FlakyStrategyDefinition("controlled data-tree interruption wrapper") from stop

    monkeypatch.setattr(native, "_machine", machine)
    monkeypatch.setattr(native, "run_state_machine_as_test", runner)
    if public_plan:
        result = native.generate_stateful_plan(spec, contract, budget=1)
    else:
        result = native.run_native_stateful(spec, contract, Subject, Subject, callbacks(),
            snapshot=lambda subject:subject.snapshot(), budget=1, trusted_execution=True)
        assert result["target_transition_calls"] == result["model_transition_calls"] == 1
        assert result["shrinking"] == "RESOURCE_BUDGET" and result["witness"] is None
    assert result["stop"] == "RESOURCE_BUDGET"
    assert result["resource_stop"]["hypothesis_wrapper"] is True


@pytest.mark.parametrize("prior_internal_stop", [False, True])
def test_unrelated_hypothesis_nondeterminism_still_propagates(monkeypatch, prior_internal_stop):
    import tomolab.discovery.native_stateful as native
    from hypothesis.errors import FlakyStrategyDefinition
    from tomolab.discovery.hypothesis_adapter import BudgetExhausted
    from tomolab.discovery.temporal import apply_action, initial_state
    spec, contract = stack_contract()
    captured = {}

    def machine(spec, contract, argument_type, **callbacks_):
        captured.update(callbacks_)
        return lambda: None

    def runner(factory, settings):
        if prior_internal_stop:
            transition = apply_action(initial_state(contract), "push", 0, 0, None, contract, spec)
            captured["step"](captured["start"](), [["push",0]], transition)
            try:
                captured["check"]()
            except BudgetExhausted:
                pass
        # This exception has no causal chain to the internal cancellation.
        raise FlakyStrategyDefinition("independent strategy nondeterminism")

    monkeypatch.setattr(native, "_machine", machine)
    monkeypatch.setattr(native, "run_state_machine_as_test", runner)
    with pytest.raises(FlakyStrategyDefinition, match="independent strategy"):
        native.run_native_stateful(spec, contract, Subject, Subject, callbacks(),
            snapshot=lambda subject:subject.snapshot(), budget=1, trusted_execution=True)
