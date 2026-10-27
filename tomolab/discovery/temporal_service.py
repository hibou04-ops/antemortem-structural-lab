"""Native-first trusted execution; public worker learns development labels only."""
from copy import deepcopy
import math
import time

from .efficient import EvidenceCache
from .native_stateful import evaluate_temporal_trace, run_native_stateful
from .schema import canonical, digest, integer, validate_spec


def _signature(result):
    row = result["records"][-1] if result["records"] else {}
    return canonical({"failed": result["failed"], "first_failure_index": result["first_failure_index"],
                      **{key: row.get(key) for key in ("actual", "expected", "actual_state", "expected_state")}})


def run_temporal(target_factory, model_factory, operations, *, snapshot, spec, temporal_contract,
                 budget=128, shrink_budget=128, seed=7, time_budget=10.0, backend="subprocess",
                 image="tomolab-e6-generator:local", strategy="integrated", pool_size=32,
                 expected_oracle_exceptions=(), trusted_execution=False, public_ir=None):
    """Host callbacks are never imported, serialized or passed into the worker.

    `budget` caps actual development transitions on each side. Native repeats
    still consume it. Shrinking starts after worker freeze and consumes its own
    transition cap; two independent complete replays are accounted separately.
    """
    if trusted_execution is not True:
        raise PermissionError("reviewed target and independent model require explicit trusted execution")
    if not all(callable(fn) for fn in (target_factory, model_factory, snapshot)) or target_factory is model_factory:
        raise ValueError("distinct trusted factories and snapshot required")
    from .temporal import validate_temporal_contract
    from .temporal_boundary import TemporalBoundary
    integer(budget, 1, 4096)
    integer(shrink_budget, 0, 10000)
    integer(seed, 0, 2**32-1)
    integer(pool_size, 1, 4096)
    if type(time_budget) not in (int, float) or not math.isfinite(time_budget) or not 0 < time_budget <= 3600:
        raise ValueError("finite positive cooperative time budget required")
    started, cpu = time.perf_counter(), time.process_time()
    spec = validate_spec(spec)
    contract = validate_temporal_contract(temporal_contract, spec)
    if len(spec["contract"]["invariants"]) != 1:
        raise ValueError("trusted temporal evaluator requires one comparison invariant")
    validation_seconds = time.perf_counter()-started
    name = spec["inputs"][0]["name"]
    steps = spec["inputs"][0]["type"]["max_size"]
    init = dict(spec=spec, temporal_contract=contract, seed=seed, strategy=strategy, pool_size=pool_size, budget=budget)
    if public_ir is not None:
        init["public_ir"] = public_ir
    from .temporal_protocol import validate_request
    validate_request(dict(action="init", **init))
    evidence, proposals, registered, observed, original_results = [], [], set(), set(), {}
    cache = EvidenceCache(spec)
    costs = {"startup_seconds": 0.0, "worker_roundtrip_seconds": 0.0, "registration_seconds": 0.0,
             "version_update_roundtrip_seconds": 0.0, "proposal_roundtrip_seconds": 0.0,
             "local_serialization_probe_seconds": 0.0, "oracle_seconds": 0.0, "shrink_seconds": 0.0,
             "replay_seconds": 0.0, "contract_ir_validation_seconds": validation_seconds}
    counts = {"development_transition_calls": 0, "shrink_transition_calls": 0, "replay_transition_calls": 0,
              "native_factory_calls": 0, "guided_trace_calls": 0, "replay_trace_calls": 0,
              "duplicate_native_prefixes": 0, "cached_trace_results": 0}
    first_failure_seconds = first_failure_call = None
    witness = None
    worker_cpu = worker_rss = worker_processes = None

    def remaining():
        return max(0.001, time_budget-(time.perf_counter()-started))

    before = time.perf_counter()
    with TemporalBoundary(backend=backend, image=image) as generator:
        costs["startup_seconds"] = time.perf_counter()-before

        def request(action, **fields):
            tick = time.perf_counter()
            canonical(dict(action=action, **fields))
            costs["local_serialization_probe_seconds"] += time.perf_counter()-tick
            tick = time.perf_counter()
            response = generator.request(action, **fields)
            duration = time.perf_counter()-tick
            costs["worker_roundtrip_seconds"] += duration
            field = {"register":"registration_seconds", "observe":"version_update_roundtrip_seconds",
                     "propose":"proposal_roundtrip_seconds"}.get(action)
            if field:
                costs[field] += duration
            return response

        request("init", **init)

        def before_trace(inputs):
            key = canonical(inputs)
            if key not in registered:
                proposal = request("register", inputs=inputs)
                registered.add(key)
                proposals.append(proposal)

        def observe_result(inputs, result):
            nonlocal first_failure_seconds, first_failure_call, witness
            key = canonical(inputs)
            if result["failed"] and first_failure_seconds is None:
                first_failure_seconds = time.perf_counter()-started
                first_failure_call = counts["development_transition_calls"]
                witness = deepcopy(inputs[name])
            if key in observed:
                counts["duplicate_native_prefixes"] += 1
                if _signature(result) != _signature(original_results[key]):
                    raise ValueError("repeated native prefix changed; deterministic callbacks required")
                return
            event = {"kind":"FAILURE" if result["failed"] else "REFUTATION", "evidence_id":f"dev-{len(evidence):04d}",
                     "inputs":inputs, "invariant":spec["contract"]["invariants"][0],
                     "category":"state_violation", "signature":"independent-state-and-output",
                     "first_failure_index":result["first_failure_index"]}
            updated = request("observe", evidence=event)
            cache.set_version(updated.get("version", len(evidence)+1))
            cache.put(inputs, result)
            observed.add(key)
            evidence.append(event)
            original_results[key] = deepcopy(result)

        def native_observation(row):
            counts["development_transition_calls"] += 1
            result = {"failed":row["failed"], "first_failure_index":row["first_failure_index"], "records":[row]}
            observe_result({name:row["trace"]}, result)

        development = run_native_stateful(spec, contract, target_factory, model_factory, operations, snapshot=snapshot,
            budget=budget, max_examples=min(1000,budget), steps=steps, seed=seed, time_budget=remaining(),
            trusted_execution=True, expected_oracle_exceptions=expected_oracle_exceptions, phase="generate",
            trace_callback=native_observation, before_trace_callback=before_trace)
        counts["native_factory_calls"] += development["factory_calls"]
        costs["oracle_seconds"] += development["oracle_seconds"]
        # Only observed failures qualify temporal guidance. Clean runs stay on
        # the complete native generation path rather than a fixed sample pool.
        if witness is not None and strategy == "integrated":
            while counts["development_transition_calls"] < budget and time.perf_counter()-started < time_budget:
                proposal = request("propose")
                if proposal is None:
                    break
                inputs = proposal["inputs"]
                if not inputs[name] or len(inputs[name]) > budget-counts["development_transition_calls"]:
                    break
                key = canonical(inputs)
                registered.add(key)
                proposals.append(proposal)
                result = cache.get(inputs)
                if result is None:
                    result = evaluate_temporal_trace(spec, contract, target_factory, model_factory, operations, inputs,
                        snapshot=snapshot, trusted_execution=True, expected_oracle_exceptions=expected_oracle_exceptions)
                    counts["development_transition_calls"] += result["model_transition_calls"]
                    counts["guided_trace_calls"] += 1
                    costs["oracle_seconds"] += result["wall_seconds"]
                else:
                    counts["cached_trace_results"] += 1
                observe_result(inputs, result)
        frozen = request("freeze")
        worker_metrics = request("metrics")
        receipt = generator.receipt
        if backend == "subprocess":
            try:
                import psutil
                process = psutil.Process(generator.process.pid)
                processes = [process, *process.children(recursive=True)]
                worker_cpu = sum(p.cpu_times().user+p.cpu_times().system for p in processes)
                worker_rss = sum(p.memory_info().rss for p in processes)
                worker_processes = len(processes)
            except (ImportError, OSError, psutil.Error if 'psutil' in locals() else OSError):
                pass

    shrinking = {"status":"NOT_REQUESTED", "generator_feedback":False, "witness":witness}
    if witness is not None and shrink_budget and time.perf_counter()-started < time_budget:
        tick = time.perf_counter()
        shrinking = run_native_stateful(spec, contract, target_factory, model_factory, operations, snapshot=snapshot,
            budget=shrink_budget, max_examples=min(1000,shrink_budget), steps=steps, seed=seed,
            time_budget=remaining(), trusted_execution=True, expected_oracle_exceptions=expected_oracle_exceptions)
        counts["shrink_transition_calls"] = shrinking["model_transition_calls"]
        counts["native_factory_calls"] += shrinking["factory_calls"]
        costs["oracle_seconds"] += shrinking["oracle_seconds"]
        costs["shrink_seconds"] = time.perf_counter()-tick
        if shrinking["witness"] is not None:
            witness = shrinking["witness"]
    counterexample = None
    if witness is not None:
        tick = time.perf_counter()
        observed = original_results.get(canonical({name:witness}))
        for row in shrinking.get("records", []):
            if row["failed"] and canonical(row["trace"]) == canonical(witness):
                observed = {"failed":True, "first_failure_index":row["first_failure_index"], "records":[row]}
        replays = [evaluate_temporal_trace(spec, contract, target_factory, model_factory, operations, {name:witness},
                    snapshot=snapshot, trusted_execution=True, expected_oracle_exceptions=expected_oracle_exceptions)
                   for _ in range(2)]
        counts["replay_transition_calls"] = sum(r["model_transition_calls"] for r in replays)
        counts["replay_trace_calls"] = 2
        if (not all(r["failed"] for r in replays) or _signature(replays[0]) != _signature(replays[1])
                or observed is None or _signature(replays[0]) != _signature(observed)):
            raise ValueError("native witness did not reproduce twice")
        costs["replay_seconds"] = time.perf_counter()-tick
        costs["oracle_seconds"] += sum(r["wall_seconds"] for r in replays)
        counterexample = dict(replays[0], replay="MATCHED_TWICE")
    total = sum(counts[key] for key in ("development_transition_calls","shrink_transition_calls","replay_transition_calls"))
    temporal_cost = frozen.get("temporal_metrics", {})
    evaluator_rss = None
    try:
        import psutil
        evaluator_rss = psutil.Process().memory_info().rss
    except (ImportError, OSError, psutil.Error if 'psutil' in locals() else OSError):
        pass
    costs.update(wall_seconds=time.perf_counter()-started, evaluator_cpu_seconds=time.process_time()-cpu,
                 evaluator_rss_at_finish_bytes=evaluator_rss,
                 worker_cpu_seconds=worker_cpu, worker_rss_at_freeze_bytes=worker_rss, worker_process_count=worker_processes,
                 worker_costs=temporal_cost, ir_analysis_seconds=None,
                 native_generation_inclusive_seconds=development["wall_seconds"],
                 version_space_update_seconds=temporal_cost.get("version_update_seconds"),
                 solver_seconds=temporal_cost.get("solver_seconds"),
                 phase_scopes={"native_generation":"INCLUDES_TARGET_MODEL_COMPARISON_AND_WORKER_RPC",
                               "oracle":"TARGET_AND_MODEL_ACTIONS_PROJECTION_AND_OUTCOME_VALIDATION",
                               "shrink":"INCLUDES_NATIVE_GENERATION_REPEATS_AND_COMPARISON",
                               "rss":"PROCESS_RESIDENT_SNAPSHOT_NOT_PEAK"},
                 worker_dispatch=worker_metrics,
                 startup_transport_residual_seconds=costs["startup_seconds"]+max(
                     0.0, costs["worker_roundtrip_seconds"]-worker_metrics["wall_seconds"]),
                 measurement_scope="worker roundtrips include serialization and child computation; phase timings overlap; RSS snapshot is not peak; IR source analysis not run")
    return {"schema":"tomolab-temporal-run-v1", "status":"COUNTEREXAMPLE_FOUND" if witness is not None else "NOT_REFUTED_WITHIN_BUDGET",
            **receipt, "spec_sha256":digest(spec), "temporal_contract_sha256":digest(contract), "snapshot":frozen,
            "proposals":proposals, "evidence":evidence, "development":development, "shrink":shrinking,
            "counterexample":counterexample, "metrics":dict(counts, target_calls=total, oracle_calls=total,
                target_transition_calls=total, model_transition_calls=total, hard_transition_limit=budget+shrink_budget+2*steps,
                first_failure_seconds=first_failure_seconds, first_failure_call=first_failure_call,
                feedback_records=len(evidence), cache_scope="specification+engine-version+actual-input; native state mutations never skipped"),
            "timing":costs, "evaluation_split":"DEVELOPMENT", "final_feedback_allowed":False,
            "oracle_verdict":{"source":"INDEPENDENT_MODEL_EXACT_JSON_AND_PROJECTED_STATE", "oracle_errors":"PROPAGATE_UNAPPROVED_EXCEPTIONS"},
            "subjective_assessment":{"status":"NOT_RUN","used_for_verdict":False}, "generalization":"UNKNOWN"}
