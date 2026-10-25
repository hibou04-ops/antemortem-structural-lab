"""C1 development evaluation with a separate truth-membership gold oracle.

The production checker is imported only for the authority arm. Gold truth tables
were frozen separately; this module never rewrites them or reads the holdout.
No target code, provider API, or Jev is executed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from research.c1.authority import analyze, adjudicate
from tomolab.claim import compile_claim

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
RELATIONS = {"EQUIVALENT", "NECESSARY_ONLY", "SUFFICIENT_ONLY", "INCOMPARABLE"}
# Independently implemented shared experiment limits, not production validator reuse.
MAX_INPUT_BYTES = 2_000_000
MAX_ORACLE_NODES = 4096
MAX_ORACLE_DEPTH = 32
MAX_ORACLE_INT = 1_000_000_000
MAX_ORACLE_VALUE_BITS = 128
MAX_ORACLE_STATES = 100_000
MAX_ORACLE_WORK = 5_000_000


def load_json(path: Path) -> Any:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("evaluation input byte limit")
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_sha256(value: Any) -> str:
    """Content hash is stable across Git newline normalization."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def oracle_expression(expression: Any, state: dict[str, Any]) -> bool | int:
    """Independent tiny evaluator used only on generated candidate obligations.

    Curated gold C/O tables were authored using separate manual Python predicates.
    This evaluator does not import or call production expression interpretation.
    """
    count = [0]
    def visit(expr: Any, depth: int) -> bool | int:
        count[0] += 1
        if count[0] > MAX_ORACLE_NODES:
            raise ValueError("oracle expression node limit")
        if depth > MAX_ORACLE_DEPTH:
            raise ValueError("oracle expression depth")
        if type(expr) in (int, bool):
            if type(expr) is int and abs(expr) > MAX_ORACLE_INT:
                raise ValueError("oracle integer literal limit")
            return expr
        if isinstance(expr, str) and expr in state:
            return state[expr]
        if not isinstance(expr, list) or not expr:
            raise ValueError("oracle invalid expression")
        op, *args = expr
        values = [visit(arg, depth + 1) for arg in args]
        if op in {"and", "or"} and len(values) >= 2:
            if any(type(v) is not bool for v in values):
                raise ValueError("oracle Boolean type")
            return all(values) if op == "and" else any(values)
        if op == "not" and len(values) == 1 and type(values[0]) is bool:
            return not values[0]
        if len(values) != 2:
            raise ValueError("oracle arity")
        a, b = values
        if op == "implies" and type(a) is type(b) is bool:
            return not a or b
        if op in {"==", "!="} and type(a) is type(b):
            return (a == b) if op == "==" else (a != b)
        if type(a) is not int or type(b) is not int:
            raise ValueError("oracle integer type")
        if op == "<": return a < b
        if op == "<=": return a <= b
        if op == ">": return a > b
        if op == ">=": return a >= b
        if op in {"+", "-", "*"}:
            value = a + b if op == "+" else a - b if op == "-" else a * b
            if abs(value).bit_length() > MAX_ORACLE_VALUE_BITS:
                raise ValueError("oracle intermediate integer limit")
            return value
        raise ValueError("oracle unsupported operator")
    result = visit(expression, 0)
    if type(result) is not bool:
        raise ValueError("oracle obligation must be Boolean")
    return result


def candidate_gold(case: dict, gold: dict, obligation: Any, *,
                   candidate_quantifier: str | None = None) -> tuple[dict, dict]:
    """Grade a new O against frozen C membership without running production code."""
    rows = gold["admissible_states"]
    nodes = 0
    pending = [(obligation, 0)]
    while pending:
        expr, depth = pending.pop()
        nodes += 1
        if nodes > MAX_ORACLE_NODES or depth > MAX_ORACLE_DEPTH:
            raise ValueError("oracle expression resource limit")
        if type(expr) is list:
            pending.extend((arg, depth + 1) for arg in expr[1:])
    if len(rows) > MAX_ORACLE_STATES or len(rows) * nodes > MAX_ORACLE_WORK:
        raise ValueError("oracle enumeration work limit")
    truths = [r for r in rows if oracle_expression(obligation, r)]
    fails = [r for r in rows if r not in truths]
    ci = all(r in truths for r in gold["claim_true_states"])
    oi = all(r in gold["claim_true_states"] for r in truths)
    relation = ("EQUIVALENT" if ci and oi else "NECESSARY_ONLY" if ci else
                "SUFFICIENT_ONLY" if oi else "INCOMPARABLE")
    contract = case["contract"]
    oq = candidate_quantifier or contract.get("obligation_quantifier", contract["quantifier"])
    if gold["relation"] in {"AMBIGUOUS", "OUT_OF_SCOPE"}:
        relation = gold["relation"]
    if not rows or oq != contract["quantifier"]:
        relation = "UNKNOWN"
    # A newly generated existential O passes when any admissible valuation holds.
    # The curated ablation intentionally reuses its originally submitted evidence.
    obligation_passes = bool(truths) if oq == "exists" else not fails
    evidence = ({"status": "PASS_EXHAUSTIVE"} if obligation_passes else
                {"status": "FAIL", "witness": fails[0]} if fails else
                {"status": "PASS_EXHAUSTIVE"})
    approved = relation in RELATIONS and bool(rows)
    forall = contract["quantifier"] == oq == "forall"
    status = ("REFUTED" if approved and ci and not obligation_passes and forall else
              "PROVED_BOUNDED" if approved and oi and obligation_passes else "UNKNOWN")
    return {**gold, "relation": relation, "expected_status": status,
            "obligation_true_states": truths, "c_implies_o": ci,
            "o_implies_c": oi, "evidence_valid": bool(rows)}, evidence


def row_result(case: dict, gold: dict, *, status: str, relation: str,
               elapsed: float, evidence: dict | None = None, reason: str = "") -> dict:
    ev = evidence or case["evidence"]
    witness = ev.get("witness")
    witness_refutes = (witness in gold["admissible_states"] and
                       witness not in gold["claim_true_states"])
    authorized_refutation = (gold["relation"] in RELATIONS and
                             bool(gold["c_implies_o"]) and
                             case["contract"]["quantifier"] == "forall" and
                             bool(gold["evidence_valid"]) and witness_refutes)
    return {"id": case["id"], "family": case["family"],
            "status": status, "expected_status": gold["expected_status"],
            "relation": relation, "gold_relation": gold["relation"],
            "claim_true_bounded": gold["claim_true_bounded"],
            "wrong_refuted": status == "REFUTED" and gold["claim_true_bounded"] is True,
            "unsupported_refuted": status == "REFUTED" and not authorized_refutation,
            "wrong_proved": status == "PROVED_BOUNDED" and gold["claim_true_bounded"] is False,
            "witness_violates_claim_predicate": witness_refutes,
            "quantified_claim_refutation_valid": (witness_refutes and
                case["contract"]["quantifier"] == "forall" and
                gold["relation"] in RELATIONS),
            "conclusion_target": "SUPPLIED_FORMAL_CLAIM",
            "natural_language_status": "UNKNOWN", "semantic_fidelity": "NOT_ESTABLISHED",
            "evidence": ev, "elapsed_seconds": elapsed, "reason": reason}


def fraction(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def summarize(rows: list[dict]) -> dict:
    refuted = [r for r in rows if r["status"] == "REFUTED"]
    nonrefutable = [r for r in rows if r["claim_true_bounded"] is True]
    eligible = [r for r in rows if r["expected_status"] == "REFUTED"]
    unknown = [r for r in rows if r["status"] == "UNKNOWN"]
    needed_unknown = [r for r in rows if r["expected_status"] == "UNKNOWN"]
    wrong = sum(r["wrong_refuted"] for r in rows)
    supported_hits = sum(r["status"] == "REFUTED" and not r["unsupported_refuted"] for r in eligible)
    return {"cases": len(rows), "status_counts": dict(Counter(r["status"] for r in rows)),
            "wrong_refuted_count": wrong,
            "wrong_refuted_among_refuted": fraction(wrong, len(refuted)),
            "wrong_refuted_among_nonrefutable": fraction(wrong, len(nonrefutable)),
            "unsupported_refuted_count": sum(r["unsupported_refuted"] for r in rows),
            "supported_refuted_among_refuted": fraction(sum(not r["unsupported_refuted"] for r in refuted), len(refuted)),
            "decision_coverage": fraction(len(rows) - len(unknown), len(rows)),
            "unknown_rate": fraction(len(unknown), len(rows)),
            "wrong_proved_count": sum(r["wrong_proved"] for r in rows),
            "true_counterexample_recall": fraction(supported_hits, len(eligible)),
            "relation_accuracy": fraction(sum(r["relation"] == r["gold_relation"] for r in rows), len(rows)),
            "decision_accuracy": fraction(sum(r["status"] == r["expected_status"] for r in rows), len(rows)),
            "unknown_precision": fraction(sum(r["expected_status"] == "UNKNOWN" for r in unknown), len(unknown)),
            "unknown_recall": fraction(sum(r["status"] == "UNKNOWN" for r in needed_unknown), len(needed_unknown)),
            "evaluator_elapsed_seconds": sum(r["elapsed_seconds"] for r in rows)}


def evaluate_curated(cases: list[dict], gold_by_id: dict) -> dict:
    arms = {"unsafe_lifting_ablation": [], "logical_authority": []}
    for case in cases:
        gold = gold_by_id[case["id"]]
        ev = case["evidence"]
        start = time.perf_counter()
        unsafe_status = "REFUTED" if ev["status"] == "FAIL" else "PROVED_BOUNDED"
        arms["unsafe_lifting_ablation"].append(row_result(
            case, gold, status=unsafe_status, relation="EQUIVALENT",
            elapsed=time.perf_counter() - start,
            reason="Deliberately unsafe ablation: assume C equivalent O and lift submitted result without validation."))
        start = time.perf_counter()
        result = adjudicate(case["contract"], ev)
        a = result["analysis"]
        arms["logical_authority"].append(row_result(
            case, gold, status=result["status"], relation=a["relation"],
            elapsed=time.perf_counter() - start, reason=result["reason"]))
    return {name: {"status": "MEASURED", "comparison_scope": "Identical curated candidates and submitted evidence, paired by case id.",
                   "model_calls": 0, "tokens": 0, "marginal_api_cost_usd": 0,
                   "metrics": summarize(rows), "rows": rows} for name, rows in arms.items()}


def evaluate_c0(cases: list[dict], gold_by_id: dict) -> dict:
    rows = []
    accepted = 0
    for case in cases:
        gold = gold_by_id[case["id"]]
        start = time.perf_counter()
        try:
            template = compile_claim(case["contract"]["claim_text"])
        except ValueError:
            rows.append(row_result(case, gold, status="UNKNOWN", relation="UNKNOWN",
                                   elapsed=time.perf_counter() - start, reason="C0 exact-template compiler rejected claim."))
            continue
        accepted += 1
        obligation = (["==", "right", "left"] if template.kind == "swap" else
                      ["==", "right", ["+", "left", 1]] if template.kind == "shift_x" else
                      [">=", "right", "left"])
        candidate, ev = candidate_gold(case, gold, obligation, candidate_quantifier=case["contract"]["quantifier"])
        status = "REFUTED" if ev["status"] == "FAIL" else "UNKNOWN"
        rows.append(row_result(case, candidate, status=status, relation="EQUIVALENT", evidence=ev,
                               elapsed=time.perf_counter() - start,
                               reason="Actual C0 compile_claim mapping; finite symbolic output fixtures, no target run."))
    return {"status": "MEASURED", "comparison_scope": "Actual exact-template compiler with a research-only symbolic-observation adapter; unsupported claims abstain.",
            "accepted": accepted, "model_calls": 0, "tokens": 0, "marginal_api_cost_usd": 0,
            "metrics": summarize(rows), "rows": rows}


def evaluate_llm(cases: list[dict], gold_by_id: dict, path: Path | None, *, guarded: bool = False) -> dict:
    if path is None:
        return {"status": "NOT_RUN", "reason": "No separately captured generation artifact supplied.",
                "model_calls": None, "tokens": None, "api_cost_usd": None, "metrics": None}
    artifact = load_json(path)
    candidates = artifact.get("candidates", [])
    ids = [c["id"] for c in candidates]
    if len(ids) != len(set(ids)) or set(ids) != {c["id"] for c in cases}:
        raise ValueError("LLM candidate ids must cover development cases exactly once")
    by_id = {c["id"]: c for c in candidates}
    rows = []
    for case in cases:
        gold = gold_by_id[case["id"]]
        pred = by_id[case["id"]]
        start = time.perf_counter()
        fields = {"id", "decision", "obligation", "reason", "relation", "obligation_quantifier"}
        malformed = (type(pred) is not dict or pred.keys() - fields or
                     type(pred.get("decision")) is not str or pred.get("decision") not in {"FORMALIZED", "UNKNOWN"} or
                     type(pred.get("reason")) is not str or
                     ("relation" in pred and (type(pred["relation"]) is not str or pred["relation"] not in RELATIONS)) or
                     ("obligation_quantifier" in pred and (type(pred["obligation_quantifier"]) is not str or pred["obligation_quantifier"] not in {"forall", "exists"})))
        if malformed:
            rows.append(row_result(case, gold, status="UNKNOWN", relation="UNKNOWN",
                                   elapsed=time.perf_counter() - start, reason="Malformed candidate fields; fail closed."))
            continue
        if pred.get("decision") == "UNKNOWN":
            rows.append(row_result(case, gold, status="UNKNOWN", relation="UNKNOWN",
                                   elapsed=time.perf_counter() - start, reason=pred.get("reason", "Generator abstained.")))
            continue
        try:
            oq = pred.get("obligation_quantifier", case["contract"]["quantifier"])
            candidate, ev = candidate_gold(case, gold, pred["obligation"], candidate_quantifier=oq)
            if guarded:
                contract = deepcopy(case["contract"])
                contract["obligation"] = pred["obligation"]
                contract["obligation_quantifier"] = oq
                judged = adjudicate(contract, ev)
                status = judged["status"]
                relation = judged["analysis"]["relation"]
                reason = "Same generated O/evidence plus supplied formal-C authority check: " + judged["reason"]
            else:
                status = "REFUTED" if ev["status"] == "FAIL" else "PROVED_BOUNDED"
                relation = pred.get("relation", "EQUIVALENT")
                reason = "Blind role-generated obligation; quantified finite candidate check and unguarded lifting."
            rows.append(row_result(case, candidate, status=status,
                                   relation=relation, evidence=ev,
                                   elapsed=time.perf_counter() - start, reason=reason))
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            rows.append(row_result(case, gold, status="UNKNOWN", relation="UNKNOWN",
                                   elapsed=time.perf_counter() - start,
                                   reason=f"Candidate not executable in bounded DSL: {type(exc).__name__}"))
    provenance = artifact.get("provenance", {})
    return {"status": "MEASURED_ROLE_BASELINE", "authority_gate": guarded,
            "artifact_content_sha256": canonical_sha256(artifact),
            "provenance": artifact.get("provenance", {}),
            "comparison_scope": "Candidate-specific gold relation against frozen C truth sets; not same O as the paired curated ablation. Same model family/session roles, not an independent model API benchmark.",
            "external_api_calls": provenance.get("external_api_calls"),
            "agent_inference_role_runs": 1,
            "new_generation_runs_for_this_arm": 0 if guarded else 1,
            "generation_cost_shared_with_unguarded_arm": guarded,
            "tokens": provenance.get("tokens", provenance.get("token_usage")),
            "api_cost_usd": provenance.get("api_cost_usd", provenance.get("monetary_cost")),
            "generation_elapsed_seconds": provenance.get("generation_elapsed_seconds", provenance.get("elapsed_seconds")),
            "metrics": summarize(rows), "rows": rows}


def run(*, direct: Path | None = None, self_review: Path | None = None) -> dict:
    dataset = load_json(FIXTURES / "dev_contracts.json")
    golden = load_json(FIXTURES / "dev_gold.json")
    cases = dataset["cases"]
    gold_by_id = {c["id"]: c for c in golden["cases"]}
    if len(gold_by_id) != len(cases) or set(gold_by_id) != {c["id"] for c in cases}:
        raise ValueError("Gold/case id mismatch")
    start = time.perf_counter()
    baselines = evaluate_curated(cases, gold_by_id)
    baselines["c0_templates"] = evaluate_c0(cases, gold_by_id)
    baselines["llm_direct"] = evaluate_llm(cases, gold_by_id, direct)
    baselines["llm_self_review"] = evaluate_llm(cases, gold_by_id, self_review)
    baselines["llm_direct_with_authority"] = evaluate_llm(cases, gold_by_id, direct, guarded=True)
    baselines["llm_self_review_with_authority"] = evaluate_llm(cases, gold_by_id, self_review, guarded=True)
    return {"schema": "c1-development-results-v1", "split": "PUBLIC_DEVELOPMENT_NOT_HELD_OUT",
            "conclusion_target": "SUPPLIED_FORMAL_CLAIM",
            "natural_language_status": "UNKNOWN", "semantic_fidelity": "NOT_ESTABLISHED",
            "case_count": len(cases), "family_count": len({c["family"] for c in cases}),
            "dataset_content_sha256": canonical_sha256(dataset),
            "gold_content_sha256": canonical_sha256(golden),
            "baseline_results": baselines,
            "total_evaluation_elapsed_seconds": time.perf_counter() - start,
            "jev": {"real_api_calls": 0, "status": "ABLATION_DEFERRED"},
            "holdout": {"status": "SEALED_UNUSED", "evaluation_runs": 0,
                        "commitment": load_json(FIXTURES / "holdout_commitment.json")},
            "metric_definitions": {
                "wrong_refuted": "REFUTED while the frozen formal C is true over its entire bounded quantifier domain. Excludes inconsistent/undefined claims.",
                "unsupported_refuted": "REFUTED without valid in-domain submitted witness, forall semantics and C=>O authority. The underlying C might still be false elsewhere.",
                "true_counterexample_recall": "Authorized REFUTED decisions divided by cases whose candidate-specific gold decision is REFUTED.",
                "relation_accuracy": "Predicted pointwise relation divided by all cases, including ambiguous/out-of-scope/unknown labels. LLM candidate gold is recomputed with an independent evaluator against frozen C membership.",
                "unknown_precision_recall": "UNKNOWN measured against candidate-specific gold inability to lift the submitted evidence. It does not validate unknown handling on arbitrary natural language.",
                "cost": "Zero additional provider calls for deterministic evaluation. LLM token/time/price receipts are null if not observable; no fabricated zero.",
            },
            "limits": ["Synthetic tiny finite domains; development set was used for implementation verification.",
                       "Gold has separate role/file/procedure provenance, but no external human annotation or model-family independence.",
                       "All claims concern supplied formal anchors; original natural-language semantic fidelity remains unproven.",
                       "No claim of superiority over PBT-Bench, Anthropic PBT, SMT systems, CrossHair, or a fresh independently sampled LLM.",
                       "Finite DSL is data-only; separate Python environment is process/dependency isolation, not an OS security sandbox.",
                       "Holdout v2 names a conceptual family absent from dev, but was authored after preliminary dev inspection by the same curator and remains unused; not qualified confirmatory evidence."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--llm-direct", type=Path)
    parser.add_argument("--llm-self-review", type=Path)
    args = parser.parse_args()
    report = run(direct=args.llm_direct, self_review=args.llm_self_review)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: value.get("metrics") for name, value in report["baseline_results"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
