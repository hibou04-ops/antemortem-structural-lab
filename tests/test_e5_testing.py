from copy import deepcopy

import pytest

from tomolab.discovery.hypothesis_adapter import guided_candidates, native_find
from tomolab.discovery.predicates import predicate_holds
from tomolab.discovery.schema import canonical, validate_inputs
from tomolab.discovery.solver import solve_predicates
from tomolab.discovery.stateful import evaluate_trace, trace_spec


INT = {"kind": "int", "min": -10, "max": 10}


def spec(type_=None, *, name="value", role="operand"):
    return {"schema": "tomolab-discovery-spec-v1", "task_id": "e5-testing",
            "inputs": [{"name": name, "role": role, "type": deepcopy(type_ or INT)}],
            "contract": {"id": "public-test-v1", "operation": "test-arithmetic",
                         "preconditions": [], "invariants": ["reference"],
                         "state_model": "stateless", "graph_signature": "UNKNOWN"}}


def compare(op, left, right):
    return {"op": op, "left": left, "right": right}


def operation(op, *args):
    return {"op": op, "args": list(args)}


def test_structural_guidance_generates_fresh_strategy_values_and_excludes_seen():
    public = spec({"kind": "int", "min": 0, "max": 10})
    predicate = compare("ge", {"var": "operand"}, 7)
    kwargs = {"predicates": [predicate], "excluded": [{"value": 7}], "seed": 71,
              "size": 3, "max_examples": 32}
    left, right = guided_candidates(public, **kwargs), guided_candidates(public, **kwargs)
    assert left["candidates"] == right["candidates"]
    assert len(left["candidates"]) == 3
    assert {p["value"] for p in left["candidates"]} == {8, 9, 10}
    assert left["constraint_rejections"] > 0 and left["duplicate_rejections"] > 0
    assert left["source"] == "NATIVE_HYPOTHESIS_STRATEGY" and left["oracle_calls"] == 0


@pytest.mark.parametrize("type_,predicate", [
    ({"kind": "float", "min": -2, "max": 2}, compare("lt", {"var": "operand"}, 0)),
    ({"kind": "str", "alphabet": "ab", "min_size": 0, "max_size": 3},
     compare("eq", operation("len", {"var": "operand"}), 2)),
    ({"kind": "list", "items": INT, "min_size": 0, "max_size": 4},
     compare("ge", operation("len", {"var": "operand"}), 2)),
    ({"kind": "tuple", "items": [INT, {"kind": "str", "alphabet": "ab", "min_size": 0, "max_size": 2}]},
     compare("eq", operation("len", {"var": "operand"}), 2)),
    ({"kind": "dict", "keys": ["a", "b"], "values": INT, "min_size": 0, "max_size": 2},
     compare("eq", operation("len", {"var": "operand"}), 2)),
])
def test_native_guidance_uses_composite_and_scalar_strategies(type_, predicate):
    public = spec(type_)
    receipt = guided_candidates(public, predicates=[predicate], seed=179, size=2, max_examples=80)
    assert len(receipt["candidates"]) == 2
    assert len({canonical(p) for p in receipt["candidates"]}) == 2
    assert all(predicate_holds(predicate, validate_inputs(p, public), public) for p in receipt["candidates"])


def test_guided_disagreement_witnesses_are_not_consistency_witnesses():
    public = spec()
    predicates = [compare("gt", {"var": "operand"}, 3), compare("lt", {"var": "operand"}, -3)]
    receipt = guided_candidates(public, predicates=predicates, relation_mode="disagreement", seed=9, size=4)
    assert len(receipt["candidates"]) == 4
    assert all(len({predicate_holds(p, value, public) for p in predicates}) == 2 for value in receipt["candidates"])
    impossible = guided_candidates(public, predicates=predicates, relation_mode="all", seed=9, size=1, max_examples=32)
    assert impossible["candidates"] == []
    assert impossible["stop"] == "DRAW_BUDGET_OR_DOMAIN_EXHAUSTED"


def test_native_find_cache_meters_calls_separately_from_repeat_attempts():
    calls = []
    public = spec({"kind": "int", "min": 0, "max": 0})
    result = native_find(public, lambda point: calls.append(point) is None, budget=10, seed=7, cache=True)
    assert result["witness"] == {"value": 0}
    assert result["oracle_calls"] == len(calls) == len(result["records"]) == 1
    assert result["cache_hits"] > 0
    assert result["hypothesis_attempts"] == result["oracle_calls"] + result["cache_hits"]
    assert result["cpu_seconds"] >= 0 and result["wall_seconds"] >= result["first_failure_seconds"]


def test_native_full_strategy_shrinks_list_values_without_a_prebuilt_pool():
    public = spec({"kind": "list", "items": {"kind": "int", "min": 0, "max": 10}, "min_size": 0, "max_size": 5})
    first = native_find(public, lambda point: len(point["value"]) >= 3, budget=160, seed=401, cache=True)
    second = native_find(public, lambda point: len(point["value"]) >= 3, budget=160, seed=401, cache=True)
    assert first["witness"] == second["witness"] == {"value": [0, 0, 0]}
    assert first["shrinking"] == "NATIVE_COMPLETED"
    assert [r["inputs"] for r in first["records"]] == [r["inputs"] for r in second["records"]]


@pytest.mark.parametrize("time_budget", [True, float("nan"), float("inf"), -1])
def test_native_find_invalid_resources_do_not_invoke_oracle(time_budget):
    with pytest.raises(ValueError):
        native_find(spec(), lambda _: pytest.fail("must not execute"), time_budget=time_budget)


@pytest.mark.parametrize("type_,predicates", [
    (INT, [compare("eq", operation("mod", operation("add", {"var": "operand"}, 3), 5), 1), compare("lt", {"var": "operand"}, 0)]),
    ({"kind": "str", "alphabet": "ab", "min_size": 0, "max_size": 4}, [compare("eq", operation("len", {"var": "operand"}), 3)]),
    ({"kind": "list", "items": INT, "min_size": 1, "max_size": 4}, [compare("lt", operation("sum", {"var": "operand"}), -3), compare("ge", operation("len", {"var": "operand"}), 2)]),
    ({"kind": "tuple", "items": [INT, INT]}, [compare("ge", operation("max", {"var": "operand"}), 7)]),
])
def test_z3_typed_witness_is_read_back_using_concrete_python(type_, predicates):
    public = spec(type_)
    result = solve_predicates(public, predicates)
    assert result["status"] == "SAT", result
    assert result["concrete_readback"] == "PASS"
    validate_inputs(result["witness"], public)
    assert all(predicate_holds(p, result["witness"], public) for p in predicates)
    excluded = solve_predicates(public, predicates, excluded=[result["witness"]])
    assert excluded["status"] in ("SAT", "UNSAT")
    if excluded["status"] == "SAT":
        assert excluded["witness"] != result["witness"]


def test_z3_disagreement_and_contradiction_have_distinct_meanings():
    public = spec()
    a, b = compare("gt", {"var": "operand"}, 3), compare("lt", {"var": "operand"}, -3)
    assert solve_predicates(public, [a, b])["status"] == "UNSAT"
    query = solve_predicates(public, [a, b], mode="disagreement")
    assert query["status"] == "SAT"
    assert predicate_holds(a, query["witness"], public) != predicate_holds(b, query["witness"], public)


@pytest.mark.parametrize("public,predicate", [
    (spec({"kind": "float", "min": -1, "max": 1}), compare("gt", {"var": "operand"}, 0)),
    (spec({"kind": "list", "items": INT, "min_size": 0, "max_size": 3}), compare("gt", operation("min", {"var": "operand"}), 0)),
    (spec(), compare("eq", operation("mul", {"var": "operand"}, {"var": "operand"}), 4)),
])
def test_z3_unsupported_semantics_abstain_instead_of_approximate(public, predicate):
    result = solve_predicates(public, [predicate])
    assert result["status"] == "UNKNOWN" and result["witness"] is None
    assert result["reason"] and result["concrete_readback"] == "NOT_APPLICABLE"


def test_invalid_modulus_is_rejected_by_shared_predicate_grammar():
    with pytest.raises(ValueError, match="positive constant"):
        solve_predicates(spec(), [compare("eq", operation("mod", {"var": "operand"}, -3), 0)])


def test_z3_nul_string_escape_abstains_instead_of_returning_a_wrong_python_value():
    public = spec({"kind": "str", "alphabet": "\x00", "min_size": 1, "max_size": 1})
    predicate = compare("eq", operation("len", {"var": "operand"}), 1)
    result = solve_predicates(public, [predicate])
    assert result["status"] == "UNKNOWN" and result["witness"] is None
    assert "non-NUL" in result["reason"]


def operations(calls, broken=False):
    def target(state, value):
        calls["target"] += 1
        state.insert(0, value) if broken else state.append(value)
    def model(state, value):
        calls["model"] += 1
        state.append(value)
    return {"append": {"arguments": INT, "target": target, "model": model}}


def test_typed_state_trace_replays_in_discovery_compatible_input_contract():
    public = trace_spec(["append"], INT, max_steps=4)
    trace = [["append", 1], ["append", 2]]
    validate_inputs({"trace": trace}, public)
    calls = {"target": 0, "model": 0}
    receipt = evaluate_trace(list, list, operations(calls, broken=True), trace, snapshot=list, trusted_execution=True)
    assert receipt["failed"] and receipt["first_failure_index"] == 1
    assert receipt["transition_calls"] == receipt["target_transition_calls"] == receipt["model_transition_calls"] == 2
    assert calls == {"target": 2, "model": 2}
    assert receipt["records"][1]["actual_state"] == [2, 1]
    assert receipt["records"][1]["expected_state"] == [1, 2]


def test_state_trace_does_not_convert_projection_errors_to_findings():
    def broken_projection(_):
        raise RuntimeError("independent model projection broken")
    with pytest.raises(RuntimeError, match="model projection"):
        evaluate_trace(list, list, operations({"target": 0, "model": 0}), [["append", 1]], snapshot=broken_projection, trusted_execution=True)


def test_state_trace_rejects_unknown_actions_before_factory_execution():
    def factory():
        pytest.fail("invalid trace must not execute")
    with pytest.raises(ValueError):
        evaluate_trace(factory, factory, operations({"target": 0, "model": 0}), [["hidden", 1]], snapshot=list, trusted_execution=True)
    with pytest.raises(PermissionError):
        evaluate_trace(factory, factory, {}, [], snapshot=list)
