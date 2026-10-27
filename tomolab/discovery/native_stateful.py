"""Trusted evaluator adapters for Hypothesis' native rule-based state machines.

Only bounded integer action arguments and declared scalar state projections are
supported. Pure public-plan generation never accepts target/Oracle callbacks.
"""
from copy import deepcopy
import math
import time

from hypothesis import HealthCheck, Phase, seed as hypothesis_seed, settings, strategies as st
from hypothesis.errors import FlakyStrategyDefinition
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, precondition, rule, run_state_machine_as_test

from .hypothesis_adapter import BudgetExhausted, type_strategy
from .schema import canonical, integer, validate_spec, validate_value
from .service import _outcome


class StateViolation(AssertionError):
    """An actual independent model/implementation discrepancy."""


def _wraps_stop(error, signal):
    """Recognize this run's exact resource stop, never arbitrary flakiness."""
    pending, seen = [error], set()
    while pending:
        item = pending.pop()
        if item is signal:
            return True
        if id(item) in seen:
            continue
        seen.add(id(item))
        pending.extend(value for value in (item.__cause__, item.__context__) if value is not None)
    return False


def _public(spec, contract):
    from .temporal import validate_temporal_contract
    spec = validate_spec(spec)
    contract = validate_temporal_contract(contract, spec)
    if spec["inputs"][0]["type"]["min_size"] != 0:
        raise ValueError("native EFSM adapter requires zero-minimum prefix-closed traces")
    argument = spec["inputs"][0]["type"]["items"]["items"][1]
    if argument["kind"] != "int" or argument["max"] - argument["min"] > 128:
        raise ValueError("native EFSM adapter requires at most 129 bounded integer argument values")
    return spec, contract, argument


def _projection(value, contract, *, strict=True):
    if not isinstance(value, dict) or set(value) != {s["role"] for s in contract["state"]}:
        raise ValueError("snapshot must contain exactly the declared state roles")
    if strict:
        for item in contract["state"]:
            validate_value(value[item["role"]], item["type"])
    canonical(value)
    return deepcopy(value)


def _operations(operations, contract):
    if not isinstance(operations, dict) or set(operations) != {a["name"] for a in contract["actions"]}:
        raise ValueError("trusted callbacks must match the declared actions")
    for operation in operations.values():
        if not isinstance(operation, dict) or set(operation) not in ({"target", "model"}, {"target", "model", "arguments"}):
            raise ValueError("operation requires target and model callbacks")
        if not callable(operation["target"]) or not callable(operation["model"]):
            raise ValueError("trusted action callbacks required")


def _invoke(operation, subject, argument, allowed=None):
    def action(argument):
        return operation(subject, argument)
    return _outcome(action, {"argument": argument}, allowed_exceptions=allowed)


def _step(target, model, operation, argument, transition, contract, snapshot, expected_exceptions):
    before, cpu = time.perf_counter(), time.process_time()
    expected = _invoke(operation["model"], model, deepcopy(argument), expected_exceptions)
    actual = _invoke(operation["target"], target, deepcopy(argument))
    expected_state = _projection(snapshot(model), contract)
    actual_state = _projection(snapshot(target), contract, strict=False)
    if expected_state != transition["post"]:
        raise ValueError("independent model differs from declared public transition effects")
    failed = canonical(expected) != canonical(actual) or canonical(expected_state) != canonical(actual_state)
    return {"failed": failed, "actual": actual, "expected": expected,
            "actual_state": actual_state, "expected_state": expected_state,
            "wall_seconds": time.perf_counter()-before, "cpu_seconds": time.process_time()-cpu}


def evaluate_temporal_trace(spec, contract, target_factory, model_factory, operations, inputs, *, snapshot,
                            trusted_execution=False, expected_oracle_exceptions=()):
    """Execute one validated trace; Oracle and projection errors propagate."""
    if trusted_execution is not True:
        raise PermissionError("explicit trusted execution required")
    from .temporal import initial_state, simulate_trace
    spec, contract, _ = _public(spec, contract)
    _operations(operations, contract)
    if not isinstance(expected_oracle_exceptions, tuple) or any(not isinstance(t,type) or not issubclass(t,Exception) for t in expected_oracle_exceptions):
        raise ValueError("explicit approved Oracle exception classes required")
    simulation = simulate_trace(inputs, spec, contract)
    if not simulation["valid"]:
        raise ValueError("trace violates a declared action precondition")
    if not all(callable(f) for f in (target_factory, model_factory, snapshot)):
        raise ValueError("trusted factories and snapshot required")
    started, cpu = time.perf_counter(), time.process_time()
    target, model = target_factory(), model_factory()
    expected_initial = _projection(snapshot(model), contract)
    if expected_initial != initial_state(contract):
        raise ValueError("independent model initial state differs from public contract")
    if _projection(snapshot(target), contract) != expected_initial:
        raise ValueError("initial-state disagreement requires a separate initial-state contract")
    rows, first_failure = [], None
    for transition in simulation["transitions"]:
        result = _step(target, model, operations[transition["action"]], transition["argument"],
                       transition, contract, snapshot, expected_oracle_exceptions)
        row = dict(result, index=transition["index"], action=transition["action"], argument=transition["argument"])
        rows.append(row)
        if result["failed"] and first_failure is None:
            first_failure = transition["index"]
    return {"failed": first_failure is not None, "first_failure_index": first_failure,
            "records": rows, "inputs": deepcopy(inputs), "target_transition_calls": len(rows),
            "model_transition_calls": len(rows), "trace_calls": 1,
            "wall_seconds": time.perf_counter()-started, "cpu_seconds": time.process_time()-cpu}


def _machine(spec, contract, argument_type, *, start, step, end, check):
    """Decorators and Bundle values are handled by Hypothesis itself."""
    from .temporal import apply_action, available_actions, initial_state
    actions = {a["name"]: a for a in contract["actions"]}
    bundles = {a["role"]: Bundle("produced_"+a["role"]) for a in contract["actions"]}
    arguments = list(range(argument_type["min"], argument_type["max"]+1))

    class Machine(RuleBasedStateMachine):
        def __init__(self):
            super().__init__()
            self.state, self.previous, self.trace = initial_state(contract), None, []
            self.produced = {role: [] for role in bundles}
            self.subject = start()
            self.failed = False

        def allowed(self, action):
            dependencies = actions[action]["dependencies"]
            possible = arguments if all(self.produced.get(role) for role in dependencies) else []
            return [value for value in possible if action in available_actions(
                self.state, value, len(self.trace), self.previous, contract, spec)]

        @invariant()
        def model_and_state_invariants(self):
            if self.failed:
                raise StateViolation("independent state/output invariant violated")

        @precondition(lambda self: not any(self.allowed(action) for action in actions))
        @rule()
        def terminal_state(self):
            # No external callback: a terminal public model may simply finish.
            check()

        def teardown(self):
            end(deepcopy(self.trace))

    namespace = {}
    for role, bundle in bundles.items():
        namespace["bundle_"+role] = bundle
    for action, declaration in actions.items():
        def build(action, declaration):
            def transition(self, data):
                allowed = self.allowed(action)
                dependencies = declaration["dependencies"]
                if dependencies:
                    strategy = st.one_of(type_strategy(argument_type),
                                         *(bundles[role] for role in dependencies if self.produced.get(role)))
                else:
                    strategy = type_strategy(argument_type)
                argument = data.draw(strategy.filter(lambda value: value in allowed), label=action)
                transition = apply_action(self.state, action, argument, len(self.trace), self.previous, contract, spec)
                trace = [*self.trace, [action, argument]]
                self.failed = step(self.subject, deepcopy(trace), transition)
                self.trace = trace
                self.state, self.previous = transition["post"], transition
                self.produced[declaration["role"]].append(argument)
                return argument
            transition.__name__ = "action_"+action
            return precondition(lambda self: bool(self.allowed(action)))(
                rule(target=bundles[declaration["role"]], data=st.data())(transition))
        namespace["action_"+action] = build(action, declaration)
    # Recreate the class so Hypothesis collects the generated decorated rules.
    return type("DeclaredTemporalMachine", (Machine,), namespace)


def _resources(budget, max_examples, steps, seed, time_budget):
    integer(budget, 1, 100000)
    integer(max_examples, 1, 1000)
    integer(steps, 1, 16)
    integer(seed, 0, 2**32-1)
    if type(time_budget) not in (int, float) or not math.isfinite(time_budget) or not 0 < time_budget <= 3600:
        raise ValueError("finite positive cooperative time budget required")


def run_native_stateful(spec, contract, target_factory, model_factory, operations, *, snapshot, budget=256,
                        max_examples=32, steps=16, seed=7, time_budget=10.0, trusted_execution=False,
                        expected_oracle_exceptions=(), phase="search", trace_callback=None, before_trace_callback=None):
    """Native generation/shrinking, with every real transition including repeats metered."""
    if trusted_execution is not True:
        raise PermissionError("explicit trusted execution required")
    from .temporal import initial_state
    spec, contract, argument_type = _public(spec, contract)
    _resources(budget, max_examples, steps, seed, time_budget)
    steps = min(steps, spec["inputs"][0]["type"]["max_size"])
    _operations(operations, contract)
    if phase not in {"search", "generate"} or (trace_callback is not None and not callable(trace_callback)):
        raise ValueError("invalid native state machine mode")
    if before_trace_callback is not None and not callable(before_trace_callback):
        raise ValueError("trusted candidate registration hook required")
    if not isinstance(expected_oracle_exceptions, tuple) or any(not isinstance(t,type) or not issubclass(t,Exception) for t in expected_oracle_exceptions):
        raise ValueError("explicit approved Oracle exception classes required")
    rows, witnesses, traces = [], [], []
    started, cpu = time.perf_counter(), time.process_time()
    factory_calls, oracle_seconds = 0, 0.0
    resource = {"reason": None, "hypothesis_wrapper": False}
    stop_signal = BudgetExhausted()

    def check():
        if len(rows) >= budget or time.perf_counter()-started >= time_budget:
            resource["reason"] = "TRANSITION_BUDGET" if len(rows) >= budget else "WALL_BUDGET"
            raise stop_signal

    def start():
        nonlocal factory_calls
        if len(rows) >= budget or time.perf_counter()-started >= time_budget:
            # Resource stops must occur after Hypothesis draws rule data.
            # Raising during construction can make an identical draw prefix
            # look like an inconsistent strategy to its data tree.
            return None
        target, model = target_factory(), model_factory()
        factory_calls += 2
        expected = _projection(snapshot(model), contract)
        if expected != initial_state(contract) or _projection(snapshot(target), contract) != expected:
            raise ValueError("trusted factories differ from declared initial state")
        return target, model

    def step(subject, trace, transition):
        nonlocal oracle_seconds
        check()
        if before_trace_callback is not None:
            before_trace_callback({spec["inputs"][0]["name"]: deepcopy(trace)})
        result = _step(*subject, operations[transition["action"]], transition["argument"], transition,
                       contract, snapshot, expected_oracle_exceptions)
        oracle_seconds += result["wall_seconds"]
        row = dict(result, trace=trace, call=len(rows)+1, elapsed_seconds=time.perf_counter()-started,
                   first_failure_index=len(trace)-1 if result["failed"] else None)
        rows.append(row)
        if result["failed"]:
            witnesses.append(deepcopy(trace))
        if trace_callback is not None:
            trace_callback(deepcopy(row))
        return result["failed"]

    machine = hypothesis_seed(seed)(_machine(spec, contract, argument_type, start=start, step=step, end=traces.append, check=check))
    stop = "COMPLETE"
    try:
        run_state_machine_as_test(machine, settings=settings(max_examples=max_examples, stateful_step_count=steps,
            deadline=None, database=None, phases=[Phase.generate, Phase.shrink] if phase == "search" else [Phase.generate],
            suppress_health_check=list(HealthCheck), report_multiple_bugs=False))
    except BudgetExhausted as error:
        if error is not stop_signal:
            raise
        stop = "RESOURCE_BUDGET"
    except FlakyStrategyDefinition as error:
        # Hypothesis may replace an interruption with a draw-prefix mismatch
        # while unwinding its data tree. Only a chained, run-local stop is an
        # incomplete resource result. Genuine strategy nondeterminism escapes.
        if resource["reason"] is None or not _wraps_stop(error, stop_signal):
            raise
        resource["hypothesis_wrapper"] = True
        stop = "RESOURCE_BUDGET"
    except StateViolation:
        stop = "NATIVE_SHRINK_COMPLETED" if phase == "search" else "OBSERVED_FAILURE"
    witness = (witnesses[-1] if stop == "NATIVE_SHRINK_COMPLETED" else
               min(witnesses, key=lambda trace: (len(trace), canonical(trace)))) if witnesses else None
    return {"schema": "tomolab-native-temporal-v1", "status": "COUNTEREXAMPLE_FOUND" if witnesses else "NOT_REFUTED_WITHIN_BUDGET",
            "stop": stop, "witness": witness, "records": rows, "traces": traces,
            "target_transition_calls": len(rows), "model_transition_calls": len(rows),
            "oracle_calls": len(rows), "trace_callbacks": len(rows) if trace_callback is not None else 0,
            "factory_calls": factory_calls, "wall_seconds": time.perf_counter()-started,
            "cpu_seconds": time.process_time()-cpu, "oracle_seconds": oracle_seconds,
            "first_failure_seconds": next((row["elapsed_seconds"] for row in rows if row["failed"]), None),
            "shrinking": stop if phase == "search" else "NOT_REQUESTED", "generator_feedback": False,
            "resource_stop": resource,
            "candidate_decisions": "PUBLIC_CONTRACT_SIMULATION_ONLY",
            "private_state_access": "TRUSTED_EVALUATOR_COMPARISON_ONLY",
            "target_execution": "TRUSTED_EVALUATOR_HOST_NOT_SANDBOXED"}


def generate_stateful_plan(spec, contract, *, seed=7, max_examples=32, steps=16, budget=256, time_budget=10.0):
    """Freeze actual RuleBasedStateMachine traces using public model data only."""
    spec, contract, argument_type = _public(spec, contract)
    _resources(budget, max_examples, steps, seed, time_budget)
    steps = min(steps, spec["inputs"][0]["type"]["max_size"])
    started, cpu = time.perf_counter(), time.process_time()
    calls, traces, seen = 0, [], set()
    resource = {"reason": None, "hypothesis_wrapper": False}
    stop_signal = BudgetExhausted()

    def check():
        if calls >= budget or time.perf_counter()-started >= time_budget:
            resource["reason"] = "PUBLIC_TRANSITION_BUDGET" if calls >= budget else "WALL_BUDGET"
            raise stop_signal

    def step(subject, trace, transition):
        nonlocal calls
        check()
        calls += 1
        return False

    def collect(trace):
        key = canonical(trace)
        if trace and key not in seen:
            seen.add(key)
            traces.append({spec["inputs"][0]["name"]: trace})

    machine = hypothesis_seed(seed)(_machine(spec, contract, argument_type, start=lambda: None, step=step, end=collect, check=check))
    stop = "COMPLETE"
    try:
        run_state_machine_as_test(machine, settings=settings(max_examples=max_examples, stateful_step_count=steps,
            deadline=None, database=None, phases=[Phase.generate], suppress_health_check=list(HealthCheck)))
    except BudgetExhausted as error:
        if error is not stop_signal:
            raise
        stop = "RESOURCE_BUDGET"
    except FlakyStrategyDefinition as error:
        if resource["reason"] is None or not _wraps_stop(error, stop_signal):
            raise
        resource["hypothesis_wrapper"] = True
        stop = "RESOURCE_BUDGET"
    return {"schema": "tomolab-native-stateful-plan-v1", "candidates": traces, "frozen": True,
            "source": "NATIVE_RULE_BASED_STATE_MACHINE", "public_transition_calls": calls,
            "target_calls": 0, "oracle_calls": 0, "final_feedback_allowed": False, "stop": stop,
            "resource_stop": resource,
            "wall_seconds": time.perf_counter()-started, "cpu_seconds": time.process_time()-cpu}
