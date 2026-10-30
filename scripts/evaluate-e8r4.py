"""Once-only CORR development comparison of precommitted frozen R3 plans.

All input plans and execution permits precede all target observations. Parent
stopwatches include child startup, lazy library imports, durable result/public
receipt writes, and child exit. The outer receipt's own write is explicitly a
separate interval, not silently added as zero or folded into its own timestamp.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
METHODS = ("A", "B", "C", "D")
IMPLEMENTATIONS = ("python-statistics-correlation", "scipy-stats-pearsonr")


class NumericEntryCounter:
    """Observe actual code entries and preserve a surrounding profiling hook."""
    def __init__(self):
        self.counts=dict(statistics_correlation=0,scipy_pearsonr=0,source_oracle_result=0,source_pearson_result=0)
        self.previous=None

    def profile(self,frame,event,arg):
        if event=="call":
            path=frame.f_code.co_filename.replace("\\","/")
            name=frame.f_code.co_name
            if name=="correlation" and path.endswith("/statistics.py"):
                self.counts["statistics_correlation"]+=1
            elif name=="pearsonr" and path.endswith("/scipy/stats/_stats_py.py"):
                self.counts["scipy_pearsonr"]+=1
            elif name=="oracle_result" and path.endswith("/discovery/numerical_source.py"):
                self.counts["source_oracle_result"]+=1
            elif name=="pearson_result" and path.endswith("/discovery/numerical_source.py"):
                self.counts["source_pearson_result"]+=1
        if self.previous is not None:
            self.previous(frame,event,arg)

    def __enter__(self):
        self.previous=sys.getprofile()
        sys.setprofile(self.profile)
        return self

    def __exit__(self,*ignored):
        sys.setprofile(self.previous)


def observed_numeric_entries(function):
    @wraps(function)
    def wrapped(args):
        with NumericEntryCounter() as counter:
            return function(args,counter)
    return wrapped


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):
    path=Path(path)
    with path.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(value,stream,ensure_ascii=True,allow_nan=False,indent=2)
        stream.write("\n");stream.flush();os.fsync(stream.fileno())


def schedule(declaration):
    rows=[]
    for index,seed in enumerate(declaration["seeds"]):
        implementations=list(IMPLEMENTATIONS if index%2==0 else reversed(IMPLEMENTATIONS))
        for position,implementation in enumerate(implementations):
            offset=(index+position)%4
            for method in METHODS[offset:]+METHODS[:offset]:
                rows.append(dict(implementation_id=implementation,method=method,seed=seed))
    return rows


def validate_declaration(value):
    if (value["schema"] != "tomolab-e8r4-corroboration-contract-v1"
            or value["scope"] != "INDEPENDENT_DEVELOPMENT_ONLY"
            or value["implementations"] != list(IMPLEMENTATIONS)
            or value["methods"] != list(METHODS)
            or value["seeds"] != [1103,1229,1367,1489,1613,1741]
            or value["run_count"] != 48
            or value["resource_budget"] != {"pair_budget":96,"shrink_budget":16}
            or value["generation"]["size"] != 32 or value["generation"]["max_examples"] != 512
            or value["generation"]["verification_profile"] != "runtime"
            or value["final_evaluation_authorized"] is not False
            or value["publication_authorized"] is not False):
        raise ValueError("registered fixed CORR declaration differs")
    return value


def verify_product(repo,manifest_path):
    manifest=read(manifest_path)
    product=manifest["product"]
    required={p.relative_to(repo).as_posix() for folder in ("tomolab","scripts","tests")
              for p in (repo/folder).rglob("*.py")}
    required.add("docs/E8_R4_EVALUATION_CONTRACT.json")
    if not required <= set(product) or manifest.get("allow_release") is not False:
        raise ValueError("CORR product freeze is incomplete or allows publication")
    for name,expected in product.items():
        path=(repo/name).resolve()
        if not path.is_relative_to(repo.resolve()) or sha(path)!=expected:
            raise ValueError("frozen CORR product differs: "+name)
    return manifest


def _imports(repo):
    sys.path.insert(0,str(repo.resolve()))
    from tomolab.discovery.corroboration_adapters import implementation_identity
    from tomolab.discovery.corroboration_permit import build_permit_context,CorroborationExecutionPermit
    from tomolab.discovery.corroboration_service import plan_candidates,run_corroboration_plan
    from tomolab.discovery.evaluation_usage import UsageLedger
    from tomolab.discovery.numerical_prepared import load_prepared_guide,read_approval_state
    return implementation_identity,build_permit_context,CorroborationExecutionPermit,plan_candidates,run_corroboration_plan,UsageLedger,load_prepared_guide,read_approval_state


@observed_numeric_entries
def freeze_child(args,counter):
    started=time.perf_counter()
    repo=args.repo.resolve(strict=True)
    if args.directory.resolve().is_relative_to(repo):
        raise ValueError("raw plans and evaluation data must remain outside the public repository")
    declaration=validate_declaration(read(args.declaration))
    verify_product(repo,args.code_freeze)
    review=read(args.review)
    if review.get("target_outcome_known") is not False or any(review["actual_calls"].values()):
        raise ValueError("pre-results contract review required")
    if review["review_digest"] != digest({k:v for k,v in review.items() if k!="review_digest"}):
        raise ValueError("contract review receipt differs")
    known=read(args.known_digests)
    known=known["known_input_digests"] if isinstance(known,dict) else known
    if len(known)!=803 or len(set(known))!=803:
        raise ValueError("unchanged common R3 803-input exclusion registry required")
    replays=read(args.replays)
    args.directory.mkdir(parents=True,exist_ok=True)
    save(args.directory/"PLANNING_START.json",dict(declaration_sha256=sha(args.declaration),
        started_utc=datetime.now(timezone.utc).isoformat(),target_calls=0,oracle_calls=0))
    identity,build,Permit,plan_candidates,_,_,load_guide,read_state=_imports(repo)
    identities={name:identity(name) for name in IMPLEMENTATIONS}
    from importlib.metadata import version
    import numpy
    if (identities[IMPLEMENTATIONS[0]]["version"]!="3.12.10"
            or identities[IMPLEMENTATIONS[1]]["version"]!="1.18.1"
            or numpy.__version__!="2.5.3" or version("hypothesis")!="6.170.11"):
        raise ValueError("reviewed exact implementation version differs")
    authority=args.authority_id
    plans=[]
    for index,item in enumerate(schedule(declaration)):
        tick=time.perf_counter()
        loaded=(load_guide(args.prepared_directory,expected_digest=declaration["frozen_guide_digest"],
            expected_current_context=read_state(args.approval_state)) if item["method"]=="D" else None)
        plan=plan_candidates(method=item["method"],seed=item["seed"],contract=declaration["candidate_contract"],
            compiled=loaded["compiled"] if loaded else None,
            expected_digest=declaration["frozen_guide_digest"] if loaded else None,
            replay_inputs=replays if item["method"]=="C" else (),excluded_digests=known,
            size=32,max_examples=512)
        elapsed=time.perf_counter()-tick
        context=build(plan,identities[item["implementation_id"]],common_input_contract=declaration["common_evaluation_contract"],
            resource_budget=declaration["resource_budget"],authority_id=authority,
            guide_digest=declaration["frozen_guide_digest"],review_digest=review["review_digest"])
        Permit.from_host_approval(context,deepcopy(context))
        if plan["metrics"]["target_calls"]!=0 or plan["metrics"]["oracle_calls"]!=0:
            raise AssertionError("candidate generation called an evaluator")
        plans.append(dict(index=index,**item,plan=plan,approval_context=context,
                          planning_outer_seconds=elapsed))
    if any(counter.counts.values()):
        save(args.directory/"UNEXPECTED_PREPLANNING_EVALUATION.json",counter.counts)
        raise RuntimeError("actual numerical implementation or Oracle ran during plan freezing")
    frozen=dict(schema="tomolab-e8r4-frozen-corroboration-batch-v1",declaration=declaration,
        declaration_sha256=sha(args.declaration),product_manifest_sha256=sha(args.code_freeze),
        review_file_sha256=sha(args.review),review_digest=review["review_digest"],
        source_replays_file_sha256=sha(args.replays),known_registry_file_sha256=sha(args.known_digests),
        prepared_files_sha256={name:sha(args.prepared_directory/name) for name in ("guide.json","approval.json","manifest.json")},
        approval_state_sha256=sha(args.approval_state),authority_id=authority,
        usage_authority=str(args.usage_authority.resolve()),implementation_identities=identities,
        source_guide_preparation_costs=read(args.preparation_costs),plans=plans,
        before_frozen_receipt_seconds=time.perf_counter()-started,
        target_calls=0,oracle_calls=0,actual_function_entries=deepcopy(counter.counts),
        method_results_observed=False,allow_release=False)
    frozen["receipt_sha256"]=digest(frozen)
    save(args.directory/"FROZEN.json",frozen)
    verify_product(repo,args.code_freeze)
    print(json.dumps(dict(status="FROZEN_NO_TARGET_CALLS",plans=len(plans),frozen_file_sha256=sha(args.directory/"FROZEN.json"))))


def _finite_nonnegative(value):
    if type(value) not in (int,float) or not math.isfinite(value) or value<0:
        raise ValueError("actual finite nonnegative duration required")
    return value


def compare_detection(left,right):
    left,right=set(left),set(right)
    if not left and not right:
        return "NOT_IDENTIFIABLE_NO_CONFIRMED_FAILURE"
    if left>right:
        return "ADDITIONAL_DETECTION_BREADTH_OBSERVED"
    if left<right:
        return "DETECTION_LOSS_OBSERVED"
    if left==right:
        return "NO_ADDITIONAL_DETECTION_BREADTH_OBSERVED"
    return "MIXED_DETECTION_BREADTH_NO_OVERALL_SUPERIORITY"


def summarize_runs(runs,measurements,plans,declaration,*,shared_execution_seconds=0.0,shared_planning_seconds=0.0,preparation_costs=None):
    """No misses become successful latency samples; no input becomes a mechanism."""
    summaries={};coverage={m:set() for m in METHODS}
    measurement_map={m["index"]:m for m in measurements}
    plan_map={p["index"]:p for p in plans}
    setup=preparation_costs or {}
    guide_setup=setup.get("shared_guide_preparation_seconds")
    if guide_setup is not None:
        _finite_nonnegative(guide_setup)
    share=_finite_nonnegative(shared_execution_seconds)+_finite_nonnegative(shared_planning_seconds)
    for implementation in IMPLEMENTATIONS:
        summaries[implementation]={}
        for method in METHODS:
            selected=[row for row in runs if row["implementation_id"]==implementation and row["method"]==method]
            first=[];confirmed=set();categories=set();prepared=share/8
            for wrapped in selected:
                run=wrapped["run"];measurement=measurement_map[wrapped["index"]];planned=plan_map[wrapped["index"]]
                if (type(run["primary_generation_executions"]) is not int or run["primary_generation_executions"]!=1
                        or type(run["reference_generation_executions"]) is not int or run["reference_generation_executions"]!=0
                        or any(type(run[name]) is not int or not 0<=run[name]<=declaration["resource_budget"]["pair_budget"] for name in ("target_calls","oracle_calls"))):
                    raise ValueError("run exceeds fixed budget or single-generation runtime contract")
                prepared+=_finite_nonnegative(planned["planning_outer_seconds"])+_finite_nonnegative(measurement["execution_through_receipt_flush_seconds"])
                if run["confirmed_contract_violation_inputs"]:
                    coverage[method].add(implementation)
                for row in run["rows"]:
                    if row.get("confirmed_failure"):
                        confirmed.add(row["input_digest"])
                        categories.add(row["comparison"]["violation_category"])
                event=run["first_confirmed_failure"]
                first.append(None if event is None else dict(event,
                    execution_run_outer_seconds=event["seconds_since_execution_api_entry"]+measurement["api_entry_offset_seconds"],
                    prepaid_plan_plus_run_event_seconds=planned["planning_outer_seconds"]+event["seconds_since_execution_api_entry"]+measurement["api_entry_offset_seconds"]))
            d_uses=12
            # The single guide is actually reused by two implementations and
            # six D plans each. A/B/C are not charged D's evidence preparation.
            cold=None if method=="D" and guide_setup is None else prepared+(guide_setup/2 if method=="D" else 0.0)
            summaries[implementation][method]=dict(trials=len(selected),
                completed_trials=sum(row["run"]["status"]=="COMPLETE" for row in selected),
                fixed_budget_discoveries=sum(row["run"]["confirmed_contract_violation_inputs"]>0 for row in selected),
                distinct_confirmed_violation_inputs=len(confirmed),confirmed_contract_categories=sorted(categories),
                mechanism_count="REQUIRES_SEPARATE_MECHANISTIC_REVIEW_NOT_INPUT_OR_CATEGORY_COUNT",
                target_calls=sum(row["run"]["target_calls"] for row in selected),
                oracle_calls=sum(row["run"]["oracle_calls"] for row in selected),
                oracle_errors=sum(row["run"]["oracle_errors"] for row in selected),
                not_comparable=sum(row["run"]["not_comparable"] for row in selected),
                replay_mismatches=sum(row["run"]["replay_mismatches"] for row in selected),
                documented_undefined_observations=sum(row["normalized"]["computability"]=="UNDEFINED_AS_DOCUMENTED" for wrapped in selected for row in wrapped["run"]["rows"]),
                first_confirmed_failure=first,prepared_seconds=prepared,cold_measured_subtotal_seconds=cold,
                D_guide_total_actual_reuse_count=d_uses if method=="D" else 0,
                guide_preparation_share_seconds=guide_setup/2 if method=="D" and guide_setup is not None else None,
                guide_preparation_cost_origin="RECORDED_R3_MEASUREMENT_REUSED_NOT_RECOMPILED_IN_R4",
                historical_source_acquisition="UNKNOWN_NOT_ZERO")
    complete=len(runs)==declaration["run_count"] and all(row["run"]["status"]=="COMPLETE" for row in runs)
    any_failure=any(coverage.values())
    outcome=("INCONCLUSIVE_PARTIAL_EXECUTION" if not complete else
             "CONFIRMED_CONTRACT_VIOLATIONS_WITHIN_BUDGET" if any_failure else "NO_CONFIRMED_FAILURE_WITHIN_BUDGET")
    paired={}
    for implementation in IMPLEMENTATIONS:
        paired[implementation]={}
        for comparator in ("B","C"):
            d={row["seed"]:row["run"]["first_confirmed_failure"] for row in runs if row["implementation_id"]==implementation and row["method"]=="D"}
            b={row["seed"]:row["run"]["first_confirmed_failure"] for row in runs if row["implementation_id"]==implementation and row["method"]==comparator}
            matched=sorted(set(d)&set(b))
            both=[seed for seed in matched if d[seed] is not None and b[seed] is not None]
            left,right=summaries[implementation]["D"],summaries[implementation][comparator]
            paired[implementation][comparator]=dict(matched_seed_count=len(matched),
                D_only_discoveries=sum(d[seed] is not None and b[seed] is None for seed in matched),
                baseline_only_discoveries=sum(b[seed] is not None and d[seed] is None for seed in matched),
                both_detected_seed_count=len(both),
                D_faster_execution_first_confirmed_count=sum(d[seed]["seconds_since_execution_api_entry"]<b[seed]["seconds_since_execution_api_entry"] for seed in both),
                baseline_faster_execution_first_confirmed_count=sum(b[seed]["seconds_since_execution_api_entry"]<d[seed]["seconds_since_execution_api_entry"] for seed in both),
                no_miss_imputation=True,
                prepared_cost_delta_D_minus_baseline_seconds=left["prepared_seconds"]-right["prepared_seconds"],
                cold_cost_delta_D_minus_baseline_seconds=None if left["cold_measured_subtotal_seconds"] is None or right["cold_measured_subtotal_seconds"] is None else left["cold_measured_subtotal_seconds"]-right["cold_measured_subtotal_seconds"],
                extra_confirmed_input_yield=left["distinct_confirmed_violation_inputs"]-right["distinct_confirmed_violation_inputs"],
                faster_execution_is_not_continuous_end_to_end_latency=True)
    return dict(schema="tomolab-e8r4-corroboration-result-v1",status="COMPLETE" if complete else "PARTIAL",
        outcome=outcome,summaries=summaries,implementation_detection_coverage={m:sorted(coverage[m]) for m in METHODS},
        added_value_over_B=compare_detection(coverage["D"],coverage["B"]) if complete else "INCONCLUSIVE_PARTIAL_EXECUTION",
        added_value_over_C=compare_detection(coverage["D"],coverage["C"]) if complete else "INCONCLUSIVE_PARTIAL_EXECUTION",
        secondary_paired_comparisons=paired,
        input_counts_are_not_mechanism_counts=True,all_methods_no_failure=not any_failure if complete else None,
        no_first_failure_time_assigned_to_misses=True,complete_adaptive_PBT_superiority_claimed=False,
        statistical_superiority_claimed=False,independent_oracle_lineages="ONE_SHARED_REVIEWED_MATH_ORACLE",
        qualified_knowledge_status="NOT_PROMOTED",final_target_readiness="NOT_AUTHORIZED_CORR_CONSUMED",
        publication_authorized=False,allow_release=False)


@observed_numeric_entries
def execute_child(args,counter):
    started=time.perf_counter()
    repo=args.repo.resolve(strict=True)
    frozen_path=args.directory/"FROZEN.json"
    if sha(frozen_path)!=args.expected_frozen_digest:
        raise PermissionError("frozen CORR batch differs from the external approved pin")
    frozen=read(frozen_path)
    if frozen["receipt_sha256"]!=digest({k:v for k,v in frozen.items() if k!="receipt_sha256"}):
        raise ValueError("frozen CORR receipt differs")
    if sha(args.code_freeze)!=frozen["product_manifest_sha256"]:
        raise ValueError("CORR product manifest identity changed")
    verify_product(repo,args.code_freeze)
    identity,_,Permit,_,run_plan,UsageLedger,_,_=_imports(repo)
    for name,expected in frozen["implementation_identities"].items():
        if canonical(identity(name))!=canonical(expected):
            raise PermissionError("installed reviewed implementation identity changed")
    if (args.directory/"START.json").exists():
        raise FileExistsError("CORR batch consumed; no retry or seed substitution")
    contexts=[row["approval_context"] for row in frozen["plans"]]
    permits=[Permit.from_host_approval(context,deepcopy(context)) for context in contexts]
    usage=UsageLedger(frozen["usage_authority"],authority_id=frozen["authority_id"])
    claim=usage.claim_corroboration(permits,contexts,output=args.directory/"USAGE_CLAIM.json")
    save(args.directory/"START.json",dict(frozen_file_sha256=args.expected_frozen_digest,
        claim_id=claim["claim_id"],started_utc=datetime.now(timezone.utc).isoformat(),retry="FORBIDDEN"))
    runs=[];measurements=[];global_first=None
    for row,permit in zip(frozen["plans"],permits):
        tick=time.perf_counter();api_tick=time.perf_counter()
        api_global_offset=api_tick-started
        prior_target_calls=sum(item["run"]["target_calls"] for item in runs)
        prior_oracle_calls=sum(item["run"]["oracle_calls"] for item in runs)
        run=run_plan(row["plan"],permit,expected_approval_context=row["approval_context"],
            usage_ledger=usage,claim_id=claim["claim_id"])
        if global_first is None and run["first_confirmed_failure"] is not None:
            event=run["first_confirmed_failure"]
            global_first=dict(index=row["index"],implementation_id=row["implementation_id"],method=row["method"],seed=row["seed"],
                seconds_since_execution_child_function_entry=api_global_offset+event["seconds_since_execution_api_entry"],
                cumulative_target_calls=prior_target_calls+event["target_calls"],
                cumulative_oracle_calls=prior_oracle_calls+event["oracle_calls"],
                phase=event["phase"],violation_category=event["violation_category"],
                excludes_previously_completed_planning_and_child_process_startup=True)
        filename=args.directory/("run-%02d.json"%row["index"])
        io_tick=time.perf_counter();save(filename,run);io_seconds=time.perf_counter()-io_tick
        measured=dict(index=row["index"],api_entry_offset_seconds=api_tick-tick,
            receipt_write_flush_seconds=io_seconds,execution_through_receipt_flush_seconds=time.perf_counter()-tick,
            run_receipt_sha256=sha(filename))
        measurements.append(measured)
        runs.append(dict(index=row["index"],implementation_id=row["implementation_id"],method=row["method"],seed=row["seed"],run=run))
        if run["status"]!="COMPLETE":
            break
    planning=sum(p["planning_outer_seconds"] for p in frozen["plans"])
    freeze_outer=read(args.directory/"FREEZE_OUTER.json")["child_process_wall_seconds"]
    if global_first is not None:
        global_first["prepaid_all_48_plans_plus_execution_event_seconds"]=(
            freeze_outer+global_first["seconds_since_execution_child_function_entry"])
        global_first["prepaid_sum_is_not_continuous_wall_clock"]=True
    shared_planning=max(0.0,freeze_outer-planning)
    evaluation=sum(m["execution_through_receipt_flush_seconds"] for m in measurements)
    shared_execution=max(0.0,time.perf_counter()-started-evaluation)
    result=summarize_runs(runs,measurements,frozen["plans"],frozen["declaration"],
        shared_execution_seconds=shared_execution,shared_planning_seconds=shared_planning,
        preparation_costs=frozen["source_guide_preparation_costs"])
    expected=dict(statistics_correlation=sum(item["run"]["target_calls"] for item in runs if item["implementation_id"]==IMPLEMENTATIONS[0]),
        scipy_pearsonr=sum(item["run"]["target_calls"] for item in runs if item["implementation_id"]==IMPLEMENTATIONS[1]),
        source_oracle_result=sum(item["run"]["oracle_calls"] for item in runs),source_pearson_result=0)
    if counter.counts!=expected:
        save(args.directory/"NUMERICAL_ENTRY_ACCOUNTING_ERROR.json",dict(actual=counter.counts,recorded=expected))
        raise RuntimeError("actual numerical function entries differ from the per-run ledger")
    usage.complete(claim["claim_id"],dict(status=result["status"],outcome=result["outcome"],completed_runs=len(runs),
        target_calls=sum(row["run"]["target_calls"] for row in runs),oracle_calls=sum(row["run"]["oracle_calls"] for row in runs),
        final_evaluation_authorized=False,publication_authorized=False))
    result.update(runs=runs,run_measurements=measurements,frozen_file_sha256=args.expected_frozen_digest,
        usage_receipt_sha256=usage.inspect()["receipt_sha256"],shared_planning_seconds=shared_planning,
        shared_execution_seconds=shared_execution,actual_function_entries=deepcopy(counter.counts),
        actual_entry_counts_match_run_records=True,global_first_confirmed_failure=global_first,
        result_and_public_write="INCLUDED_IN_PARENT_OUTER_RECEIPT_NOT_YET_PER_METHOD_ALLOCATED")
    result["receipt_sha256"]=digest(result)
    save(args.directory/"RESULT.json",result)
    public={k:deepcopy(v) for k,v in result.items() if k not in ("runs","run_measurements","receipt_sha256")}
    public["private_result_file_sha256"]=sha(args.directory/"RESULT.json")
    public["public_receipt_sha256"]=digest(public)
    save(args.output,public)
    verify_product(repo,args.code_freeze)
    print(json.dumps(dict(status=result["status"],outcome=result["outcome"],runs=len(runs))))
    return 0 if result["status"]=="COMPLETE" else 3


def outer(args,argv):
    args.directory.mkdir(parents=True,exist_ok=True)
    stage=args.command.upper()
    save(args.directory/(stage+"_PARENT_START.json"),dict(stage=stage,started_utc=datetime.now(timezone.utc).isoformat()))
    child_argv=list(argv);child_argv[0]+="-child"
    tick=time.perf_counter()
    completed=subprocess.run([sys.executable,"-I","-X","utf8",str(Path(__file__).resolve()),*child_argv],
        cwd=args.directory,capture_output=True,text=True,encoding="utf-8",timeout=1800)
    elapsed=time.perf_counter()-tick
    accounted=None
    if args.command=="execute" and (args.directory/"RESULT.json").exists() and args.output.exists():
        private=read(args.directory/"RESULT.json")
        original=read(args.output)
        per_run=sum(row["execution_through_receipt_flush_seconds"] for row in private["run_measurements"])
        residual=max(0.0,elapsed-per_run-private["shared_execution_seconds"])
        accounted=deepcopy(original)
        accounted.pop("public_receipt_sha256")
        accounted["original_public_file_sha256"]=sha(args.output)
        accounted["execution_child_outer_wall_seconds"]=elapsed
        accounted["final_result_io_startup_shutdown_residual_seconds"]=residual
        accounted["residual_allocation"]="ONE_EIGHTH_TO_EACH_IMPLEMENTATION_METHOD_GROUP"
        for methods in accounted["summaries"].values():
            for summary in methods.values():
                summary["prepared_seconds"]+=residual/8
                if summary["cold_measured_subtotal_seconds"] is not None:
                    summary["cold_measured_subtotal_seconds"]+=residual/8
        accounted["accounting_report_write"]="SEPARATE_PARENT_RECEIPT_COST_NOT_INCLUDED_IN_CHILD_PROCESS_WALL"
        accounted["public_receipt_sha256"]=digest(accounted)
        accounted_path=args.output.with_name(args.output.stem+"-accounted.json")
        save(accounted_path,accounted)
    files={}
    for path in ((args.directory/"FROZEN.json",) if args.command=="freeze" else (args.directory/"RESULT.json",args.output)):
        if path.exists():
            files[path.name]=dict(bytes=path.stat().st_size,sha256=sha(path))
    if accounted is not None:
        files[accounted_path.name]=dict(bytes=accounted_path.stat().st_size,sha256=sha(accounted_path))
    report=dict(schema="tomolab-e8r4-outer-cost-v1",stage=stage,child_process_wall_seconds=elapsed,
        child_returncode=completed.returncode,includes_child_startup_imports_result_public_fsync_shutdown=True,
        outer_receipt_self_write="EXCLUDED_FROM_CHILD_BOUNDARY_SEPARATELY_REPORTED_TO_CALLER",
        files=files,stdout=completed.stdout,stderr=completed.stderr)
    write_tick=time.perf_counter();save(args.directory/(stage+"_OUTER.json"),report)
    write_seconds=time.perf_counter()-write_tick
    print(json.dumps(dict(stage=stage,returncode=completed.returncode,child_process_wall_seconds=elapsed,
        outer_receipt_write_flush_seconds=write_seconds,files=files,
        stdout=completed.stdout,stderr=completed.stderr),ensure_ascii=True))
    return completed.returncode


def parser():
    value=argparse.ArgumentParser(description=__doc__)
    commands=value.add_subparsers(dest="command",required=True)
    for name in ("freeze","freeze-child","execute","execute-child"):
        command=commands.add_parser(name,help="CORR 계획 동결" if name.startswith("freeze") else "동결한 CORR 배치 1회 실행")
        command.add_argument("--repo",type=Path,default=ROOT)
        command.add_argument("--directory",type=Path,required=True)
        command.add_argument("--code-freeze",type=Path,required=True)
        if name.startswith("freeze"):
            command.add_argument("--declaration",type=Path,default=ROOT/"docs/E8_R4_EVALUATION_CONTRACT.json")
            for option in ("review","known-digests","replays","prepared-directory","approval-state","preparation-costs","usage-authority"):
                command.add_argument("--"+option,type=Path,required=True)
            command.add_argument("--authority-id",required=True)
        else:
            command.add_argument("--expected-frozen-digest",required=True)
            command.add_argument("--output",type=Path,required=True)
    return value


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    args=parser().parse_args(argv)
    # Resolve paths before a fresh child changes cwd to its private directory.
    for name,item in vars(args).items():
        if isinstance(item,Path):
            setattr(args,name,item.resolve())
    if args.command in ("freeze","execute"):
        # Rebuild arguments with resolved absolute paths and explicit defaults.
        child=[args.command]
        for name,item in vars(args).items():
            if name!="command":
                child.extend(["--"+name.replace("_","-"),str(item)])
        return outer(args,child)
    return freeze_child(args) if args.command=="freeze-child" else execute_child(args)


if __name__=="__main__":
    raise SystemExit(main())
