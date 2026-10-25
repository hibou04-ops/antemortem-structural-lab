"""Optional Z3 cross-check, with a separate DSL-to-SMT visitor.

Only the public development fixtures are read by the CLI. No finite evaluator,
validator, or gold truth table is used to construct the SMT result. The finite
analyzer is called afterward solely for a result comparison.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import time
from typing import Any

try:
    import z3
except ImportError:  # optional tool, never silently treated as a passing check
    z3 = None

OFFICIAL_SOURCES = [
    "https://z3prover.github.io/api/html/namespacez3py.html",
    "https://z3prover.github.io/api/html/classz3py_1_1_solver.html",
]


class Unsupported(ValueError):
    pass


def _translate(expression: Any, symbols: dict, depth: int = 0, nodes=None):
    """Own typed visitor; does not import the production evaluator."""
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if nodes[0] > 4096 or depth > 32:
        raise Unsupported("SMT_EXPRESSION_LIMIT")
    if type(expression) is bool:
        return z3.BoolVal(expression), "bool"
    if type(expression) is int:
        if abs(expression) > 1_000_000_000:
            raise Unsupported("SMT_INTEGER_LIMIT")
        return z3.IntVal(expression), "int"
    if type(expression) is str:
        if expression not in symbols:
            raise Unsupported("SMT_UNDECLARED_VARIABLE")
        return symbols[expression]
    if type(expression) is not list or not expression or type(expression[0]) is not str:
        raise Unsupported("SMT_MALFORMED_EXPRESSION")
    op, arguments = expression[0], expression[1:]
    arity = len(arguments)
    if (op in {"and", "or"} and arity < 2
            or op == "not" and arity != 1
            or op not in {"and", "or", "not"} and arity != 2):
        raise Unsupported("SMT_INVALID_ARITY")
    translated = [_translate(a, symbols, depth + 1, nodes) for a in arguments]
    sorts = [kind for _, kind in translated]
    args = [term for term, _ in translated]
    if op in {"and", "or", "not", "implies"}:
        if any(kind != "bool" for kind in sorts):
            raise Unsupported("SMT_TYPE_MISMATCH")
        constructor = {"and": z3.And, "or": z3.Or, "not": z3.Not, "implies": z3.Implies}[op]
        return constructor(*args), "bool"
    if op in {"==", "!="}:
        if sorts[0] != sorts[1]:
            raise Unsupported("SMT_TYPE_MISMATCH")
        return (args[0] == args[1] if op == "==" else args[0] != args[1]), "bool"
    if op not in {"<", "<=", ">", ">=", "+", "-", "*"}:
        raise Unsupported("SMT_UNSUPPORTED_OPERATOR")
    if any(kind != "int" for kind in sorts):
        raise Unsupported("SMT_TYPE_MISMATCH")
    a, b = args
    if op == "<":
        return a < b, "bool"
    if op == "<=":
        return a <= b, "bool"
    if op == ">":
        return a > b, "bool"
    if op == ">=":
        return a >= b, "bool"
    if op == "+":
        return a + b, "int"
    if op == "-":
        return a - b, "int"
    return a * b, "int"


def _solve(query, symbols: dict, timeout_ms: int) -> dict:
    solver = z3.Solver()
    solver.set(timeout=timeout_ms)
    solver.add(query)
    status = solver.check()
    result = {"status": str(status), "witness": None, "reason_unknown": None}
    if status == z3.sat:
        model = solver.model()
        result["witness"] = {
            name: (z3.is_true(model.eval(term, model_completion=True))
                   if kind == "bool" else model.eval(term, model_completion=True).as_long())
            for name, (term, kind) in symbols.items()
        }
        result["model_satisfies_query"] = z3.is_true(model.eval(query, model_completion=True))
    elif status == z3.unknown:
        result["reason_unknown"] = solver.reason_unknown()
    return result


def solve_relation(contract: dict, timeout_ms: int = 1000) -> dict:
    """Independent SAT/UNSAT checks of A, A&C&!O, and A&O&!C."""
    started = time.perf_counter()
    result = {"relation": "UNKNOWN", "reason": None, "premise_satisfiable": None,
              "c_implies_o": None, "o_implies_c": None, "queries": {},
              "conclusion_target": "SUPPLIED_FORMAL_CLAIM", "natural_language_status": "UNKNOWN"}
    try:
        if z3 is None:
            result["reason"] = "OPTIONAL_Z3_NOT_INSTALLED"
            return result
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= 60_000:
            raise Unsupported("INVALID_SMT_TIMEOUT")
        if contract.get("schema") != "c1-contract-v1":
            raise Unsupported("SMT_UNSUPPORTED_SCHEMA")
        interpretation = contract["interpretation"]["status"]
        if interpretation == "ambiguous":
            result.update(relation="AMBIGUOUS", reason="AMBIGUOUS_INTERPRETATION")
            return result
        if interpretation == "out_of_scope":
            result.update(relation="OUT_OF_SCOPE", reason="OUT_OF_SCOPE_INTERPRETATION")
            return result
        if interpretation != "reviewed":
            raise Unsupported("SMT_UNREVIEWED_ANCHOR")
        temporal = contract["time"]
        if ((temporal["kind"], temporal["horizon"]) not in {("state", 0), ("transition", 1)}
                or type(temporal["horizon"]) is not int):
            result.update(relation="OUT_OF_SCOPE", reason="OUT_OF_SCOPE_TIME_HORIZON")
            return result
        q = contract["quantifier"]
        if q not in {"forall", "exists"}:
            result.update(relation="OUT_OF_SCOPE", reason="OUT_OF_SCOPE_QUANTIFIER")
            return result
        if contract.get("obligation_quantifier", q) != q:
            result["reason"] = "MIXED_QUANTIFIERS"
            return result
        if contract["evidence_scope"]["kind"] != "finite":
            result.update(relation="OUT_OF_SCOPE", reason="OUT_OF_SCOPE_EVIDENCE")
            return result
        symbols, bounds = {}, []
        for name, declaration in contract["variables"].items():
            kind = declaration["type"]
            if kind == "bool":
                symbols[name] = (z3.Bool(name), "bool")
            elif kind == "int":
                lo, hi = declaration["min"], declaration["max"]
                if type(lo) is not int or type(hi) is not int or lo > hi:
                    raise Unsupported("SMT_INVALID_INTEGER_DOMAIN")
                term = z3.Int(name)
                symbols[name] = (term, "int")
                bounds.extend([term >= lo, term <= hi])
            else:
                result.update(relation="OUT_OF_SCOPE", reason="OUT_OF_SCOPE_VARIABLE_TYPE")
                return result
        if not symbols or len(symbols) > 16:
            raise Unsupported("SMT_VARIABLE_LIMIT")
        def predicate(expression):
            term, kind = _translate(expression, symbols)
            if kind != "bool":
                raise Unsupported("SMT_PREDICATE_REQUIRED")
            return term
        assumptions = [predicate(e) for e in contract["assumptions"]]
        exclusions = [z3.Not(predicate(e)) for e in contract["exceptions"]]
        domain = z3.And(*(bounds + assumptions + exclusions))
        c = predicate(contract["claim"])
        o = predicate(contract["obligation"])
        queries = result["queries"]
        queries["premises"] = _solve(domain, symbols, timeout_ms)
        if queries["premises"]["status"] == "unknown":
            result["reason"] = "SMT_UNKNOWN_PREMISES"
            return result
        if queries["premises"]["status"] == "unsat":
            result.update(premise_satisfiable=False, reason="INCONSISTENT_OR_EMPTY_PREMISES")
            return result
        result["premise_satisfiable"] = True
        queries["c_not_o"] = _solve(z3.And(domain, c, z3.Not(o)), symbols, timeout_ms)
        queries["o_not_c"] = _solve(z3.And(domain, o, z3.Not(c)), symbols, timeout_ms)
        if any(item["status"] == "unknown" for item in queries.values()):
            result["reason"] = "SMT_UNKNOWN_IMPLICATION"
            return result
        c_to_o = queries["c_not_o"]["status"] == "unsat"
        o_to_c = queries["o_not_c"]["status"] == "unsat"
        result["c_implies_o"], result["o_implies_c"] = c_to_o, o_to_c
        result["relation"] = {
            (True, True): "EQUIVALENT", (True, False): "NECESSARY_ONLY",
            (False, True): "SUFFICIENT_ONLY", (False, False): "INCOMPARABLE",
        }[c_to_o, o_to_c]
        result["reason"] = "Z3_SAT_UNSAT_PREDICATE_COMPARISON"
    except (Unsupported, KeyError, TypeError, ValueError, RecursionError) as exc:
        result["reason"] = str(exc) if isinstance(exc, Unsupported) else "SMT_INVALID_CONTRACT"
    except Exception as exc:
        # Optional solver errors fail closed without embedding machine paths.
        result["reason"] = "SMT_ERROR_" + type(exc).__name__
    finally:
        result["elapsed_seconds"] = time.perf_counter() - started
    return result


def crosscheck_dev(timeout_ms: int = 1000) -> dict:
    from .authority import analyze  # compare only after independent SMT result
    source = Path(__file__).parent / "fixtures" / "dev_contracts.json"
    cases = json.loads(source.read_text(encoding="utf-8"))["cases"]
    rows = []
    for case in cases:
        smt = solve_relation(case["contract"], timeout_ms)
        finite = analyze(case["contract"])
        parity = all(smt[field] == finite[field] for field in
                     ["relation", "premise_satisfiable", "c_implies_o", "o_implies_c"])
        rows.append({"id": case["id"], "parity": parity,
                     "finite_relation": finite["relation"], "smt": smt})
    return {
        "schema": "c1-z3-crosscheck-v1", "scope": "public development only; sealed holdout untouched",
        "solver_distribution": "z3-solver",
        "solver_package_version": importlib.metadata.version("z3-solver") if z3 else None,
        "solver_version": z3.get_version_string() if z3 else None,
        "timeout_ms_per_query": timeout_ms, "official_sources": OFFICIAL_SOURCES,
        "cases": len(rows), "parity_pass": sum(row["parity"] for row in rows),
        "sat_unsat_cases": sum(bool(row["smt"]["queries"]) for row in rows),
        "solver_unknown_cases": sum(row["smt"]["reason"].startswith("SMT_UNKNOWN") for row in rows),
        "independence": "separate typed SMT visitor; production analyze used only after SMT for parity; no gold labels read",
        "limitations": "cross-check of supplied formal predicates, not natural-language fidelity or real-world program behavior",
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-ms", type=int, default=1000)
    args = parser.parse_args()
    report = crosscheck_dev(args.timeout_ms)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["cases", "parity_pass", "sat_unsat_cases", "solver_unknown_cases"]}))
    return 0 if report["parity_pass"] == report["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
