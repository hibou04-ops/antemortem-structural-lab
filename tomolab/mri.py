"""Restricted, non-executing AST inspection. Not a general static analyzer."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from .model import Guard, Inspection, Proposal

OPS = {
    ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=",
    ast.Gt: ">", ast.GtE: ">=",
}
REVERSE = {"==": "==", "!=": "!=", ">": "<", "<": ">", ">=": "<=", "<=": ">="}


def _int_literal(node: ast.expr) -> int | None:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and
            isinstance(node.operand, ast.Constant) and type(node.operand.value) is int):
        return -node.operand.value
    return None


def _parse_comparison(expr: ast.expr, params: set[str]) -> tuple[str, str, int] | None:
    if not isinstance(expr, ast.Compare) or len(expr.ops) != 1 or len(expr.comparators) != 1:
        return None
    op = OPS.get(type(expr.ops[0]))
    if op is None:
        return None
    lhs, rhs = expr.left, expr.comparators[0]
    if isinstance(lhs, ast.Name) and lhs.id in params and _int_literal(rhs) is not None:
        return lhs.id, op, _int_literal(rhs)
    if isinstance(rhs, ast.Name) and rhs.id in params and _int_literal(lhs) is not None:
        return rhs.id, REVERSE[op], _int_literal(lhs)
    return None


def inspect_file(path: Path, function: str = "implementation") -> Inspection:
    path = path.resolve(strict=True)
    data = path.read_bytes()
    text = data.decode("utf-8")
    tree = ast.parse(text, filename=str(path))
    defs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function]
    if len(defs) != 1 or isinstance(defs[0], ast.AsyncFunctionDef):
        raise ValueError(f"expected one synchronous top-level function named {function!r}")
    fn = defs[0]
    args = fn.args
    if args.vararg or args.kwarg or args.kwonlyargs or args.posonlyargs or args.defaults:
        raise ValueError("v0.1 accepts only ordinary positional required integer parameters")
    parameters = tuple(n.arg for n in args.args)
    if not (1 <= len(parameters) <= 4):
        raise ValueError("v0.1 accepts 1–4 positional parameters")
    guards: list[Guard] = []
    limitations: list[str] = []

    def traverse(stmts: list[ast.stmt], ancestors: tuple[int, ...]) -> None:
        for stmt in stmts:
            if isinstance(stmt, ast.If):
                parsed = _parse_comparison(stmt.test, set(parameters))
                if parsed and stmt.body:
                    name, op, val = parsed
                    guards.append(Guard(stmt.lineno, name, op, val,
                                        stmt.body[0].lineno, ancestors))
                    traverse(stmt.body, ancestors + (stmt.lineno,))
                else:
                    limitations.append(f"line {stmt.lineno}: unsupported condition, descendants omitted")
                # The else arm may be analyzed independently, not as evidence of the true arm.
                if stmt.orelse:
                    limitations.append(f"line {stmt.lineno}: else/elif constraints are not modeled")
            elif isinstance(stmt, (ast.For, ast.While, ast.Try, ast.With, ast.Match)):
                limitations.append(f"line {stmt.lineno}: control structure not modeled")

    traverse(fn.body, ())
    return Inspection(str(path), hashlib.sha256(data).hexdigest(), function,
                      parameters, tuple(guards), tuple(limitations))


def static_proposals(inspection: Inspection, low: int, high: int, *, outer_only: bool = False) -> list[Proposal]:
    proposals: list[Proposal] = []
    seen: set[tuple[int, ...]] = set()
    for guard in inspection.guards:
        if outer_only and guard.ancestors:
            continue
        value = guard.satisfy()
        if not low <= value <= high:
            continue
        values = dict.fromkeys(inspection.parameters, max(low, min(0, high)))
        values[guard.name] = value
        args = tuple(values[p] for p in inspection.parameters)
        if args not in seen:
            proposals.append(Proposal(args, f"MRI predicate {guard.name} {guard.op} {guard.constant} @L{guard.line}",
                                      "static", guard.line))
            seen.add(args)
    return proposals


def predicted_trace(inspection: Inspection, args: tuple[int, ...]) -> set[int]:
    """Prediction is valid only for the narrow, supported nested-if grammar."""
    vals = dict(zip(inspection.parameters, args))
    guards = {g.line: g for g in inspection.guards}
    predicted = set()
    for g in inspection.guards:
        if all(guards[a].test(vals[guards[a].name]) for a in g.ancestors):
            predicted.add(g.line)
    return predicted
