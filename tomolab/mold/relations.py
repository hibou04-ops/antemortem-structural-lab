"""A finite typed relation grammar with enumeration and optional Z3 checks."""
from __future__ import annotations

from functools import lru_cache
from itertools import product

from .schema import digest, exact_keys, integer, roles, validate_spec

FAMILIES = ("sum", "difference", "abs_difference", "abs_sum", "sum_mod2", "sum_mod3", "sum_mod5")


def feature(family, left, right):
    if family == "sum":
        return left + right
    if family == "difference":
        return left - right
    if family == "abs_difference":
        return abs(left - right)
    if family == "abs_sum":
        return abs(left + right)
    if family.startswith("sum_mod"):
        return (left + right) % int(family[-1])
    raise ValueError("unknown relation family")


def validate_relation(relation):
    exact_keys(relation, ("family", "operator", "value", "type"))
    if relation["family"] not in FAMILIES or relation["operator"] not in ("eq", "le", "ge") or relation["type"] != "int-pair-predicate":
        raise ValueError("unsupported typed relation")
    integer(relation["value"], -2000000, 2000000, "relation value")
    return dict(relation)


def holds(relation, point):
    value = feature(relation["family"], *point)
    return {"eq": value == relation["value"], "le": value <= relation["value"],
            "ge": value >= relation["value"]}[relation["operator"]]


def relation_id(relation):
    return "R-" + digest(relation)[:20]


def bounds(spec):
    by_role = roles(spec)
    return tuple(by_role[r][k] for r in ("left", "right") for k in ("low", "high"))


@lru_cache(maxsize=8)
def universe(bound_tuple):
    a, b, c, d = bound_tuple
    points = tuple(product(range(a, b + 1), range(c, d + 1)))
    relations = []
    masks = []
    full = (1 << len(points)) - 1
    for family in FAMILIES:
        values = [feature(family, *p) for p in points]
        for threshold in sorted(set(values)):
            for op in ("eq", "le", "ge"):
                relation = {"family": family, "operator": op, "value": threshold, "type": "int-pair-predicate"}
                mask = 0
                for i, value in enumerate(values):
                    yes = value == threshold if op == "eq" else value <= threshold if op == "le" else value >= threshold
                    if yes:
                        mask |= 1 << i
                # Tautological / unsatisfiable predicates have no query value.
                if mask and mask != full:
                    relations.append(relation)
                    masks.append(mask)
    if len(relations) > 2048 or len(points) > 4225:
        raise ValueError("bounded grammar exceeds resource limit")
    return points, tuple(relations), tuple(masks)


def _z3_expr(relation, left, right, z3):
    family = relation["family"]
    if family == "sum":
        value = left + right
    elif family == "difference":
        value = left - right
    elif family == "abs_difference":
        delta = left - right
        value = z3.If(delta >= 0, delta, -delta)
    elif family == "abs_sum":
        total = left + right
        value = z3.If(total >= 0, total, -total)
    else:
        value = (left + right) % int(family[-1])
    return {"eq": value == relation["value"], "le": value <= relation["value"],
            "ge": value >= relation["value"]}[relation["operator"]]


def solve(spec, relation, other=None, *, backend="enumeration", excluded=()):
    """Find a bounded satisfying/disagreement witness, never an oracle verdict."""
    validate_spec(spec)
    relation = validate_relation(relation)
    if other is not None:
        other = validate_relation(other)
    if backend not in ("enumeration", "z3"):
        raise ValueError("solver must be enumeration or z3")
    excluded = set(tuple(p) for p in excluded)
    if backend == "enumeration":
        for point in universe(bounds(spec))[0]:
            if point in excluded:
                continue
            yes = holds(relation, point)
            if yes if other is None else yes != holds(other, point):
                return {"status": "SAT", "witness": list(point), "backend": backend}
        return {"status": "UNSAT", "witness": None, "backend": backend}
    try:
        import z3
    except ImportError as exc:
        raise ValueError("Z3 backend requires the 'solver' package extra") from exc
    left, right = z3.Ints("mold_left mold_right")
    a, b, c, d = bounds(spec)
    solver = z3.Solver()
    solver.set(timeout=2000)
    solver.add(left >= a, left <= b, right >= c, right <= d)
    expr = _z3_expr(relation, left, right, z3)
    solver.add(expr if other is None else z3.Xor(expr, _z3_expr(other, left, right, z3)))
    for x, y in excluded:
        solver.add(z3.Or(left != x, right != y))
    result = solver.check()
    if result == z3.sat:
        model = solver.model()
        return {"status": "SAT", "witness": [model.eval(left).as_long(), model.eval(right).as_long()], "backend": backend}
    return {"status": "UNSAT" if result == z3.unsat else "UNKNOWN", "witness": None, "backend": backend}
