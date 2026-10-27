"""Trusted synthetic development fixtures, not external generalization data."""
from copy import deepcopy

import pytest
from hypothesis import find, settings

from tomolab.mold.property_testing import input_strategy, run_properties
from tomolab.mold.schema import default_spec


def reference(x, y):
    return x + y


def wrong(x, y):
    return x + y + (1 if x >= 2 else 0)


def clean(x, y):
    return x + y


def test_input_strategy_obeys_renamed_declared_roles_and_bounds():
    spec = default_spec(low=-3, high=3)
    spec["variables"][0].update(name="a", low=1, high=2)
    spec["variables"][1].update(name="b", low=-3, high=-2)
    original = deepcopy(spec)
    point = find(input_strategy(spec), lambda p: True,
                 settings=settings(database=None, derandomize=True))
    assert 1 <= point[0] <= 2 and -3 <= point[1] <= -2
    assert spec == original


def test_hypothesis_counterexample_shrinking_and_version_space_update():
    result = run_properties(wrong, reference, default_spec(low=-4, high=4),
                            budget=32, max_examples=128, trusted_execution=True)
    assert result["status"] == "COUNTEREXAMPLE_FOUND"
    assert result["counterexample"]["inputs"] == {"x": 2, "y": 0}
    assert result["counterexample"]["replay"] == "MATCHED_TWICE"
    assert result["shrink"]["result_l1"] <= result["shrink"]["initial_l1"]
    assert result["snapshot"]["frozen"] is True
    assert result["snapshot"]["version"] == len(result["evidence"])
    assert result["snapshot"]["contradictions"]
    assert result["metrics"]["duplicate_candidates"] == 0
    assert result["metrics"]["oracle_calls"] <= result["metrics"]["hard_call_limit"]
    assert result["metrics"]["cache_hits"] > 0
    assert result["shrink"]["generator_feedback"] is False


def test_clean_function_is_bounded_nonrefutation_not_a_proof():
    result = run_properties(clean, reference, default_spec(low=-2, high=2),
                            budget=25, max_examples=128, trusted_execution=True)
    assert result["status"] == "NOT_REFUTED_WITHIN_BUDGET"
    assert result["counterexample"] is None
    assert result["metrics"]["development_calls"] == 25
    assert result["metrics"]["shrink_calls"] == result["metrics"]["replay_calls"] == 0
    assert result["generalization"] == "UNKNOWN"
    assert result["subjective_assessment"] == {"status": "NOT_RUN", "used_for_verdict": False}


def test_numeric_shrink_budget_is_a_hard_unique_call_bound():
    result = run_properties(wrong, reference, default_spec(low=-4, high=4),
                            budget=12, shrink_budget=1, max_examples=128,
                            trusted_execution=True)
    assert result["counterexample"] is not None
    assert result["metrics"]["shrink_calls"] <= 1
    assert result["metrics"]["oracle_calls"] <= 15
    assert result["snapshot"]["evidence"] == result["evidence"]


def test_fixed_versions_seed_and_spec_reproduce_plan_and_witness():
    kwargs = dict(budget=16, seed=23, max_examples=64, trusted_execution=True)
    a = run_properties(wrong, reference, default_spec(low=-3, high=3), **kwargs)
    b = run_properties(wrong, reference, default_spec(low=-3, high=3), **kwargs)
    assert a["proposals"] == b["proposals"]
    assert a["evidence"] == b["evidence"]
    assert a["counterexample"] == b["counterexample"]
    assert a["metrics"] == b["metrics"]


def test_generator_never_receives_callables_outputs_or_subjective_scores(monkeypatch):
    from tomolab.mold import property_testing
    from tomolab.mold.boundary import GeneratorBoundary
    requests = []

    class RecordingBoundary(GeneratorBoundary):
        def request(self, action, **fields):
            requests.append((action, deepcopy(fields)))
            return super().request(action, **fields)

    monkeypatch.setattr(property_testing, "GeneratorBoundary", RecordingBoundary)
    result = run_properties(wrong, reference, default_spec(low=-3, high=3),
                            budget=12, trusted_execution=True)
    for action, fields in requests:
        assert action in {"init", "propose", "observe", "freeze"}
        assert "target" not in fields and "oracle" not in fields
        if action == "observe":
            assert set(fields["evidence"]) == {"kind", "evidence_id", "inputs", "invariant", "signature"}
    assert requests[-1][0] == "freeze"
    assert len([1 for action, _ in requests if action == "observe"]) == len(result["evidence"])


@pytest.mark.parametrize("kwargs", [{}, {"trusted_execution": 1}, {"trusted_execution": "yes"}])
def test_trusted_execution_requires_exact_true(kwargs):
    with pytest.raises(PermissionError):
        run_properties(wrong, reference, default_spec(), **kwargs)


@pytest.mark.parametrize("kwargs", [{"budget": 0}, {"budget": True}, {"max_examples": 0},
                                   {"shrink_budget": -1}, {"round_size": 0}, {"seed": -1}])
def test_invalid_resources_are_rejected_before_execution(kwargs):
    with pytest.raises(ValueError):
        run_properties(wrong, reference, default_spec(low=-2, high=2),
                        trusted_execution=True, **kwargs)


def test_noninteger_outputs_are_not_reinterpreted_as_failure_evidence():
    with pytest.raises(ValueError, match="exact integer"):
        run_properties(lambda x, y: True, reference, default_spec(low=-2, high=2),
                        budget=4, trusted_execution=True)


def test_exceptions_are_errors_not_deterministic_mismatch_witnesses():
    def raising(x, y):
        raise RuntimeError("fixture error")
    with pytest.raises(RuntimeError, match="fixture error"):
        run_properties(raising, reference, default_spec(low=-2, high=2),
                        budget=4, trusted_execution=True)
