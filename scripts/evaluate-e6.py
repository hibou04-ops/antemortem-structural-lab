"""E6 public development QA and once-only, no-feedback final comparison.

Trusted user-owned callbacks only. Raw final material stays outside the public
repository. Whole trace calls and actual transition callbacks are distinct.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/E6_EVALUATION_CONTRACT.json"
PUBLIC = ROOT / "benchmarks/e6_public_cases.py"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def load_module(path):
    spec = importlib.util.spec_from_file_location("e6_fixture_" + file_sha(path), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(case):
    from tomolab.discovery.analysis import analyze_source
    from tomolab.discovery.schema import validate_spec
    if case["kind"] == "stateful":
        from tomolab.discovery.stateful import trace_spec
        actions = [item["name"] for item in case["temporal_contract"]["actions"]]
        spec = trace_spec(actions, case["argument_type"], task_id=case["public_contract_id"] + "-task", max_steps=case["max_steps"],
                          state_model=case["public_contract_id"])
        source = load_module(PUBLIC).PUBLIC_TRACE_MODEL
        roles = {"trace": "transitions"}
    else:
        spec = {"schema": "tomolab-discovery-spec-v1", "task_id": case["public_contract_id"] + "-task",
                "inputs": [{"name": name, "role": role, "type": deepcopy(type_)} for name, role, type_ in case["inputs"]],
                "contract": {"id": case["public_contract_id"], "operation": "static-reference-equivalence",
                             "preconditions": [], "invariants": ["state-match"], "state_model": "stateless", "graph_signature": "UNKNOWN"}}
        names = [item[0] for item in case["inputs"]]
        source = "def reference(" + ",".join(names) + "):\n    return reference_operation(" + ",".join(names) + ")\n"
        roles = {name: role for name, role, _ in case["inputs"]}
    ir = analyze_source(source, "reference", roles)
    spec["contract"]["invariants"] = ["state-match"]
    spec["contract"]["graph_signature"] = ir["graph_signature"]
    return validate_spec(spec), ir


class EvaluationStop(BaseException):
    pass


class Holder:
    def __init__(self, state, context, side):
        self.state, self.context, self.side = deepcopy(state), context, side


class Meter:
    """Count real callbacks, not library-reported or simulated Oracle calls."""
    def __init__(self, case, config, started, deadline):
        self.case, self.config, self.started, self.deadline = case, config, started, deadline
        self.model_calls = self.target_calls = 0
        self.model_seconds = self.target_seconds = 0.0
        self.contexts, self.pending = [], {}
        self.started_episodes = 0
        self.first_calls = self.first_wall = None
        self.static_expected = {}

    def check(self, side):
        if time.perf_counter() >= self.deadline:
            raise EvaluationStop("WALL_TIMEOUT")
        count = self.model_calls if side == "model" else self.target_calls
        if count >= self.config["actual_" + side + "_transition_cap"]:
            raise EvaluationStop("TRANSITION_BUDGET")

    def new_context(self, *, native_factory=False):
        context = {"model_trace": [], "target_trace": [], "model_states": [], "target_states": [],
                   "failed": False, "first_failure_index": None, "started": False, "native_factory": native_factory}
        self.contexts.append(context)
        if not native_factory:
            self.start_episode(context)
        return context

    def start_episode(self, context):
        if context["started"]:
            return
        if time.perf_counter() >= self.deadline:
            raise EvaluationStop("WALL_TIMEOUT")
        if not context["native_factory"]:
            if self.started_episodes >= self.config["trace_callback_cap"]:
                raise EvaluationStop("TRACE_BUDGET")
            self.started_episodes += 1
        context["started"] = True

    def project(self, state):
        if "project" in self.case:
            return deepcopy(self.case["project"](state))
        return {item["role"]: deepcopy(state[item["name"]]) for item in self.case["temporal_contract"]["state"]}

    def _compare(self, context, index):
        if index >= min(len(context["model_states"]), len(context["target_states"])):
            return
        if canonical(context["model_states"][index]) != canonical(context["target_states"][index]):
            context["failed"] = True
            if context["first_failure_index"] is None:
                context["first_failure_index"] = index
            if self.first_calls is None:
                self.first_calls = self.model_calls + self.target_calls
                self.first_wall = time.perf_counter() - self.started

    def step(self, subject, action, argument):
        side, context = subject.side, subject.context
        # Native Hypothesis construction must be independent of global budgets.
        # Abort only after the rule has drawn its data and invokes a callback.
        self.start_episode(context)
        self.check(side)
        if side == "model":
            self.model_calls += 1
        else:
            self.target_calls += 1
        before = time.perf_counter()
        callback = self.case["model_step" if side == "model" else "target_step"]
        try:
            subject.state = callback(deepcopy(subject.state), action, deepcopy(argument))
        except Exception as error:
            if side == "model":
                raise RuntimeError("independent model callback failed") from error
            projected = {"target_exception": type(error).__name__}
        else:
            # A broken projection is an evaluator failure on either side.
            projected = self.project(subject.state)
        if side == "model":
            self.model_seconds += time.perf_counter() - before
        else:
            self.target_seconds += time.perf_counter() - before
        context[side + "_trace"].append([action, deepcopy(argument)])
        context[side + "_states"].append(projected)
        self._compare(context, len(context[side + "_states"]) - 1)
        return None

    def bindings(self):
        last_target = [None]
        def target_factory():
            context = self.new_context(native_factory=True)
            holder = Holder(self.case.get("target_initial", self.case["initial"]), context, "target")
            last_target[0] = holder
            return holder
        def model_factory():
            if last_target[0] is None:
                raise ValueError("model factory must follow the paired target factory")
            return Holder(self.case["initial"], last_target[0].context, "model")
        operations = {}
        for action in self.case["temporal_contract"]["actions"]:
            name = action["name"]
            operations[name] = {"target": lambda subject, argument, name=name: self.step(subject, name, argument),
                                "model": lambda subject, argument, name=name: self.step(subject, name, argument)}
        return target_factory, model_factory, operations, lambda subject: self.project(subject.state)

    def oracle(self, *args, **kwargs):
        if self.case["kind"] == "static":
            context = self.new_context()
            self.check("model")
            self.model_calls += 1
            names = [item[0] for item in self.case["inputs"]]
            point = kwargs if kwargs else dict(zip(names, args))
            before = time.perf_counter()
            result = self.case["oracle"](*(deepcopy(point[name]) for name in names))
            self.model_seconds += time.perf_counter() - before
            self.static_expected[canonical(point)] = (deepcopy(result), context)
            return result
        trace = kwargs.get("trace", args[0] if args else None)
        context = self.new_context()
        context["requested_inputs"] = {"trace": deepcopy(trace)}
        subject = Holder(self.case["initial"], context, "model")
        for action, argument in trace:
            self.step(subject, action, argument)
        self.pending[canonical(trace)] = context
        return deepcopy(context["model_states"])

    def target(self, *args, **kwargs):
        if self.case["kind"] == "static":
            self.check("target")
            self.target_calls += 1
            names = [item[0] for item in self.case["inputs"]]
            point = kwargs if kwargs else dict(zip(names, args))
            before = time.perf_counter()
            result = self.case["target"](*(deepcopy(point[name]) for name in names))
            self.target_seconds += time.perf_counter() - before
            expected, context = self.static_expected[canonical(point)]
            failed = canonical(result) != canonical(expected)
            context.update(failed=failed, inputs=deepcopy(point))
            if failed and self.first_calls is None:
                self.first_calls = self.model_calls + self.target_calls
                self.first_wall = time.perf_counter() - self.started
            return result
        trace = kwargs.get("trace", args[0] if args else None)
        context = self.pending[canonical(trace)]
        subject = Holder(self.case.get("target_initial", self.case["initial"]), context, "target")
        for action, argument in trace:
            self.step(subject, action, argument)
        return deepcopy(context["target_states"])

    def predicate(self, inputs):
        self.oracle(**inputs)
        self.target(**inputs)
        return self.contexts[-1]["failed"]

    def metrics(self):
        rows = []
        for context in self.contexts:
            if not context["started"]:
                continue
            point = context.get("inputs", context.get("requested_inputs", {"trace": context["target_trace"]}))
            rows.append({"inputs": point, "failed": context["failed"], "first_failure_index": context["first_failure_index"]})
        failed = [row for row in rows if row["failed"]]
        unique = {canonical(row["inputs"]) for row in rows}
        unique_failed = {canonical(row["inputs"]) for row in failed}
        return {"actual_model_transition_calls": self.model_calls, "actual_target_transition_calls": self.target_calls,
                "actual_primitive_invocations": self.model_calls + self.target_calls,
                "whole_trace_callbacks": self.started_episodes,
                "native_factory_episodes": sum(row["started"] and row["native_factory"] for row in self.contexts),
                "trace_evaluations": len(rows), "unique_evaluated_inputs": len(unique),
                "failed_evaluations": len(failed), "unique_failing_inputs": len(unique_failed),
                "duplicate_evaluation_rate": 1 - len(unique) / len(rows) if rows else 0.0,
                "duplicate_failure_rate": 1 - len(unique_failed) / len(failed) if failed else 0.0,
                "first_failure_primitive_invocations": self.first_calls, "first_failure_wall_seconds": self.first_wall,
                "oracle_seconds": self.model_seconds + self.target_seconds,
                "confirmed_family": self.case["family_id"] if failed else None,
                "control_false_alert": bool(failed and not self.case["expected_fault"])}, rows


def runtime_hashes(root):
    root = Path(root)
    return {path.relative_to(root).as_posix(): file_sha(path) for path in sorted((root / "tomolab").rglob("*.py"))}


def product_hashes():
    paths = [Path(__file__).resolve(), PUBLIC, CONTRACT, ROOT / "pyproject.toml"]
    return {**runtime_hashes(ROOT), **{path.relative_to(ROOT).as_posix(): file_sha(path) for path in paths}}


def validate_suite(cases, contract):
    expected = {**{family: True for family in contract["families"]}, **{family: False for family in contract["controls"]}}
    observed = {case["family_id"]: case["expected_fault"] for case in cases}
    if observed != expected or len(cases) != len(expected) or len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError("preregistered five families and both controls must appear exactly once")


def validate_grid(records, cases, methods, seeds):
    expected = {(case["case_id"], method, seed) for case in cases for method in methods for seed in seeds}
    observed = [(row["case_id"], row["method"], row["seed"]) for row in records]
    if len(observed) != len(expected) or set(observed) != expected:
        raise ValueError("preregistered case/method/seed grid is incomplete or duplicated")


def consume_final_once(state_dir, manifest):
    path = Path(state_dir) / ("final-consumed-" + manifest["private_suite_sha256"] + ".jsonl")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical({"event": "FINAL_ATTEMPT_STARTED", "freeze": manifest["sha256"], "time_unix": time.time()}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def verify_freeze(state_dir, manifest):
    if digest({key: value for key, value in manifest.items() if key != "sha256"}) != manifest["sha256"]:
        raise ValueError("freeze manifest digest mismatch")
    if product_hashes() != manifest["product"] or runtime_hashes(manifest["baseline_root"]) != manifest["baseline"]:
        raise ValueError("product or baseline freeze drifted")
    if file_sha(manifest["private_suite_path"]) != manifest["private_suite_sha256"]:
        raise ValueError("private final suite drifted")
    for name, sha in manifest["source_molds"].items():
        if file_sha(Path(state_dir) / name) != sha:
            raise ValueError("source mold freeze drifted")


def crosshair(case, spec, folder, meter, remaining):
    from tomolab.discovery.symbolic import check_contract
    if case["kind"] == "stateful":
        actions = [action["name"] for action in case["temporal_contract"]["actions"]]
        annotation = "trace: list[tuple[str, int]]"
        pre = f"len(trace) <= 8 and all(action in {actions!r} and -2 <= argument <= 2 for action, argument in trace)"
        arguments = "trace"
        # Inline the actual reviewed functions with direct wrappers, avoiding
        # metadata/import machinery in the source-aware analyzer's workload.
        source = inspect.getsource(case["model_step"]) + "\n" + inspect.getsource(case["target_step"]) + "\n"
        for name, callback in (("model", case["model_step"]), ("target", case["target_step"])):
            source += (f"def {name}(trace):\n    state = {case['initial']!r}\n    rows = []\n"
                       + f"    for action, argument in trace:\n        state = {callback.__name__}(state, action, argument)\n"
                       + "        rows.append(state)\n    return rows\n")
    else:
        names = [item[0] for item in case["inputs"]]
        arguments = ",".join(names)
        annotation = ",".join(name + ": " + type_["kind"] for name, _, type_ in case["inputs"])
        if len(names) == 2:
            pre = " and ".join(f"-16 <= {name} <= 16" for name in names)
        else:
            pre = "len(value) <= 8 and all(char in 'AaB .\\t\\n' for char in value)"
        if len(names) == 2:
            from tomolab.mold.relations import feature
            dependency = inspect.getsource(feature)
            implementation = "def target(a,b):\n    return feature('difference',a,b)\n"
        else:
            from tomolab.claim import _normalize
            dependency = inspect.getsource(_normalize)
            implementation = "def target(value):\n    return _normalize(value)\n"
        reference = inspect.getsource(case["oracle"]).replace("def " + case["oracle"].__name__, "def model", 1)
        source = dependency + "\n" + implementation + "\n" + reference + "\n"
    source += (f"def obligation({annotation}):\n    \"\"\"\n    pre: {pre}\n    post: _ == model({arguments})\n    \"\"\"\n    return target({arguments})\n")
    path = Path(folder) / "public_crosshair_contract.py"
    path.write_text(source, encoding="utf-8")
    receipt = check_contract(path, "obligation", trusted_execution=True,
                             timeout_seconds=max(0.1, remaining - 0.2), per_condition_seconds=min(6.0, max(0.1, remaining - 0.3)))
    save(Path(folder) / "raw_crosshair_receipt.json", receipt)
    for point in receipt["candidates"]:
        try:
            from tomolab.discovery.schema import validate_inputs
            point = validate_inputs(point, spec)
        except (ValueError, TypeError):
            continue
        meter.predicate(point)
    return {"status": receipt["status"], "internal_symbolic_oracle_calls": None,
            "diagnostics_count": len(receipt["diagnostics"]), "candidate_count": len(receipt["candidates"]),
            "tool_version": receipt["tool_version"]}


def source_case_id(case):
    return next(row["case_id"] for row in load_module(PUBLIC).CASES if row["public_contract_id"] == case["public_contract_id"])


def independent_audits(frozen, case, spec, ir, meter, seed):
    from tomolab.discovery.hypothesis_adapter import generate_pool
    from tomolab.discovery.temporal import simulate_trace, temporal_holds
    from tomolab.discovery.temporal_transfer import transfer_temporal
    before = digest(frozen)
    ids = sorted({rid for group in frozen["groups"].values() for rid in group["remaining"]
                  if rid in frozen["temporal_relations"]})[:128]
    truths = []
    for point in generate_pool(spec, seed=seed + 65537, size=64):
        label = meter.predicate(point)
        truths.append((point, label, meter.contexts[-1]["first_failure_index"], simulate_trace(point, spec, case["temporal_contract"])))
    contradicted = []
    for rid in ids:
        if any(temporal_holds(frozen["relations"][rid], replay, first if label else None) != label
               for point, label, first, replay in truths):
            contradicted.append(rid)
    renamed = deepcopy(case)
    renamed["case_id"] += "-renamed"
    for state in renamed["temporal_contract"]["state"]:
        state["name"] = "mapped_" + state["name"]
    for action in renamed["temporal_contract"]["actions"]:
        action["name"] = "mapped_" + action["name"]
    renamed_spec, renamed_ir = prepare(renamed)
    supported = bool(ids) and not frozen.get("inconsistent", False)
    targets = [("same-contract", spec, case["temporal_contract"], ir, supported),
               ("renamed-state-and-actions", renamed_spec, renamed["temporal_contract"], renamed_ir, supported)]
    domain = deepcopy(case["temporal_contract"])
    domain["state"][0]["type"]["max"] += 1
    targets.append(("expanded-domain", spec, domain, ir, False))
    guards = deepcopy(case["temporal_contract"])
    guards["actions"][0]["preconditions"].append(False)
    targets.append(("changed-precondition", spec, guards, ir, False))
    roles = deepcopy(case["temporal_contract"])
    roles["state"][0]["role"] += "_wrong"
    targets.append(("role-mismatch", spec, roles, ir, False))
    checks = []
    for name, target_spec, contract, target_ir, expected in targets:
        try:
            receipt = transfer_temporal(frozen, target_spec, contract, target_ir=target_ir, budget=1, pool_size=128, seed=seed)
            status = receipt["gate"]["status"]
            accepted = status == "APPLICABLE_FOR_PROBING"
        except ValueError:
            if expected:
                raise
            status, accepted = "DECLARATION_REJECTED", False
        checks.append({"case": name, "expected_applicable": expected, "actual_applicable": accepted,
                       "status": status, "correct": accepted == expected})
    counterevidence = None
    failures = [row for row in frozen["temporal_evidence"] if row["kind"] == "FAILURE"]
    if failures:
        clean = dict(case, target_step=case["model_step"])
        clean_meter = Meter(clean, meter.config, meter.started, meter.deadline)
        event = deepcopy(failures[0])
        assert clean_meter.predicate(event["inputs"]) is False
        meter.model_calls += clean_meter.model_calls
        meter.target_calls += clean_meter.target_calls
        meter.contexts.extend(clean_meter.contexts)
        event.update(kind="REFUTATION", first_failure_index=None, evidence_id="independent-clean-development-0")
        receipt = transfer_temporal(frozen, spec, case["temporal_contract"], target_ir=ir, target_evidence=[event],
                                    budget=1, pool_size=128, seed=seed)
        replay = simulate_trace(event["inputs"], spec, case["temporal_contract"])
        expected_ids = {rid for rid in ids if temporal_holds(frozen["relations"][rid], replay)}
        actual_ids = {item["constraint_id"] for item in receipt["gate"]["target_contradictions"] if item["constraint_id"] in ids}
        counterevidence = {"expected_removed": len(expected_ids), "actual_removed": len(actual_ids),
                           "correct": expected_ids == actual_ids, "failure_recurrence": receipt["gate"]["failure_recurrence"]}
    if digest(frozen) != before:
        raise ValueError("audit changed a source mold")
    return {"validation_inputs": len(truths), "temporal_candidates_checked": len(ids), "contradicted_candidates": len(contradicted),
            "constraint_scope": "bounded temporal membership hypotheses, not causal laws", "transfer_checks": checks,
            "checked_clean_counterevidence": counterevidence, "feedback_to_generator": 0}


def worker(packet):
    runtime = Path(packet["baseline_root"]) if packet["method"].startswith("E5") else ROOT
    sys.path.insert(0, str(runtime))
    case = load_module(packet["suite"]).case_by_id(packet["case_id"])
    phase, method, seed = packet["phase"], packet["method"], packet["seed"]
    config = packet["config"]
    started = packet["launched_at"]
    meter = Meter(case, config, started, started + config["wall_cap_seconds"])
    folder = Path(packet["folder"])
    folder.mkdir(parents=True, exist_ok=True)
    result = {"phase": phase, "method": method, "case_id": case["case_id"], "family_id": case["family_id"],
              "kind": case["kind"], "expected_fault": case["expected_fault"], "seed": seed,
              "status": "COMPLETE", "source_access": method == "CrossHair", "final_feedback_calls": 0 if phase == "final" else None}
    cpu = time.process_time()
    try:
        before = time.perf_counter()
        spec, ir = prepare(case)
        result["ir_analysis_seconds"] = time.perf_counter() - before
        remaining = max(0.01, meter.deadline - time.perf_counter())
        if method.startswith("NativeStateful") and case["kind"] != "stateful":
            result.update(status="NOT_COMPARABLE", reason="static control has no declared state-machine actions")
        elif phase == "development":
            if method == "NativeHypothesis":
                from tomolab.discovery.hypothesis_adapter import native_find
                receipt = native_find(spec, meter.predicate, budget=config["trace_callback_cap"], seed=seed,
                                      cache=True, time_budget=remaining)
            elif method == "NativeStateful":
                from tomolab.discovery.native_stateful import run_native_stateful
                target_factory, model_factory, operations, snapshot = meter.bindings()
                receipt = run_native_stateful(spec, case["temporal_contract"], target_factory, model_factory, operations,
                    snapshot=snapshot, budget=config["actual_model_transition_cap"], max_examples=config["max_examples"],
                    steps=config["stateful_step_count"], seed=seed, time_budget=remaining, trusted_execution=True)
            elif method == "E6" and case["kind"] == "stateful":
                from tomolab.discovery.temporal_service import run_temporal
                target_factory, model_factory, operations, snapshot = meter.bindings()
                receipt = run_temporal(target_factory, model_factory, operations, snapshot=snapshot, spec=spec,
                    temporal_contract=case["temporal_contract"], budget=128, shrink_budget=config["shrink_budget"],
                    seed=seed, pool_size=config["pool_size"], time_budget=remaining, trusted_execution=True,
                    backend="subprocess", public_ir=ir)
            elif method in ("E5", "E6"):
                from tomolab.discovery.service import run_discovery
                receipt = run_discovery(meter.target, meter.oracle, spec, public_ir=ir,
                    budget=config["candidate_budget"], shrink_budget=config["shrink_budget"], pool_size=config["pool_size"],
                    seed=seed, time_budget=remaining, trusted_execution=True, backend="subprocess", solver="z3")
            elif method == "CrossHair":
                receipt = crosshair(case, spec, folder, meter, remaining)
            else:
                raise ValueError("unknown method")
            save(folder / "algorithm_receipt.json", receipt)
            if "snapshot" in receipt:
                save(folder / "snapshot.json", receipt["snapshot"])
                result["snapshot_sha256"] = digest(receipt["snapshot"])
            result["algorithm_status"] = receipt.get("status")
            result["algorithm_metrics"] = receipt.get("metrics", {})
            result["cost_components"] = receipt.get("timing", {})
            if method == "CrossHair":
                result.update(receipt)
                result["tool_status"] = receipt["status"]
                result["status"] = "UNKNOWN" if receipt["status"].startswith("UNKNOWN") else "COMPLETE"
        elif phase == "audit":
            source = Path(packet["state_dir"]) / "development" / case["case_id"] / f"E6-{seed}" / "snapshot.json"
            result["audit"] = independent_audits(json.loads(source.read_text(encoding="utf-8")), case, spec, ir, meter, seed)
        elif phase == "final":
            if method == "NativeHypothesis-frozen":
                from tomolab.discovery.hypothesis_adapter import generate_pool
                plan = {"candidates": [{"inputs": point} for point in generate_pool(spec, seed=seed, size=config["candidate_budget"])],
                        "final_feedback_allowed": False, "gate": {"status": "NO_TRANSFER_BASELINE"}}
            elif method == "NativeStateful-frozen":
                from tomolab.discovery.native_stateful import generate_stateful_plan
                receipt = generate_stateful_plan(spec, case["temporal_contract"], seed=seed,
                    max_examples=config["max_examples"], steps=config["stateful_step_count"],
                    budget=config["actual_model_transition_cap"], time_budget=remaining)
                plan = {**receipt, "candidates": [{"inputs": point} for point in receipt["candidates"][:config["candidate_budget"]]],
                        "gate": {"status": "NO_TRANSFER_BASELINE"}}
            else:
                source = Path(packet["state_dir"]) / "development" / source_case_id(case) / f"{method.removesuffix('-frozen')}-{seed}" / "snapshot.json"
                frozen = json.loads(source.read_text(encoding="utf-8"))
                if method == "E6-frozen" and case["kind"] == "stateful":
                    from tomolab.discovery.temporal_boundary import TemporalBoundary
                    with TemporalBoundary(backend="subprocess") as generator:
                        plan = generator.request("transfer", snapshot=frozen, spec=spec,
                            temporal_contract=case["temporal_contract"], budget=config["candidate_budget"],
                            pool_size=config["pool_size"], seed=seed, target_ir=ir)
                        result["generator_boundary"] = generator.receipt
                else:
                    from tomolab.discovery.service import plan_discovery
                    plan = plan_discovery(frozen, spec, target_ir=ir, budget=config["candidate_budget"],
                                          pool_size=config["pool_size"], seed=seed, backend="subprocess", solver="z3")
            if plan.get("final_feedback_allowed") is not False:
                raise ValueError("final plan feedback must be explicitly closed")
            before = digest(plan)
            save(folder / "frozen_plan.json", plan)
            for candidate in plan["candidates"]:
                meter.predicate(candidate["inputs"])
            if digest(plan) != before:
                raise ValueError("frozen plan changed while final Oracle was running")
            result.update(plan_sha256=before, candidate_count=len(plan["candidates"]), gate=plan["gate"]["status"])
        else:
            raise ValueError("unknown phase")
    except EvaluationStop as stop:
        result.update(status="WALL_TIMEOUT" if str(stop) == "WALL_TIMEOUT" else "RESOURCE_BUDGET", stop=str(stop))
    except Exception as error:
        result.update(status="ERROR", error_type=type(error).__name__)
        save(folder / "private_error.json", {"error": type(error).__name__, "message": str(error)})
    metrics, raw = meter.metrics()
    result.update(metrics, worker_cpu_seconds=time.process_time() - cpu)
    save(folder / "raw_records.json", raw)
    save(folder / "result.json", result)


def run_worker(packet):
    import psutil
    folder = Path(packet["folder"])
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "result.json").exists():
        raise FileExistsError("existing run receipt must not be overwritten; use a fresh state directory")
    runtime = Path(packet["baseline_root"]) if packet["method"].startswith("E5") else ROOT
    runtime_before = digest(runtime_hashes(runtime))
    packet["runtime_sha256_at_launch"] = runtime_before
    packet["evaluator_sha256"] = file_sha(Path(__file__).resolve())
    packet["public_fixtures_sha256"] = file_sha(PUBLIC)
    packet["contract_sha256"] = file_sha(CONTRACT)
    packet["launched_at"] = time.perf_counter()
    save(folder / "request.json", packet)
    process = subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), "--worker", str(folder / "request.json")],
        cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    monitor = psutil.Process(process.pid)
    samples, rss, timed_out = {}, 0, False
    while process.poll() is None:
        try:
            tree = [monitor, *monitor.children(recursive=True)]
            rss = max(rss, sum(item.memory_info().rss for item in tree if item.is_running()))
            for item in tree:
                identity = (item.pid, item.create_time())
                samples[identity] = max(samples.get(identity, 0.0), sum(item.cpu_times()[:2]))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        if time.perf_counter() - packet["launched_at"] > packet["config"]["wall_cap_seconds"] + 0.5:
            timed_out = True
            try:
                for item in monitor.children(recursive=True):
                    try:
                        item.kill()
                    except psutil.NoSuchProcess:
                        pass
                process.kill()
            except psutil.NoSuchProcess:
                pass
            break
        time.sleep(0.01)
    stdout, stderr = process.communicate(timeout=5)
    wall = time.perf_counter() - packet["launched_at"]
    (folder / "worker_stdout.txt").write_bytes(stdout)
    (folder / "worker_stderr.txt").write_bytes(stderr)
    path = folder / "result.json"
    if path.exists():
        result = json.loads(path.read_text(encoding="utf-8"))
    else:
        result = {key: packet[key] for key in ("phase", "method", "case_id", "seed")}
        result["status"] = "WORKER_ERROR"
    if timed_out or wall > packet["config"]["wall_cap_seconds"]:
        result["status"] = "WALL_TIMEOUT"
    runtime_after = digest(runtime_hashes(runtime))
    result.update(runtime_sha256_at_launch=runtime_before, runtime_sha256_at_completion=runtime_after,
                  evaluator_sha256=packet["evaluator_sha256"], public_fixtures_sha256=packet["public_fixtures_sha256"],
                  contract_sha256=packet["contract_sha256"])
    if runtime_before != runtime_after:
        result["status"] = "SOURCE_DRIFT"
    result.update(wall_seconds=wall, sampled_process_tree_cpu_seconds_lower_bound=sum(samples.values()),
                  maximum_sampled_live_tree_rss_bytes=rss, resource_sampling_interval_seconds=0.01,
                  process_exit_code=process.returncode)
    save(path, result)
    return result


def freeze_state(state_dir, private_suite, baseline_root):
    state_dir, private_suite = Path(state_dir), Path(private_suite).resolve(strict=True)
    if private_suite.is_relative_to(ROOT):
        raise ValueError("private final source must remain outside the public repository")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    validate_suite(load_module(private_suite).CASES, contract)
    public = load_module(PUBLIC).CASES
    validate_suite(public, contract)
    source_molds = {}
    for case in public:
        for method in ("E5", "E6"):
            for seed in contract["seeds"]:
                folder = state_dir / "development" / case["case_id"] / f"{method}-{seed}"
                source, result = folder / "snapshot.json", folder / "result.json"
                if not source.exists() or not result.exists() or json.loads(result.read_text(encoding="utf-8"))["status"] != "COMPLETE":
                    raise ValueError("all required development source molds and complete receipts must exist")
                source_molds[source.relative_to(state_dir).as_posix()] = file_sha(source)
    manifest = {"schema": "tomolab-e6-final-freeze-v1", "product": product_hashes(),
                "baseline_root": str(Path(baseline_root).resolve()), "baseline": runtime_hashes(baseline_root),
                "private_suite_path": str(private_suite), "private_suite_sha256": file_sha(private_suite),
                "source_molds": source_molds, "contract_sha256": file_sha(CONTRACT), "final_feedback_allowed": False}
    manifest["sha256"] = digest(manifest)
    path = state_dir / "FINAL_FREEZE.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != manifest:
        raise ValueError("existing final freeze differs and must not be replaced")
    if not path.exists():
        save(path, manifest)
    return manifest


def verdict(records, contract):
    final = any(row["method"].endswith("-frozen") for row in records)
    e6 = "E6-frozen" if final else "E6"
    baselines = ["NativeHypothesis", "NativeStateful", "E5"]
    if final:
        baselines = [name + "-frozen" for name in baselines]
        expected = {(family, method, seed) for family in contract["families"] + contract["controls"]
                    for method in contract["final"]["methods"] for seed in contract["seeds"]}
        seen = [(row["family_id"], row["method"], row["seed"]) for row in records]
        if len(seen) != len(expected) or set(seen) != expected:
            return {"status": "INCONCLUSIVE", "reason": "incomplete final family/control/method/seed grid"}
        labels = {**{family: True for family in contract["families"]}, **{family: False for family in contract["controls"]}}
        if any(row.get("expected_fault") is not labels[row["family_id"]] for row in records):
            return {"status": "INCONCLUSIVE", "reason": "final family/control labels differ from preregistration"}
    if any(row["status"] in {"ERROR", "WORKER_ERROR", "WALL_TIMEOUT", "SOURCE_DRIFT"} for row in records if row["method"] != "CrossHair"):
        return {"status": "INCONCLUSIVE", "reason": "required black-box or control run failed"}
    if any(row.get("control_false_alert") for row in records if row["method"] != "CrossHair"):
        return {"status": "INCONCLUSIVE", "reason": "required black-box clean control produced a false alert"}
    by_key = {(row["family_id"], row["seed"]): row for row in records if row["method"] == e6 and row.get("expected_fault")}
    comparisons = []
    for baseline in baselines:
        paired = [(by_key[(row["family_id"], row["seed"])], row) for row in records if row["method"] == baseline
                  and row.get("expected_fault") and row["status"] != "NOT_COMPARABLE" and (row["family_id"], row["seed"]) in by_key]
        found = [(a, b) for a, b in paired if a.get("confirmed_family") and b.get("confirmed_family")]
        walls = [a["wall_seconds"] / b["wall_seconds"] for a, b in found]
        calls = [a["first_failure_primitive_invocations"] / b["first_failure_primitive_invocations"] for a, b in found
                 if b.get("first_failure_primitive_invocations")]
        comparisons.append({"baseline": baseline, "paired_runs": len(paired),
            "joint_families": len({a["family_id"] for a, b in paired}),
            "e6_detected_families": len({a["family_id"] for a, b in paired if a.get("confirmed_family")}),
            "baseline_detected_families": len({b["family_id"] for a, b in paired if b.get("confirmed_family")}),
            "no_detection_loss": all(bool(a.get("confirmed_family")) >= bool(b.get("confirmed_family")) for a, b in paired),
            "median_wall_ratio": statistics.median(walls) if walls else None,
            "median_first_primitive_call_ratio": statistics.median(calls) if calls else None})
    if any(row["joint_families"] < 3 for row in comparisons[:2]):
        return {"status": "INCONCLUSIVE", "reason": "insufficient jointly comparable stateful families", "comparisons": comparisons}
    clean = not any(row.get("control_false_alert") for row in records if row["method"] == e6)
    discovery = clean and all(row["e6_detected_families"] > row["baseline_detected_families"] for row in comparisons)
    efficiency = clean and all(row["no_detection_loss"] and row["median_wall_ratio"] is not None
        and row["median_wall_ratio"] <= 0.8 and row["median_first_primitive_call_ratio"] is not None
        and row["median_first_primitive_call_ratio"] <= 0.8 for row in comparisons)
    return {"status": "DISCOVERY_IMPROVED" if discovery else "EFFICIENCY_IMPROVED_ONLY" if efficiency else "NO_IMPROVEMENT",
            "comparisons": comparisons, "external_generalization": "NOT_EXECUTED", "scope": "bounded authored scalar EFSM software QA"}


def summarize(records):
    result = []
    for method in sorted({row["method"] for row in records}):
        rows = [row for row in records if row["method"] == method]
        complete = [row for row in rows if row["status"] == "COMPLETE"]
        failures = sum(row.get("failed_evaluations", 0) for row in rows)
        unique_failed = sum(row.get("unique_failing_inputs", 0) for row in rows)
        result.append({"method": method, "attempted_runs": len(rows), "comparable_runs": len(complete),
            "not_comparable": sum(row["status"] == "NOT_COMPARABLE" for row in rows),
            "resource_budget_runs": sum(row["status"] == "RESOURCE_BUDGET" for row in rows),
            "incomplete_runs": sum(row["status"] not in {"COMPLETE", "NOT_COMPARABLE", "RESOURCE_BUDGET"} for row in rows),
            "unique_fault_families": len({row["confirmed_family"] for row in rows if row.get("confirmed_family")}),
            "control_false_alerts": sum(bool(row.get("control_false_alert")) for row in rows),
            "actual_model_transition_calls": None if method == "CrossHair" else sum(row.get("actual_model_transition_calls", 0) for row in rows),
            "actual_target_transition_calls": None if method == "CrossHair" else sum(row.get("actual_target_transition_calls", 0) for row in rows),
            "independent_concrete_replay_invocations": sum(row.get("actual_primitive_invocations", 0) for row in rows) if method == "CrossHair" else None,
            "trace_evaluations": sum(row.get("trace_evaluations", 0) for row in rows),
            "total_wall_seconds": sum(row["wall_seconds"] for row in rows),
            "sampled_process_tree_cpu_seconds_lower_bound": sum(row.get("sampled_process_tree_cpu_seconds_lower_bound", 0) for row in rows),
            "maximum_sampled_live_tree_rss_bytes": max((row.get("maximum_sampled_live_tree_rss_bytes", 0) for row in rows), default=0),
            "failed_evaluations": failures, "unique_failing_inputs_summed_per_run": unique_failed,
            "duplicate_failure_rate": 1 - unique_failed / failures if failures else 0.0})
    return result


def run_phase(args):
    state = Path(args.state_dir).resolve()
    state.mkdir(parents=True, exist_ok=True)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if args.phase == "freeze":
        if not args.private_suite:
            raise ValueError("private final suite required")
        return freeze_state(state, args.private_suite, args.baseline_root)
    manifest = ledger = None
    suite = PUBLIC
    if args.phase == "final":
        if args.case:
            raise ValueError("partial final --case selection is forbidden")
        manifest = json.loads((state / "FINAL_FREEZE.json").read_text(encoding="utf-8"))
        if Path(args.baseline_root).resolve() != Path(manifest["baseline_root"]).resolve():
            raise ValueError("final baseline root must match the frozen baseline runtime")
        verify_freeze(state, manifest)
        suite = Path(manifest["private_suite_path"])
        ledger = consume_final_once(state, manifest)
    module = load_module(suite)
    if manifest:
        validate_suite(module.CASES, contract)
    cases = [case for case in module.CASES if not args.case or case["case_id"] == args.case]
    if not cases:
        raise ValueError("no cases selected")
    config = contract["final" if manifest else "development"]
    records = []
    methods = config["methods"] if args.phase != "audit" else ["E6"]
    for case in cases:
        if args.phase == "audit" and case["kind"] != "stateful":
            continue
        for method in methods:
            seeds = contract["seeds"] if method != "CrossHair" and args.phase != "audit" else [contract["seeds"][0]]
            for seed in seeds:
                if manifest:
                    verify_freeze(state, manifest)
                packet = {"phase": args.phase, "method": method, "seed": seed, "case_id": case["case_id"],
                    "suite": str(suite), "state_dir": str(state),
                    "baseline_root": manifest["baseline_root"] if manifest else str(args.baseline_root), "config": config,
                    "folder": str(state / args.phase / case["case_id"] / f"{method}-{seed}")}
                records.append(run_worker(packet))
                print(canonical({key: records[-1].get(key) for key in ("phase", "case_id", "method", "seed", "status")}), flush=True)
    if manifest:
        validate_grid(records, module.CASES, methods, contract["seeds"])
        verify_freeze(state, manifest)
        with ledger.open("a", encoding="utf-8") as stream:
            stream.write(canonical({"event": "FINAL_ATTEMPT_COMPLETED", "records_sha256": digest(records), "time_unix": time.time()}) + "\n")
    report = {"schema": "tomolab-e6-comparison-v1", "phase": args.phase, "contract_sha256": file_sha(CONTRACT),
        "freeze_sha256": manifest["sha256"] if manifest else None, "generator_final_feedback_calls": 0 if manifest else None,
        "external_generalization": "NOT_EXECUTED", "records": records, "summary": summarize(records),
        "verdict": verdict(records, contract) if args.phase != "audit" else None,
        "boundary": "LOGICAL_ISOLATION_ONLY; trusted evaluator callbacks are not sandboxed"}
    if args.output:
        save(args.output, report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--phase", choices=("development", "audit", "freeze", "final"), default="development")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--baseline-root", type=Path, default=ROOT.parent / "e5-repo")
    parser.add_argument("--private-suite", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case")
    parser.add_argument("--allow-local-execution", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(json.loads(args.worker.read_text(encoding="utf-8")))
        return
    if not args.allow_local_execution:
        parser.error("explicit trusted local execution is required")
    if args.state_dir is None or args.state_dir.resolve().is_relative_to(ROOT):
        parser.error("raw evaluation state must be outside the public repository")
    if not args.baseline_root.is_dir():
        parser.error("read-only E5 baseline runtime directory is required")
    report = run_phase(args)
    print(json.dumps({key: report[key] for key in ("schema", "phase", "summary", "verdict", "sha256") if key in report}, indent=2))


if __name__ == "__main__":
    main()
