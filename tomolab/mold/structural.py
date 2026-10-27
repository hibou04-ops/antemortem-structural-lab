"""Bounded public relation expressions, interpreted without executing Python.

Only integer arithmetic, comparisons, Boolean composition and ``abs`` are
accepted. These are declared relations, never source extracted from a target.
Canonical nodes use roles so renaming public parameters preserves relation IDs.
Z3 answers concern this finite contract, not implementation correctness.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from itertools import product

from .schema import (digest, exact_keys, integer, normalize_evidence,
                     point_from_inputs, point_to_inputs, roles, validate_spec)

TYPE = "structural-int-pair-predicate-v1"
MAX_NODES = 96
MAX_DEPTH = 16


def _checked_node(node, *, depth=0, count=None):
    """Validate serialized nodes too: caller-created JSON has no special trust."""
    if count is None:
        count = [0]
    count[0] += 1
    if count[0] > MAX_NODES or depth > MAX_DEPTH:
        raise ValueError("structural expression exceeds resource limit")
    if not isinstance(node, list) or not node or not isinstance(node[0], str):
        raise ValueError("invalid structural expression node")
    op = node[0]
    if op == "int":
        if len(node) != 2:
            raise ValueError("invalid integer node")
        integer(node[1], -2000000, 2000000, "expression integer")
        return "int"
    if op == "var":
        if len(node) != 2 or node[1] not in ("left", "right"):
            raise ValueError("invalid variable role")
        return "int"
    arity = {"neg": 1, "abs": 1, "not": 1, "add": 2, "sub": 2,
             "mul": 2, "mod": 2, "eq": 2, "ne": 2, "lt": 2,
             "le": 2, "gt": 2, "ge": 2}
    if op in ("and", "or"):
        if not 3 <= len(node) <= MAX_NODES:
            raise ValueError("invalid Boolean composition")
    elif op not in arity or len(node) != arity[op] + 1:
        raise ValueError("unsupported structural operator or arity")
    kinds = [_checked_node(child, depth=depth + 1, count=count) for child in node[1:]]
    expected = "bool" if op in ("not", "and", "or") else "int"
    if any(kind != expected for kind in kinds):
        raise ValueError("structural expression type mismatch")
    if op == "mul" and not any(child[0] == "int" for child in node[1:]):
        raise ValueError("multiplication requires an integer constant")
    if op == "mod" and (node[2][0] != "int" or node[2][1] <= 0):
        raise ValueError("modulo requires a positive integer constant")
    return "bool" if op in ("eq", "ne", "lt", "le", "gt", "ge", "not", "and", "or") else "int"


def validate_structural_relation(relation):
    exact_keys(relation, ("type", "expression"))
    if relation["type"] != TYPE or _checked_node(relation["expression"]) != "bool":
        raise ValueError("a structural relation must be a Boolean predicate")
    return deepcopy(relation)


def compile_relation(expression, spec):
    """Compile a public expression to typed role-based JSON; never eval/exec it.

    Supported: +, -, constant multiplication, positive-constant modulo,
    abs(integer), ==, !=, <, <=, >, >=, and/or/not and chained comparisons.
    Calls other than the explicitly interpreted abs form are rejected.
    """
    spec = validate_spec(spec)
    if not isinstance(expression, str) or not 1 <= len(expression) <= 2000:
        raise ValueError("expression must be bounded text")
    names = {var["name"]: var["role"] for var in spec["variables"]}
    try:
        parsed = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("invalid public relation expression") from exc
    if sum(1 for _ in ast.walk(parsed)) > MAX_NODES * 3:
        raise ValueError("structural expression exceeds resource limit")

    def convert(node, depth=0):
        if depth > MAX_DEPTH:
            raise ValueError("structural expression exceeds resource limit")
        visit = lambda child: convert(child, depth + 1)
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return ["int", node.value]
        if isinstance(node, ast.Name) and node.id in names:
            return ["var", names[node.id]]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
            child = visit(node.operand)
            if isinstance(node.op, ast.UAdd):
                if _checked_node(child) != "int":
                    raise ValueError("unary plus requires an integer expression")
                return child
            if isinstance(node.op, ast.USub) and child[0] == "int":
                return ["int", -child[1]]
            return ["not" if isinstance(node.op, ast.Not) else "neg", child]
        if isinstance(node, ast.BinOp):
            op = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Mod: "mod"}.get(type(node.op))
            if op:
                return [op, visit(node.left), visit(node.right)]
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            return ["and" if isinstance(node.op, ast.And) else "or", *map(visit, node.values)]
        if isinstance(node, ast.Compare):
            ops = {ast.Eq: "eq", ast.NotEq: "ne", ast.Lt: "lt", ast.LtE: "le", ast.Gt: "gt", ast.GtE: "ge"}
            operands = [node.left, *node.comparators]
            parts = []
            for index, op in enumerate(node.ops):
                if type(op) not in ops:
                    raise ValueError("unsupported comparison")
                parts.append([ops[type(op)], visit(operands[index]), visit(operands[index + 1])])
            return parts[0] if len(parts) == 1 else ["and", *parts]
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "abs" and node.func.id not in names
                and len(node.args) == 1 and not node.keywords):
            return ["abs", visit(node.args[0])]
        raise ValueError("unsupported Python syntax in public relation")

    return validate_structural_relation({"type": TYPE, "expression": convert(parsed.body)})


def structural_relation_id(relation):
    return "AST-" + digest(validate_structural_relation(relation))[:20]


def _interpret(node, left, right, z3=None):
    op = node[0]
    if op == "int":
        return node[1]
    if op == "var":
        return left if node[1] == "left" else right
    values = [_interpret(child, left, right, z3) for child in node[1:]]
    a = values[0]
    b = values[1] if len(values) > 1 else None
    if op == "neg":
        return -a
    if op == "abs":
        return abs(a) if z3 is None else z3.If(a >= 0, a, -a)
    if op == "not":
        return not a if z3 is None else z3.Not(a)
    if op == "and":
        return all(values) if z3 is None else z3.And(*values)
    if op == "or":
        return any(values) if z3 is None else z3.Or(*values)
    if op == "add":
        return a + b
    if op == "sub":
        return a - b
    if op == "mul":
        return a * b
    if op == "mod":
        return a % b
    if op == "eq":
        return a == b
    if op == "ne":
        return a != b
    if op == "lt":
        return a < b
    if op == "le":
        return a <= b
    if op == "gt":
        return a > b
    if op == "ge":
        return a >= b
    raise ValueError("unsupported structural operator")


def structural_holds(relation, inputs, spec):
    spec = validate_spec(spec)
    relation = validate_structural_relation(relation)
    return _interpret(relation["expression"], *point_from_inputs(inputs, spec))


def _points(spec):
    by_role = roles(spec)
    return tuple(product(*(range(by_role[role]["low"], by_role[role]["high"] + 1)
                           for role in ("left", "right"))))


def check_consistency(spec, relations, *, backend="enumeration", excluded=(), timeout_ms=2000):
    """Check the conjunction within public bounds, with a concrete SAT witness.

    An UNSAT core need not be minimal and is relative to the declared bounds
    and excluded inputs. Enumeration returns the complete conflicting set;
    Z3 supplies its tracked subset. UNKNOWN is never converted to UNSAT.
    """
    spec = validate_spec(spec)
    if not isinstance(relations, (list, tuple)) or len(relations) > 128:
        raise ValueError("at most 128 structural relations are accepted")
    clean = [validate_structural_relation(relation) for relation in relations]
    ids = [structural_relation_id(relation) for relation in clean]
    integer(timeout_ms, 1, 10000, "solver timeout")
    if backend not in ("enumeration", "z3"):
        raise ValueError("solver must be enumeration or z3")
    excluded_points = set()
    for index, point in enumerate(excluded):
        if index >= 4225 or not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("invalid excluded input")
        # Reuse the existing spec's exact type and domain validation.
        excluded_points.add(point_from_inputs(point_to_inputs(point, spec), spec))
    result = {"status": "UNSAT", "witness": None, "backend": backend,
              "unsat_core": sorted(set(ids)), "scope": "declared-bounds-and-exclusions"}
    if backend == "enumeration":
        for point in _points(spec):
            if point not in excluded_points and all(_interpret(r["expression"], *point) for r in clean):
                result.update(status="SAT", witness=point_to_inputs(point, spec), unsat_core=[])
                break
        return result
    try:
        import z3
    except ImportError as exc:
        raise ValueError("Z3 backend requires the 'solver' package extra") from exc
    left, right = z3.Ints("structural_left structural_right")
    by_role = roles(spec)
    solver = z3.Solver()
    solver.set(timeout=timeout_ms)
    for symbol, role in ((left, "left"), (right, "right")):
        solver.add(symbol >= by_role[role]["low"], symbol <= by_role[role]["high"])
    for point in excluded_points:
        solver.add(z3.Or(left != point[0], right != point[1]))
    labels = {}
    for index, relation in enumerate(clean):
        label = z3.Bool(f"structural_constraint_{index}")
        labels[str(label)] = ids[index]
        solver.assert_and_track(_interpret(relation["expression"], left, right, z3), label)
    status = solver.check()
    if status == z3.sat:
        model = solver.model()
        point = tuple(model.eval(symbol, model_completion=True).as_long() for symbol in (left, right))
        inputs = point_to_inputs(point, spec)
        if point in excluded_points or not all(structural_holds(relation, inputs, spec) for relation in clean):
            raise ValueError("Z3 witness failed concrete relation readback")
        result.update(status="SAT", witness=inputs, unsat_core=[])
    elif status == z3.unsat:
        result["unsat_core"] = sorted({labels[str(label)] for label in solver.unsat_core()})
    else:
        result.update(status="UNKNOWN", unsat_core=[], reason=solver.reason_unknown())
    return result


def filter_hypotheses(spec, relations, evidence):
    """Return alternative predicates consistent with structured development labels.

    This shares the existing Mold evidence contract. FAILURE supports predicate
    membership and REFUTATION rejects it; no labels or oracle calls are invented.
    Relations are alternatives, unlike check_consistency's conjunction. Exact
    canonical JSON duplicates share one hypothesis; semantic equivalence across
    different ASTs is not inferred.
    """
    spec = validate_spec(spec)
    if not isinstance(relations, (list, tuple)) or len(relations) > 128:
        raise ValueError("at most 128 structural hypotheses are accepted")
    input_count = len(relations)
    unique = {}
    for relation in relations:
        relation = validate_structural_relation(relation)
        unique.setdefault(structural_relation_id(relation), relation)
    clean = list(unique.values())
    if not isinstance(evidence, (list, tuple)) or len(evidence) > 8450:
        raise ValueError("evidence exceeds bounded protocol limit")
    events = [normalize_evidence(event, spec) for event in evidence]
    if len({event["evidence_id"] for event in events}) != len(events):
        raise ValueError("evidence_id must be unique")
    labels = {}
    inconsistent = False
    for event in events:
        point = point_from_inputs(event["inputs"], spec)
        label = event["kind"] == "FAILURE"
        inconsistent |= point in labels and labels[point] != label
        labels[point] = label
    remaining, contradictions = [], []
    for relation in clean:
        rid = structural_relation_id(relation)
        rejected = [event["evidence_id"] for event in events
                    if structural_holds(relation, event["inputs"], spec) != (event["kind"] == "FAILURE")]
        if rejected:
            contradictions.append({"constraint_id": rid, "evidence_ids": rejected})
        else:
            remaining.append({"constraint_id": rid, "relation": relation})
    status = "INCONSISTENT_EVIDENCE" if inconsistent else "HYPOTHESES_REMAIN" if remaining else "OUT_OF_GRAMMAR"
    if not events:
        status = "NO_EVIDENCE"
    return {"status": status, "version_space": remaining, "contradictions": contradictions,
            "evidence_count": len(events), "input_count": input_count,
            "unique_hypotheses": len(clean), "duplicate_hypotheses": input_count - len(clean),
            "claim": "bounded membership hypotheses; no causal or generalization proof"}
