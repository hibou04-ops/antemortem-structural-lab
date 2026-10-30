"""Trusted-host numerical execution; no Oracle values enter the Generator.

This is Source development, not the independent C/Target release pathway.
Frozen guides remain unchanged after comparison, shrinking and replay.
"""
from copy import deepcopy
import hashlib
from importlib.metadata import version
import json
import math
import platform
import time

from .schema import canonical, digest, integer
from .numerical_guidance import (FailureGuidanceRecipe, domain_guard,
    numerical_input_digest, public_input_contract,
    shrink_numerical_failure, validate_input_contract)
from .compact_guidance import generate_baseline_candidates as generate_numerical_candidates

METHODS = ("A", "B", "C", "D")


def runtime_identity():
    return {"python": platform.python_version(), "hypothesis": version("hypothesis")}


def _guide_context(compiled, expected_digest):
    from .compact_guidance import validate_execution_artifact
    artifact = validate_execution_artifact(compiled["artifact"], expected_digest,
                                            compiled["approval_receipt"])
    return artifact


def run_numerical_method(compiled=None, *, expected_digest=None, method="D", seed=7,
        size=32, max_examples=512, pair_budget=96, shrink_budget=16,
        excluded_digests=(), replay_inputs=(), contract=None,
        backend="subprocess", image="tomolab-e7-generator:local", setup_seconds=0.0,
        verification_profile=None):
    """Meter actual calls, fresh inputs, known replay, native shrink and errors.

    One initial evaluation and two independently invoked replays confirm a
    new failing input. Shrink calls share the same total per-method budget.
    The public response retains private rows only for the caller's local log.
    """
    api_tick = time.perf_counter()
    from .numerical_source import (target_result, oracle_result, compare_results,
        classify_mechanism, source_identity, comparison_policy)
    from .compact_guidance import host_candidate_plan
    from .numerical_boundary import NumericalBoundary
    from .numerical_response import (assert_equivalent_plans,
        validate_worker_response)
    from .compact_guidance import validate_numerical_request
    if verification_profile not in (None, "runtime", "audit"):
        raise ValueError("verification_profile must be runtime or audit")
    legacy = verification_profile is None
    profile = verification_profile or ("audit" if method == "D" else "runtime")
    if method not in METHODS:
        raise ValueError("method must be A, B, C or D")
    integer(seed, 0, 2**32-1); integer(size, 1, 1024)
    integer(max_examples, size, 8192); integer(pair_budget, 3, 4096)
    integer(shrink_budget, 0, min(1024, pair_budget-3))
    if type(setup_seconds) not in (int, float) or not math.isfinite(setup_seconds) or setup_seconds < 0:
        raise ValueError("nonnegative measured preparation time required")
    artifact_tick = time.perf_counter()
    bound_compiled = compiled if method == "D" or legacy else None
    if method == "D" or legacy:
        artifact = _guide_context(compiled, expected_digest)
        recipe = FailureGuidanceRecipe.from_dict(artifact["bounded_recipe_parameters"][0]).to_dict()
        contract = validate_input_contract(contract or artifact["public_input_contract"])
        if (contract["profile"] != artifact["public_input_contract"]["profile"] or
                not set(contract["lengths"]) <= set(artifact["public_input_contract"]["lengths"])):
            raise ValueError("validation contract must narrow the approved applicability scope")
        artifact_status = "PASS_HOST_APPROVED_COMPACT_GUIDE"
    else:
        # Independent baselines require a public input contract, never D's
        # archive, calibrated recipe, approval receipt or expected digest.
        artifact = None
        contract = validate_input_contract(contract or public_input_contract())
        artifact_status = "NOT_APPLICABLE_BASELINE_NO_GUIDE"
    artifact_seconds = time.perf_counter()-artifact_tick
    known = set(excluded_digests)
    replay_inputs = list(replay_inputs)
    known.update(numerical_input_digest(p) for p in replay_inputs)
    before = digest(bound_compiled)
    tick = time.perf_counter()
    result = {"schema": "tomolab-numerical-execution-v1", "method": method, "seed": seed,
        "scope": "SOURCE_DEVELOPMENT_NOT_INDEPENDENT_CORROBORATION",
        "origin_type": "OBSERVED_VALIDATION_RESULT", "status": "COMPLETE",
        "source_identity": source_identity(), "comparison_contract": comparison_policy(),
        "guide_digest": expected_digest if method == "D" or legacy else None, "contract": contract,
        "pair_budget": pair_budget, "target_calls": 0, "oracle_calls": 0,
        "first_evaluated_valid_inputs": 0, "confirmed_new_failure_inputs": 0,
        "known_input_replay_calls": 0, "initial_known_replays": 0,
        "domain_rejections": 0, "oracle_errors": 0, "target_errors": 0,
        "replay_mismatches": 0, "mechanisms": {}, "unreviewed_failure_inputs": 0,
        "first_new_failure_seconds": None, "first_new_failure_target_calls": None,
        "first_new_failure_oracle_calls": None,
        "cost": {"preparation_seconds": setup_seconds, "generation_seconds": 0.0,
            "worker_seconds": 0.0, "host_equivalence_check_seconds": 0.0,
            "serialization_seconds": 0.0, "target_seconds": 0.0, "oracle_seconds": 0.0,
            "comparison_seconds": 0.0, "replay_seconds": 0.0, "shrink_seconds": 0.0},
        "rows": [], "shrinking": None, "boundary": None,
        "final_feedback_allowed": False, "allow_release": False}
    verification = result["r3"] = {
        "schema": "tomolab-numerical-runtime-verification-v1",
        "verification_profile": profile,
        "api_compatibility": "R2_LEGACY_DEFAULT" if legacy else "EXPLICIT_R3_STRICT",
        "primary_generation_executions": 0, "reference_generation_executions": 0,
        "artifact_validation_status": artifact_status,
        "response_validation_status": "NOT_EXECUTED",
        "equivalence_check_status": "NOT_RUN_IN_RUNTIME" if profile == "runtime" else "NOT_EXECUTED",
        "generation_trace": [], "discovery_events": [], "first_mismatch_observation": None,
        "first_confirmed_failure": None,
        "timing": {"artifact_load_and_validation": artifact_seconds,
            "artifact_load": None, "source_preparation_and_compilation": None,
            "worker_startup_and_generation": None, "response_validation": None,
            "reference_generation": None, "target_execution": None,
            "oracle_execution": None, "failure_replay": None, "shrinking": None,
            "receipt_io": None, "end_to_end_wall": None},
        "timing_contract": "API_ENTRY_INCLUDES_IMPORTS_AND_VALIDATION_NESTED_INTERVALS_NOT_ADDITIVE",
        "generation_count_contract": "GENERATION_REQUESTS_DISPATCHED_TO_STARTED_BOUNDARIES_COMPLETION_SEPARATE_IN_TRACE",
        "receipt_io_included": False,
        "historical_collection_seconds": "UNKNOWN"}
    measured = result["cost"]
    seen = set(known); first_failure = None

    def event():
        return {"seconds_since_api_entry": time.perf_counter()-api_tick,
                "target_calls": result["target_calls"], "oracle_calls": result["oracle_calls"]}

    def evaluate(point, phase):
        if not domain_guard(point, public_input_contract() if phase == "known_replay" else contract):
            result["domain_rejections"] += 1
            return None
        if max(result["target_calls"], result["oracle_calls"]) >= pair_budget:
            return None
        token = numerical_input_digest(point)
        new = token not in seen
        seen.add(token)
        row = {"inputs": deepcopy(point), "input_digest": token, "phase": phase,
               "first_evaluated_valid_input": new, "known_development_input": token in known}
        result["first_evaluated_valid_inputs"] += int(new)
        if token in known:
            result["known_input_replay_calls"] += 1
        try:
            start = time.perf_counter(); result["oracle_calls"] += 1
            try:
                expected = oracle_result(deepcopy(point)); canonical(expected)
                row["expected"] = expected
            except Exception as error:
                result["oracle_errors"] += 1
                row.update(status="ORACLE_ERROR", error_type=type(error).__name__)
                raise
            finally:
                measured["oracle_seconds"] += time.perf_counter()-start
            start = time.perf_counter(); result["target_calls"] += 1
            try:
                actual = target_result(deepcopy(point)); canonical(actual)
                row["actual"] = actual
            except Exception as error:
                result["target_errors"] += 1
                row.update(status="TARGET_ERROR", error_type=type(error).__name__)
                raise
            finally:
                measured["target_seconds"] += time.perf_counter()-start
            start = time.perf_counter()
            row["failed"] = not compare_results(row["actual"], row["expected"])
            row["mechanism"] = classify_mechanism(point, row["actual"], row["expected"])
            measured["comparison_seconds"] += time.perf_counter()-start
            row["status"] = "FAILURE" if row["failed"] else "REFUTATION"
        except Exception:
            result["status"] = "ABORTED_EXECUTION_ERROR"
            result["rows"].append(row)
            raise
        result["rows"].append(row)
        return row

    try:
        request = (dict(artifact=compiled["artifact"], approval_receipt=compiled["approval_receipt"],
            expected_digest=expected_digest, seed=seed, size=size, max_examples=max_examples,
            excluded_digests=sorted(known), contract=contract) if method == "D" else None)
        transport = (dict(action="plan", **request) if method == "D" else
            dict(action="baseline", method=method, seed=seed, size=size, max_examples=max_examples,
                 excluded_digests=sorted(known), contract=contract))
        if method == "C":
            transport["replay_inputs"] = replay_inputs
        # The explicit path validates the complete request before any Source
        # replay. A/B never receive C's counterexamples or D's guide.
        if not legacy:
            transport = validate_numerical_request(transport)
        # C is allowed the identical failure material used for D calibration.
        # Direct replay is paid and reported separately from fresh generation.
        if method == "C":
            replay_started = time.perf_counter()
            for point in replay_inputs:
                if max(result["target_calls"], result["oracle_calls"])+3 > pair_budget-shrink_budget:
                    break
                for _ in range(3):
                    evaluate(point, "known_replay")
                    result["initial_known_replays"] += 1
            measured["replay_seconds"] += time.perf_counter()-replay_started
        start = time.perf_counter()
        encoded = json.dumps(transport,ensure_ascii=True,allow_nan=False).encode("utf-8")
        if len(encoded)+1 > 8_000_000:
            raise ValueError("complete serialized worker request exceeds 8000000 bytes")
        result["serialized_request_bytes"] = len(encoded)+1
        measured["serialization_seconds"] = time.perf_counter()-start
        if method == "D":
            start = time.perf_counter()
            with NumericalBoundary(backend=backend, image=image) as boundary:
                trace = {"role": "primary", "action": "plan", "request_digest": digest(transport),
                         "process_id": boundary.process.pid, "process_started": True,
                         "plan_attempted": True, "plan_completed": False, "boundary": None}
                verification["generation_trace"].append(trace)
                verification["primary_generation_executions"] += 1
                try:
                    planned = boundary.request("plan", **request)
                    trace["plan_completed"] = True
                    plan_snapshot = boundary.request("snapshot") if not legacy else None
                finally:
                    result["boundary"] = boundary.receipt
                    trace["boundary"] = boundary.receipt
            measured["worker_seconds"] = time.perf_counter()-start
            verification["timing"]["worker_startup_and_generation"] = measured["worker_seconds"]
            if not legacy:
                start = time.perf_counter()
                try:
                    generation = validate_worker_response(planned, transport, snapshot=plan_snapshot)
                    verification["response_validation_status"] = "PASS"
                except Exception:
                    verification["response_validation_status"] = "FAIL"
                    raise
                finally:
                    verification["timing"]["response_validation"] = time.perf_counter()-start
            else:
                generation = planned["generation"]
                verification["response_validation_status"] = "LEGACY_R2_DIGEST_AUDIT"
            if profile == "audit":
                start = time.perf_counter()
                try:
                    if legacy:
                        host = host_candidate_plan(**request)
                        verification["reference_generation_executions"] += 1
                        verification["generation_trace"].append({"role": "reference", "action": "plan",
                            "request_digest": digest(transport), "process_id": None,
                            "process_started": True, "plan_attempted": True, "plan_completed": True,
                            "boundary": host.get("reference_boundary")})
                        if host["candidate_digest"] != planned["candidate_digest"]:
                            raise ValueError("host and compact worker candidate results differ")
                        verification["equivalence_check_status"] = "PASS_LEGACY_R2_CANDIDATE_DIGEST"
                    else:
                        reference_image = (result["boundary"]["container_image_id"]
                                           if backend == "docker" else image)
                        with NumericalBoundary(backend=backend, image=reference_image) as reference_worker:
                            trace = {"role": "reference", "action": "plan", "request_digest": digest(transport),
                                     "process_id": reference_worker.process.pid, "process_started": True,
                                     "plan_attempted": True, "plan_completed": False, "boundary": None}
                            verification["generation_trace"].append(trace)
                            verification["reference_generation_executions"] += 1
                            try:
                                reference = reference_worker.request("plan", **request)
                                trace["plan_completed"] = True
                                reference_snapshot = reference_worker.request("snapshot")
                            finally:
                                trace["boundary"] = reference_worker.receipt
                        validate_worker_response(reference, transport, snapshot=reference_snapshot)
                        if trace["boundary"]["generator_sha256"] != result["boundary"]["generator_sha256"]:
                            raise ValueError("reference worker module identities differ")
                        if trace["boundary"]["container_image_id"] != result["boundary"]["container_image_id"]:
                            raise ValueError("reference worker container identities differ")
                        verification["equivalence_semantic_digest"] = assert_equivalent_plans(planned, reference)
                        verification["equivalence_check_status"] = "PASS_FULL_STRUCTURED_SEMANTICS"
                except Exception:
                    verification["equivalence_check_status"] = "FAIL"
                    if legacy:
                        verification["reference_generation_executions"] = None
                    raise
                finally:
                    measured["host_equivalence_check_seconds"] = time.perf_counter()-start
                    verification["timing"]["reference_generation"] = measured["host_equivalence_check_seconds"]
        else:
            start = time.perf_counter()
            if legacy:
                # Preserve the original public API and its baseline extension
                # hook. New explicitly selected modes always use strict workers.
                generation = generate_numerical_candidates(method, seed=seed, size=size,
                    max_examples=max_examples, excluded_digests=sorted(known), contract=contract,
                    replay_inputs=replay_inputs if method == "C" else None)
                verification["response_validation_status"] = "LEGACY_R2_BASELINE_API"
                result["boundary"] = generation.get("generation_boundary")
                verification["primary_generation_executions"] = 1 if result["boundary"] is not None else None
            else:
                fields = {k:v for k,v in transport.items() if k != "action"}
                with NumericalBoundary(backend=backend, image=image) as boundary:
                    trace = {"role": "primary", "action": "baseline", "request_digest": digest(transport),
                             "process_id": boundary.process.pid, "process_started": True,
                             "plan_attempted": True, "plan_completed": False, "boundary": None}
                    verification["generation_trace"].append(trace)
                    verification["primary_generation_executions"] += 1
                    try:
                        response = boundary.request("baseline", **fields)
                        trace["plan_completed"] = True
                        snapshot = boundary.request("snapshot")
                    finally:
                        result["boundary"] = boundary.receipt
                        trace["boundary"] = boundary.receipt
                worker_seconds = time.perf_counter()-start
                verification["timing"]["worker_startup_and_generation"] = worker_seconds
                measured["worker_seconds"] = worker_seconds
                validation_tick = time.perf_counter()
                try:
                    generation = validate_worker_response(response, transport, snapshot=snapshot)
                    verification["response_validation_status"] = "PASS"
                except Exception:
                    verification["response_validation_status"] = "FAIL"
                    raise
                finally:
                    verification["timing"]["response_validation"] = time.perf_counter()-validation_tick
            measured["generation_seconds"] = time.perf_counter()-start
            if profile == "audit":
                verification["equivalence_check_status"] = "NOT_APPLICABLE_BASELINE_SINGLE_GENERATION"
        verification["candidate_semantic_digest"] = digest(generation["candidates"])
        result["generation"] = {k:v for k,v in generation.items() if k != "candidates"}
        result["candidate_count"] = len(generation["candidates"])
        result["candidate_input_digest"] = digest([r["inputs"] for r in generation["candidates"]])
        reserve = shrink_budget + (2 if shrink_budget else 0)
        for candidate in generation["candidates"]:
            point = candidate["inputs"]; token = numerical_input_digest(point)
            if token in seen:
                continue  # C explicit replays were already paid above.
            if max(result["target_calls"], result["oracle_calls"])+3 > pair_budget-reserve:
                result["stop"] = "PAIR_BUDGET_RESERVED_FOR_SHRINKING"
                break
            row = evaluate(point, "fresh_generation")
            row.update(origin=candidate["origin"], transform=candidate["transform"], recipe_id=candidate["recipe_id"])
            if not row["failed"]:
                continue
            if verification["first_mismatch_observation"] is None:
                verification["first_mismatch_observation"] = event()
            if first_failure is None:
                first_failure = deepcopy(point)
                result["first_new_failure_seconds"] = time.perf_counter()-tick+setup_seconds
                result["first_new_failure_target_calls"] = result["target_calls"]
                result["first_new_failure_oracle_calls"] = result["oracle_calls"]
            start = time.perf_counter()
            replays = [evaluate(point, "new_failure_replay") for _ in range(2)]
            measured["replay_seconds"] += time.perf_counter()-start
            if any(r is None or (r["actual"], r["expected"], r["failed"]) !=
                    (row["actual"], row["expected"], row["failed"]) for r in replays):
                result["replay_mismatches"] += 1
                result["status"] = "INCONCLUSIVE_REPLAY_MISMATCH"
                continue
            result["confirmed_new_failure_inputs"] += 1
            row["confirmed_failure"] = True
            confirmed_event = dict(event(), input_digest=token,
                confirmed_failure_index=result["confirmed_new_failure_inputs"])
            verification["discovery_events"].append(confirmed_event)
            if verification["first_confirmed_failure"] is None:
                verification["first_confirmed_failure"] = deepcopy(confirmed_event)
            mechanism = row["mechanism"]
            if mechanism == "OTHER_REQUIRES_REVIEW":
                result["unreviewed_failure_inputs"] += 1
            else:
                result["mechanisms"][mechanism] = result["mechanisms"].get(mechanism, 0)+1
        if first_failure is not None and shrink_budget:
            start = time.perf_counter()
            def predicate(point):
                row = evaluate(point, "native_shrink")
                return bool(row is not None and row["failed"])
            # All methods use the same public-prior shrink grammar. No method
            # receives extra calibration knowledge during reduction.
            result["shrinking"] = shrink_numerical_failure(predicate, method="B", contract=contract,
                budget=shrink_budget, seed=seed+1 if seed < 2**32-1 else 0,
                initial_witness=first_failure)
            witness = result["shrinking"]["witness"]
            result["shrinking"]["original_witness"] = first_failure
            if witness is not None:
                replays = [evaluate(witness, "shrink_replay") for _ in range(2)]
                result["shrinking"]["reproduced_twice"] = all(r is not None and r["failed"] for r in replays)
                if not result["shrinking"]["reproduced_twice"]:
                    result["status"] = "INCONCLUSIVE_REPLAY_MISMATCH"
            measured["shrink_seconds"] = time.perf_counter()-start
    except Exception as error:
        result["status"] = "ABORTED_EXECUTION_ERROR"
        result["error_type"] = type(error).__name__
        result["error"] = str(error)
        if verification["response_validation_status"] == "NOT_EXECUTED":
            verification["response_validation_status"] = "NOT_COMPLETED_EXECUTION_ERROR"
    if digest(bound_compiled) != before:
        raise ValueError("guide changed after freeze")
    result["confirmed_mechanism_count"] = len(result["mechanisms"])
    result["phase_counts"] = {phase:{
        "source_oracle_pairs":len([r for r in result["rows"] if r["phase"] == phase and "actual" in r]),
        "first_evaluated_valid_inputs":sum(r["first_evaluated_valid_input"] for r in result["rows"] if r["phase"] == phase)}
        for phase in sorted({r["phase"] for r in result["rows"]})}
    result["distinct_new_mechanisms"] = 0  # Only the reviewed existing mechanism is counted.
    result["oracle_target_primitive_calls"] = result["oracle_calls"]+result["target_calls"]
    measured["current_execution_seconds"] = time.perf_counter()-tick
    measured["measured_cold_total_seconds"] = measured["current_execution_seconds"]+setup_seconds
    measured["archive_reuse_incremental_seconds"] = measured["current_execution_seconds"]
    measured["historical_collection_seconds"] = "UNKNOWN"
    measured["complete_historical_collection_to_discovery_seconds"] = None
    result["guide_unchanged"] = True
    for name, legacy_name in (("target_execution", "target_seconds"),
            ("oracle_execution", "oracle_seconds"), ("failure_replay", "replay_seconds"),
            ("shrinking", "shrink_seconds")):
        verification["timing"][name] = measured[legacy_name]
    if not any(row["phase"] in ("known_replay", "new_failure_replay") for row in result["rows"]):
        verification["timing"]["failure_replay"] = None
    if result["shrinking"] is None:
        verification["timing"]["shrinking"] = None
    verification["timing"]["end_to_end_wall"] = time.perf_counter()-api_tick
    for field in ("verification_profile", "primary_generation_executions", "reference_generation_executions",
                  "artifact_validation_status", "response_validation_status", "equivalence_check_status"):
        result[field] = verification[field]
    result["receipt_sha256"] = digest(result)
    return result


def run_numerical_comparison(compiled, *, expected_digest, seeds=(13,47,89),
        contract=None, excluded_digests=(), replay_inputs=(), size=32,
        max_examples=512, pair_budget=96, shrink_budget=16, backend="subprocess",
        image="tomolab-e7-generator:local", preparation_costs=None):
    """One predeclared Source comparison with strong, equally informed controls."""
    contract = validate_input_contract(contract or public_input_contract(lengths=[4,5,6]))
    preparation_costs = dict(preparation_costs or {})
    if not 1 <= len(seeds) <= 16 or len(set(seeds)) != len(seeds):
        raise ValueError("bounded unique preregistered seeds required")
    runs = []
    for index, seed in enumerate(seeds):
        # Balanced deterministic ordering avoids always warming D last.
        order = METHODS[index % 4:]+METHODS[:index % 4]
        for method in order:
            runs.append(run_numerical_method(compiled, expected_digest=expected_digest,
                method=method, seed=seed, contract=contract, excluded_digests=excluded_digests,
                replay_inputs=replay_inputs, size=size, max_examples=max_examples,
                pair_budget=pair_budget, shrink_budget=shrink_budget, backend=backend, image=image,
                setup_seconds=preparation_costs.get(method,0.0)))
    summaries = {}
    for method in METHODS:
        rows = [r for r in runs if r["method"] == method]
        unique_inputs = {v["input_digest"] for r in rows for v in r["rows"]
                         if v["phase"] == "fresh_generation" and not v["known_development_input"]}
        unique_failures = {v["input_digest"] for r in rows for v in r["rows"]
                           if v["phase"] == "fresh_generation" and v.get("confirmed_failure")}
        summaries[method] = {"trials": len(rows),
            "completed_trials": sum(r["status"] == "COMPLETE" for r in rows),
            "unique_fresh_generation_valid_inputs": len(unique_inputs),
            "first_evaluated_valid_inputs_trial_sum_including_shrink": sum(r["first_evaluated_valid_inputs"] for r in rows),
            "confirmed_new_failure_inputs": len(unique_failures),
            "confirmed_new_failure_inputs_trial_sum": sum(r["confirmed_new_failure_inputs"] for r in rows),
            "confirmed_mechanisms": sorted({m for r in rows for m in r["mechanisms"]}),
            "target_calls": sum(r["target_calls"] for r in rows),
            "oracle_calls": sum(r["oracle_calls"] for r in rows),
            "known_input_replay_calls": sum(r["known_input_replay_calls"] for r in rows),
            "domain_rejections": sum(r["domain_rejections"]+r.get("generation",{}).get("domain_rejections",0) for r in rows),
            "oracle_errors": sum(r["oracle_errors"] for r in rows),
            "current_execution_seconds": sum(r["cost"]["current_execution_seconds"] for r in rows),
            "one_time_preparation_seconds": preparation_costs.get(method,0.0),
            "first_new_failure_primitive_calls": [None if r["first_new_failure_target_calls"] is None else
                r["first_new_failure_target_calls"]+r["first_new_failure_oracle_calls"] for r in rows],
            "first_new_failure_cold_seconds": [r["first_new_failure_seconds"] for r in rows]}
        summaries[method]["measured_total_with_one_preparation_seconds"] = (
            summaries[method]["current_execution_seconds"]+preparation_costs.get(method,0.0))
    def beats(method):
        # Descriptive, preregistered engineering criterion; no significance claim.
        left, right = summaries["D"], summaries[method]
        return (left["confirmed_new_failure_inputs"] > right["confirmed_new_failure_inputs"] and
                left["measured_total_with_one_preparation_seconds"] <= right["measured_total_with_one_preparation_seconds"])
    if any(r["status"] != "COMPLETE" for r in runs):
        verdict = "INCONCLUSIVE"
    elif beats("B") and beats("C"):
        verdict = "SOURCE_GUIDANCE_VALUE_OBSERVED"
    elif not beats("B"):
        verdict = "NO_ADDITIONAL_VALUE_OVER_DOMAIN_PRIOR"
    elif not beats("C"):
        verdict = "NO_ADDITIONAL_VALUE_OVER_REPLAY"
    else:
        verdict = "INCONCLUSIVE"
    global_seen = set(excluded_digests)
    global_seen.update(numerical_input_digest(p) for p in replay_inputs)
    global_new = {method:0 for method in METHODS}
    global_new_failures = set()
    for run in runs:
        for row in run["rows"]:
            token = row["input_digest"]
            if token not in global_seen:
                global_new[run["method"]] += 1
                global_seen.add(token)
            if row.get("confirmed_failure"):
                global_new_failures.add(token)
    result = {"schema": "tomolab-numerical-comparison-v1", "scope": "SOURCE_INPUT_GENERALIZATION_ONLY",
        "status": "COMPLETE" if all(r["status"] == "COMPLETE" for r in runs) else "INCONCLUSIVE",
        "verdict": verdict, "criterion": "MORE_CONFIRMED_NEW_INPUTS_AND_NO_MORE_MEASURED_TOTAL_COST_THAN_B_AND_C",
        "public_prior_shared_by": ["B","C","D"], "same_source_failure_material_for": ["C","D"],
        "summaries": summaries, "runs": runs, "runtime": runtime_identity(),
        "independent_C": 0, "eligible_unconsumed_Target": 0, "external_generalization": "NOT_EXECUTED",
        "allow_release": False, "publication": "NOT_AUTHORIZED", "statistical_superiority_claimed": False,
        "historical_acquisition_cost": "UNKNOWN", "distinct_new_mechanisms": 0}
    result["input_counting"] = {"method_unique_counts_relative_to":"FROZEN_PREVALIDATION_KNOWN_SET",
        "trial_sum_is_not_distinct_count":True,
        "actual_first_evaluations_across_all_methods_and_shrink_by_execution_order":global_new,
        "actual_first_evaluations_across_entire_batch":sum(global_new.values()),
        "batch_distinct_confirmed_new_failure_inputs":len(global_new_failures),
        "cross_method_overlap_does_not_influence_generation_or_primary_method_comparison":True}
    result["receipt_sha256"] = digest(result)
    return result
