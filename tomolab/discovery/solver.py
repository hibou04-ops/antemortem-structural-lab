"""Generator-safe Z3 queries over public typed JSON predicates.

SAT witnesses are decoded and checked with the exact concrete interpreter.
Unsupported semantics abstain with UNKNOWN; no file, source or Oracle callback
is accepted. Floats are deliberately not approximated as mathematical reals.
"""
from __future__ import annotations

import time

from .schema import canonical, integer, validate_inputs, validate_spec


class _Unsupported(ValueError):
    pass


def _default(schema):
    kind = schema["kind"]
    if kind in ("int", "float"):
        result = min(schema["max"], max(schema["min"], 0))
        return float(result) if kind == "float" else result
    if kind == "str":
        return schema["choices"][0] if "choices" in schema else schema["alphabet"][:1] * schema["min_size"]
    if kind == "list":
        return [_default(schema["items"]) for _ in range(schema["min_size"])]
    if kind == "tuple":
        return [_default(item) for item in schema["items"]]
    return {key: _default(schema["values"]) for key in schema["keys"][:schema["min_size"]]}


def solve_predicates(spec, predicates, *, mode="all", excluded=(), timeout_ms=1000):
    """Find consistency or disagreement witnesses using the shared JSON DSL.

    Exact subset: bounded integers, ASCII strings, list/tuple lengths and integer
    elements, sum, nonempty min/max, constant multiplication and positive
    constant modulo. Composite/float semantics outside that subset return
    UNKNOWN. UNSAT concerns only this declared finite/bounded contract.
    """
    from .predicates import predicate_holds, validate_predicate
    started, cpu = time.perf_counter(), time.process_time()
    spec = validate_spec(spec)
    integer(timeout_ms, 1, 10000)
    if mode not in ("all", "any", "disagreement"):
        raise ValueError("unsupported predicate solver mode")
    if not isinstance(predicates, (list, tuple)) or len(predicates) > 128:
        raise ValueError("bounded public predicate list required")
    clean = [validate_predicate(p, spec) for p in predicates]
    if mode == "disagreement" and len(clean) < 2:
        raise ValueError("disagreement requires two or more predicates")
    if not isinstance(excluded, (list, tuple)) or len(excluded) > 8192:
        raise ValueError("bounded excluded inputs required")
    excluded = [validate_inputs(point, spec) for point in excluded]
    result = {"status": "UNKNOWN", "witness": None, "backend": "Z3", "mode": mode,
              "timeout_ms": timeout_ms, "scope": "public typed predicates and declared bounds",
              "concrete_readback": "NOT_APPLICABLE"}
    try:
        import z3
    except ImportError:
        result["reason"] = "Z3 optional dependency is not installed"
        return result
    solver = z3.Solver()
    solver.set(timeout=timeout_ms)
    declared = {}

    def scalar(schema, name):
        kind = schema["kind"]
        if kind == "int":
            value = z3.Int(name)
            solver.add(value >= schema["min"], value <= schema["max"])
            return {"kind": kind, "value": value, "schema": schema}
        if kind == "str":
            if schema["max_size"] > 16 or len(schema["alphabet"]) > 32 or any(not 1 <= ord(c) <= 127 for c in schema["alphabet"]):
                raise _Unsupported("Z3 strings require bounded non-NUL ASCII alphabet and length at most 16")
            value = z3.String(name)
            solver.add(z3.Length(value) >= schema["min_size"], z3.Length(value) <= schema["max_size"])
            if "choices" in schema:
                solver.add(z3.Or(*(value == z3.StringVal(choice) for choice in schema["choices"])))
            else:
                for i in range(schema["max_size"]):
                    allowed = [z3.SubString(value, i, 1) == z3.StringVal(c) for c in schema["alphabet"]]
                    solver.add(z3.Implies(z3.Length(value) > i, z3.Or(*allowed)))
            return {"kind": kind, "value": value, "schema": schema}
        raise _Unsupported("Z3 does not approximate floats or nested scalar objects")

    def domain(schema, name):
        kind = schema["kind"]
        if kind in ("int", "str", "float"):
            return scalar(schema, name)
        if kind == "tuple":
            return {"kind": kind, "length": z3.IntVal(len(schema["items"])),
                    "items": [scalar(t, name + "_" + str(i)) for i, t in enumerate(schema["items"])],
                    "schema": schema}
        if kind == "list":
            length = z3.Int(name + "_length")
            solver.add(length >= schema["min_size"], length <= schema["max_size"])
            if schema["items"]["kind"] not in ("int", "str"):
                raise _Unsupported("Z3 list witnesses require integer or ASCII-string elements")
            return {"kind": kind, "length": length,
                    "items": [scalar(schema["items"], name + "_" + str(i)) for i in range(schema["max_size"])],
                    "schema": schema}
        raise _Unsupported("Z3 dictionary and nested composite witnesses are unsupported")

    def decode(item, model):
        if item["kind"] == "int":
            return model.eval(item["value"], model_completion=True).as_long()
        if item["kind"] == "str":
            return model.eval(item["value"], model_completion=True).as_string()
        length = model.eval(item["length"], model_completion=True).as_long()
        return [decode(child, model) for child in item["items"][:length]]

    def equals(item, value):
        if item["kind"] in ("int", "str"):
            return item["value"] == value
        return z3.And(item["length"] == len(value), *(equals(child, v) for child, v in zip(item["items"], value)))

    def numeric(item):
        if isinstance(item, dict):
            if item["kind"] not in ("int", "str"):
                raise _Unsupported("composite variables require len, sum, min or max")
            return item["value"]
        return item

    def term(node):
        if type(node) is bool:
            return z3.BoolVal(node)
        if type(node) in (int, str):
            return node
        if type(node) is float:
            raise _Unsupported("IEEE float terms are not mathematical reals")
        if set(node) == {"var"}:
            return declared[node["var"]]
        if node.get("op") in ("eq", "ne", "lt", "le", "gt", "ge", "and", "or", "not"):
            return boolean(node)
        op, args = node["op"], node["args"]
        values = [term(arg) for arg in args]
        first = values[0]
        if op == "len":
            if not isinstance(first, dict) or first["kind"] not in ("str", "list", "tuple"):
                raise _Unsupported("len requires a declared string or sequence")
            return z3.Length(first["value"]) if first["kind"] == "str" else first["length"]
        if op in ("sum", "min", "max"):
            if not isinstance(first, dict) or first["kind"] not in ("list", "tuple") or any(x["kind"] != "int" for x in first["items"]):
                raise _Unsupported("numeric sequence operation requires integer elements")
            if op == "sum":
                return z3.Sum(*(z3.If(first["length"] > i, child["value"], 0) for i, child in enumerate(first["items"])))
            minimum = len(first["items"]) if first["kind"] == "tuple" else first["schema"]["min_size"]
            if minimum < 1:
                raise _Unsupported("min/max of potentially empty sequences requires concrete-only semantics")
            value = first["items"][0]["value"]
            for i, child in enumerate(first["items"][1:], 1):
                comparison = child["value"] < value if op == "min" else child["value"] > value
                value = z3.If(z3.And(first["length"] > i, comparison), child["value"], value)
            return value
        values = [numeric(value) for value in values]
        if op in ("add", "sub"):
            return values[0] + values[1] if op == "add" else values[0] - values[1]
        if op == "mul":
            if not any(type(arg) is int for arg in args):
                raise _Unsupported("nonlinear multiplication is outside the exact solver subset")
            return values[0] * values[1]
        if op == "mod":
            if type(args[1]) is not int or args[1] <= 0:
                raise _Unsupported("modulo requires a positive constant divisor")
            return values[0] % values[1]
        if op == "neg":
            return -values[0]
        if op == "abs":
            return z3.If(values[0] >= 0, values[0], -values[0])
        raise _Unsupported("unsupported term operation")

    def boolean(node):
        if type(node) is bool:
            return z3.BoolVal(node)
        op = node["op"]
        if op in ("and", "or", "not"):
            expressions = [boolean(arg) for arg in node["args"]]
            return z3.And(*expressions) if op == "and" else z3.Or(*expressions) if op == "or" else z3.Not(expressions[0])
        left, right = numeric(term(node["left"])), numeric(term(node["right"]))
        try:
            if op == "eq":
                return left == right
            if op == "ne":
                return left != right
            if op == "lt":
                return left < right
            if op == "le":
                return left <= right
            if op == "gt":
                return left > right
            if op == "ge":
                return left >= right
        except (TypeError, z3.Z3Exception) as exc:
            raise _Unsupported("comparison is outside exact Z3/Python correspondence") from exc
        raise _Unsupported("unsupported predicate operation")

    try:
        for i, item in enumerate(spec["inputs"]):
            declared[item["role"]] = domain(item["type"], "e5_" + str(i))
        expressions = [boolean(p) for p in clean]
        query = z3.And(*expressions) if mode == "all" else z3.Or(*expressions)
        if mode == "disagreement":
            query = z3.And(z3.Or(*expressions), z3.Not(z3.And(*expressions)))
        solver.add(query)
        for point in excluded:
            solver.add(z3.Not(z3.And(*(equals(declared[item["role"]], point[item["name"]]) for item in spec["inputs"]))))
        status = solver.check()
        if status == z3.sat:
            model = solver.model()
            try:
                witness = {item["name"]: decode(declared[item["role"]], model) for item in spec["inputs"]}
                witness = validate_inputs(witness, spec)
            except (ValueError, TypeError, OverflowError, z3.Z3Exception) as exc:
                raise _Unsupported("symbolic witness failed declared Python input-domain readback") from exc
            votes = [predicate_holds(p, witness, spec) for p in clean]
            valid = all(votes) if mode == "all" else any(votes)
            if mode == "disagreement":
                valid = any(votes) and not all(votes)
            if not valid or canonical(witness) in {canonical(p) for p in excluded}:
                result["reason"] = "symbolic witness failed exact concrete Python readback"
            else:
                result.update(status="SAT", witness=witness, concrete_readback="PASS")
        elif status == z3.unsat:
            result["status"] = "UNSAT"
        else:
            result["reason"] = solver.reason_unknown()
    except _Unsupported as exc:
        result["reason"] = str(exc)
    result["wall_seconds"] = time.perf_counter() - started
    result["cpu_seconds"] = time.process_time() - cpu
    return result
