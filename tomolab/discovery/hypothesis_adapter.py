"""Public Hypothesis APIs for typed generation and bounded native shrinking."""
from copy import deepcopy
import math
import time

from hypothesis import HealthCheck, Phase, find, given, seed as hypothesis_seed, settings
from hypothesis import strategies as st
from hypothesis.errors import NoSuchExample, Unsatisfiable

from .schema import canonical, integer, validate_inputs, validate_spec, validate_type


def type_strategy(schema):
    validate_type(schema)
    kind = schema["kind"]
    if kind == "int":
        return st.integers(schema["min"], schema["max"])
    if kind == "float":
        return st.floats(schema["min"], schema["max"], allow_nan=False, allow_infinity=False, width=64)
    if kind == "str":
        return st.sampled_from(schema["choices"]) if "choices" in schema else st.text(alphabet=schema["alphabet"], min_size=schema["min_size"], max_size=schema["max_size"])
    if kind == "list":
        return st.lists(type_strategy(schema["items"]), min_size=schema["min_size"], max_size=schema["max_size"])
    if kind == "dict":
        return st.dictionaries(st.sampled_from(schema["keys"]), type_strategy(schema["values"]), min_size=schema["min_size"], max_size=schema["max_size"])
    return st.tuples(*(type_strategy(t) for t in schema["items"]))


def input_strategy(spec):
    validate_spec(spec)
    return st.fixed_dictionaries({item["name"]: type_strategy(item["type"]) for item in spec["inputs"]})


def generate_pool(spec, *, seed=7, size=512):
    spec = validate_spec(spec)
    integer(seed, 0, 2**32-1)
    integer(size, 1, 4096)
    found = []
    seen = set()

    @hypothesis_seed(seed)
    @settings(max_examples=size, deadline=None, database=None, phases=[Phase.generate],
              suppress_health_check=list(HealthCheck), report_multiple_bugs=False)
    @given(input_strategy(spec))
    def collect(value):
        point = validate_inputs(value, spec)
        encoded = canonical(point)
        if encoded not in seen:
            seen.add(encoded)
            found.append(point)
    collect()
    return found


def guided_candidates(spec, *, predicates=(), excluded=(), seed=7, size=8,
                      max_examples=128, relation_mode="any"):
    """Fresh typed Strategy draws filtered by public JSON conditions only.

    No callback or Oracle is accepted. Predicate evaluation shares the reviewed
    interpreter used by the Version Space. Every rejected draw is metered;
    search exhaustion never creates a fictitious satisfying candidate.
    """
    from .predicates import predicate_value, validate_predicate
    spec = validate_spec(spec)
    integer(seed, 0, 2**32 - 1)
    integer(size, 1, 64)
    integer(max_examples, 1, 4096)
    if relation_mode not in ("any", "all", "disagreement"):
        raise ValueError("unsupported structural strategy mode")
    if not isinstance(predicates, (list, tuple)) or len(predicates) > 128:
        raise ValueError("bounded public predicates required")
    predicates = [validate_predicate(p, spec) for p in predicates]
    if relation_mode == "disagreement" and len(predicates) < 2:
        raise ValueError("disagreement requires at least two predicates")
    if not isinstance(excluded, (list, tuple)) or len(excluded) > 8192:
        raise ValueError("bounded excluded input list required")
    seen = {canonical(validate_inputs(p, spec)) for p in excluded}
    candidates = []
    metrics = {"attempts": 0, "duplicate_rejections": 0, "constraint_rejections": 0}
    started, cpu = time.perf_counter(), time.process_time()

    class Complete(BaseException):
        pass

    @hypothesis_seed(seed)
    @settings(max_examples=max_examples, deadline=None, database=None,
              phases=[Phase.generate], suppress_health_check=list(HealthCheck),
              report_multiple_bugs=False)
    @given(input_strategy(spec))
    def collect(raw):
        metrics["attempts"] += 1
        point = validate_inputs(raw, spec)
        encoded = canonical(point)
        if encoded in seen:
            metrics["duplicate_rejections"] += 1
            return
        votes = [predicate_value(p, point, spec) for p in predicates]
        accepted = (not votes or any(votes)) if relation_mode == "any" else all(votes)
        if relation_mode == "disagreement":
            accepted = any(votes) and not all(votes)
        if not accepted:
            metrics["constraint_rejections"] += 1
            return
        seen.add(encoded)
        candidates.append(point)
        if len(candidates) >= size:
            raise Complete()
    try:
        collect()
    except Complete:
        pass
    return {"schema": "tomolab-guided-strategy-v1", "candidates": candidates,
            **metrics, "source": "NATIVE_HYPOTHESIS_STRATEGY", "mode": relation_mode,
            "stop": "REQUESTED_CANDIDATES" if len(candidates) == size else "DRAW_BUDGET_OR_DOMAIN_EXHAUSTED",
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu, "oracle_calls": 0}


class BudgetExhausted(BaseException):
    """Do not let Hypothesis interpret the resource stop as a test failure."""


def native_find(spec, predicate, *, budget=256, seed=7, time_budget=10.0, cache=False):
    """Native find+shrink; predicate must be a caller-authorized Oracle adapter.

    Every actual predicate invocation, including repeats/shrinks, consumes a call.
    Optional caching requires a deterministic pure predicate. Cache hits count
    as attempts, never Oracle calls; uncached native behavior is the default.
    An outer process/container must bound callbacks which do not return.
    """
    spec = validate_spec(spec)
    integer(budget, 1, 10000)
    integer(seed, 0, 2**32-1)
    if type(time_budget) not in (int, float) or not math.isfinite(time_budget) or not 0 < time_budget <= 3600:
        raise ValueError("time_budget must be in (0,3600]")
    if not callable(predicate) or type(cache) is not bool:
        raise ValueError("a trusted predicate and exact cache bool are required")
    calls, failures, rows = 0, [], []
    started, cpu = time.perf_counter(), time.process_time()
    attempts, cache_hits = 0, 0
    memo = {}
    first_failure_seconds = None
    def condition(value):
        nonlocal calls, first_failure_seconds, attempts, cache_hits
        if time.perf_counter()-started >= time_budget:
            raise BudgetExhausted()
        clean = validate_inputs(value, spec)
        attempts += 1
        encoded = canonical(clean)
        if cache and encoded in memo:
            cache_hits += 1
            return memo[encoded]
        if calls >= budget:
            raise BudgetExhausted()
        calls += 1
        failed = predicate(deepcopy(clean))
        if type(failed) is not bool:
            raise ValueError("predicate must return an exact bool")
        memo[encoded] = failed
        elapsed = time.perf_counter()-started
        rows.append({"call": calls, "inputs": clean, "failed": failed, "elapsed_seconds": elapsed})
        if failed:
            failures.append(clean)
            if first_failure_seconds is None:
                first_failure_seconds = elapsed
        return failed
    stop = "COMPLETE"
    result = None
    try:
        # random is an explicit reproducible source; no ambient database reuse.
        import random
        result = find(input_strategy(spec), condition, random=random.Random(seed),
                      settings=settings(max_examples=budget, deadline=None, database=None,
                                        phases=[Phase.generate, Phase.shrink], suppress_health_check=list(HealthCheck)))
        result = validate_inputs(result, spec)
    except BudgetExhausted:
        stop = "RESOURCE_BUDGET"
    except (NoSuchExample, Unsatisfiable):
        stop = "NO_WITNESS_WITHIN_SEARCH"
    # If native shrinking was interrupted, preserve an observed witness without
    # claiming it is globally minimal or Hypothesis' completed shrink result.
    witness = result if result is not None else (min(failures, key=lambda x: (len(canonical(x)), canonical(x))) if failures else None)
    return {"schema": "tomolab-hypothesis-search-v1", "status": "COUNTEREXAMPLE_FOUND" if failures else "NOT_REFUTED_WITHIN_BUDGET",
            "stop": stop, "witness": witness, "oracle_calls": calls, "first_failure_seconds": first_failure_seconds,
            "wall_seconds": time.perf_counter()-started, "cpu_seconds": time.process_time()-cpu,
            "hypothesis_attempts": attempts, "cache_hits": cache_hits, "cache_enabled": cache,
            "unique_evaluated_inputs": len(memo), "records": rows,
            "shrinking": "NATIVE_COMPLETED" if result is not None else "INCOMPLETE_OR_NO_WITNESS"}
