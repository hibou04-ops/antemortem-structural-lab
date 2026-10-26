"""Trusted evaluator: target and reference never enter the generator workspace."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import time

from .boundary import GeneratorBoundary


def _load(path, function):
    source = Path(path).resolve(strict=True)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location("tomolab_trusted_" + before, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hashlib.sha256(source.read_bytes()).hexdigest() != before:
        raise ValueError("trusted source changed during import")
    fn = getattr(module, function, None)
    if not callable(fn):
        raise ValueError(f"callable {function!r} missing")
    return fn, before


def run_mold(target, oracle, spec, *, function="implementation", oracle_function="reference",
             budget=32, seed=7, backend="subprocess", solver="enumeration", trusted_execution=False):
    if not trusted_execution:
        raise PermissionError("explicit trusted execution required; evaluator is NOT sandboxed")
    if type(budget) is not int or not 1 <= budget <= 256:
        raise ValueError("budget must be 1..256")
    if Path(target).resolve() == Path(oracle).resolve():
        raise ValueError("mold-run requires a separately authored oracle file")
    started = time.perf_counter()
    observations, failures, proposals = [], [], []
    oracle_seconds = 0.0
    with GeneratorBoundary(backend=backend) as generator:
        generator.request("init", spec=spec, seed=seed, solver=solver)
        domain_size = 1
        for var in spec["variables"]:
            domain_size *= var["high"] - var["low"] + 1
        if budget > domain_size:
            raise ValueError("budget exceeds unique inputs in the finite domain")
        fn, target_hash = _load(target, function)
        ref, oracle_hash = _load(oracle, oracle_function)
        by_role = {v["role"]: v["name"] for v in spec["variables"]}
        names = [by_role[role] for role in ("left", "right")]
        for index in range(budget):
            proposal = generator.request("propose")
            if proposal is None:
                break
            values = [proposal["inputs"][name] for name in names]
            before = time.perf_counter()
            expected, actual = ref(*values), fn(*values)
            oracle_seconds += time.perf_counter() - before
            if type(expected) is not int or type(actual) is not int:
                raise ValueError("mold evaluator currently requires exact integer outputs")
            mismatch = expected != actual
            proposals.append(proposal)
            # REFUTATION is a structural counterexample to predicted failure
            # membership, not a score/reward. No output value or source is sent.
            evidence = {"kind": "FAILURE" if mismatch else "REFUTATION",
                        "evidence_id": f"dev-{index:04d}", "inputs": proposal["inputs"],
                        "invariant": spec["invariant"], "signature": "integer-mismatch"}
            generator.request("observe", evidence=evidence)
            observations.append(evidence)
            if mismatch:
                failures.append(evidence)
        snapshot = generator.request("freeze")
        boundary = generator.receipt
    if hashlib.sha256(Path(target).read_bytes()).hexdigest() != target_hash:
        raise ValueError("target changed during development")
    if hashlib.sha256(Path(oracle).read_bytes()).hexdigest() != oracle_hash:
        raise ValueError("oracle changed during development")
    return {"schema": "tomolab-mold-run-v1",
            "status": "COUNTEREXAMPLES_FOUND" if failures else "NOT_REFUTED_WITHIN_BUDGET",
            **boundary, "target_sha256": target_hash, "oracle_sha256": oracle_hash,
            "budget": budget, "seed": seed, "target_calls": len(proposals), "oracle_calls": len(proposals),
            "failures": failures, "evidence": observations, "proposals": proposals, "snapshot": snapshot,
            "timing": {"wall_seconds": time.perf_counter() - started, "oracle_seconds": oracle_seconds},
            "generalization": "UNKNOWN", "contract_semantics": "USER_DECLARED_NOT_INFERRED_FROM_SOURCE"}


def plan_mold(snapshot, spec, *, budget=32, seed=7, backend="subprocess", solver="enumeration"):
    if type(budget) is not int or not 1 <= budget <= 256:
        raise ValueError("budget must be 1..256")
    snapshot = snapshot.get("snapshot", snapshot)
    with GeneratorBoundary(backend=backend) as generator:
        result = generator.request("transfer", snapshot=snapshot, spec=spec, seed=seed,
                                   budget=budget, solver=solver)
        result.update(generator.receipt)
    result["schema"] = "tomolab-mold-plan-v1"
    result["final_feedback_allowed"] = False
    result["candidate_sha256"] = hashlib.sha256(json.dumps(result["candidates"], sort_keys=True,
                                                             separators=(",", ":")).encode()).hexdigest()
    return result
