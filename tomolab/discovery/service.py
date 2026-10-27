"""Trusted evaluator around the data-only discovery worker.

Callables, execution outcomes and native shrinking stay here. A frozen final
plan has no observation endpoint and cannot learn final labels.
"""
from copy import deepcopy
import inspect
import time

from .boundary import DiscoveryBoundary
from .schema import canonical, decode_inputs, digest, integer, validate_spec


def prepare_public_contract(spec, source, *, function="implementation"):
    """Bind an explicitly approved public source IR; never read target implicitly."""
    from .analysis import analyze_file
    from .predicates import validate_public_ir
    spec = validate_spec(spec)
    roles = {item["name"]:item["role"] for item in spec["inputs"]}
    ir = analyze_file(source,function,roles)
    declared = spec["contract"]["graph_signature"]
    if declared != "UNKNOWN" and declared != ir["graph_signature"]:
        raise ValueError("approved public source differs from declared operation graph")
    spec["contract"]["graph_signature"] = ir["graph_signature"]
    validate_public_ir(ir,spec)
    return spec, ir


def _outcome(fn, arguments, *, allowed_exceptions=None):
    signature = inspect.signature(fn)
    copied = deepcopy(arguments)
    positional = []
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            if parameter.name not in copied:
                raise ValueError("all positional-only parameters must be declared")
            positional.append(copied.pop(parameter.name))
    # A contract/call-signature mismatch is an evaluator error. Binding happens
    # outside the target-exception path so it cannot become a false finding.
    signature.bind(*positional,**copied)
    try:
        value = fn(*positional,**copied)
    except Exception as error:
        if allowed_exceptions is not None and type(error) not in allowed_exceptions:
            raise
        return {"kind":"exception","type":type(error).__module__+"."+type(error).__qualname__}
    # Unsupported outcomes are evaluator errors, never program exceptions or
    # findings. This validation must stay outside the function exception path.
    encoded = canonical(value)
    if len(encoded) > 65536:
        raise ValueError("trusted function returned an oversized outcome")
    return {"kind":"return","value":value}


def evaluate_pair(target, oracle, inputs, spec, *, expected_oracle_exceptions=()):
    """Execute reviewed functions; expected exceptions compare by category only."""
    arguments = decode_inputs(inputs, spec)
    if not isinstance(expected_oracle_exceptions,tuple) or any(not isinstance(t,type) or not issubclass(t,Exception) for t in expected_oracle_exceptions):
        raise ValueError("explicit approved Oracle exception classes required")
    expected = _outcome(oracle, arguments,allowed_exceptions=expected_oracle_exceptions)
    actual = _outcome(target, arguments)
    mismatch = canonical(expected) != canonical(actual)
    return {"failure":mismatch,"expected":expected,"actual":actual,
            "category":"exception" if mismatch and (expected["kind"]=="exception" or actual["kind"]=="exception") else "mismatch"}


def run_discovery(target, oracle, spec, *, public_ir=None, budget=64, seed=7,
                  pool_size=128, strategy="integrated", solver="enumeration",
                  backend="subprocess", trusted_execution=False, shrink_budget=64,
                  time_budget=10.0, image="tomolab-e5-generator:local",expected_oracle_exceptions=()):
    if trusted_execution is not True:
        raise PermissionError("reviewed target and independent Oracle require explicit trusted execution")
    if not callable(target) or not callable(oracle) or target is oracle:
        raise ValueError("distinct trusted target and Oracle callables required")
    spec = validate_spec(spec)
    if len(spec["contract"]["invariants"]) != 1:
        raise ValueError("this reference evaluator requires exactly one declared invariant")
    integer(budget,1,4096)
    integer(shrink_budget,0,10000)
    integer(seed,0,2**32-1)
    integer(pool_size,1,4096)
    if type(time_budget) not in (int,float) or not 0 < time_budget <= 3600:
        raise ValueError("time_budget must be in (0,3600]")
    init = dict(spec=spec,seed=seed,strategy=strategy,pool_size=pool_size,
                public_ir=public_ir,solver=solver)
    from .protocol import validate_request
    validate_request(dict(action="init",**init))
    started = time.perf_counter()
    cpu_started = time.process_time()
    cache, proposals, evidence, failures = {}, [], [], []
    generation_seconds = oracle_seconds = shrink_seconds = 0.0
    first_failure_seconds = first_failure_call = None
    stop = "CANDIDATE_BUDGET"
    development_calls = shrink_calls = replay_calls = cache_hits = 0
    worker_cpu = None
    worker_process_count = None
    worker_rss_at_freeze = None

    def execute(inputs, phase):
        nonlocal oracle_seconds, development_calls, shrink_calls, replay_calls
        before = time.perf_counter()
        result = evaluate_pair(target,oracle,inputs,spec,expected_oracle_exceptions=expected_oracle_exceptions)
        oracle_seconds += time.perf_counter()-before
        if phase == "development": development_calls += 1
        elif phase == "shrink": shrink_calls += 1
        else: replay_calls += 1
        return result

    before = time.perf_counter()
    with DiscoveryBoundary(backend=backend,image=image) as generator:
        generator.request("init",**init)
        generation_seconds += time.perf_counter()-before
        for index in range(budget):
            if time.perf_counter()-started >= time_budget:
                stop = "WALL_BUDGET"
                break
            before = time.perf_counter()
            proposal = generator.request("propose")
            generation_seconds += time.perf_counter()-before
            if proposal is None:
                stop = "DOMAIN_OR_POOL_EXHAUSTED"
                break
            inputs = proposal["inputs"]
            key = canonical(inputs)
            if key in cache:
                raise ValueError("generator proposed a duplicate input")
            result = cache[key] = execute(inputs,"development")
            event = {"kind":"FAILURE" if result["failure"] else "REFUTATION",
                     "evidence_id":f"dev-{index:04d}","inputs":inputs,
                     "invariant":spec["contract"]["invariants"][0],
                     "category":result["category"],"signature":"reference-comparison"}
            generator.request("observe",evidence=event)
            proposals.append(proposal)
            evidence.append(event)
            if result["failure"]:
                failures.append(event)
                if first_failure_seconds is None:
                    first_failure_seconds = time.perf_counter()-started
                    first_failure_call = development_calls
        snapshot = generator.request("freeze")
        receipt = generator.receipt
        if backend == "subprocess":
            try:
                import psutil
                process = psutil.Process(generator.process.pid)
                processes = {p.pid:p for p in [process,*process.children(recursive=True)]}
                worker_process_count = len(processes)
                worker_cpu = sum(p.cpu_times().user+p.cpu_times().system for p in processes.values())
                worker_rss_at_freeze = sum(p.memory_info().rss for p in processes.values())
            except (ImportError, OSError, psutil.Error if 'psutil' in locals() else OSError):
                worker_cpu = None

    witness = failures[0]["inputs"] if failures else None
    shrink = {"status":"NO_COUNTEREXAMPLE","witness":witness,"generator_feedback":False}
    if witness is not None and shrink_budget and time.perf_counter()-started < time_budget:
        from .hypothesis_adapter import native_find
        before = time.perf_counter()
        def predicate(inputs):
            nonlocal cache_hits
            key = canonical(inputs)
            if key in cache:
                cache_hits += 1
                return cache[key]["failure"]
            result = cache[key] = execute(inputs,"shrink")
            return result["failure"]
        shrink = native_find(spec,predicate,budget=shrink_budget,seed=seed,
                             time_budget=max(0.001,time_budget-(time.perf_counter()-started)))
        shrink["predicate_calls"] = shrink.pop("oracle_calls")
        shrink["oracle_calls"] = shrink_calls
        shrink["target_calls"] = shrink_calls
        shrink["generator_feedback"] = False
        if shrink.get("witness") is not None:
            witness = shrink["witness"]
        shrink_seconds = time.perf_counter()-before
    elif witness is not None:
        shrink["status"] = "DISABLED_OR_WALL_BUDGET"
    counterexample = None
    if witness is not None:
        original = cache[canonical(witness)]
        for _ in range(2):
            if canonical(execute(witness,"replay")) != canonical(original):
                raise ValueError("witness replay changed; deterministic trusted callbacks required")
        counterexample = {"inputs":witness,"expected":original["expected"],
                          "actual":original["actual"],"replay":"MATCHED_TWICE"}
    return {"schema":"tomolab-discovery-run-v1",
            "status":"COUNTEREXAMPLE_FOUND" if counterexample else "NOT_REFUTED_WITHIN_BUDGET",
            **receipt,"spec_sha256":digest(spec),"snapshot":snapshot,"proposals":proposals,
            "evidence":evidence,"failures":failures,"counterexample":counterexample,"shrink":shrink,
            "metrics":{"candidate_count":len(proposals),"unique_candidates":len(proposals),
                       "unique_evaluated_inputs":len(cache),
                       "duplicate_candidates":0,"development_calls":development_calls,
                       "shrink_calls":shrink_calls,"replay_calls":replay_calls,"cache_hits":cache_hits,
                       "oracle_calls":development_calls+shrink_calls+replay_calls,
                       "target_calls":development_calls+shrink_calls+replay_calls,
                       "hard_call_limit":budget+shrink_budget+2,
                       "first_failure_call":first_failure_call,"first_failure_seconds":first_failure_seconds,
                       "stop":stop},
            "timing":{"wall_seconds":time.perf_counter()-started,"generation_seconds":generation_seconds,
                      "oracle_seconds":oracle_seconds,"shrink_seconds":shrink_seconds,
                      "evaluator_cpu_seconds":time.process_time()-cpu_started,"worker_cpu_seconds":worker_cpu,
                      "worker_process_count":worker_process_count,"worker_rss_at_freeze_bytes":worker_rss_at_freeze,
                      "cpu_scope":"evaluator plus separately measured local worker; Docker CPU unknown"},
            "oracle_verdict":{"source":"EXACT_JSON_RETURN_OR_APPROVED_EXCEPTION_CATEGORY_COMPARISON",
                              "oracle_error_policy":"PROPAGATE_UNAPPROVED_EXCEPTIONS",
                              "approved_exception_types":[t.__module__+"."+t.__qualname__ for t in expected_oracle_exceptions]},
            "subjective_assessment":{"status":"NOT_RUN","used_for_verdict":False},
            "evaluation_split":"DEVELOPMENT","final_feedback_allowed":False,
            "generalization":"UNKNOWN"}


def plan_discovery(snapshot, target_spec, *, target_ir, mapping=None, budget=64,seed=7,
                   pool_size=128,solver="enumeration",backend="subprocess",
                   image="tomolab-e5-generator:local",target_evidence=None):
    snapshot = snapshot.get("snapshot",snapshot)
    fields = dict(snapshot=snapshot,spec=target_spec,target_ir=target_ir,mapping=mapping,
                  budget=budget,seed=seed,pool_size=pool_size,solver=solver)
    if target_evidence is not None:
        fields["target_evidence"] = target_evidence
    with DiscoveryBoundary(backend=backend,image=image) as generator:
        result = generator.request("transfer",**fields)
        result.update(generator.receipt)
    result.update(schema="tomolab-discovery-plan-v1",final_feedback_allowed=False,
                  candidate_sha256=digest(result["candidates"]),generalization="UNKNOWN")
    return result
