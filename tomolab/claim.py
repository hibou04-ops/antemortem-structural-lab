"""Phase C: narrow, auditable claim-to-metamorphic-witness experiment.

There is NO executable reference implementation here. A user-supplied, tightly
recognized natural-language claim becomes a relational obligation. The claim
itself is NOT independently proven faithful to the real-world requirement.

Security: ONLY run local, trusted, side-effect-free Python. This has NO sandbox.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .cast import _load_module
from .mri import inspect_file, predicted_trace, static_proposals
from .model import Inspection, Proposal

SCHEMA = "tomolab-claim-evidence-v1"

# Exact, human-readable claim sentences are the current semantic boundary.
# Unrecognized or ambiguous claims FAIL CLOSED, not to an LLM guess.
CLAIMS = {
    "두 정수 입력의 순서를 바꿔도 반환값은 같다": ("swap", "f(x,y) == f(y,x)"),
    "Swapping the two integer inputs does not change the result": ("swap", "f(x,y) == f(y,x)"),
    "첫 번째 정수 입력을 1 증가시키면 반환값도 1 증가한다": ("shift_x", "f(x,y) == f(x-1,y) + 1"),
    "Increasing the first integer input by one increases the result by one": ("shift_x", "f(x,y) == f(x-1,y) + 1"),
    "첫 번째 정수 입력을 1 증가시키면 반환값이 감소하지 않는다": ("monotone_x", "f(x,y) >= f(x-1,y)"),
    "Increasing the first integer input by one does not decrease the result": ("monotone_x", "f(x,y) >= f(x-1,y)"),
}


def _normalize(claim: str) -> str:
    return " ".join(claim.strip().removesuffix(".").split())


@dataclass(frozen=True)
class Contract:
    text: str
    kind: str
    obligation: str
    contract_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text, "kind": self.kind,
            "formal_obligation": self.obligation,
            "contract_sha256": self.contract_sha256,
            "trust_boundary": "exact allowed claim text; user must confirm semantic faithfulness",
            "assumptions": ["two integer positional arguments", "integer result",
                            "pure and deterministic target", "only inputs in the declared closed integer domain"],
        }


def compile_claim(text: str) -> Contract:
    normalized = _normalize(text)
    if normalized not in CLAIMS:
        raise ValueError(
            "UNSUPPORTED_CLAIM: no exact recognized relational contract; "
            "do not guess from arbitrary natural language"
        )
    kind, obligation = CLAIMS[normalized]
    h = hashlib.sha256(f"tomolab-claim-v1\n{normalized}\n{kind}\n{obligation}".encode()).hexdigest()
    return Contract(normalized, kind, obligation, h)


def _pair(contract: Contract, args: tuple[int, int], low: int, high: int):
    x, y = args
    if contract.kind == "swap":
        left, right = (x, y), (y, x)
    else:
        left, right = (x - 1, y), (x, y)
    if any(not low <= v <= high for case in (left, right) for v in case):
        return None
    return left, right


def _evaluate_relation(contract: Contract, a: int, b: int) -> bool:
    if contract.kind == "swap":
        return a == b
    if contract.kind == "shift_x":
        return b == a + 1
    if contract.kind == "monotone_x":
        return b >= a
    raise AssertionError("unknown contract kind")


def _execute(fn: Callable, inputs: tuple[int, int]) -> dict[str, Any]:
    """Return an integer result plus traced lines, without copying exception messages."""
    lines: list[int] = []
    code = fn.__code__
    old = sys.gettrace()

    def trace(frame, event, arg):
        if frame.f_code is code:
            if event == "line":
                lines.append(frame.f_lineno)
            return trace
        return None

    try:
        sys.settrace(trace)
        try:
            value = fn(*inputs)
        except Exception as exc:
            return {"kind": "exception", "value": type(exc).__name__, "traced_lines": lines}
        if type(value) is not int:
            return {"kind": "unsupported_result", "value": type(value).__name__, "traced_lines": lines}
        return {"kind": "return_int", "value": value, "traced_lines": lines}
    finally:
        sys.settrace(old)


def _guard_feedback(ins: Inspection, args: tuple[int, int], trace: list[int],
                    low: int, high: int) -> list[Proposal]:
    """Observe an unentered true-arm and propose satisfying its supported guard."""
    executed = set(trace)
    reached = {g.line for g in ins.guards if g.line in executed}
    taken = {g.line for g in ins.guards if g.line in executed and g.body_line in executed}
    values = dict(zip(ins.parameters, args))
    proposals: list[Proposal] = []
    for g in ins.guards:
        if g.line not in reached or g.line in taken or not all(a in taken for a in g.ancestors):
            continue
        v = g.satisfy()
        if not low <= v <= high or values[g.name] == v:
            continue
        changed = dict(values)
        changed[g.name] = v
        new_args = tuple(changed[name] for name in ins.parameters)
        if len(new_args) == 2:
            proposals.append(Proposal(new_args,
                f"observed guard L{g.line} without true arm; target {g.name}={v}",
                "mri_cast_feedback", g.line))
    return proposals


def _observe_pair(fn: Callable, ins: Inspection, contract: Contract,
                  p: Proposal, low: int, high: int) -> dict[str, Any] | None:
    pair = _pair(contract, p.inputs, low, high)
    if pair is None:
        return None
    left_args, right_args = pair
    left = _execute(fn, left_args)
    right = _execute(fn, right_args)
    left_again = _execute(fn, left_args)  # weak nondeterminism screen, not purity proof
    stable = left == left_again  # includes lines; same function on same args
    comparable = stable and all(o["kind"] == "return_int" for o in (left, right, left_again))
    violated = comparable and not _evaluate_relation(contract, left["value"], right["value"])
    discrepancies = []
    for args, outcome in ((left_args, left), (right_args, right)):
        predicted = predicted_trace(ins, args)
        actual = {g.line for g in ins.guards if g.line in outcome["traced_lines"]}
        discrepancies.extend({"args": list(args), "line": k,
                              "kind": "mri_cast_trace_disagreement"}
                             for k in sorted(predicted ^ actual))
    return {
        "probe": list(p.inputs), "origin": p.origin, "reason": p.reason,
        "left_args": list(left_args), "right_args": list(right_args),
        "left": left, "right": right, "left_repeat": left_again,
        "stable_on_repeat": stable, "comparable": comparable,
        "obligation_violated": violated,
        "actual_target_calls": 3,
        "structural_disagreements": discrepancies,
    }


def run_claim(
    path: Path, claim: str, *, function: str = "implementation", mode: str = "cross",
    budget: int = 12, seed: int = 7, low: int = -25, high: int = 25,
    trusted_execution: bool = False,
) -> dict[str, Any]:
    if not trusted_execution:
        raise PermissionError("claim-run executes arbitrary local code; explicit opt-in required; no sandbox")
    if mode not in ("cast", "mri", "parallel", "cross"):
        raise ValueError("unsupported mode")
    if budget < 3 or budget > 10000:
        raise ValueError("budget must be 3..10000 target function calls")
    if high < low:
        raise ValueError("invalid integer range")
    contract = compile_claim(claim)  # first: reject unsupported semantics before target import
    ins = inspect_file(path, function)
    if len(ins.parameters) != 2:
        raise ValueError("Phase C supports exactly two ordinary integer arguments")
    module = _load_module(Path(ins.source_file), "_tomolab_claim_target")
    if hashlib.sha256(Path(ins.source_file).read_bytes()).hexdigest() != ins.source_sha256:
        raise ValueError("SOURCE_DRIFT while importing source")
    fn = getattr(module, function)
    if not callable(fn) or not hasattr(fn, "__code__"):
        raise ValueError("trusted target must be Python callable")
    rng = random.Random(seed)
    statics = static_proposals(ins, low, high)
    outers = static_proposals(ins, low, high, outer_only=True)
    queue: list[Proposal] = outers.copy()
    feedback_queue: list[Proposal] = []
    visited: set[tuple[int, int]] = set()
    observations: list[dict[str, Any]] = []
    si = 0
    target_calls = 0
    status = "NOT_REFUTED_WITHIN_BUDGET"

    def random_proposal() -> Proposal:
        return Proposal((rng.randint(low, high), rng.randint(low, high)), "uniform random", "cast")

    while target_calls + 3 <= budget:
        if mode == "cast":
            p = random_proposal()
        elif mode == "mri":
            p = statics[si] if si < len(statics) else random_proposal()
            si += 1
        elif mode == "parallel":
            p = (statics[si] if si < len(statics) else random_proposal()) if len(observations) % 2 == 0 else random_proposal()
            if len(observations) % 2 == 0:
                si += 1
        else:
            candidates = [p for p in feedback_queue + queue if p.inputs not in visited]
            p = candidates[0] if candidates else random_proposal()
            feedback_queue = [q for q in feedback_queue if q.inputs != p.inputs]
            queue = [q for q in queue if q.inputs != p.inputs]
        if p.inputs in visited or _pair(contract, p.inputs, low, high) is None:
            for _ in range(30):
                alternate = random_proposal()
                if alternate.inputs not in visited and _pair(contract, alternate.inputs, low, high) is not None:
                    p = alternate
                    break
            else:
                break
        visited.add(p.inputs)
        observation = _observe_pair(fn, ins, contract, p, low, high)
        if observation is None:
            break
        observations.append(observation)
        target_calls += 3
        if observation["obligation_violated"]:
            status = "CLAIM_REFUTED"
            break
        if mode == "cross":
            for args_key, outcome_key in (("left_args", "left"), ("right_args", "right")):
                obs_args = tuple(observation[args_key])
                for nextp in _guard_feedback(ins, obs_args, observation[outcome_key]["traced_lines"], low, high):
                    if (nextp.inputs not in visited and
                        nextp.inputs not in {p.inputs for p in feedback_queue}):
                        feedback_queue.append(nextp)

    if status != "CLAIM_REFUTED" and observations and not any(o["comparable"] for o in observations):
        status = "INCONCLUSIVE_EXECUTION"
    all_disagreements = [d for o in observations for d in o["structural_disagreements"]]
    return {
        "schema": SCHEMA, "status": status,
        "claim": contract.as_dict(), "source": {
            "source_file": str(path), "source_sha256": ins.source_sha256,
            "function": function, "parameters": list(ins.parameters),
            "guards": [g.__dict__ for g in ins.guards],
            "limitations": list(ins.limitations),
        },
        "domain": {"low": low, "high": high},
        "mode": mode, "budget_target_calls": budget, "seed": seed,
        "target_calls": target_calls, "candidate_relations_tested": len(observations),
        "observations": observations,
        "findings": [o for o in observations if o["obligation_violated"]],
        "structural_model_disagreements": all_disagreements,
        "oracle_function": None,
        "result_scope": ("a violating witness refutes the exact encoded relation on tested inputs; "
                         "it does not prove the original natural-language intent or general program correctness; "
                         "absence of witnesses is UNKNOWN"),
        "decision_provider": "deterministic (no Jev or LLM invoked)",
    }


def replay_claim(evidence_file: Path, *, trusted_execution: bool = False,
                 source_override: Path | None = None) -> dict[str, Any]:
    if not trusted_execution:
        raise PermissionError("claim replay requires trusted_execution=True")
    evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    if evidence.get("schema") != SCHEMA:
        raise ValueError("wrong evidence schema")
    evidence_contract = evidence["claim"]
    contract = compile_claim(evidence_contract["text"])
    if (contract.contract_sha256 != evidence_contract["contract_sha256"] or
        contract.kind != evidence_contract["kind"] or
        contract.obligation != evidence_contract["formal_obligation"]):
        return {"status": "CONTRACT_DRIFT", "replayed": 0}
    source = evidence["source"]
    path = source_override or Path(source["source_file"])
    ins = inspect_file(path, source["function"])
    if ins.source_sha256 != source["source_sha256"]:
        return {"status": "SOURCE_DRIFT", "replayed": 0}
    findings = evidence["findings"]
    if not findings:
        return {"status": "NO_FINDINGS", "replayed": 0}
    fn = getattr(_load_module(Path(ins.source_file), "_tomolab_claim_replay"), ins.function)
    if hashlib.sha256(Path(ins.source_file).read_bytes()).hexdigest() != ins.source_sha256:
        return {"status": "SOURCE_DRIFT", "replayed": 0}
    rows = []
    for item in findings:
        p = item["probe"]
        if (not isinstance(p, list) or len(p) != 2 or
            any(type(v) is not int for v in p)):
            raise ValueError("malformed replay inputs")
        observation = _observe_pair(fn, ins, contract,
            Proposal(tuple(p), "replaying counterexample", "replay"),
            evidence["domain"]["low"], evidence["domain"]["high"])
        reproduced = (observation is not None and observation["obligation_violated"] and
            observation["left_args"] == item["left_args"] and
            observation["right_args"] == item["right_args"] and
            observation["left"]["value"] == item["left"]["value"] and
            observation["right"]["value"] == item["right"]["value"])
        rows.append({"probe": p, "reproduced": reproduced})
    return {"status": "REPRODUCED" if all(x["reproduced"] for x in rows) else "NOT_REPRODUCED",
            "replayed": len(rows), "results": rows,
            "scope": "exact contract+source hash, same violating input/output; not a universal proof"}
