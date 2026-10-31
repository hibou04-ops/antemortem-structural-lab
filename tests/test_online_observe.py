"""Instrumentation must observe a single execution without changing meaning."""
import sys

import pytest

from tomolab.discovery.online_observe import inspect_target, observe, _capture
from tomolab.discovery.online_schema import validate_contract

CONTRACT = {"kind": "int", "low": -5, "high": 5}


def scalar_branch(point):
    if point < 2:
        return point + 1
    return point


def test_public_structure_and_scalar_distance_are_explicitly_bounded():
    structure = inspect_target(scalar_branch, CONTRACT)
    assert structure["status"] == "SUPPORTED_BOUNDED_OBSERVATION"
    assert structure["comparisons"][0]["literal"] == 2
    row = observe(scalar_branch, scalar_branch, 1, CONTRACT, structure)
    assert row["feedback"]["branch_distance"] == 1
    assert row["feedback"]["coverage"]
    assert row["target_calls"] == row["oracle_calls"] == 1
    assert not {"actual", "expected", "oracle", "value"} & row["feedback"].keys()


def test_negative_literal_preserves_its_sign_for_public_edit_operators():
    def negative_branch(point):
        return point < -3
    structure = inspect_target(negative_branch, CONTRACT)
    assert structure["literals"] == [-3]
    assert structure["comparisons"][0]["literal"] == -3


def test_operator_iterator_short_circuit_and_mutation_order_are_not_replayed():
    log = []
    class Box:
        def __lt__(self, other):
            log.append("compare")
            return True
    def target(point):
        values = iter([point, 3])
        log.append("start")
        if Box() < 2 and next(values) > 0:
            log.append("taken")
        return [next(values), list(log)]
    original, _, _ = _capture(target, 1, tracing=False)
    assert log.count("compare") == 1
    log.clear()
    instrumented, lines, _ = _capture(target, 1, tracing=True)
    assert instrumented == original
    assert log == ["start", "compare", "taken"]
    assert lines


def test_exception_order_matches_uninstrumented_execution():
    actions = []
    def target(point):
        actions.append("before")
        if point:
            raise ValueError("documented")
        actions.append("after")
        return 0
    normal, _, _ = _capture(target, 1, tracing=False)
    actions.clear()
    traced, _, _ = _capture(target, 1, tracing=True)
    assert normal == traced
    assert actions == ["before"]


def test_prior_trace_is_not_displaced_or_silently_disabled():
    events = []
    def prior(frame, event, arg):
        if frame.f_code is scalar_branch.__code__:
            events.append(event)
        return prior
    old = sys.gettrace()
    try:
        sys.settrace(prior)
        _capture(scalar_branch, 1, tracing=True)
        assert sys.gettrace() is prior
        assert "call" in events and "line" in events
    finally:
        sys.settrace(old)


def test_independent_input_copies_preserve_reference_and_original():
    point = [1, 2]
    def target(value):
        value.pop()
        return len(value)
    row = observe(target, lambda value: len(value), point, {"kind": "sequence_int"})
    assert point == [1, 2]
    assert row["feedback"]["status"] == "FAILURE"


def test_unsupported_dynamic_callable_and_explicit_black_box_fallback():
    assert inspect_target(len, {"kind": "text"})["status"] == "UNSUPPORTED"
    assert inspect_target(len, {"kind": "text"}, mode="black_box")["status"] == "BLACK_BOX_FALLBACK"


def test_nonscalar_comparisons_are_unknown_instead_of_fake_branch_distance():
    def target(point):
        return len(point) < 2
    structure = inspect_target(target, {"kind": "sequence_int"})
    assert structure["comparisons"][0]["status"] == "UNKNOWN"
    assert "NONSCALAR_OR_EFFECTFUL_COMPARISON_DISTANCE:UNKNOWN" in structure["limitations"]
    assert observe(target, target, [1], {"kind": "sequence_int"}, structure)["feedback"]["branch_distance"] is None


def test_invalid_and_unsupported_outputs_do_not_become_normal_counterexamples():
    calls = []
    def target(point):
        calls.append(point)
        return object()
    invalid = observe(target, target, 100, CONTRACT)
    assert invalid["feedback"]["status"] == "INVALID_INPUT" and not calls
    unknown = observe(target, target, 1, CONTRACT)
    assert unknown["feedback"]["status"] == "UNKNOWN"


def test_oracle_errors_need_an_explicit_expected_exception_contract():
    def oracle(point):
        raise ValueError("reference error")
    result = observe(lambda point: 0, oracle, 1, CONTRACT)
    assert result["feedback"]["status"] == "ORACLE_ERROR"
    explicit = dict(CONTRACT, comparison={"expected_exceptions": ["builtins.ValueError"]})
    assert observe(oracle, oracle, 1, explicit)["feedback"]["status"] == "PASS"


@pytest.mark.parametrize("exc", [MemoryError, ImportError, OSError, RecursionError])
def test_environment_failures_are_not_contract_bugs(exc):
    def target(point):
        raise exc()
    assert observe(target, lambda point: point, 1, CONTRACT)["feedback"]["status"] == "EXECUTION_ERROR"


def test_unsupported_domain_expression_is_rejected_instead_of_evaluated():
    with pytest.raises(ValueError, match="UNSUPPORTED"):
        validate_contract(dict(CONTRACT, preconditions=["eval('secret')"]))
