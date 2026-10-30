"""Bounded R3 engineering measurements and once-only Source development batch.

Public profiling executes real clean Generator processes and the real host
service with authored callbacks, never the fixed Source or its Oracle. Source
execution is a separate once-only operation requiring a passing public receipt,
a complete frozen product manifest, and a fixed common known-input registry.
Raw Source rows are retained only outside the repository.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_FILES = ("__init__.py", "schema.py", "numerical_guidance.py", "compact_guidance.py", "numerical_worker.py")
PROFILES = ("r2", "runtime", "audit")
METHODS = ("A", "B", "C", "D")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    """Exclusive, durable file creation; no consumed receipt is overwritten."""
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=True, allow_nan=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def generator_hashes(repo):
    return {name: sha(Path(repo)/"tomolab/discovery"/name) for name in GENERATOR_FILES}


def rotation(items, index):
    return list(items[index % len(items):] + items[:index % len(items)])


def _non_timing_generation(generation):
    return {k: v for k, v in generation.items() if k not in
            ("wall_seconds", "cpu_seconds", "generation_boundary", "generation_execution")}


def semantic_projection(result, plans):
    """Keep all ordered candidate semantics and legacy evaluation behavior.

    R3-only timing and verification metadata may differ. Nothing is reduced to
    a set: candidate/evaluation order and source metadata remain meaningful.
    """
    fields = ("method", "seed", "status", "source_identity", "comparison_contract", "guide_digest",
        "contract", "pair_budget", "target_calls", "oracle_calls", "first_evaluated_valid_inputs",
        "confirmed_new_failure_inputs", "known_input_replay_calls", "initial_known_replays",
        "domain_rejections", "oracle_errors", "target_errors", "replay_mismatches", "mechanisms",
        "unreviewed_failure_inputs", "first_new_failure_target_calls", "first_new_failure_oracle_calls",
        "candidate_count", "candidate_input_digest", "rows", "shrinking", "phase_counts",
        "confirmed_mechanism_count", "distinct_new_mechanisms", "oracle_target_primitive_calls",
        "guide_unchanged", "allow_release", "final_feedback_allowed", "stop")
    projection = {name: deepcopy(result[name]) for name in fields if name in result}
    projection["generation"] = _non_timing_generation(result["generation"])
    projection["ordered_candidates"] = plans[0]["generation"]["candidates"]
    projection["execution_contract_digest"] = plans[0]["execution_contract_digest"]
    return projection


def summarize_variation(values):
    median = statistics.median(values)
    return {"median": median, "minimum": min(values), "maximum": max(values),
            "median_absolute_deviation": statistics.median(abs(v-median) for v in values)}


def assess_public(runs, declaration):
    expected = declaration["required_generation_counts"]
    by_profile = {p: [r for r in runs if r["profile"] == p] for p in PROFILES}
    seeds = declaration["seeds"]
    semantics = all(len({r["semantic_digest"] for r in runs if r["seed"] == seed}) == 1 for seed in seeds)
    counts = all(r["actual_generation_processes"] == expected[r["profile"]]
        and r["actual_plan_requests"] == expected[r["profile"]] for r in runs)
    complete = len(runs) == len(seeds)*len(PROFILES) and all(r["status"] == "COMPLETE" for r in runs)
    validation = all(r["fixed_source_calls"] == r["fixed_oracle_calls"] == 0 and
        all(v == 0 for v in r["archive_processing_calls"].values()) for r in runs)
    strict = all(r["response_validation_status"] == "PASS" and
        r["equivalence_check_status"] in (("PASS", "PASS_FULL_STRUCTURED_SEMANTICS") if r["profile"] == "audit" else ("NOT_RUN_IN_RUNTIME",))
        for r in runs if r["profile"] != "r2")
    stats = {p: summarize_variation([r["outer_process_wall_seconds"] for r in by_profile[p]]) for p in PROFILES}
    criterion = declaration["cost_criterion"]
    comparisons = {}
    for comparator in criterion["comparators"]:
        reductions = []
        for seed in seeds:
            left = next(r for r in by_profile["runtime"] if r["seed"] == seed)["outer_process_wall_seconds"]
            right = next(r for r in by_profile[comparator] if r["seed"] == seed)["outer_process_wall_seconds"]
            reductions.append((right-left)/right)
        median_reduction = 1-stats["runtime"]["median"]/stats[comparator]["median"]
        comparisons[comparator] = {"paired_reduction_fractions": reductions,
            "ratio_of_medians_reduction_fraction": median_reduction,
            "paired_wins": sum(v > 0 for v in reductions),
            "criterion_pass": median_reduction >= criterion["minimum_median_reduction_fraction_vs_each_comparator"] and
                sum(v > 0 for v in reductions) >= criterion["minimum_paired_wins_of_four_vs_each_comparator"]}
    engineering_pass = complete and semantics and counts and validation and strict
    return {"status": "PASS" if engineering_pass else "FAIL",
        "generation_semantics_preserved": semantics, "actual_generation_counts_correct": counts,
        "source_and_oracle_not_executed": validation, "strict_response_and_audit_checks_passed": strict,
        "variation_seconds": stats, "runtime_comparisons": comparisons,
        "prepared_efficiency": "IMPROVED" if engineering_pass and all(v["criterion_pass"] for v in comparisons.values())
            else "NO_IMPROVEMENT" if engineering_pass else "INCONCLUSIVE",
        "cold_efficiency": "INCONCLUSIVE", "cold_reason": "SEPARATE_COLD_PREPARATION_NOT_IN_PUBLIC_RUN",
        "statistical_superiority_claimed": False, "research_performance_inferred": False}


def public_child(args):
    """One real service invocation; imports and receipt IO timed by parent."""
    started = time.perf_counter()
    repo = args.repo.resolve(strict=True)
    sys.path.insert(0, str(repo))
    from tomolab.discovery import numerical_service as service
    from tomolab.discovery import numerical_source as source
    from tomolab.discovery import compact_guidance as compact
    from tomolab.discovery import numerical_guidance as guidance
    from tomolab.discovery.knowledge import KnowledgeArchive
    from tomolab.discovery.numerical_boundary import NumericalBoundary
    if not Path(service.__file__).resolve().is_relative_to(repo):
        raise ValueError("selected repository import identity differs")
    declaration = read(args.declaration)
    artifact = read(repo/"examples/numerical/source-guide.json")
    compiled = {"artifact": artifact, "approval_receipt": read(repo/"examples/numerical/source-approval.json")}
    if artifact["artifact_digest"] != declaration["guide_digest"]:
        raise ValueError("public guide identity differs from preregistration")
    calls = {"target": 0, "oracle": 0}
    def target(point):
        calls["target"] += 1
        return {"authored_value": int(len(set(point["b"])) == 1)}
    def oracle(point):
        calls["oracle"] += 1
        return {"authored_value": 0}
    source.target_result = target
    source.oracle_result = oracle
    source.compare_results = lambda actual, expected: actual == expected
    source.classify_mechanism = lambda *_: "AUTHORED_CALLBACK_MISMATCH"
    archive_calls = {"full_archive_replay": 0, "recipe_preparation": 0, "recipe_calibration": 0, "compilation": 0}
    def wrap_archive(name, owner, attribute):
        original = getattr(owner, attribute)
        def tracked(*positional, **keywords):
            archive_calls[name] += 1
            return original(*positional, **keywords)
        setattr(owner, attribute, tracked)
    wrap_archive("full_archive_replay", KnowledgeArchive, "from_snapshot")
    wrap_archive("recipe_preparation", compact, "prepare_recipe_from_archive")
    wrap_archive("recipe_calibration", guidance, "calibrate_recipe")
    wrap_archive("compilation", compact, "compile_execution_artifact")
    processes, actions, plans = [], [], []
    original_init = NumericalBoundary.__init__
    original_request = NumericalBoundary.request
    def init(boundary, *positional, **keywords):
        original_init(boundary, *positional, **keywords)
        if boundary.process is None or boundary.process.pid is None:
            raise AssertionError("real Generator process was not started")
        processes.append({"pid": boundary.process.pid, "module_hashes": boundary.code_hashes})
    def request(boundary, action, **fields):
        value = original_request(boundary, action, **fields)
        actions.append(action)
        if action == "plan":
            plans.append(deepcopy(value))
        return value
    NumericalBoundary.__init__, NumericalBoundary.request = init, request
    parameters = dict(declaration["parameters"], seed=args.seed, contract=declaration["contract"],
        excluded_digests=declaration["excluded_digests"], expected_digest=declaration["guide_digest"])
    if args.profile != "r2":
        parameters["verification_profile"] = args.profile
    result = service.run_numerical_method(compiled, **parameters)
    if not plans or any(p["generation"]["candidates"] != plans[0]["generation"]["candidates"] for p in plans):
        raise AssertionError("actual ordered candidate semantics differ")
    r3 = result.get("r3", {})
    payload = {"schema": "tomolab-e8r3-public-profile-child-v1", "profile": args.profile,
        "seed": args.seed, "status": result["status"], "runtime": service.runtime_identity(),
        "semantic_digest": digest(semantic_projection(result, plans)),
        "ordered_candidates_digest": digest(plans[0]["generation"]["candidates"]),
        "actual_generation_processes": len(processes), "actual_plan_requests": actions.count("plan"),
        "actual_process_ids": [p["pid"] for p in processes], "observed_worker_actions": actions,
        "generator_module_hashes": processes[0]["module_hashes"],
        "all_worker_module_hashes_identical": all(p["module_hashes"] == processes[0]["module_hashes"] for p in processes),
        "authored_target_calls": calls["target"], "authored_oracle_calls": calls["oracle"],
        "fixed_source_calls": 0, "fixed_oracle_calls": 0, "archive_processing_calls": archive_calls,
        "candidate_count": result["candidate_count"],
        "confirmed_authored_failure_inputs": result["confirmed_new_failure_inputs"],
        "response_validation_status": result.get("response_validation_status", r3.get("response_validation_status", "R2_COMPATIBILITY")),
        "equivalence_check_status": result.get("equivalence_check_status", r3.get("equivalence_check_status", "R2_DIGEST_COMPARISON")),
        "r3_timing": r3.get("timing"), "legacy_cost": result["cost"],
        "child_entry_to_completed_service_seconds": time.perf_counter()-started,
        "receipt_io_in_internal_service_timer": False,
        "receipt_io_in_parent_outer_process_timer": True,
        "actual_fixed_source_evaluation": "NONE_AUTHORED_CALLBACKS_ONLY", "allow_release": False}
    tick = time.perf_counter()
    save(args.output, payload)
    completion = {"receipt_sha256": sha(args.output), "receipt_io_seconds": time.perf_counter()-tick,
        "child_entry_to_receipt_flush_seconds": time.perf_counter()-started}
    print(json.dumps(completion, sort_keys=True))


def public_profile(args):
    declaration = read(args.declaration)
    if declaration["schema"] != "tomolab-e8r3-public-profile-contract-v1":
        raise ValueError("unsupported public preregistration")
    baseline, current = args.baseline.resolve(strict=True), args.repo.resolve(strict=True)
    hashes = generator_hashes(baseline)
    if generator_hashes(current) != hashes:
        raise ValueError("R2 Generator module bytes changed; stop before performance comparison")
    baseline_tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=baseline, text=True).strip()
    if baseline_tree != declaration["baseline_tree"]:
        raise ValueError("R2 isolated baseline tree differs from preserved revision")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=baseline, text=True).strip():
        raise ValueError("R2 tracked baseline worktree contains changes")
    args.directory.mkdir(parents=True, exist_ok=True)
    save(args.directory/"START.json", {"schema": "tomolab-e8r3-public-profile-start-v1",
        "declaration_sha256": sha(args.declaration), "driver_sha256": sha(__file__),
        "started_utc": datetime.now(timezone.utc).isoformat(), "retry_policy": declaration["repeat_policy"]})
    runs = []
    for block, seed in enumerate(declaration["seeds"]):
        for profile in rotation(PROFILES, block):
            receipt = args.directory/("block-%s-%s.json" % (block, profile))
            command = [sys.executable, "-I", "-X", "utf8", str(Path(__file__).resolve()), "public-child",
                "--repo", str(baseline if profile == "r2" else current), "--declaration", str(args.declaration.resolve()),
                "--seed", str(seed), "--profile", profile, "--output", str(receipt.resolve())]
            tick = time.perf_counter()
            child = subprocess.run(command, cwd=args.directory, capture_output=True, encoding="utf-8", timeout=180)
            wall = time.perf_counter()-tick
            if child.returncode:
                save(args.directory/("block-%s-%s-ERROR.json" % (block, profile)),
                    {"exit_code": child.returncode, "stdout": child.stdout, "stderr": child.stderr,
                     "outer_process_wall_seconds": wall})
                raise RuntimeError("public profile child failed; preserve START and partial receipts")
            run = read(receipt)
            completion = json.loads(child.stdout)
            if sha(receipt) != completion["receipt_sha256"]:
                raise ValueError("child completion differs from durable receipt")
            run.update(completion, outer_process_wall_seconds=wall, block=block)
            runs.append(run)
    result = {"schema": "tomolab-e8r3-public-profile-result-v1", "declaration_sha256": sha(args.declaration),
        "driver_sha256": sha(__file__), "baseline_tree": baseline_tree,
        "generator_module_hashes": hashes, "runs": runs,
        "assessment": assess_public(runs, declaration), "actual_source_calls": 0, "actual_oracle_calls": 0,
        "allow_release": False, "historical_r2_research_result_changed": False}
    result["receipt_sha256"] = digest(result)
    save(args.output, result)
    print(json.dumps(result["assessment"], indent=2))
    return 0 if result["assessment"]["status"] == "PASS" else 3


def reassess_public(args):
    """Correct a measurement enum adapter without repeating any experiment."""
    original = read(args.input)
    unsigned = {k: v for k, v in original.items() if k != "receipt_sha256"}
    if original["receipt_sha256"] != digest(unsigned) or original["declaration_sha256"] != sha(args.declaration):
        raise ValueError("original public receipt or preregistration changed")
    result = deepcopy(original)
    result["original_result_file_sha256"] = sha(args.input)
    result["original_assessment_preserved"] = deepcopy(original["assessment"])
    result["assessment"] = assess_public(result["runs"], read(args.declaration))
    result["measurement_adapter_correction"] = "AUDIT_PASS_FULL_STRUCTURED_SEMANTICS_ENUM_ACCEPTED_AS_SUCCESS_NO_THRESHOLD_OR_DATA_CHANGE"
    result["experiment_reexecuted"] = False
    result["assessment_driver_sha256"] = sha(__file__)
    result.pop("receipt_sha256")
    result["receipt_sha256"] = digest(result)
    save(args.output, result)
    print(json.dumps(result["assessment"], indent=2))
    return 0 if result["assessment"]["status"] == "PASS" else 3


def _verify_manifest(repo, manifest_path):
    manifest = read(manifest_path)
    product = manifest["product"]
    if not isinstance(product, dict) or not product:
        raise ValueError("nonempty frozen product required")
    for name, expected in product.items():
        target = (repo/name).resolve(strict=True)
        if not target.is_relative_to(repo) or sha(target) != expected:
            raise ValueError("frozen product changed: "+name)
    required = {p.relative_to(repo).as_posix() for p in (repo/"tomolab").rglob("*.py")}
    required.update({"scripts/evaluate-e8r3.py", "docs/E8_R3_SOURCE_CONTRACT.json", "docs/E8_R3_PUBLIC_PROFILE_CONTRACT.json"})
    if not required <= set(product):
        raise ValueError("Source freeze omits executable product or preregistration")
    return manifest


def known_union(r2_frozen, r2_result, later, input_digest):
    """No batch-derived adaptation; preserve the provenance of fixed sets."""
    if later.get("complete_post_r2_source_functional_inputs") is not True:
        raise ValueError("post-R2 known registry completeness attestation required")
    old = set(r2_frozen["known_input_digests"])
    evaluated = {row["input_digest"] for run in r2_result["runs"] for row in run["rows"]}
    post = set(later.get("input_digests", []))
    post.update(input_digest(p) for p in later.get("inputs", []))
    union = old | evaluated | post
    if any(not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token) for token in union):
        raise ValueError("valid numerical input digests required")
    return sorted(union), {"r2_frozen": len(old), "all_r2_evaluated": len(evaluated),
        "post_r2_conservative_known": len(post), "union": len(union)}


def freeze_source(args):
    sys.path.insert(0, str(args.repo.resolve()))
    from tomolab.discovery.numerical_guidance import numerical_input_digest
    from tomolab.discovery.numerical_service import runtime_identity
    from tomolab.discovery.numerical_prepared import load_prepared_guide, read_approval_state
    repo = args.repo.resolve(strict=True)
    directory = args.directory.resolve()
    if directory.is_relative_to(repo):
        raise ValueError("private Source receipts must stay outside the public repository")
    declaration = read(args.declaration)
    public = read(args.public_result)
    if (public["assessment"]["status"] != "PASS" or
            public["receipt_sha256"] != digest({k: v for k, v in public.items() if k != "receipt_sha256"})):
        raise ValueError("Track 1 must PASS before Source freeze")
    if (declaration["verification_profile"] != "runtime" or len(declaration["seeds"]) != 6 or
            len(set(declaration["seeds"])) != 6 or set(declaration["seeds"]) & {13, 47, 89} or
            declaration["run_count"] != 24 or declaration["methods"] != list(METHODS) or
            declaration["parameters"] != {"size": 32, "max_examples": 512, "pair_budget": 96, "shrink_budget": 16}):
        raise ValueError("fixed six-seed runtime Source contract required")
    if generator_hashes(repo) != public["generator_module_hashes"]:
        raise ValueError("Generator policy bytes changed after public verification")
    preparation_costs = read(args.preparation_costs)
    if set(preparation_costs) != set(METHODS) or any(value is not None and
            (type(value) not in (int, float) or not math.isfinite(value) or value < 0)
            for value in preparation_costs.values()):
        raise ValueError("four actual nonnegative preparation measurements or null UNKNOWN required")
    _verify_manifest(repo, args.code_freeze)
    load_prepared_guide(args.prepared_directory, expected_digest=declaration["guide_digest"],
        expected_current_context=read_approval_state(args.approval_state))
    prepared_hashes = {name: sha(args.prepared_directory/name) for name in ("guide.json", "approval.json", "manifest.json")}
    known, counts = known_union(read(args.r2_frozen), read(args.r2_result), read(args.later_known), numerical_input_digest)
    directory.mkdir(parents=True, exist_ok=True)
    frozen = {"schema": "tomolab-e8r3-once-only-source-batch-v1", "declaration_sha256": sha(args.declaration),
        "product_manifest_sha256": sha(args.code_freeze), "driver_sha256": sha(__file__),
        "public_result_sha256": sha(args.public_result), "runtime": runtime_identity(),
        "known_input_digests": known, "known_provenance_counts": counts,
        "r2_frozen_sha256": sha(args.r2_frozen), "r2_result_sha256": sha(args.r2_result),
        "later_known_sha256": sha(args.later_known), "replay_inputs_sha256": sha(args.replays),
        "prepared_file_sha256": prepared_hashes, "approval_state_sha256": sha(args.approval_state),
        "declaration": declaration, "preparation_costs": preparation_costs,
        "method_outcomes_seen": False, "allow_release": False}
    frozen["receipt_sha256"] = digest(frozen)
    save(directory/"FROZEN.json", frozen)
    print(json.dumps({k: v for k, v in frozen.items() if k not in ("known_input_digests", "declaration")}, indent=2))


def redact_source(result):
    public = {k: deepcopy(v) for k, v in result.items() if k != "runs"}
    public["runs"] = []
    for original in result["runs"]:
        clean = {k: deepcopy(v) for k, v in original.items() if k not in ("rows", "shrinking")}
        shrink = original.get("shrinking")
        clean["shrinking"] = None if shrink is None else {k: v for k, v in shrink.items() if k not in ("witness", "original_witness")}
        public["runs"].append(clean)
    public.pop("receipt_sha256", None)
    public["public_receipt_sha256"] = digest(public)
    return public


def execute_source(args):
    started = time.perf_counter()
    sys.path.insert(0, str(args.repo.resolve()))
    from tomolab.discovery.numerical_service import runtime_identity, run_numerical_method
    from tomolab.discovery.numerical_prepared import load_prepared_guide, read_approval_state
    from tomolab.discovery import compact_guidance as compact
    from tomolab.discovery import numerical_guidance as guidance
    from tomolab.discovery.knowledge import KnowledgeArchive
    frozen = read(args.directory/"FROZEN.json")
    if (frozen["receipt_sha256"] != digest({k: v for k, v in frozen.items() if k != "receipt_sha256"}) or
            frozen["driver_sha256"] != sha(__file__) or frozen["runtime"] != runtime_identity() or
            frozen["product_manifest_sha256"] != sha(args.code_freeze) or
            frozen["replay_inputs_sha256"] != sha(args.replays) or
            frozen["approval_state_sha256"] != sha(args.approval_state) or
            any(sha(args.prepared_directory/name) != expected for name, expected in frozen["prepared_file_sha256"].items())):
        raise ValueError("frozen Source execution identity differs")
    _verify_manifest(args.repo.resolve(), args.code_freeze)
    declaration = frozen["declaration"]
    if sha(args.repo/"docs/E8_R3_SOURCE_CONTRACT.json") != frozen["declaration_sha256"]:
        raise ValueError("Source preregistration changed after freeze")
    # Exclusive durable START precedes the first actual Source call. Any crash
    # leaves this batch consumed; there is no retry/resume optimization path.
    save(args.directory/"START.json", {"frozen_receipt_sha256": frozen["receipt_sha256"],
        "started_utc": datetime.now(timezone.utc).isoformat(), "retry": "FORBIDDEN"})
    replays = read(args.replays)
    archive_calls = {"full_archive_replay": 0, "recipe_preparation": 0, "recipe_calibration": 0, "compilation": 0}
    def track(owner, attribute, name):
        original = getattr(owner, attribute)
        def called(*positional, **keywords):
            archive_calls[name] += 1
            return original(*positional, **keywords)
        setattr(owner, attribute, called)
    track(KnowledgeArchive, "from_snapshot", "full_archive_replay")
    track(compact, "prepare_recipe_from_archive", "recipe_preparation")
    track(guidance, "calibrate_recipe", "recipe_calibration")
    track(compact, "compile_execution_artifact", "compilation")
    runs, run_measurements = [], []
    for index, seed in enumerate(declaration["seeds"]):
        for method in rotation(METHODS, index):
            outer_tick = time.perf_counter()
            calls_before = deepcopy(archive_calls)
            load_tick = time.perf_counter()
            loaded = (load_prepared_guide(args.prepared_directory, expected_digest=declaration["guide_digest"],
                expected_current_context=read_approval_state(args.approval_state)) if method == "D" else None)
            load_seconds = time.perf_counter()-load_tick if loaded is not None else None
            api_offset = time.perf_counter()-outer_tick
            api_tick = time.perf_counter()
            run = run_numerical_method(loaded["compiled"] if method == "D" else None,
                expected_digest=declaration["guide_digest"] if method == "D" else None,
                method=method, seed=seed, contract=declaration["contract"], verification_profile="runtime",
                excluded_digests=frozen["known_input_digests"], replay_inputs=replays,
                **declaration["parameters"])
            api_outer_seconds = time.perf_counter()-api_tick
            run_file = args.directory/("run-%s-%s.json" % (seed, method))
            receipt_tick = time.perf_counter()
            save(run_file, run)
            receipt_io = time.perf_counter()-receipt_tick
            measured = {"method": method, "seed": seed, "source_run_receipt_sha256": sha(run_file),
                "prepared_load_and_validation_seconds": load_seconds, "api_entry_offset_seconds": api_offset,
                "api_call_outer_seconds": api_outer_seconds, "receipt_io_seconds": receipt_io,
                "outer_to_primary_receipt_flush_seconds": time.perf_counter()-outer_tick,
                "archive_processing_calls": {name: count-calls_before[name] for name, count in archive_calls.items()}}
            completion_tick = time.perf_counter()
            save(args.directory/("run-%s-%s-completion.json" % (seed, method)), measured)
            measured["completion_receipt_io_seconds"] = time.perf_counter()-completion_tick
            measured["prepared_outer_wall_seconds"] = time.perf_counter()-outer_tick
            run_measurements.append(measured)
            runs.append(run)
            if run["status"] != "COMPLETE":
                save(args.directory/"PARTIAL.json", {"status": "INCONCLUSIVE", "completed_runs": len(runs),
                    "stop_reason": "REGISTERED_RUN_FAILED_NO_SILENT_RETRY", "failed_seed": seed, "failed_method": method})
                raise RuntimeError("Source run incomplete; preserve START and partial receipts")
    result = summarize_source(runs, declaration, frozen["preparation_costs"], run_measurements=run_measurements)
    result["frozen_receipt_sha256"] = frozen["receipt_sha256"]
    result["known_provenance_counts"] = frozen["known_provenance_counts"]
    result["outer_source_driver_wall_before_receipt_seconds"] = time.perf_counter()-started
    outer_sum = sum(r["prepared_outer_wall_seconds"] for r in run_measurements)
    shared = max(0.0, result["outer_source_driver_wall_before_receipt_seconds"]-outer_sum)
    result["shared_batch_administration_seconds"] = shared
    result["shared_cost_allocation"] = "ONE_QUARTER_TO_EACH_METHOD_EXCLUDES_FINAL_RESULT_AND_PUBLIC_REPORT_WRITE"
    result["archive_processing_calls"] = archive_calls
    for method in METHODS:
        summary = result["summaries"][method]
        summary["shared_batch_administration_seconds"] = shared/len(METHODS)
        summary["prepared_total_seconds"] += shared/len(METHODS)
        if summary["cold_total_seconds"] is not None:
            summary["cold_total_seconds"] += shared/len(METHODS)
        setup = summary["one_time_preparation_seconds"]
        events = result["method_discovery_events"][method]
        result["curves"][method] = {"confirmed_fresh_inputs_at_fixed_seconds": [{"seconds": checkpoint,
            "prepared": len({token for when, token in events if when+shared/len(METHODS) <= checkpoint}),
            "cold": None if setup is None else len({token for when, token in events if when+shared/len(METHODS)+setup <= checkpoint})}
            for checkpoint in declaration["fixed_time_checkpoints_seconds"]],
            "shared_administration": "CONSERVATIVE_EQUAL_ONE_QUARTER_OFFSET_BEFORE_FIRST_RUN",
            "observations_are_cumulative_same_source_inputs_not_independent_mechanisms": True}
    # Equal shared overhead does not change the pairwise no-greater-cost test.
    result["receipt_sha256"] = digest(result)
    save(args.directory/"RESULT.json", result)
    public = redact_source(result)
    public["private_result_file_sha256"] = sha(args.directory/"RESULT.json")
    public.pop("public_receipt_sha256")
    public["public_receipt_sha256"] = digest(public)
    save(args.output, public)
    _verify_manifest(args.repo.resolve(), args.code_freeze)
    print(json.dumps({"status": result["status"], "summaries": result["summaries"],
        "added_value": result["added_value"], "allow_release": False}, indent=2))


def summarize_source(runs, declaration, preparation_costs, *, run_measurements):
    summaries, curves, method_events = {}, {}, {}
    for method in METHODS:
        trials = [r for r in runs if r["method"] == method]
        unique = {row["input_digest"] for r in trials for row in r["rows"] if row["phase"] == "fresh_generation" and not row["known_development_input"]}
        failures = {row["input_digest"] for r in trials for row in r["rows"] if row["phase"] == "fresh_generation" and row.get("confirmed_failure")}
        measurements = [r for r in run_measurements if r["method"] == method]
        elapsed = sum(r["prepared_outer_wall_seconds"] for r in measurements)
        api_elapsed = sum(r["r3"]["timing"]["end_to_end_wall"] for r in trials)
        setup = preparation_costs.get(method)
        if setup is not None and (not isinstance(setup, (int, float)) or not math.isfinite(setup) or setup < 0):
            raise ValueError("preparation cost must be an actual nonnegative measurement or null UNKNOWN")
        summaries[method] = {"trials": len(trials), "completed_trials": sum(r["status"] == "COMPLETE" for r in trials),
            "unique_fresh_valid_inputs": len(unique), "distinct_confirmed_fresh_failure_inputs": len(failures),
            "confirmed_mechanisms": sorted({m for r in trials for m in r["mechanisms"]}),
            "distinct_new_mechanisms": 0, "target_calls": sum(r["target_calls"] for r in trials),
            "oracle_calls": sum(r["oracle_calls"] for r in trials),
            "known_input_replay_calls": sum(r["known_input_replay_calls"] for r in trials),
            "first_evaluated_valid_inputs_trial_sum_including_shrink": sum(r["first_evaluated_valid_inputs"] for r in trials),
            "domain_rejections": sum(r["domain_rejections"]+r["generation"].get("domain_rejections", 0) for r in trials),
            "duplicate_rejections": sum(r["generation"].get("duplicate_rejections", 0) for r in trials),
            "existing_input_rejections": sum(r["generation"].get("existing_input_rejections", 0) for r in trials),
            "oracle_errors": sum(r["oracle_errors"] for r in trials), "target_errors": sum(r["target_errors"] for r in trials),
            "replay_mismatches": sum(r["replay_mismatches"] for r in trials),
            "evaluation_pairs_by_phase": {phase: sum(sum(row["phase"] == phase and "actual" in row for row in r["rows"]) for r in trials)
                for phase in sorted({row["phase"] for r in trials for row in r["rows"]})},
            "prepared_total_seconds": elapsed, "prepared_api_wall_seconds": api_elapsed, "one_time_preparation_seconds": setup,
            "cold_total_seconds": None if setup is None else elapsed+setup,
            "primary_generation_executions": sum(r["primary_generation_executions"] for r in trials),
            "reference_generation_executions": sum(r["reference_generation_executions"] for r in trials),
            "first_confirmed_failure": [None if r["r3"].get("first_confirmed_failure") is None else
                dict(r["r3"]["first_confirmed_failure"],
                    seconds_since_method_outer_entry=r["r3"]["first_confirmed_failure"]["seconds_since_api_entry"]+m["api_entry_offset_seconds"],
                    cold_seconds_including_one_preparation=None if setup is None else
                        setup+r["r3"]["first_confirmed_failure"]["seconds_since_api_entry"]+m["api_entry_offset_seconds"])
                for r, m in zip(trials, measurements)]}
        events, offset = [], 0.0
        for run, measured in zip(trials, measurements):
            for event in run["r3"].get("discovery_events", []):
                events.append((offset+measured["api_entry_offset_seconds"]+event["seconds_since_api_entry"], event["input_digest"]))
            offset += measured["prepared_outer_wall_seconds"]
        method_events[method] = events
        curves[method] = {"confirmed_fresh_inputs_at_fixed_seconds": [{"seconds": checkpoint,
            "prepared": len({token for when, token in events if when <= checkpoint}),
            "cold": None if setup is None else len({token for when, token in events if when+setup <= checkpoint})}
            for checkpoint in declaration["fixed_time_checkpoints_seconds"]],
            "observations_are_cumulative_same_source_inputs_not_independent_mechanisms": True}
    added = {}
    for comparator in ("B", "C"):
        left, right = summaries["D"], summaries[comparator]
        more = left["distinct_confirmed_fresh_failure_inputs"] > right["distinct_confirmed_fresh_failure_inputs"]
        added[comparator] = {"prepared": "OBSERVED" if more and left["prepared_total_seconds"] <= right["prepared_total_seconds"] else "NOT_ESTABLISHED",
            "cold": "OBSERVED" if more and left["cold_total_seconds"] is not None and right["cold_total_seconds"] is not None
                and left["cold_total_seconds"] <= right["cold_total_seconds"] else "NOT_ESTABLISHED"}
    global_seen, confirmed, actual_first = set(), set(), {method: 0 for method in METHODS}
    for run in runs:
        for row in run["rows"]:
            if not row["known_development_input"] and row["input_digest"] not in global_seen:
                global_seen.add(row["input_digest"])
                actual_first[run["method"]] += 1
            if row.get("confirmed_failure"):
                confirmed.add(row["input_digest"])
    return {"schema": "tomolab-e8r3-source-comparison-v1", "status": "COMPLETE", "scope": declaration["scope"],
        "summaries": summaries, "runs": runs, "run_measurements": run_measurements, "curves": curves,
        "method_discovery_events": method_events, "added_value": added,
        "input_counting": {"method_relative_to": "SAME_FROZEN_PREBATCH_KNOWN_SET",
            "actual_first_evaluations_by_execution_order_including_shrink": actual_first,
            "batch_distinct_new_valid_inputs_including_shrink": len(global_seen),
            "batch_distinct_confirmed_fresh_failure_inputs": len(confirmed),
            "method_overlap_does_not_change_any_generation_request": True},
        "preserved_r2_verdict": declaration["preserved_r2_verdict"], "historical_collection_cost": "UNKNOWN",
        "independent_corroboration": "NOT_AVAILABLE", "external_generalization": "NOT_ESTABLISHED",
        "statistical_superiority_claimed": False, "allow_release": False}


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="command", required=True)
    public = commands.add_parser("public", help="등록된 공개 12회 실행: 실제 Source/Oracle 호출 없음")
    public.add_argument("--repo", type=Path, default=ROOT)
    public.add_argument("--baseline", type=Path, required=True)
    public.add_argument("--declaration", type=Path, default=ROOT/"docs/E8_R3_PUBLIC_PROFILE_CONTRACT.json")
    public.add_argument("--directory", type=Path, required=True)
    public.add_argument("--output", type=Path, required=True)
    reassess = commands.add_parser("public-reassess", help="측정 enum 수정 후 기존 영수증만 재판정; 실험 재실행 없음")
    reassess.add_argument("--declaration", type=Path, default=ROOT/"docs/E8_R3_PUBLIC_PROFILE_CONTRACT.json")
    reassess.add_argument("--input", type=Path, required=True)
    reassess.add_argument("--output", type=Path, required=True)
    child = commands.add_parser("public-child", help=argparse.SUPPRESS)
    for name in ("repo", "declaration", "output"):
        child.add_argument("--"+name, type=Path, required=True)
    child.add_argument("--profile", choices=PROFILES, required=True)
    child.add_argument("--seed", type=int, required=True)
    freeze = commands.add_parser("source-freeze", help="Track 1 통과 후 개발 Source 24회 실행을 한 번 등록")
    execute = commands.add_parser("source-execute", help="동결된 개발 배치 1회 실행; 실패/중단 후 재실행 금지")
    for command in (freeze, execute):
        command.add_argument("--repo", type=Path, default=ROOT)
        for name in ("directory", "code-freeze", "replays"):
            command.add_argument("--"+name, type=Path, required=True)
        command.add_argument("--prepared-directory", type=Path, required=True)
        command.add_argument("--approval-state", type=Path, required=True)
    freeze.add_argument("--declaration", type=Path, default=ROOT/"docs/E8_R3_SOURCE_CONTRACT.json")
    for name in ("public-result", "r2-frozen", "r2-result", "later-known", "preparation-costs"):
        freeze.add_argument("--"+name, type=Path, required=True)
    execute.add_argument("--output", type=Path, required=True)
    return value


def main(argv=None):
    args = parser().parse_args(argv)
    return {"public": public_profile, "public-reassess": reassess_public, "public-child": public_child,
        "source-freeze": freeze_source, "source-execute": execute_source}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
