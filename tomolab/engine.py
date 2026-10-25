"""Deterministic ablations and cross-modal feedback exploration."""
from __future__ import annotations

import random
import hashlib
from pathlib import Path

from .cast import load_trusted_functions, observe
from .jev import JevError, choose
from .model import ExperimentResult, Inspection, Observation, Proposal
from .mri import inspect_file, predicted_trace, static_proposals

MODES = ("cast", "mri", "parallel", "cross")


def _random_proposal(rng: random.Random, ins: Inspection, low: int, high: int) -> Proposal:
    return Proposal(tuple(rng.randint(low, high) for _ in ins.parameters), "CAST uniform probe", "random")


def _feedback(ins: Inspection, obs: Observation, low: int, high: int) -> list[Proposal]:
    """Use actually observed inner guards to propose single-variable interventions.

    This is a causal *candidate*, not a proof that changing the variable caused an outcome.
    """
    reached, taken = set(obs.reached_guards), set(obs.taken_guards)
    values = dict(zip(ins.parameters, obs.inputs))
    proposals = []
    for g in ins.guards:
        if g.line not in reached or g.line in taken:
            continue
        if not all(a in taken for a in g.ancestors):
            continue
        proposed_value = g.satisfy()
        if not low <= proposed_value <= high or values[g.name] == proposed_value:
            continue
        altered = dict(values)
        altered[g.name] = proposed_value
        args = tuple(altered[p] for p in ins.parameters)
        proposals.append(Proposal(
            args,
            f"CAST saw L{g.line} unreached true-arm after ancestor path {g.ancestors}; MRI suggests {g.name}={proposed_value}",
            "feedback", g.line,
        ))
    return proposals


def run_experiment(
    path: Path,
    *,
    function: str = "implementation",
    oracle_function: str = "reference",
    oracle_path: Path | None = None,
    mode: str = "cross",
    budget: int = 12,
    seed: int = 7,
    low: int = -25,
    high: int = 25,
    trusted_execution: bool = False,
    use_jev: bool = False,
) -> ExperimentResult:
    if not trusted_execution:
        raise PermissionError("execution requires explicit trusted_execution=True; no OS sandbox is provided")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if not 1 <= budget <= 10000:
        raise ValueError("budget must be 1..10000")
    if high < low:
        raise ValueError("high must be >= low")
    if use_jev and mode != "cross":
        raise ValueError("Jev selection only supported for cross mode")

    ins = inspect_file(path, function)
    actual_oracle_path = (oracle_path or path).resolve(strict=True)
    oracle_hash = hashlib.sha256(actual_oracle_path.read_bytes()).hexdigest()
    fn, ref = load_trusted_functions(path, function, oracle_function, oracle_path)
    # Reject a basic source-swap/side-effect race between AST inspection and import.
    if hashlib.sha256(Path(ins.source_file).read_bytes()).hexdigest() != ins.source_sha256:
        raise ValueError("source changed during target import; no evidence produced")
    if hashlib.sha256(actual_oracle_path.read_bytes()).hexdigest() != oracle_hash:
        raise ValueError("oracle changed during target import; no evidence produced")
    source_info = ins.as_dict()
    source_info["oracle_source_file"] = str(actual_oracle_path)
    source_info["oracle_source_sha256"] = oracle_hash
    result = ExperimentResult("tomolab-evidence-v1", mode, source_info, oracle_function, budget, seed,
                              decision_provider="jev_not_invoked" if use_jev else "deterministic")
    rng = random.Random(seed)
    statics = static_proposals(ins, low, high)
    outers = static_proposals(ins, low, high, outer_only=True)
    remaining: list[Proposal] = outers.copy()
    feedback_queue: list[Proposal] = []
    tested: set[tuple[int, ...]] = set()
    static_idx = 0

    for turn in range(budget):
        if mode == "cast":
            candidates = [_random_proposal(rng, ins, low, high)]
        elif mode == "mri":
            candidates = [statics[static_idx]] if static_idx < len(statics) else [_random_proposal(rng, ins, low, high)]
            static_idx += 1
        elif mode == "parallel":
            if turn % 2 == 0 and static_idx < len(statics):
                candidates = [statics[static_idx]]
                static_idx += 1
            else:
                candidates = [_random_proposal(rng, ins, low, high)]
        else:
            candidates = []
            for proposal in feedback_queue + remaining:
                if proposal.inputs not in tested and proposal.inputs not in {p.inputs for p in candidates}:
                    candidates.append(proposal)
            if not candidates:
                candidates = [_random_proposal(rng, ins, low, high)]

        if use_jev and mode == "cross" and len(candidates) > 1:
            result.decision_calls += 1
            try:
                selected = choose(candidates[:8], {
                    "tested": len(tested),
                    "observed_guards": len({l for o in result.observations for l in o.reached_guards}),
                })
                result.decision_provider = "jev_live"
            except JevError:
                selected = 0
                result.decision_fallbacks += 1
                result.decision_provider = "jev_error_deterministic_fallback"
            probe = candidates[selected]
        else:
            probe = candidates[0]

        if mode == "cross":
            feedback_queue = [p for p in feedback_queue if p.inputs != probe.inputs]
            remaining = [p for p in remaining if p.inputs != probe.inputs]
        if probe.inputs in tested:
            # Do not consume a call for duplicate input: draw novel random if possible.
            for _ in range(30):
                alternate = _random_proposal(rng, ins, low, high)
                if alternate.inputs not in tested:
                    probe = alternate
                    break
        tested.add(probe.inputs)
        obs = observe(fn, ref, ins, probe)
        result.observations.append(obs)
        predicted = predicted_trace(ins, probe.inputs)
        actually = set(obs.reached_guards)
        for line in sorted(predicted ^ actually):
            result.meta_disagreements.append({
                "probe": list(probe.inputs), "guard_line": line,
                "kind": "predicted_not_reached" if line in predicted else "reached_not_predicted",
                "status": "MODEL_UNCERTAIN_NOT_A_PROGRAM_DEFECT",
            })
        if obs.contradicts_oracle:
            result.status = "ORACLE_CONTRADICTION_FOUND"
            break
        if mode == "cross":
            # Observation-driven branch feedback receives priority over unvisited static suggestions.
            for next_probe in _feedback(ins, obs, low, high):
                if next_probe.inputs not in tested and all(x.inputs != next_probe.inputs for x in feedback_queue):
                    feedback_queue.append(next_probe)

    return result
