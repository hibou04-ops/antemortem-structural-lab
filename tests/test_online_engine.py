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


def _learned_operator_mold(operators, *, kind="sequence_int", observations=None):
    from tomolab.discovery.online_learning import learn_mold
    contract = dict(kind=kind, low=-10, high=10, min_size=0, max_size=3)
    if observations is None:
        observations = [([1, 2], "PASS"), ([1, 1], "FAILURE")]
    rows = [dict(input=point, status=status, contract=contract, source_identity="authored-parity-source")
            for point, status in observations]
    return learn_mold(rows, operator_grammar=operators)


def _only_rule(mold, operators, *, preconditions=None):
    """Bounded authored runtime-contract fixture, never research evidence."""
    result = deepcopy(mold)
    rule = next(deepcopy(r) for r in result["rules"] if r["edit_composition"] == operators)
    if preconditions is not None:
        rule["preconditions"] = preconditions
        rule["provenance"] = ["COMMON_PRIOR", "SOURCE_LEARNED_SELECTION"] + (
            ["SOURCE_LEARNED_COMPOSITION"] if len(operators) == 2 else []) + (
            ["SOURCE_LEARNED_APPLICABILITY"] if preconditions else [])
        rule["rule_id"] = digest({k:v for k,v in rule.items() if k != "rule_id"})
    result["rules"] = [rule]
    result["artifact_digest"] = digest({k:v for k,v in result.items() if k != "artifact_digest"})
    return result


def _policy_pair(mold, *, contract=None, anchor=None):
    contract = contract or dict(kind="sequence_int", low=-10, high=10, min_size=0, max_size=3)
    anchor = [1, 2] if anchor is None else anchor
    policies = [OnlinePolicy(contract, method=method, seed=47, budget=60, mold=mold if method == "D" else None,
                              replays=[deepcopy(anchor)]) for method in ("C", "D")]
    for policy in policies:
        row = dict(status="PASS", input_digest=input_identity(anchor), coverage=[1], branch_distance=None,
                   contract_checked=digest(contract), exception_type=None, exception_location=None)
        policy.receive(deepcopy(anchor), row)
    return policies


@pytest.mark.parametrize("case", ["none", "empty", "wrong_kind", "false", "unknown", "duplicate", "invalid"])
def test_rejected_source_guidance_keeps_common_rng_replay_feedback_and_budget_equal(case):
    from tomolab.discovery.online_learning import learn_mold
    contract = dict(kind="sequence_int", low=-10, high=10, min_size=0, max_size=3)
    anchor = [1, 2]
    mold = _only_rule(_learned_operator_mold(["constantize"]), ["constantize"])
    if case == "none":
        mold = None
    elif case == "empty":
        mold = learn_mold([])
    elif case == "wrong_kind":
        mold = _learned_operator_mold(["negate"], kind="int", observations=[(1, "PASS"), (-1, "FAILURE")])
    elif case == "false":
        mold = _only_rule(mold, ["constantize"], preconditions={"all_equal": True})
    elif case == "unknown":
        anchor = []
        mold = _only_rule(mold, ["constantize"], preconditions={"has_negative": True})
    elif case == "invalid":
        contract = dict(contract, min_size=2, max_size=2)
        mold = _only_rule(_learned_operator_mold(["constantize", "duplicate"],
            observations=[([1,2], "PASS"), ([1,1,1], "FAILURE")]), ["constantize", "duplicate"])
    c, d = _policy_pair(mold, contract=contract, anchor=anchor)
    # The same feedback history keeps the anchor fixed. Seen contains every
    # valid result for this controlled test, so every learned proposal is rejected.
    if case == "duplicate":
        for policy in (c,d):
            policy.seen.add(input_identity([1,1]))
    for index in range(24):
        base = deepcopy(anchor)
        left, right = c.propose(base), d.propose(base)
        assert left == right
        assert c.rng.getstate() == d.rng.getstate()
        assert c.common_state_digest() == d.common_state_digest()
        assert c.archive == d.archive and c.used == d.used and c.seen == d.seen
        for policy, choice in ((c,left),(d,right)):
            policy.used[choice[1]] += 1
            row = dict(status="PASS", input_digest=input_identity(anchor), coverage=[1], branch_distance=None,
                       contract_checked=digest(contract), exception_type=None, exception_location=None)
            policy.receive(deepcopy(anchor), row, operator=choice[2])
        assert c.common_state_digest() == d.common_state_digest()
    assert d.guidance_applied == 0


def test_partial_source_edit_and_execution_error_fall_back_from_original_anchor(monkeypatch):
    from tomolab.discovery import online_engine as engine
    contract = dict(kind="sequence_int", low=-10, high=10, min_size=2, max_size=2)
    mold = _only_rule(_learned_operator_mold(["constantize", "duplicate"],
        observations=[([1,2], "PASS"), ([1,1,1], "FAILURE")]), ["constantize", "duplicate"])
    c,d = _policy_pair(mold, contract=contract)
    for policy in (c,d):
        policy.attempts = 2
        monkeypatch.setattr(policy, "_local_operator", lambda: "reverse")
    assert c.propose([1,2]) == d.propose([1,2])
    assert d.last_selection["source_state"] == "INVALID_RESULT"
    assert d.archive[-1]["input"] == [1,2]
    assert d.guidance_invalid == 1
    simple = _only_rule(_learned_operator_mold(["constantize"]), ["constantize"])
    c,d = _policy_pair(simple)
    original = engine.apply_edit
    def cannot_apply(point, operator, contract, structure=None):
        if operator == "constantize":
            raise ValueError("authored execution failure")
        return original(point, operator, contract, structure)
    monkeypatch.setattr(engine, "apply_edit", cannot_apply)
    for policy in (c,d):
        policy.attempts = 2
        monkeypatch.setattr(policy, "_local_operator", lambda: "reverse")
    assert c.propose([1,2]) == d.propose([1,2])
    assert d.last_selection["source_state"] == "UNEXECUTABLE"
    assert d.guidance_unexecutable == 1


def test_valid_guidance_distinguishes_matching_application_and_common_candidate_change(monkeypatch):
    mold = _only_rule(_learned_operator_mold(["constantize"]), ["constantize"])
    c,d = _policy_pair(mold)
    for policy in (c,d):
        policy.attempts = 2
        monkeypatch.setattr(policy, "_local_operator", lambda: "reverse")
    left,right = c.propose([1,2]),d.propose([1,2])
    assert left[0] == [2,1] and right[0] == [1,1]
    assert right[3] == mold["rules"][0]["rule_id"]
    assert d.guidance_matches == d.guidance_applied == d.guidance_changed_common == 1
    assert d.last_selection["source_changed_common"] is True
    assert c.rng.getstate() == d.rng.getstate()
    same = _policy_pair(mold)[1]
    same.attempts = 2
    monkeypatch.setattr(same,"_local_operator",lambda:"constantize")
    assert same.propose([1,2])[0] == [1,1]
    assert same.guidance_applied == 1 and same.guidance_changed_common == 0


@pytest.mark.parametrize("mutation", ["digest", "version", "schema"])
def test_corrupt_mold_is_an_error_not_an_inapplicable_proposal(mutation):
    mold = _learned_operator_mold(["constantize"])
    if mutation == "digest":
        mold["rules"][0]["selection_statistics"]["support"] += 1
    else:
        mold["semantic_contract_version" if mutation == "version" else "schema_version"] = "unapproved"
        mold["artifact_digest"] = digest({k:v for k,v in mold.items() if k != "artifact_digest"})
    with pytest.raises(ValueError):
        OnlinePolicy(dict(kind="sequence_int"), method="D", seed=1,budget=30,mold=mold)


def normalized_control_trace(result):
    """Explicit semantic fields; lookup cost/diagnostics/method are not equality claims."""
    return dict(observations=result["observations"],
        events=[{k:v for k,v in event.items() if k not in (
            "seconds","policy_state_before","policy_state_after","source_selection")}
            for event in result["events"]],target_calls=result["target_calls"],oracle_calls=result["oracle_calls"],
        budget=result["budget"],actual=result["scheduler"]["actual"],
        shrinking=result["shrinking"],confirmed=result["confirmed_failures"],first=(
            {k:v for k,v in result["first_confirmed_failure"].items() if k != "seconds"}
            if result["first_confirmed_failure"] else None))


@pytest.mark.parametrize("case", ["none", "empty", "wrong_kind", "false", "unknown", "invalid", "duplicate"])
def test_real_worker_no_effective_guidance_matches_c_semantics(case):
    from tomolab.discovery.online_learning import learn_mold
    mold = _learned_operator_mold(["negate"], kind="int",observations=[(1,"PASS"),(-1,"FAILURE")])
    mold = _only_rule(mold,["negate"])
    contract = dict(CONTRACT)
    replays = [8]
    if case == "none":
        mold = None
    elif case == "empty":
        mold = learn_mold([])
    elif case == "wrong_kind":
        mold = _learned_operator_mold(["constantize"])
    elif case in ("false","unknown"):
        mold = _only_rule(mold,["negate"],preconditions={"has_negative":True} if case=="false" else {"all_equal":True})
    elif case == "invalid":
        # Every nonzero eligible Source negation is out of this public domain;
        # zero's unchanged result is already in the seen set before structure.
        contract = dict(CONTRACT,low=1)
    elif case == "duplicate":
        # MRI's public boundary is already evaluated in the shared Source
        # replay lane. Every later boundary proposal repeats that input.
        mold = _only_rule(_learned_operator_mold(["boundary"],kind="int",
            observations=[(1,"PASS"),(0,"FAILURE")]),["boundary"])
        replays = [5]
    c = run_online(target,oracle,contract,method="C",seed=611,budget=30,shrink_budget=6,replays=replays)
    d = run_online(target,oracle,contract,method="D",seed=611,budget=30,shrink_budget=6,replays=replays,mold=mold)
    assert c["status"] == d["status"] == "COMPLETE"
    assert normalized_control_trace(c) == normalized_control_trace(d)
    assert not d["scheduler"]["learned_rule_uses"]
    assert d["cost"]["source_lookup_seconds"] >= 0
    if case == "duplicate":
        assert d["scheduler"]["learned_duplicate_results"] > 0


def test_reviewed_upstream_reference_supplies_only_public_ast_and_real_root_coverage():
    from test_online_observe import upstream_with_two_arguments,transparent_argument_wrapper
    result=run_online(transparent_argument_wrapper,transparent_argument_wrapper,CONTRACT,
        method="A",seed=317,budget=12,shrink_budget=0,inspection_target=upstream_with_two_arguments)
    assert result["status"]=="COMPLETE"
    assert result["mri"]["parameters"]==["point","offset"]
    assert result["mri"]["status"]=="PARTIAL"
    assert 3 in result["mri"]["literals"]
    assert any("ADAPTER_ARGUMENT_MAPPING_NOT_MODELED" in message for message in result["mri"]["limitations"])
    assert all(row["status"]=="UNKNOWN" for row in result["mri"]["comparisons"])
    assert any(event["feedback"]["coverage"] for event in result["events"])
    assert all(event["feedback"]["branch_distance"] is None for event in result["events"])
    assert result["boundary"]["target_code_transferred"] is False
    assert result["boundary"]["oracle_code_transferred"] is False
    assert "tomolab.discovery.online_observe" not in result["boundary"]["imported_modules"]


def test_oracle_cannot_be_used_as_public_target_inspection_reference():
    calls=[]
    def wrapped(point):
        calls.append(point)
        return point
    with pytest.raises(ValueError,match="Oracle"):
        run_online(wrapped,oracle,CONTRACT,method="A",budget=6,shrink_budget=0,inspection_target=oracle)
    assert calls==[]


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
