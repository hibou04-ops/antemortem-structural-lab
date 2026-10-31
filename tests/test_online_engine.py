"""Real online feedback, shared scheduling, resource bounds and reproduction."""
from copy import deepcopy

import pytest
from hypothesis import given, settings, strategies as st

from tomolab.discovery.online_engine import OnlinePolicy, run_online
from tomolab.discovery.online_schema import (apply_edit, common_operators, hypothesis_strategy,
    input_identity, validate_input, public_numeric_literals)
from tomolab.discovery.schema import digest


def target(point):
    if point >= 5:
        return -1
    return point


def oracle(point):
    return point


CONTRACT = {"kind": "int", "low": 0, "high": 10}


def feedback(status):
    return dict(status=status, input_digest=input_identity(2), coverage=[1, 2],
                branch_distance=1, contract_checked=digest(CONTRACT), exception_type=None,
                exception_location=None)


def test_different_permitted_feedback_changes_next_input():
    policies = [OnlinePolicy(CONTRACT, method="B", seed=11, budget=30) for _ in range(2)]
    assert policies[0].state_digest() == policies[1].state_digest()
    for policy, status in zip(policies, ["PASS", "FAILURE"]):
        policy.receive(2, feedback(status))
        policy.attempts = 2  # The same next structural slot in both runs.
    assert policies[0].propose(8)[0] != policies[1].propose(8)[0]


def test_feedback_cannot_smuggle_oracle_output_into_policy():
    policy = OnlinePolicy(CONTRACT, method="B", seed=7, budget=30)
    with pytest.raises(ValueError, match="private"):
        policy.receive(2, dict(feedback("PASS"), expected=2))


def test_all_methods_share_automatic_public_literal_prior_with_typed_adjacency():
    literals = public_numeric_literals(CONTRACT, {"literals": [7, -999, 3.5, "not_numeric"]})
    assert literals == [7, 6, 8]
    assert public_numeric_literals(CONTRACT, {"oracle_output": 9}) == []
    floating = public_numeric_literals({"kind": "float", "low": 0.0, "high": 1.0}, {"literals": [0.5, 20]})
    assert len(floating) == 3 and floating[1] < 0.5 < floating[2]


def test_input_identity_preserves_mapping_order_and_float_representation():
    assert input_identity({"a": 1, "b": 2}) != input_identity({"b": 2, "a": 1})
    assert input_identity([{"a": 1, "b": 2}]) != input_identity([{"b": 2, "a": 1}])
    assert input_identity(0.0) != input_identity(-0.0)
    from tomolab.discovery.online_boundary import bounded_message
    import json
    point = {"b": 2, "a": 1}
    assert list(json.loads(bounded_message({"input": point}))["input"]) == list(point)


def test_native_hypothesis_and_online_methods_use_the_same_total_call_budget():
    for method in "ABCD":
        result = run_online(target, oracle, CONTRACT, method=method, seed=19,
                            budget=30, shrink_budget=6, replays=[8])
        assert result["target_calls"] == result["oracle_calls"] <= 30
        assert result["method"] == "E9_" + method
        assert result["first_confirmed_failure"]["confirmation_calls"] == 3
        assert result["first_confirmed_failure"]["target_calls"] >= 3
        assert result["hypothesis"]["database"] is None
        assert result["cost"]["wall_seconds"] > 0
        assert result["allow_release"] is False
        assert result["shrinking"]["minimality"] == "BUDGET_BOUNDED_REDUCTION_NOT_MINIMALITY_PROOF"


def test_replay_is_not_counted_as_a_new_input():
    result = run_online(target, oracle, CONTRACT, method="C", seed=23,
                        budget=30, shrink_budget=6, replays=[8])
    assert result["source_replay_calls"] >= 3
    assert result["known_input_identities_observed"] == 1
    assert any(not row["new_input"] for row in result["confirmed_failures"])


def test_same_seed_and_initial_state_reproduce_all_policy_choices():
    results = [run_online(target, oracle, CONTRACT, method="C", seed=123,
                          budget=30, shrink_budget=6, replays=[8]) for _ in range(2)]
    def trace(result):
        return [{k: v for k, v in row.items() if k != "seconds"} for row in result["events"]]
    assert trace(results[0]) == trace(results[1])
    assert results[0]["scheduler"] == results[1]["scheduler"]
    assert results[0]["policy_state_reused"] is False


def test_c_d_share_scheduler_and_caps_even_when_d_has_no_applicable_rule():
    from tomolab.discovery.online_learning import learn_mold
    empty = learn_mold([])
    c = run_online(target, oracle, CONTRACT, method="C", seed=29, budget=40, shrink_budget=8, replays=[8])
    d = run_online(target, oracle, CONTRACT, method="D", seed=29, budget=40, shrink_budget=8, replays=[8], mold=empty)
    assert c["scheduler"]["policy"] == d["scheduler"]["policy"]
    assert c["scheduler"]["caps"] == d["scheduler"]["caps"]
    for result in (c, d):
        actual, caps = result["scheduler"]["actual"], result["scheduler"]["caps"]
        assert actual["replay"] <= caps["replay"]
        assert actual["structure"] <= caps["structure"]
        assert sum(actual.values()) <= result["scheduler"]["discovery_call_limit"]
    assert not d["scheduler"]["learned_rule_uses"]


def test_duplicate_and_domain_invalid_guidance_returns_to_native_base():
    contract = {"kind": "sequence_int", "low": 0, "high": 2, "min_size": 1, "max_size": 1}
    policy = OnlinePolicy(contract, method="C", seed=3, budget=30, replays=[[1]])
    policy.seen.add(input_identity([1]))
    point, phase, _, _, reason = policy.propose([2])
    assert point == [2] and phase == "base" and reason.startswith("DUPLICATE")
    assert apply_edit([1], "delete", contract) is None


def test_unknown_outputs_do_not_create_failure_knowledge():
    result = run_online(lambda point: object(), lambda point: object(), CONTRACT,
                        method="B", budget=12, shrink_budget=0)
    assert not result["confirmed_failures"]
    assert result["outcome"] == "INCONCLUSIVE"
    assert result["unknown"] > 0


def test_state_is_local_and_previous_target_results_do_not_change_new_run():
    before = run_online(target, oracle, CONTRACT, method="B", seed=41, budget=18, shrink_budget=0)
    run_online(lambda point: -7, oracle, CONTRACT, method="B", seed=99, budget=12, shrink_budget=0)
    after = run_online(target, oracle, CONTRACT, method="B", seed=41, budget=18, shrink_budget=0)
    assert [row["input_digest"] for row in before["observations"]] == [row["input_digest"] for row in after["observations"]]


@pytest.mark.parametrize("kind", ["int", "float", "sequence_int", "sequence_float", "text", "mapping", "state_trace", "graph"])
def test_native_strategy_and_shared_edits_preserve_declared_domain(kind):
    contract = {"kind": kind, "max_size": 4}
    @settings(max_examples=12, database=None, deadline=None)
    @given(hypothesis_strategy(contract))
    def check(point):
        assert validate_input(point, contract)
        original = deepcopy(point)
        for operator in common_operators(kind):
            edited = apply_edit(point, operator, contract)
            assert edited is None or validate_input(edited, contract)
            assert point == original
    check()


def test_unexpected_oracle_error_is_separate_from_target_failure():
    def broken_oracle(point):
        raise ValueError()
    result = run_online(target, broken_oracle, CONTRACT, method="B", budget=12, shrink_budget=0)
    assert result["oracle_errors"] == result["oracle_calls"] > 0
    assert not result["confirmed_failures"]
    assert result["outcome"] == "INCONCLUSIVE"
