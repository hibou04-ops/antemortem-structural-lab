"""Trusted execution around E7's public-data-only knowledge planner.

With no qualified prior this calls the existing native Hypothesis adapter
directly. A qualified, bounded prefix is frozen before native search/shrinking
and independent replay. Private outcomes and callbacks never enter the worker.
"""
from copy import deepcopy
import math
import time

from .schema import canonical, digest, integer, validate_spec


def _settings(spec, archive, target_provenance, temporal_contract, public_ir,
              budget, shrink_budget, guidance_budget, seed, pool_size, time_budget):
    from .knowledge_engine import KnowledgeEngine
    integer(budget, 1, 4096)
    integer(shrink_budget, 0, 4096)
    integer(guidance_budget, 0, 2048)
    if type(time_budget) not in (int,float) or not math.isfinite(time_budget) or not 0 < time_budget <= 3600:
        raise ValueError("finite cooperative time budget in (0,3600] required")
    spec = validate_spec(spec)
    if len(spec["contract"]["invariants"]) != 1:
        raise ValueError("one independent comparison invariant required")
    engine = KnowledgeEngine(spec, archive=archive, target_provenance=target_provenance,
        temporal_contract=temporal_contract, public_ir=public_ir, budget=budget,
        guidance_budget=min(guidance_budget,budget//2), seed=seed, pool_size=pool_size)
    return engine


def _signature(result, temporal):
    if not temporal:
        return canonical(result)
    return canonical({"failed":result["failed"],"first_failure_index":result["first_failure_index"],
        "records":[{k:row[k] for k in ("action","argument","actual","expected","actual_state","expected_state")}
                   for row in result["records"]]})


def _run(execute_pair, native_search, engine, *, budget, shrink_budget,
         guidance_budget, time_budget, backend, image, failure_signature, started, cpu,
         input_accepts=None):
    from .knowledge import make_observation
    spec, contract = engine.spec, engine.temporal_contract
    temporal = contract is not None
    counts = {"guided_prefix_calls":0,"native_search_and_shrink_calls":0,
              "replay_calls":0,"model_calls":0,"target_calls":0,
              "native_factory_calls":0,"generator_feedback_calls":0,
              "guided_prefix_attempts":0,"native_predicate_attempts":0,
              "precondition_checks":0,"precondition_rejected_attempts":0}
    timing = {"gating_seconds":engine.metrics["gating_seconds"],"worker_startup_seconds":0.0,
              "worker_roundtrip_seconds":0.0,"serialization_probe_seconds":0.0,
              "guided_prefix_seconds":0.0,"oracle_seconds":0.0,
              "native_search_and_shrink_seconds":0.0,"shrink_seconds":None,
              "shrink_timing_scope":"INCLUDED_IN_NATIVE_HYPOTHESIS_SEARCH_AND_SHRINK",
              "replay_seconds":0.0,"ir_analysis_seconds":None,
              "input_precondition_seconds":0.0,
              "ir_analysis_scope":"PRECOMPUTED_APPROVED_IR_VALIDATION_INCLUDED_IN_GATING"}
    evidence, observations, proposals, records, results = [], [], [], [], {}
    first_failure_seconds = first_failure_calls = None
    witness = None
    total = budget+shrink_budget
    receipt = {"protocol":"tomolab-knowledge-protocol-v1","backend":"native-direct",
               "isolation":"LOGICAL_ISOLATION_ONLY","worker_started":False,
               "target_execution":"TRUSTED_EVALUATOR_HOST_NOT_SANDBOXED"}
    worker_metrics = None
    worker_cpu = worker_rss = None
    rejected_attempts = []
    native_rejections = set()

    def accepts(point, phase):
        if input_accepts is None:
            return True
        counts["precondition_checks"] += 1
        tick = time.perf_counter()
        try:
            allowed = input_accepts(deepcopy(point))
        finally:
            timing["input_precondition_seconds"] += time.perf_counter()-tick
        if type(allowed) is not bool:
            raise ValueError("input_accepts must return an exact bool")
        if not allowed:
            counts["precondition_rejected_attempts"] += 1
            rejected_attempts.append({"inputs":deepcopy(point),"phase":phase,
                "status":"PRECONDITION_REJECTED","target_calls":0,"oracle_calls":0,
                "generator_feedback":False,"observed_failure":None})
        return allowed

    def remaining_time():
        return max(0.001,time_budget-(time.perf_counter()-started))

    def label(point, result, phase, count):
        nonlocal first_failure_seconds, first_failure_calls, witness
        failed = result["failed"] if temporal else result["failure"]
        row = {"kind":"FAILURE" if failed else "REFUTATION",
               "evidence_id":f"{phase}-{len(evidence):05d}","inputs":deepcopy(point),
               "invariant":spec["contract"]["invariants"][0],
               "category":"state_violation" if temporal else result["category"],
               "signature":failure_signature}
        if temporal:
            row["first_failure_index"] = result["first_failure_index"]
        evidence.append(row)
        records.append({"inputs":deepcopy(point),"failed":failed,"phase":phase,
                        "model_calls":count,"target_calls":count})
        results[canonical(point)] = result
        if failed:
            if witness is None:
                witness = deepcopy(point)
            if first_failure_seconds is None:
                first_failure_seconds = time.perf_counter()-started
                first_failure_calls = counts["model_calls"]
        return row

    def execute(point, phase):
        before = time.perf_counter()
        result = execute_pair(point)
        count = result["model_transition_calls"] if temporal else 1
        counts["model_calls"] += count
        counts["target_calls"] += count
        counts[phase+"_calls"] += count
        timing["oracle_seconds"] += time.perf_counter()-before
        return result, count

    if engine.qualified:
        from .knowledge_boundary import KnowledgeBoundary
        before = time.perf_counter()
        with KnowledgeBoundary(backend=backend,image=image) as worker:
            timing["worker_startup_seconds"] = time.perf_counter()-before

            def request(action, **fields):
                before = time.perf_counter();canonical(dict(action=action,**fields))
                timing["serialization_probe_seconds"] += time.perf_counter()-before
                before = time.perf_counter();response = worker.request(action,**fields)
                timing["worker_roundtrip_seconds"] += time.perf_counter()-before
                return response

            request("init",spec=spec,archive=engine.archive,temporal_contract=contract,
                target_provenance=engine.target_provenance,public_ir=engine.public_ir,
                budget=budget,seed=engine.seed,pool_size=engine.pool_size,
                guidance_budget=engine.guidance_budget)
            tick = time.perf_counter()
            # The prefix includes interleaved unconditioned native proposals.
            # Ordinary native search retains at least half the total call cap.
            limit = min(guidance_budget,budget//2)
            for _ in range(limit):
                if time.perf_counter()-started >= time_budget:
                    break
                proposal = request("propose")
                if proposal is None:
                    break
                point = proposal["inputs"]
                counts["guided_prefix_attempts"] += 1
                cost = len(point[spec["inputs"][0]["name"]]) if temporal else 1
                if cost > limit-counts["guided_prefix_calls"]:
                    break
                if not accepts(point,"guided_prefix"):
                    proposals.append({**proposal,"execution_status":"PRECONDITION_REJECTED"})
                    continue
                result, count = execute(point,"guided_prefix")
                event = label(point,result,"development",count)
                envelope = make_observation(spec,event,engine.target_provenance,
                    temporal_contract=contract,public_ir=engine.public_ir)
                request("observe",evidence=envelope)
                counts["generator_feedback_calls"] += 1
                observations.append(envelope);proposals.append(proposal)
                if counts["guided_prefix_calls"] >= limit:
                    break
            timing["guided_prefix_seconds"] = time.perf_counter()-tick
            snapshot = request("freeze")
            worker_metrics = request("metrics")
            receipt = {**worker.receipt,"worker_started":True,
                       "target_execution":"TRUSTED_EVALUATOR_HOST_NOT_SANDBOXED"}
            if backend == "subprocess":
                try:
                    import psutil
                    process = psutil.Process(worker.process.pid)
                    processes = {p.pid:p for p in [process,*process.children(recursive=True)]}
                    worker_cpu = sum(p.cpu_times().user+p.cpu_times().system for p in processes.values())
                    worker_rss = sum(p.memory_info().rss for p in processes.values())
                except (ImportError,OSError,psutil.Error if 'psutil' in locals() else OSError):
                    pass
    else:
        # No pool, grammar, SMT context or worker is initialized on this path.
        snapshot = engine.freeze()

    native = None
    remaining_calls = total-counts["model_calls"]
    if remaining_calls > 0 and time.perf_counter()-started < time_budget:
        before = time.perf_counter()

        def predicate(point):
            counts["native_predicate_attempts"] += 1
            if not accepts(point,"native_search_and_shrink"):
                native_rejections.add(counts["native_predicate_attempts"])
                return False
            result,count = execute(point,"native_search_and_shrink")
            label(point,result,"native",count)
            return result["failed"] if temporal else result["failure"]

        native = native_search(predicate,remaining_calls,remaining_time())
        if temporal:
            # Stateful Hypothesis meters all primitive transitions itself.
            count = native["model_transition_calls"]
            counts["model_calls"] += count;counts["target_calls"] += count
            counts["native_search_and_shrink_calls"] += count
            counts["native_factory_calls"] += native["factory_calls"]
            timing["oracle_seconds"] += native["oracle_seconds"]
            for row in native["records"]:
                point = {spec["inputs"][0]["name"]:row["trace"]}
                records.append({"inputs":point,"failed":row["failed"],"phase":"native",
                                "model_calls":1,"target_calls":1})
                evidence.append({"kind":"FAILURE" if row["failed"] else "REFUTATION",
                    "evidence_id":f"native-{len(evidence):05d}","inputs":deepcopy(point),
                    "invariant":spec["contract"]["invariants"][0],"category":"state_violation",
                    "signature":failure_signature,"first_failure_index":row["first_failure_index"]})
                if row["failed"] and first_failure_seconds is None:
                    first_failure_seconds = before-started+row["elapsed_seconds"]
                    first_failure_calls = counts["guided_prefix_calls"]+row["call"]
            if native.get("witness") is not None:
                witness = {spec["inputs"][0]["name"]:native["witness"]}
        elif native.get("witness") is not None:
            witness = native["witness"]
        if not temporal and input_accepts is not None:
            # Native find counts condition invocations. A rejected condition
            # draw did not execute either reviewed function and is not clean
            # evidence. Preserve the attempt while separating actual costs.
            native["predicate_calls"] = native["oracle_calls"]
            native["oracle_calls"] = counts["native_search_and_shrink_calls"]
            native["target_calls"] = counts["native_search_and_shrink_calls"]
            native["unique_predicate_inputs"] = native["unique_evaluated_inputs"]
            native["unique_evaluated_inputs"] = len({canonical(r["inputs"]) for r in records if r["phase"]=="native"})
            for row in native["records"]:
                rejected = row["call"] in native_rejections
                row["predicate_result"] = row["failed"]
                row["execution_status"] = "PRECONDITION_REJECTED" if rejected else "EXECUTED"
                row["oracle_calls"] = row["target_calls"] = 0 if rejected else 1
                if rejected:
                    row["failed"] = None
            native["precondition_scope"] = "TRUSTED_HOST_ONLY; REJECTIONS_ARE_NOT_ORACLE_OBSERVATIONS"
        timing["native_search_and_shrink_seconds"] = time.perf_counter()-before

    counterexample = None
    if witness is not None:
        before = time.perf_counter()
        original = results.get(canonical(witness))
        replays = []
        for _ in range(2):
            if not accepts(witness,"replay"):
                raise ValueError("counterexample precondition changed during independent replay")
            result,count = execute(witness,"replay")
            failed = result["failed"] if temporal else result["failure"]
            if not failed or (original is not None and _signature(original,temporal) != _signature(result,temporal)):
                raise ValueError("counterexample changed during independent replay")
            replays.append(_signature(result,temporal));original=result
        if replays[0] != replays[1]:
            raise ValueError("counterexample replay was nondeterministic")
        counterexample = {"inputs":witness,"replay":"MATCHED_TWICE","result":original}
        timing["replay_seconds"] = time.perf_counter()-before
    unique = {canonical(row["inputs"]) for row in records}
    timing.update(wall_seconds=time.perf_counter()-started,evaluator_cpu_seconds=time.process_time()-cpu,
                  worker_cpu_seconds=worker_cpu,worker_rss_at_freeze_bytes=worker_rss,
                  cpu_scope="EVALUATOR_PLUS_SEPARATELY_METERED_LOCAL_WORKER; DOCKER_WORKER_UNKNOWN",
                  memory_scope="WORKER_SNAPSHOT_NOT_OS_PEAK; NO_HOST_RSS_ESTIMATE",
                  phase_overlap="GATING/PREFIX/TRANSPORT/GUARD/ORACLE COMPONENTS OVERLAP; DO_NOT_SUM")
    return {"schema":"tomolab-knowledge-run-v1",**receipt,
        "status":"COUNTEREXAMPLE_FOUND" if counterexample else "NOT_REFUTED_WITHIN_BUDGET",
        "spec_sha256":digest(spec),"archive_sha256":digest(engine.archive),"snapshot":snapshot,
        "gate":engine.gate,"proposals":proposals,"evidence":evidence,"observations":observations,
        "records":records,"counterexample":counterexample,"native":native,
        "precondition_rejections":rejected_attempts,
        "input_precondition":{"enabled":input_accepts is not None,
            "execution":"TRUSTED_HOST_ONLY_NOT_TRANSMITTED",
            "rejection_semantics":"NOT_EXECUTED_NOT_REFUTATION",
            "arguments":"DEEPCOPIED_CANONICAL_INPUT_DICTIONARY"},
        "metrics":{**counts,"oracle_calls":counts["model_calls"],
            "actual_primitive_invocations":counts["model_calls"]+counts["target_calls"],
            "development_and_native_call_cap_per_side":total,
            "native_predicate_attempt_cap":remaining_calls,
            "guided_prefix_attempt_cap":min(guidance_budget,budget//2) if engine.qualified else 0,
            "replay_call_cap_per_side":2*(spec["inputs"][0]["type"]["max_size"] if temporal else 1),
            "unique_evaluated_inputs":len(unique),"duplicate_evaluations":len(records)-len(unique),
            "native_generation_and_shrink_interleaved":True,"worker":worker_metrics},
        "timing":timing,"evaluation_split":"DEVELOPMENT","final_feedback_allowed":False,
        "subjective_assessment":{"status":"NOT_RUN","used_for_verdict":False},
        "generalization":"UNKNOWN"}


def run_knowledge(target, oracle, spec, *, archive=None, target_provenance=None,
                  public_ir=None, budget=64, shrink_budget=64, guidance_budget=16,
                  seed=7, pool_size=128, time_budget=10.0, backend="subprocess",
                  image="tomolab-e7-generator:local", trusted_execution=False,
                  expected_oracle_exceptions=(), failure_signature="reference-comparison",
                  input_accepts=None):
    """Execute reviewed pure functions; no source is implicitly opened/imported.

    Optional ``input_accepts`` is a reviewed host precondition over a deep copy
    of the canonical input dictionary. Rejections consume bounded predicate
    attempts, but no target/Oracle call and no failure/refutation observation.
    Its exceptions propagate; this callback is never sent to the Generator.
    """
    if trusted_execution is not True:
        raise PermissionError("reviewed target and independent Oracle require explicit trusted execution")
    if not callable(target) or not callable(oracle) or target is oracle:
        raise ValueError("distinct trusted target and Oracle callables required")
    if input_accepts is not None and not callable(input_accepts):
        raise ValueError("input_accepts must be a reviewed callable or None")
    started,cpu = time.perf_counter(),time.process_time()
    engine = _settings(spec,archive,target_provenance,None,public_ir,budget,shrink_budget,
                       guidance_budget,seed,pool_size,time_budget)
    from .hypothesis_adapter import native_find
    from .service import evaluate_pair
    return _run(lambda point:evaluate_pair(target,oracle,point,engine.spec,
                    expected_oracle_exceptions=expected_oracle_exceptions),
        lambda predicate,calls,seconds:native_find(engine.spec,predicate,budget=calls,seed=seed,
                                                    time_budget=seconds,cache=False),
        engine,budget=budget,shrink_budget=shrink_budget,guidance_budget=guidance_budget,
        time_budget=time_budget,backend=backend,image=image,failure_signature=failure_signature,
        started=started,cpu=cpu,input_accepts=input_accepts)


def run_knowledge_stateful(target_factory, model_factory, operations, *, snapshot, spec,
                           temporal_contract, archive=None, target_provenance=None,
                           public_ir=None, budget=128, shrink_budget=128,guidance_budget=16,
                           seed=7,pool_size=128,time_budget=10.0,backend="subprocess",
                           image="tomolab-e7-generator:local",trusted_execution=False,
                           expected_oracle_exceptions=(),failure_signature="independent-state-and-output",
                           input_accepts=None):
    """Reuse actual native RuleBasedStateMachine and its own native shrinking."""
    if trusted_execution is not True:
        raise PermissionError("reviewed stateful callbacks require explicit trusted execution")
    if input_accepts is not None:
        raise ValueError("opaque stateful input_accepts is unsupported; declare public EFSM preconditions")
    if target_factory is model_factory or not all(callable(fn) for fn in (target_factory,model_factory,snapshot)):
        raise ValueError("distinct reviewed factories and snapshot required")
    started,cpu=time.perf_counter(),time.process_time()
    engine=_settings(spec,archive,target_provenance,temporal_contract,public_ir,budget,shrink_budget,
                     guidance_budget,seed,pool_size,time_budget)
    from .native_stateful import evaluate_temporal_trace,run_native_stateful
    def pair(point):
        return evaluate_temporal_trace(engine.spec,engine.temporal_contract,target_factory,model_factory,
            operations,point,snapshot=snapshot,trusted_execution=True,
            expected_oracle_exceptions=expected_oracle_exceptions)
    def native(_predicate,calls,seconds):
        return run_native_stateful(engine.spec,engine.temporal_contract,target_factory,model_factory,
            operations,snapshot=snapshot,budget=calls,max_examples=calls,
            steps=engine.spec["inputs"][0]["type"]["max_size"],seed=seed,time_budget=seconds,
            trusted_execution=True,expected_oracle_exceptions=expected_oracle_exceptions)
    return _run(pair,native,engine,budget=budget,shrink_budget=shrink_budget,
        guidance_budget=guidance_budget,time_budget=time_budget,backend=backend,image=image,
        failure_signature=failure_signature,started=started,cpu=cpu)


def run_source_development(target, oracle, spec, *, source_provenance, comparison_policy,
                           method="C", archive=None, approved_counterexamples=(),
                           known_development_inputs=(), budget=64, guidance_budget=16,
                           seed=313, pool_size=128, time_budget=15.0,
                           trusted_execution=False, input_accepts=None,
                           allow_unvalidated_empirical=False,
                           failure_signature="reference-comparison"):
    """Gate A only: bounded same-Source testing; no transfer authorization.

    This reuses KnowledgeEngine and native_find/shrinking. Frozen public rule
    plans never receive measured labels. Oracle callbacks remain on the trusted
    host. Independent final transfer must use EvaluationReadiness instead.
    """
    if trusted_execution is not True:
        raise PermissionError("explicit reviewed Source execution approval required")
    if not callable(target) or not callable(oracle) or target is oracle:
        raise ValueError("distinct reviewed Source and Oracle callbacks required")
    if method not in ("A","B","C","D"):
        raise ValueError("fixed A-D Source development method required")
    from .schema import decode_inputs, keys, validate_inputs
    from .knowledge import validate_provenance
    from .qualified_comparison import equivalent
    from .hypothesis_adapter import native_find
    from .knowledge_engine import KnowledgeEngine
    spec = validate_spec(spec); origin = validate_provenance(source_provenance)
    integer(budget,3,4096); integer(guidance_budget,0,budget//2)
    integer(seed,0,2**32-1); integer(pool_size,1,4096)
    if len(spec["contract"]["invariants"]) != 1:
        raise ValueError("one independently checked Source comparison invariant required")
    if type(time_budget) not in (int,float) or not math.isfinite(time_budget) or not 0 < time_budget <= 15:
        raise ValueError("bounded cooperative Source wall budget in (0,15] required")
    keys(comparison_policy,("kind","absolute_tolerance","relative_tolerance","undefined","exceptions"))
    if comparison_policy["kind"] != "FINITE_JSON" or comparison_policy["undefined"] != "EXECUTION_ERROR" or comparison_policy["exceptions"] != "EXECUTION_ERROR":
        raise ValueError("explicit finite Source comparison and error policy required")
    for key in ("absolute_tolerance","relative_tolerance"):
        value = comparison_policy[key]
        if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
            raise ValueError("finite nonnegative Source comparison tolerances required")
    if input_accepts is not None and not callable(input_accepts):
        raise ValueError("reviewed Source precondition callback required")
    if not isinstance(approved_counterexamples,(list,tuple)) or len(approved_counterexamples)>512:
        raise ValueError("bounded approved Source counterexample list required")
    if not isinstance(known_development_inputs,(list,tuple)) or len(known_development_inputs)>512:
        raise ValueError("bounded known Source development inputs required")
    known = {canonical(validate_inputs(point,spec)) for point in known_development_inputs}
    replays = [validate_inputs(point,spec) for point in approved_counterexamples]
    started,cpu = time.perf_counter(),time.process_time()
    engine = None; plans=[]; plan_seconds=0.0
    if method in ("B","C"):
        tick=time.perf_counter()
        engine=KnowledgeEngine(spec,archive=archive if method=="C" else None,
            target_provenance=origin,budget=budget,pool_size=pool_size,
            guidance_budget=guidance_budget,seed=seed,purpose="SOURCE_DEVELOPMENT",
            allow_unvalidated_empirical=allow_unvalidated_empirical if method=="C" else False)
        if method=="C" and engine.qualified:
            # At most half the call budget goes to this fixed prefix. Ordinary
            # native search retains its independent, unchanged RNG stream.
            for _ in range(min(guidance_budget,budget//2,budget-2)):
                proposal=engine.propose()
                if proposal is None:break
                plans.append({**proposal,"frozen":True})
        engine.freeze();plan_seconds=time.perf_counter()-tick
    elif method=="D":
        seen=set()
        for point in replays:
            token=canonical(point)
            if token not in seen:
                seen.add(token);plans.append(dict(inputs=point,source="SOURCE_COUNTEREXAMPLE_REPLAY",claim_ids=[],frozen=True))
    planning_seconds=time.perf_counter()-started
    if planning_seconds>120:
        raise TimeoutError("Source data validation/planning exceeded its separate 120-second cap")
    execution_started=time.perf_counter()
    rows=[]; rejected=[]; counters={"target":0,"oracle":0}; observed={}
    guard_checks=0;guard_seconds=0.0
    first=None; witness=None; native=None; error=None; replay_status="NOT_NEEDED";active_attempt=None
    def check_time():
        if time.perf_counter()-execution_started>=time_budget:
            raise TimeoutError("cooperative Source development wall budget exhausted")
    def pair(point, phase, candidate_source, claim_ids=()):
        nonlocal first,guard_checks,guard_seconds,active_attempt
        check_time();point=validate_inputs(point,spec)
        active_attempt=dict(inputs=deepcopy(point),phase=phase,candidate_source=candidate_source,stage="DOMAIN_GUARD")
        if input_accepts is not None:
            guard_checks+=1;guard_tick=time.perf_counter()
            try:accepted=input_accepts(deepcopy(point))
            finally:guard_seconds+=time.perf_counter()-guard_tick
            if type(accepted) is not bool:raise ValueError("Source input guard must return bool")
            if not accepted:
                rejected.append(dict(inputs=point,phase=phase,status="DOMAIN_REJECTED",label=None,target_calls=0,oracle_calls=0))
                return None
        if counters["target"]>=budget or counters["oracle"]>=budget:
            raise ValueError("Source call budget exhausted")
        counters["oracle"]+=1
        active_attempt["stage"]="ORACLE"
        expected=oracle(**decode_inputs(deepcopy(point),spec));active_attempt["oracle_output_type"]=type(expected).__name__
        canonical(expected);active_attempt["expected"]=deepcopy(expected);check_time()
        counters["target"]+=1
        active_attempt["stage"]="TARGET"
        actual=target(**decode_inputs(deepcopy(point),spec));active_attempt["target_output_type"]=type(actual).__name__
        canonical(actual);active_attempt["actual"]=deepcopy(actual);check_time()
        failed=not equivalent(actual,expected,comparison_policy)
        row=dict(inputs=point,actual=actual,expected=expected,failed=failed,phase=phase,
            candidate_source=candidate_source,claim_ids=list(claim_ids),
            known_development_input=canonical(point) in known)
        rows.append(row);observed[canonical(point)]=row
        if failed and first is None:
            first=dict(wall_seconds=time.perf_counter()-started,target_calls=counters["target"],oracle_calls=counters["oracle"],
                candidate_source=candidate_source,claim_ids=list(claim_ids),known_development_input=row["known_development_input"])
        return failed
    try:
        # All prefix decisions are frozen before the first measured Source call.
        for proposal in plans:
            if counters["target"]>=budget-2 or counters["oracle"]>=budget-2:break
            if pair(proposal["inputs"],"frozen-prefix",proposal["source"],proposal["claim_ids"]) is True:
                witness=proposal["inputs"];break
        remaining=min(budget-2-counters["target"],budget-2-counters["oracle"])
        if witness is None and remaining>0:
            def predicate(point):
                return pair(point,"native-search-and-shrink","NATIVE_HYPOTHESIS") is True
            native=native_find(spec,predicate,budget=remaining,seed=seed,
                time_budget=max(0.001,time_budget-(time.perf_counter()-execution_started)),cache=False)
            if "oracle_calls" in native:
                # The adapter counts predicate attempts, including guard-only
                # rejections. Only the trusted host knows actual executions.
                native["predicate_calls"]=native.pop("oracle_calls")
            native["oracle_calls"]=sum(row["phase"]=="native-search-and-shrink" for row in rows)
            native["target_calls"]=native["oracle_calls"]
            witness=native.get("witness")
            if witness is not None and (canonical(witness) not in observed or not observed[canonical(witness)]["failed"]):
                raise ValueError("native witness has no actual failing Source observation")
        if witness is not None:
            original=observed[canonical(witness)]
            fingerprint=digest({k:original[k] for k in ("actual","expected")})
            matched=[]
            for _ in range(2):
                flag=pair(witness,"independent-replay",original["candidate_source"],original["claim_ids"])
                matched.append(flag is True and digest({k:rows[-1][k] for k in ("actual","expected")})==fingerprint)
            replay_status="MATCHED_TWICE" if all(matched) else "NONDETERMINISTIC_QUARANTINED"
    except Exception as exc:
        error=dict(kind="EXECUTION_OR_ORACLE_ERROR",type=type(exc).__name__,active_attempt=deepcopy(active_attempt),
                   partial_target_calls=counters["target"],partial_oracle_calls=counters["oracle"])
    found=witness is not None and replay_status=="MATCHED_TWICE" and error is None
    unique={canonical(row["inputs"]) for row in rows}
    search=[row for row in rows if row["phase"]!="independent-replay"]
    native_rows=[row for row in search if row["candidate_source"]=="NATIVE_HYPOTHESIS"]
    guided_rows=[row for row in search if row["candidate_source"] in ("PARTIAL_CONDITION_PROBE","EMPIRICAL_GUIDANCE_EXPERIMENT")]
    return dict(schema="tomolab-e8r1-source-run-v1",evaluation_split="DEVELOPMENT",method=method,
        status="ABORTED_EXECUTION_ERROR" if error else "COUNTEREXAMPLE_FOUND" if found else "NOT_REFUTED_WITHIN_BUDGET",
        gate="SOURCE_DEVELOPMENT_ONLY_NOT_INDEPENDENT_TRANSFER",source_provenance=origin,
        spec_sha256=digest(spec),archive_sha256=digest(archive) if archive is not None else None,
        comparison_policy=deepcopy(comparison_policy),first_failure=first,found=found,
        replay_status=replay_status,target_calls=counters["target"],oracle_calls=counters["oracle"],
        budget_per_side_including_replay=budget,actual_primitive_calls=sum(counters.values()),
        unique_evaluated_inputs=len(unique),duplicate_search_evaluations=len(search)-len({canonical(r["inputs"]) for r in search}),
        native_search_calls=len(native_rows),guided_search_calls=len(guided_rows),
        known_source_reuse_calls=sum(r["known_development_input"] for r in search),
        novel_guided_candidates=sum(not r["known_development_input"] for r in guided_rows),
        plan_wall_seconds=plan_seconds,pre_execution_wall_seconds=planning_seconds,
        input_guard_calls=guard_checks,input_guard_wall_seconds=guard_seconds,
        wall_seconds=time.perf_counter()-started,cpu_seconds=time.process_time()-cpu,
        timing_scope="TOTAL_INCLUDES_ARCHIVE_REPLAY_PLANNING_GUARD_SEARCH_SHRINK_REPLAYS; PHASE_TIMES_OVERLAP",
        time_policy="COOPERATIVE_NOT_CALLBACK_PREEMPTION",plans=plans,rows=rows,domain_rejections=rejected,native=native,error=error,
        generator_feedback=0,archive_updated=False,external_transfer="NOT_EXECUTED_READINESS_BLOCKED",
        classification="KNOWN_SOURCE_DEVELOPMENT_NOT_NEW_PRODUCTION_DISCOVERY")
