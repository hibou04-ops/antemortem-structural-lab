"""Hypothesis search and shrinking in the trusted evaluator.

The generator receives only the existing typed spec and counterevidence.  It
never receives callables, outputs, Hypothesis internals or subjective scores.
Only reviewed, deterministic, pure integer-pair functions may be supplied here;
this API is not a sandbox and cannot establish purity by inspecting a callable.
"""
from __future__ import annotations

from copy import deepcopy
import random
import time

from .boundary import GeneratorBoundary
from .schema import integer, normalize_evidence, point_from_inputs, point_to_inputs, roles, validate_spec


def _hypothesis():
    try:
        from hypothesis import find, Phase, settings, strategies, Verbosity
        from hypothesis.errors import NoSuchExample
    except ImportError as exc:
        raise ValueError("property testing requires the 'qa' package extra") from exc
    return find, Phase, settings, strategies, Verbosity, NoSuchExample


def input_strategy(spec):
    """Build a bounded integer-pair strategy from public typed data only."""
    spec = validate_spec(spec)
    _, _, _, st, _, _ = _hypothesis()
    by_role = roles(spec)
    return st.tuples(*(st.integers(by_role[role]["low"], by_role[role]["high"])
                       for role in ("left", "right")))


def _complexity(point):
    return (sum(abs(x) for x in point), max(abs(x) for x in point), *point)


class _ShrinkBudgetReached(Exception):
    pass


def run_properties(target, oracle, spec, *, budget=32, max_examples=128,
                   shrink_budget=128, seed=7, backend="subprocess",
                   solver="enumeration", trusted_execution=False, round_size=8):
    """Develop a Mold with Hypothesis and retain a separately shrunk witness.

    Each round first fixes a novel Mold candidate plan. Hypothesis searches
    ``sampled_from`` that plan; its index shrinking is distinct from the later
    numeric shrinking over ``input_strategy``. Only assessed, proposed inputs
    update the Version Space. Numeric shrinking runs after freeze and never
    feeds back. ``max_examples`` is a Hypothesis setting, not an oracle-call
    cap. Unique calls are bounded by ``budget + shrink_budget + 2``; the final
    two calls replay a witness and are counted separately. Cache hits preserve
    the pure-function contract and avoid repeated oracle execution.
    """
    if trusted_execution is not True:
        raise PermissionError("explicit trusted execution required; evaluator is NOT sandboxed")
    if not callable(target) or not callable(oracle) or target is oracle:
        raise ValueError("distinct trusted target and oracle callables are required")
    spec = validate_spec(spec)
    integer(budget, 1, 256, "budget")
    integer(max_examples, 1, 10000, "max_examples")
    integer(shrink_budget, 0, 4225, "shrink_budget")
    integer(round_size, 1, 64, "round_size")
    integer(seed, 0, 2**32 - 1, "seed")
    domain_size = 1
    for var in spec["variables"]:
        domain_size *= var["high"] - var["low"] + 1
    if budget > domain_size:
        raise ValueError("budget exceeds unique inputs in the finite domain")
    find, Phase, settings, st, Verbosity, NoSuchExample = _hypothesis()
    configured = settings(database=None, max_examples=max_examples, deadline=None,
                          phases=(Phase.generate, Phase.shrink), verbosity=Verbosity.quiet,
                          derandomize=False)
    rng = random.Random(seed)
    started = time.perf_counter()
    timing = {"oracle_seconds": 0.0, "generation_seconds": 0.0, "shrink_seconds": 0.0}
    proposals, observations, failures = [], [], []
    cache = {}
    metrics = {"hypothesis_attempts": 0, "cache_hits": 0, "development_calls": 0,
               "shrink_calls": 0, "replay_calls": 0, "numeric_domain_rejections": 0,
               "first_failure_attempt": None}
    first_failure = None
    best = None

    def execute(point):
        before = time.perf_counter()
        expected, actual = oracle(*point), target(*point)
        timing["oracle_seconds"] += time.perf_counter() - before
        if type(expected) is not int or type(actual) is not int:
            raise ValueError("property evaluator requires exact integer outputs")
        return {"expected": expected, "actual": actual, "failure": expected != actual}

    with GeneratorBoundary(backend=backend) as generator:
        generator.request("init", spec=spec, seed=seed, solver=solver)
        for offset in range(0, budget, round_size):
            before = time.perf_counter()
            batch = [generator.request("propose") for _ in range(min(round_size, budget - offset))]
            timing["generation_seconds"] += time.perf_counter() - before
            proposals.extend(batch)
            points = sorted((point_from_inputs(p["inputs"], spec) for p in batch), key=_complexity)

            def condition(point):
                nonlocal first_failure, best
                metrics["hypothesis_attempts"] += 1
                if point in cache:
                    metrics["cache_hits"] += 1
                    return cache[point]["failure"]
                result = cache[point] = execute(point)
                metrics["development_calls"] += 1
                evidence = normalize_evidence({
                    "kind": "FAILURE" if result["failure"] else "REFUTATION",
                    "evidence_id": f"pbt-dev-{len(observations):04d}",
                    "inputs": point_to_inputs(point, spec),
                    "invariant": spec["invariant"], "signature": "integer-mismatch"}, spec)
                generator.request("observe", evidence=evidence)
                observations.append(evidence)
                if result["failure"]:
                    failures.append(evidence)
                    if first_failure is None:
                        first_failure = point
                        metrics["first_failure_attempt"] = metrics["development_calls"]
                    if best is None or _complexity(point) < _complexity(best):
                        best = point
                return result["failure"]

            try:
                find(st.sampled_from(points), condition, settings=configured, random=rng)
            except NoSuchExample:
                pass
        snapshot = generator.request("freeze")
        receipt = generator.receipt

    # Numeric search gets public bounds and a deterministic predicate inside the
    # evaluator only. Its counterexamples are not observations of the Mold.
    candidate_minimum = best
    shrink_status = "NO_DEVELOPMENT_COUNTEREXAMPLE"
    if best is not None and shrink_budget:
        before = time.perf_counter()
        ceiling = _complexity(best)

        def numeric_condition(point):
            nonlocal best
            metrics["hypothesis_attempts"] += 1
            if _complexity(point) > ceiling:
                metrics["numeric_domain_rejections"] += 1
                return False
            if point in cache:
                metrics["cache_hits"] += 1
                result = cache[point]
            else:
                if metrics["shrink_calls"] >= shrink_budget:
                    raise _ShrinkBudgetReached
                result = cache[point] = execute(point)
                metrics["shrink_calls"] += 1
            if result["failure"] and _complexity(point) < _complexity(best):
                best = point
            return result["failure"]

        try:
            find(input_strategy(spec), numeric_condition, settings=configured, random=rng)
            shrink_status = "HYPOTHESIS_SEARCH_FINISHED"
        except NoSuchExample:
            shrink_status = "NOT_REDUCED_WITHIN_SEARCH_BUDGET"
        except _ShrinkBudgetReached:
            shrink_status = "EVALUATION_BUDGET_REACHED"
        timing["shrink_seconds"] = time.perf_counter() - before
    elif best is not None:
        shrink_status = "DISABLED"

    counterexample = None
    if best is not None:
        original = cache[best]
        for _ in range(2):
            replay = execute(best)
            metrics["replay_calls"] += 1
            if replay != original:
                raise ValueError("counterexample replay changed; deterministic pure functions are required")
        counterexample = {"inputs": point_to_inputs(best, spec),
                          "expected": original["expected"], "actual": original["actual"],
                          "signature": "integer-mismatch", "replay": "MATCHED_TWICE"}

    metrics["candidate_count"] = len(proposals)
    metrics["unique_candidates"] = len({point_from_inputs(p["inputs"], spec) for p in proposals})
    metrics["duplicate_candidates"] = len(proposals) - metrics["unique_candidates"]
    metrics["duplicate_candidate_rate"] = metrics["duplicate_candidates"] / len(proposals)
    metrics["unique_evaluated_inputs"] = len(cache)
    metrics["oracle_calls"] = metrics["development_calls"] + metrics["shrink_calls"] + metrics["replay_calls"]
    metrics["target_calls"] = metrics["oracle_calls"]
    metrics["hard_call_limit"] = budget + shrink_budget + 2
    metrics["duplicate_search_rate"] = metrics["cache_hits"] / max(1, metrics["hypothesis_attempts"])
    metrics["candidate_evaluation_fraction"] = metrics["development_calls"] / len(proposals)
    cells = set()
    by_role = roles(spec)
    for point in cache:
        cells.add(tuple(min(3, 4 * (value - by_role[role]["low"]) //
                            (by_role[role]["high"] - by_role[role]["low"] + 1))
                        for value, role in zip(point, ("left", "right"))))
    metrics["occupied_input_cells"] = len(cells)
    timing["wall_seconds"] = time.perf_counter() - started
    return {"schema": "tomolab-property-run-v1",
            "status": "COUNTEREXAMPLE_FOUND" if counterexample else "NOT_REFUTED_WITHIN_BUDGET",
            **receipt, "seed": seed, "budget": budget, "max_examples": max_examples,
            "shrink_budget": shrink_budget, "round_size": round_size,
            "proposals": proposals, "evidence": observations, "failures": failures,
            "snapshot": snapshot, "counterexample": counterexample,
            "shrink": {"status": shrink_status,
                       "first_failure": None if first_failure is None else point_to_inputs(first_failure, spec),
                       "candidate_minimum": None if candidate_minimum is None else point_to_inputs(candidate_minimum, spec),
                       "result": None if best is None else point_to_inputs(best, spec),
                       "initial_l1": None if first_failure is None else _complexity(first_failure)[0],
                       "result_l1": None if best is None else _complexity(best)[0],
                       "scope": "sample-index shrinking followed by bounded numeric search; no global minimum proof",
                       "generator_feedback": False},
            "metrics": metrics, "timing": timing,
            "oracle_verdict": {"source": "EXACT_INTEGER_COMPARISON",
                               "status": "FAILURE" if counterexample else "NOT_REFUTED_WITHIN_BUDGET"},
            "subjective_assessment": {"status": "NOT_RUN", "used_for_verdict": False},
            "evaluation_split": "DEVELOPMENT_ONLY", "final_feedback_allowed": False,
            "generalization": "UNKNOWN"}
