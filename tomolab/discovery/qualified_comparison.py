"""Trusted-host A-D comparison; live readiness and atomic START precede calls.

All plans are frozen without Target results. This is not adaptive Hypothesis
PBT. Host callbacks, raw outcomes and final inputs never go to the Generator.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import time

from .development_evidence import DevelopmentEvidenceArchive
from .evaluation_readiness import EvaluationReadiness, plans_fingerprint
from .hypothesis_adapter import generate_pool
from .predicates import predicate_value
from .schema import canonical, digest, validate_inputs, decode_inputs

METHODS = ("A", "B", "C", "D")
EXECUTION_WALL_SECONDS = 15.0


def equivalent(left, right, policy):
    """Declared finite JSON values; integer and bool contracts remain exact."""
    canonical(left); canonical(right)
    if isinstance(left,bool) or isinstance(right,bool):
        return type(left) is type(right) and left == right
    if isinstance(left,(int,float)) and isinstance(right,(int,float)):
        if type(left) is int and type(right) is int:
            return left == right
        return math.isclose(left,right,rel_tol=policy["relative_tolerance"],abs_tol=policy["absolute_tolerance"])
    if isinstance(left,dict) and isinstance(right,dict):
        return left.keys() == right.keys() and all(equivalent(left[k],right[k],policy) for k in left)
    if isinstance(left,(list,tuple)) and isinstance(right,(list,tuple)):
        return len(left) == len(right) and all(equivalent(a,b,policy) for a,b in zip(left,right))
    return type(left) is type(right) and left == right


def _public_valid(point, target):
    validate_inputs(point,target["spec"])
    return all(predicate_value(p,point,target["spec"]) is True for p in target["public_guard"]["predicates"])


def _source_points(context):
    evidence = DevelopmentEvidenceArchive.from_snapshot(context["evidence_bundle"])
    source = context["knowledge_snapshot"]["source"]
    return [dict(record_id=r["record_id"],spec=r["spec"],inputs=r["input_or_trace"])
            for r in evidence.accepted_records()
            if r["provenance"]["origin"] == source and r["observed_failure_or_refutation"]["status"] == "FAILURE"]


def _simple_replay(source_points, target, native, budget):
    candidates, seen, rejected, duplicated = [], set(), 0, 0
    target_names = {item["role"]:item["name"] for item in target["spec"]["inputs"]}
    for row in source_points:
        source_names = {item["role"]:item["name"] for item in row["spec"]["inputs"]}
        if source_names.keys() != target_names.keys():
            rejected += 1; continue
        point = {target_names[role]:deepcopy(row["inputs"][source_names[role]]) for role in target_names}
        try:
            validate_inputs(point,target["spec"])
        except ValueError:
            rejected += 1; continue
        token = canonical(point)
        if token in seen:
            duplicated += 1; continue
        seen.add(token)
        candidates.append({"inputs":point,"source":"SOURCE_COUNTEREXAMPLE_ROLE_REPLAY",
                           "source_record_id":row["record_id"],"claim_ids":[],"frozen":True})
        if len(candidates) == budget:
            break
    for point in native:
        if len(candidates) >= budget:
            break
        token = canonical(point)
        if token in seen:
            continue
        seen.add(token)
        candidates.append({"inputs":deepcopy(point),"source":"NATIVE_FILL_AFTER_SOURCE_REPLAY","claim_ids":[],"frozen":True})
    return {"candidates":candidates,"source_mapping_rejected":rejected,
            "source_mapping_duplicates":duplicated,"target_calls":0,"oracle_calls":0,
            "final_feedback_allowed":False}


def _comparison_plan_hash(plans):
    # Timings are charged separately. Only frozen public input order and its
    # actual source/claim bindings determine the comparative intervention.
    return digest([{k:v for k,v in row.items() if k != "planning_seconds" and k != "plan"} |
                   {"candidates":row["plan"]["candidates"]} for row in plans])


def prepare_comparison(readiness):
    if not isinstance(readiness,EvaluationReadiness):
        raise TypeError("a live EvaluationReadiness object is required")
    started = time.perf_counter()
    authorization = readiness.authorize_final_comparison()
    if authorization["status"] != "PASS":
        return {"status":"NOT_EXECUTED_READINESS_BLOCKED","readiness":authorization,
                "target_calls":0,"oracle_calls":0,"final_execution_started":False}
    context = readiness.get_execution_context()
    protocol = context["fixed_protocol"]
    real = any(target["scope"] == "REVIEWED_REAL_PROJECT" for target in context["targets"])
    if real and not protocol.get("decision_rules"):
        return {"status":"NOT_EXECUTED_READINESS_BLOCKED","readiness":authorization,
                "blockers":["READINESS_BLOCKED_COMPARISON_CONTRACT"],
                "reason":"real comparison thresholds and measured source costs were not preregistered",
                "target_calls":0,"oracle_calls":0,"final_execution_started":False}
    policy = protocol["comparison_policy"]
    if (policy["kind"] != "FINITE_JSON" or policy["undefined"] != "EXECUTION_ERROR"
            or policy["exceptions"] != "EXECUTION_ERROR"):
        raise ValueError("predeclared finite JSON comparison policy required")
    baseline = readiness.get_prepared_plans()
    if plans_fingerprint(baseline) != authorization["bindings"]["prepared_plans_sha256"]:
        raise ValueError("readiness plans differ from their authorization")
    lookup = {(r["target_id"],r["seed"],r["method"]):r for r in baseline}
    source_started = time.perf_counter()
    source = _source_points(context)
    source_retrieval_seconds = time.perf_counter()-source_started
    plans = []
    for target in context["targets"]:
        for seed in protocol["seeds"]:
            tick = time.perf_counter()
            native = generate_pool(target["spec"],seed=seed,size=max(protocol["budget"],protocol["pool_size"]))
            unique = []; seen = set()
            for point in native:
                validate_inputs(point,target["spec"])
                token = canonical(point)
                if token not in seen:
                    seen.add(token); unique.append(point)
            a = {"candidates":[{"inputs":deepcopy(p),"source":"HYPOTHESIS_STRATEGY_PLAN","claim_ids":[],"frozen":True}
                                for p in unique[:protocol["budget"]]],"target_calls":0,"oracle_calls":0,"final_feedback_allowed":False}
            a_time = time.perf_counter()-tick
            tick = time.perf_counter()
            # D receives its own identical-budget strategy initialization.
            # Sharing A's already-generated pool would undercharge its cost.
            replay_pool = generate_pool(target["spec"],seed=seed,size=max(protocol["budget"],protocol["pool_size"]))
            d = _simple_replay(source,target,replay_pool,protocol["budget"])
            d_time = time.perf_counter()-tick
            for method, plan, seconds in (("A",a,a_time),
                    ("B",lookup[(target["target_id"],seed,"B")]["plan"],lookup[(target["target_id"],seed,"B")]["parent_plan_wall_seconds"]),
                    ("C",lookup[(target["target_id"],seed,"C")]["plan"],lookup[(target["target_id"],seed,"C")]["parent_plan_wall_seconds"]),("D",d,d_time)):
                if plan["target_calls"] or plan["oracle_calls"] or plan["final_feedback_allowed"] is not False:
                    raise ValueError("planning information boundary failed")
                plans.append({"target_id":target["target_id"],"seed":seed,"method":method,
                              "planning_seconds":seconds,"plan":plan})
    return {"schema":"tomolab-e8-frozen-comparison-v1","status":"PREPARED",
            "readiness":authorization,"context_sha256":digest(context),"plans":plans,
            "comparison_plan_sha256":_comparison_plan_hash(plans),
            "preparation_wall_seconds":time.perf_counter()-started,
            "source_replay_retrieval_wall_seconds":source_retrieval_seconds,
            "readiness_validation_metrics":readiness.get_validation_metrics(),
            "target_calls":0,"oracle_calls":0,"final_execution_started":False}


def compare_frozen(readiness, evaluators, *, output, trusted_execution=False, expected_authorization=None,
                   host_preflight_wall_seconds=0.0):
    """Run only approved host callbacks after live readiness and fixed START.

    Each evaluator entry has target/Oracle callables and their pinned hashes.
    Exceptions and unsupported results abort; an interrupted START stays used.
    """
    if trusted_execution is not True:
        raise PermissionError("explicit trusted host execution approval required")
    runner_started = time.perf_counter()
    if (type(host_preflight_wall_seconds) not in (int,float)
            or not math.isfinite(host_preflight_wall_seconds) or host_preflight_wall_seconds < 0):
        raise ValueError("finite nonnegative host-only preflight wall seconds required")
    result = prepare_comparison(readiness)
    if result["status"] != "PREPARED":
        return result
    authorization = result["readiness"]
    if expected_authorization is not None and canonical(expected_authorization) != canonical(authorization):
        raise PermissionError("saved authorization differs from live revalidation")
    context = readiness.get_execution_context()
    if digest(context) != result["context_sha256"]:
        raise PermissionError("captured readiness context changed")
    targets = {t["target_id"]:t for t in context["targets"]}
    if not isinstance(evaluators,dict) or set(evaluators) != set(targets):
        raise ValueError("exact reviewed evaluator batch required")
    for key, target in targets.items():
        value = evaluators[key]
        if (set(value) != {"target","oracle","implementation_sha256","oracle_sha256"}
                or not callable(value["target"]) or not callable(value["oracle"])
                or value["target"] is value["oracle"]
                or value["implementation_sha256"] != target["provenance"]["implementation_sha256"]
                or value["oracle_sha256"] != target["provenance"]["oracle_sha256"]):
            raise PermissionError("evaluator identity differs from reviewed Target")
    destination = Path(output).resolve()
    public_root = Path(__file__).resolve().parents[2]
    if destination.is_relative_to(public_root):
        raise ValueError("private comparison outcomes must remain outside the public package checkout")
    if destination.exists():
        raise FileExistsError("preserve existing comparison outputs")
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Recheck live code/protocol/history after every method's plan is frozen.
    live_started = time.perf_counter()
    live = readiness.authorize_final_comparison()
    live_validation_seconds = time.perf_counter()-live_started
    if canonical(live) != canonical(authorization):
        raise PermissionError("readiness changed while all A-D plans were prepared")
    bound = deepcopy(live)
    bound["bindings"]["comparison_plan_sha256"] = result["comparison_plan_sha256"]
    bound["receipt_sha256"] = digest({k:v for k,v in bound.items() if k != "receipt_sha256"})
    ledger = readiness.get_usage_ledger()
    claim = ledger.claim(list(targets.values()),bound,output=destination)
    rows = []
    policy = context["fixed_protocol"]["comparison_policy"]
    budget = context["fixed_protocol"]["budget"]
    failure = None
    try:
        for frozen in result["plans"]:
            target = targets[frozen["target_id"]]
            callbacks = evaluators[frozen["target_id"]]
            started = time.perf_counter()
            raw, rejected, seen = [], 0, set()
            target_calls = oracle_calls = 0
            first = None; confirmed = False; replay_status = "NOT_NEEDED"
            def check_time():
                # Cooperative checks cannot interrupt a blocked host callback.
                # Only separately reviewed bounded pure functions are allowed.
                if time.perf_counter()-started > EXECUTION_WALL_SECONDS:
                    raise TimeoutError("cooperative per-method execution wall budget exhausted")
            def evaluate(point, phase):
                nonlocal target_calls, oracle_calls
                check_time()
                oracle_calls += 1
                expected = callbacks["oracle"](**decode_inputs(deepcopy(point), target["spec"]))
                canonical(expected)
                check_time()
                target_calls += 1
                actual = callbacks["target"](**decode_inputs(deepcopy(point), target["spec"]))
                canonical(actual)
                check_time()
                mismatch = not equivalent(actual,expected,policy)
                row = {"inputs":deepcopy(point),"actual":actual,"expected":expected,
                       "failed":mismatch,"phase":phase}
                raw.append(row)
                return mismatch, digest({"actual":actual,"expected":expected})
            for candidate in frozen["plan"]["candidates"]:
                check_time()
                point = candidate["inputs"]
                if not _public_valid(point,target):
                    rejected += 1; continue
                token = canonical(point)
                if token in seen:
                    continue
                seen.add(token)
                if target_calls >= budget or oracle_calls >= budget:
                    break
                failed, observed = evaluate(point,"frozen-search")
                if not failed:
                    continue
                first = {"wall_seconds":time.perf_counter()-started,"target_calls":target_calls,
                         "oracle_calls":oracle_calls,"candidate_source":candidate["source"],
                         "claim_ids":candidate.get("claim_ids",[])}
                if target_calls+2 <= budget and oracle_calls+2 <= budget:
                    replays = [evaluate(point,"independent-replay") for _ in range(2)]
                    confirmed = all(flag and value == observed for flag,value in replays)
                    replay_status = "MATCHED_TWICE" if confirmed else "NONDETERMINISTIC_QUARANTINED"
                else:
                    replay_status = "UNVERIFIED_RESOURCE_BUDGET"
                break
            rows.append({"target_id":frozen["target_id"],"method":frozen["method"],"seed":frozen["seed"],
                "evaluation_role":target["evaluation_role"],"status":"COMPLETE",
                "found":confirmed and target["evaluation_role"] == "POSITIVE_REPRODUCTION",
                "control_false_alert":first is not None and target["evaluation_role"] == "CLEAN_CONTROL",
                "observed_mismatch":first is not None,"first_failure":first,
                "replay_status":replay_status,"target_calls":target_calls,"oracle_calls":oracle_calls,
                "precondition_rejected":rejected,"evaluation_wall_seconds":time.perf_counter()-started,
                "planning_seconds":frozen["planning_seconds"],"raw":raw})
    except Exception as error:
        failure = {"kind":"EXECUTION_OR_ORACLE_ERROR","type":type(error).__name__,
                   "target_id":frozen["target_id"],"method":frozen["method"],"seed":frozen["seed"],
                   "partial_target_calls":target_calls,"partial_oracle_calls":oracle_calls,"raw":raw}
    required = len(targets)*len(context["fixed_protocol"]["seeds"])*len(METHODS)
    complete = failure is None and len(rows) == required
    invalid_replays = sum(row["replay_status"] in ("NONDETERMINISTIC_QUARANTINED", "UNVERIFIED_RESOURCE_BUDGET") for row in rows)
    controls = sum(row["control_false_alert"] for row in rows)
    status = ("ABORTED_EXECUTION_ERROR" if not complete else
              "INVALID_REPLAY_COMPARISON" if invalid_replays else "COMPLETE")
    summary = {"schema":"tomolab-e8-comparison-result-v1","comparison_status":status,
        "methods":list(METHODS),"full_grid":complete,"final_attempts":1,"generator_feedback":0,
        "required_errors":int(failure is not None)+invalid_replays,"invalid_replay_rows":invalid_replays,"control_false_alerts":controls,
        "readiness_receipt_sha256":authorization["receipt_sha256"],
        "comparison_plan_sha256":result["comparison_plan_sha256"],"claim_id":claim["claim_id"],
        "execution_wall_budget_seconds_per_method":EXECUTION_WALL_SECONDS,
        "execution_timeout_policy":"COOPERATIVE_CHECKS_NOT_HOST_CALLBACK_PREEMPTION",
        "scope":sorted({t["scope"] for t in targets.values()}),
        "classification":"HISTORICAL_DEFECT_REDISCOVERY_OR_AUTHORED_FIXTURE_NOT_NEW_PRODUCTION_DISCOVERY",
        "target_calls":sum(r["target_calls"] for r in rows)+(failure or {}).get("partial_target_calls",0),
        "oracle_calls":sum(r["oracle_calls"] for r in rows)+(failure or {}).get("partial_oracle_calls",0),
        "rows":rows,"error":failure,"frozen_plans":result["plans"],"authorization":bound,
        "preparation_wall_seconds":result["preparation_wall_seconds"],
        "source_replay_retrieval_wall_seconds":result["source_replay_retrieval_wall_seconds"],
        "live_revalidation_wall_seconds":live_validation_seconds,
        "source_costs":context["fixed_protocol"].get("decision_rules",{}).get("source_costs","UNKNOWN_NOT_MEASURED"),
        "decision_rules":context["fixed_protocol"].get("decision_rules"),
        "verdict":"INCONCLUSIVE" if any(t["scope"] == "REVIEWED_REAL_PROJECT" for t in targets.values()) else "FUNCTIONAL_ONLY_NOT_RESEARCH",
        "verdict_scope":"RAW_REGISTERED_RESULTS_REQUIRE_INDEPENDENT_RULE_ANALYSIS; NO_AUTOMATIC_SUPERIORITY_PROMOTION",
        "further_final_execution_forbidden":True}
    summary["method_summary"] = [{"method":method,
        "confirmed_problem_ids":sorted({r["target_id"] for r in rows if r["method"] == method and r["found"]}),
        "confirmed_unique_defect_mechanisms":"NOT_INFERRED_FROM_PROBLEM_OR_SEED_COUNT",
        "actual_target_calls":sum(r["target_calls"] for r in rows if r["method"] == method),
        "actual_oracle_calls":sum(r["oracle_calls"] for r in rows if r["method"] == method),
        "planning_wall_seconds":sum(r["planning_seconds"] for r in rows if r["method"] == method),
        "evaluation_wall_seconds":sum(r["evaluation_wall_seconds"] for r in rows if r["method"] == method),
        "first_discovery_times":[{"target_id":r["target_id"],"seed":r["seed"],
            "wall_seconds":r["planning_seconds"]+r["first_failure"]["wall_seconds"] if r["found"] else None,
            "censoring":"OBSERVED" if r["found"] else "RESOURCE_BUDGET_NOT_OBSERVED"}
            for r in rows if r["method"] == method]} for method in METHODS]
    runner_wall = time.perf_counter()-runner_started
    summary["wall_accounting"] = {
        "host_preflight_wall_seconds":host_preflight_wall_seconds,
        "runner_through_result_assembly_wall_seconds":runner_wall,
        "host_through_result_assembly_wall_seconds":host_preflight_wall_seconds+runner_wall,
        "intervals":"HOST_PREFLIGHT_THEN_RUNNER; INNER_PHASE_TIMES_OVERLAP_AND_ARE_NOT_ADDITIVE",
        "method_discovery_times":"PLANNING_PLUS_ROW_EXECUTION_EXCLUDES_SHARED_HOST_PREFLIGHT_AND_PRIOR_ROWS",
        "excluded":"RESULT_SERIALIZATION_OUTPUT_FSYNC_AND_LEDGER_COMPLETE_COMMIT",
        "shared_cost_amortization":"NOT_ASSUMED_OR_ALLOCATED_TO_METHODS"}
    # Completed error records are still consumed. No retry can re-open START.
    with destination.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(summary,stream,ensure_ascii=False,allow_nan=False,indent=2); stream.write("\n")
    ledger.complete(claim["claim_id"],{"status":summary["comparison_status"],"output_sha256":digest(summary)})
    return summary
