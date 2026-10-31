"""Independent invariants for online observation and bounded execution.

These local regression callables are not research benchmark problems and do
not contain evaluator-only targets or hidden final-evaluation witnesses.
"""
from copy import deepcopy
import math
import sys

import pytest

from tomolab.discovery.online_engine import OnlinePolicy, run_online
from tomolab.discovery.online_observe import inspect_target, observe
from tomolab.discovery.online_schema import validate_input


INTEGER = dict(kind="int", low=-8, high=8)
SEQUENCE = dict(kind="sequence_int", low=-8, high=8, max_size=8)
COMPARISONS = []
ORDER = []


class CountedComparison:
    def __lt__(self, other):
        COMPARISONS.append(other)
        return other > 0


def custom_comparison(point):
    if CountedComparison() < point:
        return 1
    return 0


def short_circuit(point):
    return point < 0 and 1 // 0


def consumes_iterator(point):
    cursor = iter([point, point+1])
    return [next(cursor), next(cursor)]


def exception_order(point):
    ORDER.append("before")
    if point:
        raise ValueError("reviewed local exception")
    ORDER.append("after")
    return len(ORDER)


def numeric_reference(point):
    return int(point > 0)


def test_line_observation_never_reexecutes_user_comparison():
    COMPARISONS.clear()
    expected = custom_comparison(3)
    original_side_effect = list(COMPARISONS)
    COMPARISONS.clear()
    structure = inspect_target(custom_comparison, INTEGER)
    row = observe(custom_comparison, numeric_reference, 3, INTEGER, structure)
    assert row["feedback"]["status"] == "PASS" and expected == 1
    assert COMPARISONS == original_side_effect == [3]
    assert all(item["status"] == "UNKNOWN" for item in structure["comparisons"])


def test_short_circuit_iterator_and_exception_order_are_preserved():
    for target, point in ((short_circuit, 0), (consumes_iterator, 2)):
        original = target(point)
        row = observe(target, lambda _: original, point, INTEGER,
                      inspect_target(target, INTEGER))
        assert row["feedback"]["status"] == "PASS"
    ORDER.clear()
    with pytest.raises(ValueError):
        exception_order(1)
    before = list(ORDER)
    ORDER.clear()
    def expected_exception(_):
        raise ValueError("reference exception text is not compared")
    exception_contract = dict(INTEGER, comparison={"expected_exceptions": ["builtins.ValueError"]})
    row = observe(exception_order, expected_exception, 1, exception_contract,
                  inspect_target(exception_order, exception_contract))
    assert row["feedback"]["status"] == "PASS"
    assert ORDER == before == ["before"]


def test_output_types_nan_and_user_dictionary_tags_do_not_collapse():
    # A representation choice must never erase a real contract difference.
    cases = [(lambda _: (1, 2), lambda _: [1, 2], INTEGER),
             (lambda _: False, lambda _: 0, INTEGER),
             (lambda _: {"$float": "NAN"}, lambda _: math.nan,
              dict(INTEGER, comparison={"nan_equal": True}))]
    for target, oracle, contract in cases:
        row = observe(target, oracle, 0, contract)
        assert row["feedback"]["status"] == "FAILURE"


def test_large_builtin_integer_comparison_cannot_escape_actual_call_accounting():
    row = observe(lambda _: 10**1000, lambda _: 10**1000, 0, INTEGER)
    assert row["feedback"]["status"] == "PASS"
    assert row["target_calls"] == row["oracle_calls"] == 1


def test_unknown_outputs_remain_unknown_and_policy_never_receives_answers():
    row = observe(lambda _: object(), lambda _: object(), 0, INTEGER)
    assert row["feedback"]["status"] == "UNKNOWN"
    assert not {"actual", "expected", "private_outcome", "oracle_value"} & row["feedback"].keys()
    policy = OnlinePolicy(INTEGER, method="C", seed=1, budget=30)
    policy.receive(0, row["feedback"])
    assert policy.archive == []
    forbidden = dict(row["feedback"], expected=42)
    with pytest.raises(ValueError, match="private"):
        policy.receive(0, forbidden)


def test_mutating_target_does_not_mutate_oracle_input_or_later_candidate():
    def target(values):
        values.append(7)
        return values[:-1]
    def oracle(values):
        return values
    point = [1, 2]
    initial = deepcopy(point)
    for _ in range(2):
        row = observe(target, oracle, point, SEQUENCE)
        assert row["feedback"]["status"] == "PASS"
        assert point == initial


def test_existing_trace_hook_is_restored_even_when_target_raises():
    original = sys.gettrace()
    called = []
    def raises(_):
        raise ZeroDivisionError()
    def prior(frame, event, arg):
        if frame.f_code is raises.__code__ and event == "call":
            called.append(True)
        return prior
    try:
        sys.settrace(prior)
        contract = dict(INTEGER, comparison={"expected_exceptions": ["builtins.ZeroDivisionError"]})
        row = observe(raises, raises, 1, contract)
        assert row["feedback"]["status"] in ("PASS", "UNKNOWN")
        assert sys.gettrace() is prior
        assert called == [True, True]
    finally:
        sys.settrace(original)


def test_actual_target_oracle_calls_equal_all_phases_and_stay_within_total_budget():
    counters = dict(target=0, oracle=0)
    def target(point):
        counters["target"] += 1
        return point
    def oracle(point):
        counters["oracle"] += 1
        return abs(point)
    result = run_online(target, oracle, INTEGER, method="C", seed=17, budget=30,
                        shrink_budget=6, replays=[-1], max_seconds=10)
    assert counters["target"] == result["target_calls"] <= 30
    assert counters["oracle"] == result["oracle_calls"] <= 30
    assert len(result["observations"]) == result["target_calls"]
    assert result["first_confirmed_failure"]["target_calls"] >= 3
    assert result["shrinking"]["target_calls"] <= 6
    assert "GLOBAL" not in result["shrinking"]["minimality"].replace("NOT_GLOBAL_MINIMUM", "")


def test_same_c_d_scheduler_caps_no_feedback_cross_run_and_domain_rejections():
    c = OnlinePolicy(INTEGER, method="C", seed=9, budget=100, replays=[-1])
    d = OnlinePolicy(INTEGER, method="D", seed=9, budget=100, replays=[-1])
    assert c.caps == d.caps == dict(replay=20, structure=30)
    feedback = dict(status="FAILURE", input_digest="x", coverage=[1],
                    branch_distance=None, contract_checked="public")
    c.receive(-1, feedback)
    assert d.archive == [] and d.last_feedback is None
    invalid = observe(lambda x: x, lambda x: x, 99, INTEGER)
    assert invalid["feedback"]["status"] == "INVALID_INPUT"
    assert invalid["target_calls"] == invalid["oracle_calls"] == 0
    assert not validate_input(99, INTEGER)


def test_black_box_mode_does_not_claim_ast_analysis_success():
    structure = inspect_target(abs, INTEGER, mode="black_box")
    assert structure["status"] == "BLACK_BOX_FALLBACK"
    assert structure["comparisons"] == structure["literals"] == []
    assert inspect_target(abs, INTEGER)["status"] == "UNSUPPORTED"


def test_nonserializable_public_contract_is_rejected_before_any_execution():
    calls = []
    def target(point):
        calls.append("target")
        return point
    def oracle(point):
        calls.append("oracle")
        return point
    with pytest.raises((ValueError, TypeError)):
        observe(target, oracle, 0, dict(INTEGER, description=object()))
    assert calls == []


def test_noncallable_adapter_is_rejected_before_the_other_adapter_executes():
    calls = []
    def target(point):
        calls.append("target")
        return point
    with pytest.raises((ValueError, TypeError)):
        observe(target, None, 0, INTEGER)
    assert calls == []
