"""Preregistered E5 software QA comparison and once-only frozen evaluation.

All targets are caller-trusted user-owned code. This evaluator is not a security
sandbox. A final suite is kept outside the repository and its labels never go
back to the generator. Public development reproductions are not blind results.
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
import textwrap
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CONTRACT = ROOT / "docs/E5_EVALUATION_CONTRACT.json"
PUBLIC_CASES = ROOT / "benchmarks/e5_public_cases.py"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def load_module(path):
    path = Path(path).resolve(strict=True)
    spec = importlib.util.spec_from_file_location("e5_evaluation_" + file_sha(path), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepared_case(case):
    from tomolab.discovery.analysis import analyze_source
    from tomolab.discovery.schema import validate_spec
    roles = {name: role for name, role, _ in case["inputs"]}
    # This is the predeclared public reference skeleton, never hidden target code.
    ir = analyze_source(case["public_model"], case["public_model_function"], roles)
    spec = {"schema": "tomolab-discovery-spec-v1", "task_id": case["case_id"],
            "inputs": [{"name": name, "role": role, "type": deepcopy(type_)} for name, role, type_ in case["inputs"]],
            "contract": {"id": case["family_id"] + "-v1", "operation": case["operation"],
                         "preconditions": [], "invariants": ["reference-equivalence"],
                         "state_model": "bounded-trace" if case["category"] == "state_violation" else "stateless",
                         "graph_signature": ir["graph_signature"]}}
    return validate_spec(spec), ir


def e4_spec(case):
    from tomolab.mold.schema import default_spec
    if not case["e4_eligible"]:
        raise ValueError("outside E4 two-integer contract")
    spec = default_spec(case["case_id"], -16, 16)
    for item, declared in zip(spec["variables"], case["inputs"]):
        item["name"], item["role"] = declared[0], declared[1]
    spec["invariant"] = "reference-equivalence"
    spec["semantic_contract"] = "public-addition-v1"
    return spec


class EvaluationBudgetStop(BaseException):
    pass


class Meter:
    """Independent actual-call meter; no cache or invented target calls."""
    def __init__(self, case, spec, cap, started, deadline):
        self.case, self.spec, self.cap = case, spec, cap
        self.started, self.deadline = started, deadline
        self.oracle_calls = self.target_calls = self.transition_steps = 0
        self.rows, self.expected = [], {}

    def point(self, args, kwargs):
        from tomolab.discovery.schema import validate_inputs
        names = [item["name"] for item in self.spec["inputs"]]
        values = kwargs if kwargs else dict(zip(names, args))
        if args and len(args) != len(names):
            raise ValueError("evaluation adapter arity mismatch")
        return validate_inputs(values, self.spec)

    def invoke(self, function, point):
        from tomolab.discovery.schema import decode_inputs
        values = decode_inputs(point, self.spec)
        return function(*(deepcopy(values[item["name"]]) for item in self.spec["inputs"]))

    @staticmethod
    def outcome(function):
        try:
            return {"kind": "return", "value": function()}
        except Exception as error:
            return {"kind": "exception", "type": type(error).__name__}

    def oracle(self, *args, **kwargs):
        if time.perf_counter() >= self.deadline:
            raise EvaluationBudgetStop("WALL_TIMEOUT")
        if self.oracle_calls >= self.cap:
            raise EvaluationBudgetStop("ORACLE_BUDGET")
        point = self.point(args, kwargs)
        self.oracle_calls += 1
        if "trace" in point:
            self.transition_steps += len(point["trace"])
        result = self.outcome(lambda: self.invoke(self.case["oracle"], point))
        self.expected[canonical(point)] = result
        if result["kind"] == "exception":
            # The benchmark fixtures currently have no valid-domain exceptions;
            # retain the category rather than silently changing the property.
            raise RuntimeError("reference raised " + result["type"])
        return result["value"]

    def target(self, *args, **kwargs):
        point = self.point(args, kwargs)
        self.target_calls += 1
        observed = self.outcome(lambda: self.invoke(self.case["target"], point))
        expected = self.expected.get(canonical(point))
        if expected is None:
            raise ValueError("target called without independently metered reference")
        failed = canonical(observed) != canonical(expected)
        self.rows.append({"oracle_call": self.oracle_calls, "inputs": point, "failed": failed,
                          "elapsed_seconds": time.perf_counter() - self.started,
                          "signature": self.case["category"]})
        if observed["kind"] == "exception":
            raise RuntimeError("target raised " + observed["type"])
        return observed["value"]

    def predicate(self, point):
        self.oracle(**point)
        self.target(**point)
        return self.rows[-1]["failed"]

    def metrics(self):
        failures = [row for row in self.rows if row["failed"]]
        unique = {canonical(row["inputs"]) for row in self.rows}
        failed_unique = {canonical(row["inputs"]) + ":" + row["signature"] for row in failures}
        return {"oracle_calls": self.oracle_calls, "target_calls": self.target_calls,
                "unique_evaluated_inputs": len(unique), "failed_evaluations": len(failures),
                "unique_failing_inputs": len(failed_unique),
                "duplicate_failure_rate": 1 - len(failed_unique) / len(failures) if failures else 0.0,
                "first_failure_oracle_calls": failures[0]["oracle_call"] if failures else None,
                "first_failure_wall_seconds": failures[0]["elapsed_seconds"] if failures else None,
                "transition_steps": self.transition_steps,
                "confirmed_family": self.case["family_id"] if failures else None,
                "control_false_alert": bool(failures and not self.case["expected_fault"])}


def _precondition(type_, name, depth=0):
    kind = type_["kind"]
    if kind in ("int", "float"):
        return f"({type_['min']!r} <= {name} <= {type_['max']!r})"
    if kind == "str":
        if "choices" in type_:
            return f"({name} in {type_['choices']!r})"
        return f"({type_['min_size']} <= len({name}) <= {type_['max_size']} and all(ch in {type_['alphabet']!r} for ch in {name}))"
    if kind == "tuple":
        return "(" + " and ".join(_precondition(child, f"{name}[{i}]", depth+1) for i, child in enumerate(type_["items"])) + ")"
    if kind == "list":
        var = "element" + str(depth)
        return f"({type_['min_size']} <= len({name}) <= {type_['max_size']} and all({_precondition(type_['items'], var, depth+1)} for {var} in {name}))"
    raise ValueError("CrossHair fixture type not in declared comparison stratum")


def _annotation(type_):
    kind = type_["kind"]
    if kind == "list":
        return "list[" + _annotation(type_["items"]) + "]"
    if kind == "tuple":
        return "tuple[" + ", ".join(_annotation(item) for item in type_["items"]) + "]"
    if kind in ("int", "float", "str"):
        return kind
    raise ValueError("CrossHair fixture annotation unsupported")


def run_crosshair(case, folder, remaining, meter):
    from tomolab.discovery.symbolic import check_contract
    target = textwrap.dedent(inspect.getsource(case["target"]))
    oracle = textwrap.dedent(inspect.getsource(case["oracle"]))
    names = [name for name, _, _ in case["inputs"]]
    signature = ", ".join(name + ": " + _annotation(type_) for name, _, type_ in case["inputs"])
    arguments = ", ".join(names)
    pre = " and ".join(_precondition(type_, name) for name, _, type_ in case["inputs"])
    source = ("from __future__ import annotations\n\n" + target + "\n\n" + oracle + "\n\n"
              + f"def obligation({signature}):\n"
              + '    """\n' + "    pre: " + pre + "\n"
              + "    post: _ == " + case["oracle"].__name__ + "(" + arguments + ")\n"
              + '    """\n' + "    return " + case["target"].__name__ + "(" + arguments + ")\n")
    path = Path(folder) / "trusted_crosshair_contract.py"
    path.write_text(source, encoding="utf-8")
    receipt = check_contract(path, "obligation", timeout_seconds=max(0.1, remaining - 0.2),
                             per_condition_seconds=min(6.0, max(0.01, remaining - 0.3)), trusted_execution=True)
    for point in receipt["candidates"]:
        try:
            meter.predicate(point)
        except (ValueError, TypeError):
            continue
    return {"tool_status": receipt["status"], "source_access": True,
            "internal_symbolic_oracle_calls": None, "diagnostics_count": len(receipt["diagnostics"]),
            "candidate_count": len(receipt["candidates"]), "tool_version": receipt["tool_version"]}


def _source_case_id(case):
    module = load_module(PUBLIC_CASES)
    return next(row["case_id"] for row in module.CASES if row["family_id"] == case["family_id"])


def audit_constraints(snapshot, case, spec, meter, seed):
    from tomolab.discovery.features import holds, measurements
    from tomolab.discovery.hypothesis_adapter import generate_pool
    from tomolab.discovery.predicates import predicate_holds
    identifiers = sorted({rid for group in snapshot["groups"].values() for rid in group["remaining"]})
    selected = identifiers[:128]
    points = generate_pool(spec, seed=seed + 65537, size=64)
    truths = [(point, meter.predicate(point)) for point in points]
    contradicted = []
    unsupported = []
    for rid in selected:
        relation = snapshot["relations"][rid]
        wrong = False
        try:
            for point, label in truths:
                prediction = (predicate_holds(relation["term"]["expression"], point, spec)
                              if relation["term"]["kind"] == "ast"
                              else holds(relation, measurements(point, spec)))
                wrong |= prediction != label
        except (ValueError, TypeError, KeyError):
            unsupported.append(rid)
            continue
        if wrong:
            contradicted.append(rid)
    evaluated = len(selected) - len(unsupported)
    return {"source_candidate_hypotheses": len(identifiers), "checked_hypotheses": evaluated,
            "unsupported_hypotheses": len(unsupported), "validation_inputs": len(points),
            "contradicted_candidate_hypotheses": len(contradicted),
            "contradicted_candidate_rate": len(contradicted) / evaluated if evaluated else None,
            "scope": "bounded first-128-canonical-ID membership candidates; not proved causal laws",
            "feedback_to_generator": 0}


def _widen(type_):
    changed = deepcopy(type_)
    if changed["kind"] in ("int", "float"):
        changed["max"] += 1
    elif changed["kind"] == "str":
        changed["alphabet"] += "Z"
        if "choices" in changed:
            changed["choices"].append("Z" * max(1, changed["min_size"]))
    elif changed["kind"] in ("list", "dict"):
        changed["max_size"] += 1
    else:
        changed["items"][0] = _widen(changed["items"][0])
    return changed


def audit_transfer(snapshot, spec, ir, meter, seed):
    from tomolab.discovery.engine import transfer
    from tomolab.discovery.features import transferable
    supported = any(transferable(snapshot["relations"][rid]) for group in snapshot["groups"].values() for rid in group["remaining"])
    targets = [("same-contract", deepcopy(spec), bool(supported))]
    domain = deepcopy(spec)
    domain["inputs"][0]["type"] = _widen(domain["inputs"][0]["type"])
    targets.append(("expanded-domain", domain, False))
    roles = deepcopy(spec)
    roles["inputs"][0]["role"] += "-wrong"
    targets.append(("role-mismatch", roles, False))
    contract = deepcopy(spec)
    contract["contract"]["preconditions"].append("different-precondition")
    targets.append(("precondition-mismatch", contract, False))
    checks = []
    for name, target, expected in targets:
        target["task_id"] += ":gate:" + name
        try:
            receipt = transfer(snapshot, target, target_ir=ir, budget=1, pool_size=128, seed=seed)
            gate = receipt["gate"]["status"]
            accepted = gate == "APPLICABLE_FOR_PROBING"
        except ValueError:
            if expected:
                raise
            # A deliberately incompatible declaration can fail validation before
            # a gate receipt exists. This is an explicit, correct rejection.
            gate, accepted = "DECLARATION_REJECTED", False
        checks.append({"case": name, "expected_applicable": expected, "actual_applicable": accepted,
                       "correct": accepted == expected, "gate": gate})
    # An actually checked clean development implementation can refute a source
    # failure's recurrence. Never invent or flip a target truth label.
    failures = [event for event in snapshot["evidence"] if event["kind"] == "FAILURE"]
    counterevidence = None
    if failures and "target_evidence" in inspect.signature(transfer).parameters:
        clean_case = dict(meter.case, target=lambda *values: meter.case["oracle"](*values))
        clean_meter = Meter(clean_case, spec, 1, meter.started, meter.deadline)
        event = deepcopy(failures[0])
        assert clean_meter.predicate(event["inputs"]) is False
        meter.oracle_calls += clean_meter.oracle_calls
        meter.target_calls += clean_meter.target_calls
        meter.transition_steps += clean_meter.transition_steps
        meter.rows.extend(clean_meter.rows)
        event.update(kind="REFUTATION", evidence_id="checked-clean-target-0")
        receipt = transfer(snapshot, spec, target_ir=ir, budget=1, pool_size=128, seed=seed, target_evidence=[event])
        from tomolab.discovery.features import holds, measurements
        from tomolab.discovery.predicates import predicate_holds
        expected_ids = set()
        for group in snapshot["groups"].values():
            if group["invariant"] != event["invariant"]:
                continue
            for rid in group["remaining"]:
                relation = snapshot["relations"][rid]
                if not transferable(relation):
                    continue
                active = predicate_holds(relation["term"]["expression"], event["inputs"], spec) if relation["term"]["kind"] == "ast" else holds(relation, measurements(event["inputs"], spec))
                if active:
                    expected_ids.add(rid)
        actual_ids = {item["constraint_id"] for item in receipt["gate"]["target_contradictions"]
                      if item["reason"] == "target-development-counterexample"}
        counterevidence = {"expected_removed_constraints": len(expected_ids), "actual_removed_constraints": len(actual_ids),
                           "filter_correct": expected_ids == actual_ids,
                           "gate": receipt["gate"]["status"], "failure_recurrence": receipt["gate"]["failure_recurrence"],
                           "meaning": "one checked clean input refutes active constraints, not every source hypothesis"}
    return {"checks": checks, "correct": sum(row["correct"] for row in checks), "checked": len(checks),
            "accuracy": sum(row["correct"] for row in checks) / len(checks),
            "checked_development_counterevidence": counterevidence,
            "meaning": "typed correspondence and checked development contradiction; not target-bug precision"}


def worker(packet):
    module = load_module(packet["suite"])
    case = module.case_by_id(packet["case_id"])
    spec, ir = prepared_case(case)
    phase, method, seed = packet["phase"], packet["method"], packet["seed"]
    started = packet["launched_at"]
    deadline = started + packet["wall_cap"]
    meter = Meter(case, spec, packet["call_cap"], started, deadline)
    folder = Path(packet["folder"])
    folder.mkdir(parents=True, exist_ok=True)
    result = {"method": method, "phase": phase, "case_id": case["case_id"], "family_id": case["family_id"],
              "expected_fault": case["expected_fault"], "seed": seed, "origin": case["origin"],
              "status": "COMPLETE", "source_access": method == "CrossHair",
              "final_feedback_calls": 0 if phase == "final" else None}
    cpu_started = time.process_time()
    try:
        remaining = max(0.05, deadline - time.perf_counter())
        if method.startswith("E4") and not case["e4_eligible"]:
            result.update(status="NOT_COMPARABLE", reason="outside E4 two-integer contract")
        elif phase == "development":
            if method == "E4":
                from tomolab.mold.property_testing import run_properties
                receipt = run_properties(meter.target, meter.oracle, e4_spec(case), budget=64, shrink_budget=62,
                                         max_examples=128, seed=seed, trusted_execution=True)
            elif method == "Hypothesis":
                from tomolab.discovery.hypothesis_adapter import native_find
                options = {"cache": True} if "cache" in inspect.signature(native_find).parameters else {}
                receipt = native_find(spec, meter.predicate, budget=128, seed=seed, time_budget=remaining, **options)
            elif method == "CrossHair":
                receipt = run_crosshair(case, folder, remaining, meter)
            elif method == "E5":
                from tomolab.discovery.service import run_discovery
                receipt = run_discovery(meter.target, meter.oracle, spec, public_ir=ir, budget=64,
                                        shrink_budget=62, pool_size=128, seed=seed, solver="z3",
                                        backend="subprocess", trusted_execution=True, time_budget=remaining)
            else:
                raise ValueError("unknown comparison method")
            if "snapshot" in receipt:
                save(folder / "snapshot.json", receipt["snapshot"])
                result["snapshot_sha256"] = digest(receipt["snapshot"])
            # Keep actual algorithm receipts private, with a comparable public
            # metrics subset. Oracle accounting still comes from our own meter.
            save(folder / "algorithm_receipt.json", receipt)
            result["algorithm_metrics"] = receipt.get("metrics", {key: receipt[key] for key in
                ("hypothesis_attempts", "cache_hits", "cache_enabled", "unique_inputs") if key in receipt})
            if receipt.get("timing"):
                result["algorithm_timing"] = receipt["timing"]
            result["algorithm_status"] = receipt.get("status", receipt.get("tool_status"))
            if method == "CrossHair":
                result.update(receipt)
            elif "shrinking" in receipt:
                result["shrinking"] = receipt["shrinking"]
            elif "shrink" in receipt:
                result["shrinking"] = receipt["shrink"].get("status")
        elif phase in ("constraint-audit", "gate-audit"):
            source_path = Path(packet["state_dir"]) / "development" / case["case_id"] / f"E5-{seed}" / "snapshot.json"
            snapshot = json.loads(source_path.read_text(encoding="utf-8"))
            before = digest(snapshot)
            result["audit"] = (audit_constraints(snapshot, case, spec, meter, seed) if phase == "constraint-audit"
                               else audit_transfer(snapshot, spec, ir, meter, seed))
            if digest(snapshot) != before:
                raise ValueError("independent development audit mutated the frozen mold")
        elif phase == "final":
            source_case = _source_case_id(case)
            if method == "E4-frozen":
                from tomolab.mold.service import plan_mold
                source_path = Path(packet["state_dir"]) / "development" / source_case / f"E4-{seed}" / "snapshot.json"
                source = json.loads(source_path.read_text(encoding="utf-8"))
                plan = plan_mold(source, e4_spec(case), budget=64, seed=seed, backend="subprocess")
            elif method == "Hypothesis-strategy-plan":
                from tomolab.discovery.hypothesis_adapter import generate_pool
                plan = {"candidates": [{"inputs": point} for point in generate_pool(spec, seed=seed, size=64)],
                        "final_feedback_allowed": False, "gate": {"status": "NO_TRANSFER_BASELINE"}}
            elif method == "E5-frozen":
                from tomolab.discovery.service import plan_discovery
                source_path = Path(packet["state_dir"]) / "development" / source_case / f"E5-{seed}" / "snapshot.json"
                source = json.loads(source_path.read_text(encoding="utf-8"))
                plan = plan_discovery(source, spec, target_ir=ir, budget=64, seed=seed, pool_size=128,
                                      backend="subprocess", solver="z3")
            else:
                raise ValueError("unknown frozen method")
            if plan.get("final_feedback_allowed") is not False:
                raise ValueError("final feedback boundary not explicitly closed")
            before = digest(plan)
            save(folder / "frozen_plan.json", plan)
            for candidate in plan["candidates"]:
                meter.predicate(candidate["inputs"])
            if digest(plan) != before:
                raise ValueError("frozen plan changed during final evaluation")
            result.update(plan_sha256=before, gate=plan["gate"]["status"],
                          candidate_count=len(plan["candidates"]),
                          duplicate_candidates=len(plan["candidates"])-len({canonical(p["inputs"]) for p in plan["candidates"]}))
        else:
            raise ValueError("unknown worker phase")
    except EvaluationBudgetStop as stop:
        result["status"] = "WALL_TIMEOUT" if str(stop) == "WALL_TIMEOUT" else "RESOURCE_BUDGET"
    except Exception as error:
        result.update(status="ERROR", error_type=type(error).__name__)
        # Error messages can contain private paths: keep them only in raw state.
        save(folder / "private_error.json", {"error": type(error).__name__, "message": str(error)})
    result.update(meter.metrics())
    result["worker_cpu_seconds"] = time.process_time() - cpu_started
    result["worker_completed_at"] = time.perf_counter()
    save(folder / "raw_records.json", meter.rows)
    save(folder / "result.json", result)


def run_worker(packet):
    import psutil
    folder = Path(packet["folder"])
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "result.json").exists():
        raise FileExistsError("evaluation result already exists; use a fresh state directory")
    packet["launched_at"] = time.perf_counter()
    save(folder / "request.json", packet)
    environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", str(folder / "request.json")],
                               cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    peak_rss = descendant_cpu = 0.0
    sampled_cpu = {}
    monitor = psutil.Process(process.pid)
    timed_out = False
    while process.poll() is None:
        try:
            children = monitor.children(recursive=True)
            live = [p for p in [monitor, *children] if p.is_running()]
            peak_rss = max(peak_rss, sum(p.memory_info().rss for p in live))
            descendant_cpu = max(descendant_cpu, sum(sum(p.cpu_times()[:2]) for p in children if p.is_running()))
            for observed in live:
                identity = (observed.pid, observed.create_time())
                sampled_cpu[identity] = max(sampled_cpu.get(identity, 0.0), sum(observed.cpu_times()[:2]))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        if time.perf_counter() - packet["launched_at"] > packet["wall_cap"] + 0.5:
            timed_out = True
            for child in monitor.children(recursive=True):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            process.kill()
            break
        time.sleep(0.01)
    stdout, stderr = process.communicate(timeout=5)
    wall = time.perf_counter() - packet["launched_at"]
    (folder / "worker_stdout.txt").write_bytes(stdout)
    (folder / "worker_stderr.txt").write_bytes(stderr)
    result_path = folder / "result.json"
    if result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        result = {"method": packet["method"], "phase": packet["phase"], "case_id": packet["case_id"],
                  "seed": packet["seed"], "status": "WALL_TIMEOUT" if timed_out else "WORKER_ERROR"}
    if timed_out or wall > packet["wall_cap"]:
        result["status"] = "WALL_TIMEOUT"
    result.update(wall_seconds=wall, sampled_peak_rss_bytes=int(peak_rss),
                  sampled_descendant_cpu_seconds_lower_bound=descendant_cpu,
                  sampled_process_tree_cpu_seconds_lower_bound=sum(sampled_cpu.values()),
                  resource_sampling_interval_seconds=0.01,
                  resource_accounting="PER_PROCESS_IDENTITY_LAST_CPU_SAMPLES_SUMMED; WORKER_CPU_NOT_ADDED_AGAIN; RSS_LIVE_TREE_SAMPLED",
                  process_exit_code=process.returncode)
    save(result_path, result)
    return result


def product_hashes():
    paths = [*sorted((ROOT / "tomolab").rglob("*.py")), Path(__file__).resolve(), PUBLIC_CASES, CONTRACT, ROOT / "pyproject.toml"]
    return {p.relative_to(ROOT).as_posix(): file_sha(p) for p in paths}


def validate_final_suite(cases, contract):
    config = contract["tracks"]["frozen_final_transfer"]
    expected = {**{family: True for family in config["final_case_families"]},
                **{family: False for family in config["controls"]}}
    if len(cases) != len(expected) or len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError("final suite must include every family and control exactly once")
    observed = {}
    for case in cases:
        family = case["family_id"]
        if family in observed or family not in expected or case["expected_fault"] is not expected[family]:
            raise ValueError("final family/control selection differs from preregistered contract")
        observed[family] = case["expected_fault"]
    if observed != expected:
        raise ValueError("final suite is missing a preregistered family or control")


def validate_final_records(records, cases, methods, seeds):
    expected = {(case["case_id"], method, seed) for case in cases for method in methods for seed in seeds}
    observed = [(row["case_id"], row["method"], row["seed"]) for row in records]
    if len(observed) != len(expected) or set(observed) != expected:
        raise ValueError("final method/seed/case records are incomplete or duplicated")


def freeze_state(state_dir, private_suite):
    state_dir, private_suite = Path(state_dir), Path(private_suite).resolve(strict=True)
    if private_suite.is_relative_to(ROOT):
        raise ValueError("private final suite must remain outside public repository")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    final_cases = load_module(private_suite).CASES
    validate_final_suite(final_cases, contract)
    public_cases = load_module(PUBLIC_CASES).CASES
    snapshots = []
    for case in public_cases:
        for method in (["E4", "E5"] if case["e4_eligible"] else ["E5"]):
            for seed in contract["tracks"]["frozen_final_transfer"]["seeds"]:
                folder = state_dir / "development" / case["case_id"] / f"{method}-{seed}"
                snapshot, result = folder / "snapshot.json", folder / "result.json"
                if not snapshot.exists() or not result.exists() or json.loads(result.read_text(encoding="utf-8")).get("status") != "COMPLETE":
                    raise ValueError("run all required public development cases/seeds; frozen source mold is missing")
                snapshots.append(snapshot)
    manifest = {"schema": "tomolab-e5-final-freeze-v1", "product": product_hashes(),
                "private_suite_sha256": file_sha(private_suite), "private_suite_path": str(private_suite),
                "source_molds": {p.relative_to(state_dir).as_posix(): file_sha(p) for p in snapshots},
                "contract_sha256": file_sha(CONTRACT), "final_feedback_allowed": False}
    manifest["sha256"] = digest(manifest)
    path = state_dir / "FINAL_FREEZE.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("existing freeze differs; do not replace a consumed final contract")
    else:
        save(path, manifest)
    return manifest


def verify_freeze(state_dir, manifest):
    raw = {k: v for k, v in manifest.items() if k != "sha256"}
    if digest(raw) != manifest["sha256"] or product_hashes() != manifest["product"]:
        raise ValueError("product or evaluation freeze drifted")
    if file_sha(manifest["private_suite_path"]) != manifest["private_suite_sha256"]:
        raise ValueError("private final source drifted")
    for name, expected in manifest["source_molds"].items():
        if file_sha(Path(state_dir) / name) != expected:
            raise ValueError("source mold drifted")


def consume_final_once(state_dir, manifest):
    path = Path(state_dir) / ("final-consumed-" + manifest["private_suite_sha256"] + ".jsonl")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical({"event": "FINAL_ATTEMPT_STARTED", "freeze": manifest["sha256"],
                                "time_unix": time.time()}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def verdict(records):
    """Descriptive bounded efficiency; no real-world generalization claim."""
    comparable = [r for r in records if r.get("expected_fault") and r.get("status") != "NOT_COMPARABLE"]
    if any(r.get("status") in {"ERROR", "WORKER_ERROR", "WALL_TIMEOUT"} for r in records
           if r["method"] != "CrossHair"):
        return {"status": "INCONCLUSIVE", "reason": "required black-box run did not complete"}
    e5_name = "E5-frozen" if any(r["method"] == "E5-frozen" for r in records) else "E5"
    hyp_name = "Hypothesis-strategy-plan" if e5_name.endswith("frozen") else "Hypothesis"
    if e5_name == "E5-frozen":
        config = json.loads(CONTRACT.read_text(encoding="utf-8"))["tracks"]["frozen_final_transfer"]
        families = {**{family: True for family in config["final_case_families"]},
                    **{family: False for family in config["controls"]}}
        expected = {(family, method, seed) for family in families for method in config["methods"] for seed in config["seeds"]}
        observed = [(row["family_id"], row["method"], row["seed"]) for row in records]
        if len(observed) != len(expected) or set(observed) != expected or any(
                row.get("expected_fault") is not families.get(row["family_id"]) for row in records):
            return {"status": "INCONCLUSIVE", "reason": "preregistered final families, controls, methods or seeds are incomplete"}
    comparisons = []
    e5 = {(r["family_id"], r["seed"]): r for r in comparable if r["method"] == e5_name}
    for baseline in (hyp_name, "E4-frozen" if e5_name.endswith("frozen") else "E4"):
        paired = [(e5[(r["family_id"], r["seed"])], r) for r in comparable
                  if r["method"] == baseline and (r["family_id"], r["seed"]) in e5]
        jointly_found = [(a, b) for a, b in paired if a.get("confirmed_family") and b.get("confirmed_family")]
        no_detection_loss = all(bool(a.get("confirmed_family")) >= bool(b.get("confirmed_family")) for a, b in paired)
        wall_ratios = [a["wall_seconds"] / b["wall_seconds"] for a, b in jointly_found if b["wall_seconds"] > 0]
        call_ratios = [a["first_failure_oracle_calls"] / b["first_failure_oracle_calls"] for a, b in jointly_found
                       if b.get("first_failure_oracle_calls")]
        comparisons.append({"baseline": baseline, "paired_runs": len(paired),
                            "joint_families": len({a["family_id"] for a, b in paired}),
                            "no_detection_loss": no_detection_loss,
                            "median_wall_ratio": statistics.median(wall_ratios) if wall_ratios else None,
                            "median_first_call_ratio": statistics.median(call_ratios) if call_ratios else None})
    primary = next(row for row in comparisons if row["baseline"] == hyp_name)
    if primary["joint_families"] < 3:
        return {"status": "INCONCLUSIVE", "reason": "fewer than three primary jointly comparable families", "comparisons": comparisons}
    false_alert = any(r.get("control_false_alert") for r in records if r["method"] == e5_name)
    improved = not false_alert and all(row["no_detection_loss"] and row["median_wall_ratio"] is not None
                                      and row["median_wall_ratio"] <= 0.80 and row["median_first_call_ratio"] <= 0.80
                                      for row in comparisons if row["paired_runs"])
    return {"status": "EFFICIENCY_IMPROVED_ONLY" if improved else "NO_IMPROVEMENT",
            "comparisons": comparisons, "generalization": "NOT_EXECUTED",
            "scope": "descriptive bounded synthetic/user-owned-control software QA"}


def summary(records):
    by_method = []
    for method in sorted({r["method"] for r in records}):
        rows = [r for r in records if r["method"] == method]
        by_method.append({"method": method, "runs": len(rows),
                          "comparable_runs": sum(r.get("status") != "NOT_COMPARABLE" for r in rows),
                          "confirmed_unique_fault_families": len({r["confirmed_family"] for r in rows if r.get("confirmed_family") and r.get("expected_fault")}),
                          "control_false_alerts": sum(bool(r.get("control_false_alert")) for r in rows),
                          "oracle_calls": None if method == "CrossHair" else sum(r.get("oracle_calls", 0) for r in rows),
                          "independent_concrete_replay_calls": sum(r.get("oracle_calls", 0) for r in rows) if method == "CrossHair" else None,
                          "wall_seconds": sum(r["wall_seconds"] for r in rows),
                          "not_comparable": sum(r.get("status") == "NOT_COMPARABLE" for r in rows),
                          "incomplete_runs": sum(r.get("status") not in {"COMPLETE", "NOT_COMPARABLE", "RESOURCE_BUDGET"} for r in rows)})
    return by_method


def run_phase(args):
    state_dir = Path(args.state_dir).resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if args.phase == "freeze":
        if not args.private_suite:
            raise ValueError("--private-suite required")
        return freeze_state(state_dir, args.private_suite)
    ledger = manifest = None
    if args.phase == "final":
        if args.case:
            raise ValueError("final phase forbids partial --case selection")
        manifest = json.loads((state_dir / "FINAL_FREEZE.json").read_text(encoding="utf-8"))
        verify_freeze(state_dir, manifest)
        ledger = consume_final_once(state_dir, manifest)
        suite = manifest["private_suite_path"]
        methods = contract["tracks"]["frozen_final_transfer"]["methods"]
        config = contract["tracks"]["frozen_final_transfer"]
    else:
        suite = str(PUBLIC_CASES)
        methods = contract["tracks"]["development_search"]["methods"]
        config = contract["tracks"]["development_search"]
    module = load_module(suite)
    if manifest:
        validate_final_suite(module.CASES, contract)
    selected = [case for case in module.CASES if not args.case or case["case_id"] == args.case]
    if not selected:
        raise ValueError("no case selected")
    records = []
    for case in selected:
        for method in methods:
            for seed in config["seeds"] if method != "CrossHair" else [config["seeds"][0]]:
                if manifest:
                    verify_freeze(state_dir, manifest)
                folder = state_dir / args.phase / case["case_id"] / f"{method}-{seed}"
                packet = {"suite": str(suite), "case_id": case["case_id"], "method": method, "seed": seed,
                          "phase": args.phase, "folder": str(folder), "state_dir": str(state_dir),
                          "call_cap": config["oracle_call_cap"], "wall_cap": config["total_wall_cap_seconds"]}
                records.append(run_worker(packet))
                print(canonical({"phase": args.phase, "case": case["case_id"], "method": method,
                                 "seed": seed, "status": records[-1]["status"]}), flush=True)
    audits = []
    if not manifest:
        for case in selected:
            seed = config["seeds"][0]
            source = state_dir / "development" / case["case_id"] / f"E5-{seed}" / "snapshot.json"
            if source.exists():
                for phase in ("constraint-audit", "gate-audit"):
                    packet = {"suite": str(PUBLIC_CASES), "case_id": case["case_id"], "method": "E5-audit", "seed": seed,
                              "phase": phase, "folder": str(state_dir / phase / case["case_id"]), "state_dir": str(state_dir),
                              "call_cap": 64, "wall_cap": config["total_wall_cap_seconds"]}
                    audits.append(run_worker(packet))
    if manifest:
        validate_final_records(records, module.CASES, methods, config["seeds"])
        verify_freeze(state_dir, manifest)
        with ledger.open("a", encoding="utf-8") as stream:
            stream.write(canonical({"event": "FINAL_ATTEMPT_COMPLETED", "records_sha256": digest(records), "time_unix": time.time()}) + "\n")
    report = {"schema": "tomolab-e5-comparison-v1", "phase": args.phase,
              "contract_sha256": file_sha(CONTRACT), "old_holdouts_reused": False,
              "fixture_scope": "NEW_AUTHORED_MUTATIONS_AND_EXISTING_USER_PROJECT_CONTROLS",
              "external_real_project_generalization": "NOT_EXECUTED",
              "generator_final_feedback_calls": 0 if manifest else None,
              "information_boundary": "LOGICAL_ONLY_LOCAL_SUBPROCESS; CONTAINER_ACCESS_CONTROL_VERIFIED_SEPARATELY_IN_CI",
              "freeze_sha256": manifest["sha256"] if manifest else None,
              "summary": summary(records), "verdict": verdict(records), "records": records,
              "independent_development_audits": audits}
    if args.output:
        save(args.output, report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--phase", choices=("development", "freeze", "final"), default="development")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--private-suite", type=Path)
    parser.add_argument("--case")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-local-execution", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(json.loads(args.worker.read_text(encoding="utf-8")))
        return
    if not args.allow_local_execution:
        parser.error("requires --allow-local-execution; all targets must be trusted")
    if args.state_dir is None:
        parser.error("--state-dir outside the repository is required")
    if args.state_dir.resolve().is_relative_to(ROOT):
        parser.error("raw evaluation state must remain outside public repository")
    report = run_phase(args)
    print(json.dumps({k: report[k] for k in ("schema", "phase", "summary", "verdict") if k in report}, indent=2))


if __name__ == "__main__":
    main()
