"""Reviewed local CORR seam reusing the frozen R3 generation and Oracle APIs.

All plans are materialized before any CORR observation. No evaluator, library
identity, warning, result, permit or Oracle is sent into the Generator.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

from .schema import canonical, digest, integer, keys
from .numerical_guidance import (domain_guard, numerical_input_digest,
    public_input_contract, shrink_numerical_failure)

PLAN_SCHEMA = "tomolab-corroboration-candidate-plan-v1"
PLAN_FIELDS = ("schema", "method", "seed", "request", "response", "snapshot", "generation",
    "boundary", "verification_profile", "primary_generation_executions",
    "reference_generation_executions", "response_validation_status", "metrics", "plan_digest")


def _plan_digest(plan):
    return digest({k:v for k,v in plan.items() if k != "plan_digest"})


def validate_candidate_plan(plan):
    from .compact_guidance import validate_numerical_request
    from .numerical_response import validate_worker_response
    from .numerical_boundary import GENERATOR_FILES
    keys(plan, PLAN_FIELDS)
    if (plan["schema"] != PLAN_SCHEMA or plan["verification_profile"] != "runtime"
            or type(plan["primary_generation_executions"]) is not int or plan["primary_generation_executions"] != 1
            or type(plan["reference_generation_executions"]) is not int or plan["reference_generation_executions"] != 0
            or plan["response_validation_status"] != "PASS"
            or plan["plan_digest"] != _plan_digest(plan)):
        raise ValueError("invalid frozen single-generation CORR plan")
    request = validate_numerical_request(plan["request"])
    if (plan["method"] != ("D" if request["action"] == "plan" else request["method"])
            or plan["seed"] != request["seed"]
            or request["contract"] != public_input_contract(lengths=[4,5,6])):
        raise ValueError("CORR plan method, seed or unchanged generation domain differs")
    actual = validate_worker_response(plan["response"], request, snapshot=plan["snapshot"])
    if canonical(actual) != canonical(plan["generation"]):
        raise ValueError("stored generation differs from actual validated worker response")
    expected = {name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                for name in GENERATOR_FILES}
    if plan["boundary"].get("generator_sha256") != expected:
        raise ValueError("frozen Generator module identity changed")
    return deepcopy(plan)


def plan_candidates(*, method, seed, contract=None, compiled=None, expected_digest=None,
        replay_inputs=(), excluded_digests=(), size=32, max_examples=512,
        backend="subprocess", image="tomolab-e7-generator:local"):
    """Use the exact existing runtime worker once; never call a Target here."""
    started = time.perf_counter()
    from .compact_guidance import validate_numerical_request
    from .numerical_boundary import NumericalBoundary
    from .numerical_response import validate_worker_response
    contract = public_input_contract(lengths=[4,5,6]) if contract is None else deepcopy(contract)
    if method == "D":
        if compiled is None:
            raise ValueError("D requires the unchanged externally approved compact Source guide")
        request = dict(action="plan", artifact=compiled["artifact"], approval_receipt=compiled["approval_receipt"],
            expected_digest=expected_digest, seed=seed, size=size, max_examples=max_examples,
            excluded_digests=sorted(set(excluded_digests)), contract=contract)
    else:
        if compiled is not None or expected_digest is not None:
            raise ValueError("independent baselines do not receive D's guide or approval")
        request = dict(action="baseline", method=method, seed=seed,size=size,max_examples=max_examples,
            excluded_digests=sorted(set(excluded_digests)), contract=contract)
        if method == "C":
            request["replay_inputs"] = deepcopy(list(replay_inputs))
        elif replay_inputs:
            raise ValueError("A/B do not receive failure input exemplars")
    request = validate_numerical_request(request)
    serialization_tick = time.perf_counter()
    encoded = json.dumps(request, ensure_ascii=True, allow_nan=False).encode("utf-8")
    if len(encoded)+1 > 8_000_000:
        raise ValueError("complete CORR generation request exceeds the existing transport limit")
    serialization_seconds = time.perf_counter()-serialization_tick
    worker_tick = time.perf_counter()
    with NumericalBoundary(backend=backend, image=image) as worker:
        response = worker.request(request["action"], **{k:v for k,v in request.items() if k != "action"})
        snapshot = worker.request("snapshot")
        boundary = worker.receipt
    worker_seconds = time.perf_counter()-worker_tick
    validation_tick = time.perf_counter()
    generation = validate_worker_response(response, request, snapshot=snapshot)
    validation_seconds = time.perf_counter()-validation_tick
    plan = dict(schema=PLAN_SCHEMA, method=method, seed=seed, request=request,
        response=response,snapshot=snapshot,generation=generation,boundary=boundary,
        verification_profile="runtime", primary_generation_executions=1,
        reference_generation_executions=0, response_validation_status="PASS",
        metrics=dict(generation_wall_seconds=time.perf_counter()-started,
            worker_startup_generation_shutdown_seconds=worker_seconds,
            response_validation_seconds=validation_seconds, serialization_seconds=serialization_seconds,
            serialized_request_bytes=len(encoded)+1, target_calls=0, oracle_calls=0,
            algorithm="Hypothesis-strategy-plan", target_identity_sent_to_worker=False,
            evaluator_feedback_sent_to_worker=False))
    plan["plan_digest"] = _plan_digest(plan)
    validate_candidate_plan(plan)
    return plan


def _semantic_result(row):
    return digest({k:row[k] for k in ("normalized", "raw_outcome", "expected", "comparison")})


def run_corroboration_plan(plan, permit, *, expected_approval_context, usage_ledger, claim_id):
    """Evaluate a precommitted plan using one specifically approved local API.

    The fixed usage authority must already have consumed the implementation as
    CORR. A final-readiness receipt or an edited JSON permit cannot replace it.
    """
    started = time.perf_counter()
    from .corroboration_permit import CorroborationExecutionPermit, SCOPE
    from .corroboration_adapters import create_reviewed_adapter
    if not isinstance(permit, CorroborationExecutionPermit):
        raise PermissionError("an independently authorized CORR permit object is required")
    permit.validate(expected_approval_context, plan=plan)
    context = permit.context
    if usage_ledger.authority_id != context["authority_id"]:
        raise PermissionError("CORR execution usage authority differs")
    usage = usage_ledger.inspect()
    starts = [row for row in usage["rows"] if row["event"] == "START" and row["claim_id"] == claim_id]
    if (claim_id not in usage["open_claim_ids"] or len(starts) != 1
            or starts[0]["payload"].get("scope") != SCOPE
            or permit.permit_digest not in starts[0]["payload"].get("permit_digests", [])):
        raise PermissionError("CORR requires a matching consumed development START, never a final authorization")
    adapter_tick = time.perf_counter()
    identity = context["approved_implementation_identity"]
    adapter = create_reviewed_adapter(identity["implementation_id"], expected_identity=identity)
    adapter_seconds = time.perf_counter()-adapter_tick
    budgets = context["resource_budget"]
    common = context["common_input_contract"]
    fresh_contract = context["candidate_generation_contract"]
    method, seed = plan["method"], plan["seed"]
    result = dict(schema="tomolab-corroboration-execution-v1", scope=SCOPE,
        status="COMPLETE", outcome=None, implementation_id=identity["implementation_id"],
        implementation_identity_digest=digest(identity), permit_digest=permit.permit_digest,
        claim_id=claim_id, method=method, seed=seed, plan_digest=plan["plan_digest"],
        guide_digest=context["frozen_source_guide_digest"], common_input_contract=common,
        candidate_generation_contract=fresh_contract, resource_budget=budgets,
        verification_profile="runtime", primary_generation_executions=1, reference_generation_executions=0,
        target_calls=0, oracle_calls=0, actual_target_function_entries=0,
        domain_rejections=0, oracle_errors=0, target_errors=0, adapter_errors=0, not_comparable=0, replay_mismatches=0,
        confirmed_contract_violation_inputs=0, confirmed_fresh_violation_inputs=0,
        confirmed_source_replay_violation_inputs=0, violation_categories={},
        first_mismatch_observation=None, first_confirmed_failure=None, rows=[],shrinking=None,
        cost=dict(adapter_initialization_seconds=adapter_seconds,
            target_call_seconds=0.0, normalization_seconds=0.0, oracle_seconds=0.0,
            comparison_seconds=0.0, replay_seconds=0.0, shrink_seconds=0.0),
        source_archive_modified=False, generator_feedback_calls=0, allow_release=False,
        final_evaluation_authorized=False, publication_authorized=False)
    source_known = set(plan["request"]["excluded_digests"])
    seen, confirmed = set(), set()
    first_fresh_failure = None

    def event():
        return dict(seconds_since_execution_api_entry=time.perf_counter()-started,
            target_calls=result["target_calls"],oracle_calls=result["oracle_calls"])

    def evaluate(point, phase):
        selected_contract = common if phase == "known_source_replay" else fresh_contract
        if not domain_guard(point, selected_contract):
            result["domain_rejections"] += 1
            return None
        if max(result["target_calls"], result["oracle_calls"]) >= budgets["pair_budget"]:
            return None
        token = numerical_input_digest(point)
        row = dict(inputs=deepcopy(point), input_digest=token, phase=phase,
            first_evaluation_within_run=token not in seen,
            previously_observed_source_input=token in source_known,
            source_replay=phase == "known_source_replay")
        seen.add(token)
        before = adapter.call_counters
        try:
            observation = adapter.evaluate(deepcopy(point),contract=selected_contract)
            row.update(observation)
        except Exception as error:
            row.update(execution_error_type=type(error).__name__,execution_error=str(error),
                comparison=dict(status="EXECUTION_ERROR",component="ADAPTER"))
            result["adapter_errors"] += 1
            result["rows"].append(row)
            raise
        finally:
            after = adapter.call_counters
            for field in ("target_calls", "oracle_calls", "actual_target_function_entries"):
                result[field] += after[field]-before[field]
        result["rows"].append(row)
        for name in ("target_call_seconds", "normalization_seconds", "oracle_seconds", "comparison_seconds"):
            result["cost"][name] += row["timings"][name] or 0.0
        if row["comparison"]["status"] == "EXECUTION_ERROR":
            component = row["comparison"].get("component", "ORACLE")
            result["target_errors" if component == "TARGET_ENVIRONMENT" else "oracle_errors"] += 1
            raise RuntimeError("CORR target/Oracle infrastructure execution failed")
        if row["comparison"]["status"] == "NOT_COMPARABLE":
            result["not_comparable"] += 1
        if row["comparison"]["status"] == "MISMATCH" and result["first_mismatch_observation"] is None:
            result["first_mismatch_observation"] = event()
        return row

    def confirm(rows, *, fresh):
        nonlocal first_fresh_failure
        if len(rows) != 3 or any(row is None for row in rows):
            return
        if any(_semantic_result(row) != _semantic_result(rows[0]) for row in rows[1:]):
            result["replay_mismatches"] += 1
            result["status"] = "INCONCLUSIVE_REPLAY_MISMATCH"
            return
        row = rows[0]
        if row["comparison"]["status"] != "MISMATCH" or row["input_digest"] in confirmed:
            return
        confirmed.add(row["input_digest"])
        row["confirmed_failure"] = True
        result["confirmed_contract_violation_inputs"] += 1
        result["confirmed_fresh_violation_inputs" if fresh else "confirmed_source_replay_violation_inputs"] += 1
        category = row["comparison"]["violation_category"]
        result["violation_categories"][category] = result["violation_categories"].get(category, 0)+1
        if result["first_confirmed_failure"] is None:
            result["first_confirmed_failure"] = dict(event(),input_digest=row["input_digest"],
                phase=row["phase"],violation_category=category)
        if fresh and first_fresh_failure is None:
            first_fresh_failure = deepcopy(row["inputs"])

    try:
        if method == "C":
            replay_tick = time.perf_counter()
            for point in plan["request"]["replay_inputs"]:
                if max(result["target_calls"],result["oracle_calls"])+3 > budgets["pair_budget"]-budgets["shrink_budget"]:
                    break
                confirm([evaluate(point,"known_source_replay") for _ in range(3)],fresh=False)
            result["cost"]["replay_seconds"] += time.perf_counter()-replay_tick
        reserve = budgets["shrink_budget"]+(2 if budgets["shrink_budget"] else 0)
        for candidate in plan["generation"]["candidates"]:
            point = candidate["inputs"]
            if numerical_input_digest(point) in seen:
                continue
            if max(result["target_calls"],result["oracle_calls"])+3 > budgets["pair_budget"]-reserve:
                result["stop"] = "PAIR_BUDGET_RESERVED_FOR_SHRINKING"
                break
            row = evaluate(point,"fresh_generation")
            row.update(origin=candidate["origin"],transform=candidate["transform"],recipe_id=candidate["recipe_id"])
            if row["comparison"]["status"] == "MISMATCH":
                replay_tick = time.perf_counter()
                replays = [evaluate(point,"new_failure_replay") for _ in range(2)]
                result["cost"]["replay_seconds"] += time.perf_counter()-replay_tick
                confirm([row,*replays],fresh=True)
        if first_fresh_failure is not None and budgets["shrink_budget"]:
            shrink_tick = time.perf_counter()
            def predicate(point):
                row = evaluate(point,"native_shrink")
                return row is not None and row["comparison"]["status"] == "MISMATCH"
            result["shrinking"] = shrink_numerical_failure(predicate,method="B",contract=fresh_contract,
                budget=budgets["shrink_budget"],seed=seed+1 if seed < 2**32-1 else 0,
                initial_witness=first_fresh_failure)
            witness = result["shrinking"]["witness"]
            if witness is not None:
                witness_digest = numerical_input_digest(witness)
                reference = next((row for row in reversed(result["rows"])
                    if row["input_digest"] == witness_digest and row.get("comparison",{}).get("status") == "MISMATCH"),None)
                replays = [evaluate(witness,"shrink_replay") for _ in range(2)]
                result["shrinking"]["reproduced_twice"] = reference is not None and all(
                    row is not None and row["comparison"]["status"] == "MISMATCH"
                    and _semantic_result(row) == _semantic_result(reference) for row in replays)
                if not result["shrinking"]["reproduced_twice"]:
                    result["replay_mismatches"] += 1
                    result["status"] = "INCONCLUSIVE_REPLAY_MISMATCH"
            result["cost"]["shrink_seconds"] = time.perf_counter()-shrink_tick
    except Exception as exc:
        result.update(status="ABORTED_EXECUTION_ERROR",error_type=type(exc).__name__,error=str(exc))
    if result["status"] != "COMPLETE":
        result["outcome"] = "INCONCLUSIVE"
    elif result["not_comparable"]:
        result["outcome"] = "PARTIAL_NOT_COMPARABLE"
    elif confirmed:
        result["outcome"] = "CONFIRMED_CONTRACT_VIOLATION_WITHIN_BUDGET"
    else:
        result["outcome"] = "NO_CONFIRMED_FAILURE_WITHIN_BUDGET"
    result["cost"]["execution_api_wall_seconds"] = time.perf_counter()-started
    result["cost"]["generation_plan_wall_seconds"] = plan["metrics"]["generation_wall_seconds"]
    result["cost"]["logical_prepared_before_receipt_seconds"] = (
        result["cost"]["execution_api_wall_seconds"]+plan["metrics"]["generation_wall_seconds"])
    result["cost"]["intervals_nested_not_additive"] = True
    if result["first_confirmed_failure"] is not None:
        result["first_confirmed_failure"]["charged_plan_plus_execution_seconds"] = (
            plan["metrics"]["generation_wall_seconds"]+result["first_confirmed_failure"]["seconds_since_execution_api_entry"])
    result["receipt_sha256"] = digest(result)
    return result
