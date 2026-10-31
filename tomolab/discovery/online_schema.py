"""Bounded public input language and shared, hand-written edit operators.

Operators are COMMON_PRIOR. Learning which operators to use does not invent
them. Only JSON values are supported; no expressions or import strings run.
"""
from copy import deepcopy
import math

from .schema import canonical, digest

KINDS = ("int", "float", "sequence_int", "sequence_float", "text", "mapping", "state_trace", "graph")
OPERATORS = ("identity", "boundary", "adjacent", "negate", "delete", "append", "duplicate",
             "reverse", "constantize", "rotate", "key_alias", "trace_delete", "trace_duplicate",
             "graph_edge_delete", "graph_self_loop")


def validate_contract(contract):
    if not isinstance(contract, dict) or contract.get("kind") not in KINDS:
        raise ValueError("UNSUPPORTED input contract")
    allowed = {"kind", "low", "high", "min_size", "max_size", "alphabet", "actions", "max_nodes",
               "comparison", "description", "preconditions"}
    if set(contract) - allowed:
        raise ValueError("unsupported contract fields")
    if type(contract.get("description", "")) is not str or len(contract.get("description", "")) > 4096:
        raise ValueError("bounded public contract description required")
    lo, hi = contract.get("low", -16), contract.get("high", 16)
    if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 10**12 for v in (lo, hi)) or lo > hi:
        raise ValueError("bounded finite ordered numeric limits required")
    if contract["kind"] in ("int", "sequence_int", "mapping", "state_trace") and any(type(v) is not int for v in (lo, hi)):
        raise ValueError("integer contract limits required")
    a, b = contract.get("min_size", 0), contract.get("max_size", 8)
    if any(type(v) is not int for v in (a, b)) or not 0 <= a <= b <= 64:
        raise ValueError("bounded sizes required")
    alphabet = contract.get("alphabet", "ab01")
    if not isinstance(alphabet, str) or not 1 <= len(alphabet) <= 64:
        raise ValueError("bounded nonempty alphabet required")
    actions = contract.get("actions", ["push", "pop", "peek"])
    if not isinstance(actions, list) or not 1 <= len(actions) <= 16 or any(type(x) is not str or not 1 <= len(x) <= 32 for x in actions):
        raise ValueError("bounded action vocabulary required")
    if type(contract.get("max_nodes", 6)) is not int or not 0 <= contract.get("max_nodes", 6) <= 16:
        raise ValueError("bounded graph node count required")
    comparison = contract.get("comparison", {})
    if not isinstance(comparison, dict) or set(comparison) - {"absolute", "relative", "nan_equal", "exception_policy", "expected_exceptions"}:
        raise ValueError("unsupported comparison contract")
    for key in ("absolute", "relative"):
        value = comparison.get(key, 0)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("bounded nonnegative comparison tolerance required")
    if type(comparison.get("nan_equal", False)) is not bool or comparison.get("exception_policy", "match_type") not in ("match_type", "unexpected"):
        raise ValueError("unsupported comparison policy")
    exceptions = comparison.get("expected_exceptions", [])
    if not isinstance(exceptions, list) or len(exceptions) > 16 or any(type(x) is not str or not 1 <= len(x) <= 160 for x in exceptions):
        raise ValueError("bounded explicit expected exception names required")
    if contract.get("preconditions", []) not in ([], ["nonempty"], ["nonzero"], ["acyclic"]):
        raise ValueError("UNSUPPORTED precondition; provide a reviewed adapter/domain")
    return deepcopy(contract)


def validate_input(point, contract):
    """Return a domain decision; no target or Oracle calls occur here."""
    validate_contract(contract)
    kind, lo, hi = contract["kind"], contract.get("low", -16), contract.get("high", 16)
    small, large = contract.get("min_size", 0), contract.get("max_size", 8)
    integer = lambda x: type(x) is int and lo <= x <= hi
    number = lambda x: type(x) in (int, float) and math.isfinite(x) and lo <= x <= hi
    size = lambda x: small <= len(x) <= large
    if kind == "int":
        valid = integer(point)
    elif kind == "float":
        valid = type(point) is float and number(point)
    elif kind in ("sequence_int", "sequence_float"):
        check = integer if kind == "sequence_int" else number
        valid = type(point) is list and size(point) and all(check(x) for x in point)
    elif kind == "text":
        valid = type(point) is str and size(point) and all(c in contract.get("alphabet", "ab01") for c in point)
    elif kind == "mapping":
        alphabet = contract.get("alphabet", "ab01")
        valid = type(point) is dict and size(point) and all(type(k) is str and len(k) <= 8 and all(c in alphabet for c in k) and integer(v) for k, v in point.items())
    elif kind == "state_trace":
        valid = type(point) is list and size(point) and all(type(x) is dict and set(x) == {"op", "value"} and x["op"] in contract.get("actions", ["push", "pop", "peek"]) and integer(x["value"]) for x in point)
    else:
        valid = (type(point) is dict and set(point) == {"n", "edges"} and type(point["n"]) is int
                 and 0 <= point["n"] <= contract.get("max_nodes", 6) and type(point["edges"]) is list
                 and size(point["edges"]) and all(type(e) is list and len(e) == 2 and all(type(i) is int and 0 <= i < point["n"] for i in e) for e in point["edges"]))
    if not valid:
        return False
    for condition in contract.get("preconditions", []):
        if condition == "nonempty" and not point:
            return False
        if condition == "nonzero" and point == 0:
            return False
        if condition == "acyclic":
            adjacency = {i: [] for i in range(point["n"])}
            for u, v in point["edges"]:
                adjacency[u].append(v)
            done, active = set(), set()
            def visit(u):
                if u in active:
                    return False
                if u in done:
                    return True
                active.add(u)
                if not all(visit(v) for v in adjacency[u]):
                    return False
                active.remove(u); done.add(u)
                return True
            if not all(visit(u) for u in adjacency):
                return False
    return True


def public_numeric_literals(contract, structure=None):
    """Shared COMMON_PRIOR from automatic target MRI, never Oracle modules."""
    lo, hi = contract.get("low", -16), contract.get("high", 16)
    floating = contract["kind"] in ("float", "sequence_float")
    values = []
    for literal in (structure or {}).get("literals", []):
        if type(literal) not in (int, float) or not math.isfinite(literal):
            continue
        if not floating and type(literal) is not int:
            continue
        value = float(literal) if floating else literal
        neighbours = [value, math.nextafter(value, -math.inf), math.nextafter(value, math.inf)] if floating else [value, value-1, value+1]
        for candidate in neighbours:
            if math.isfinite(candidate) and lo <= candidate <= hi and candidate not in values:
                values.append(candidate)
    return values[:192]


def hypothesis_strategy(contract, structure=None):
    """Native Hypothesis SearchStrategy. No .example() or private engine API."""
    from hypothesis import strategies as st
    validate_contract(contract)
    kind, lo, hi = contract["kind"], contract.get("low", -16), contract.get("high", 16)
    sizes = dict(min_size=contract.get("min_size", 0), max_size=contract.get("max_size", 8))
    ints = st.integers(int(lo), int(hi))
    floats = st.floats(float(lo), float(hi), allow_nan=False, allow_infinity=False)
    literals = public_numeric_literals(contract, structure)
    if literals:
        if contract["kind"] in ("float", "sequence_float"):
            floats = st.one_of(floats, st.sampled_from(literals))
        else:
            ints = st.one_of(ints, st.sampled_from(literals))
    if kind == "int":
        result = ints
    elif kind == "float":
        result = floats
    elif kind in ("sequence_int", "sequence_float"):
        result = st.lists(ints if kind == "sequence_int" else floats, **sizes)
    elif kind == "text":
        result = st.text(alphabet=contract.get("alphabet", "ab01"), **sizes)
        texts = [v for v in (structure or {}).get("literals", []) if type(v) is str and validate_input(v, contract)]
        if texts:
            result = st.one_of(result, st.sampled_from(texts))
    elif kind == "mapping":
        keys = st.text(alphabet=contract.get("alphabet", "ab01"), min_size=0, max_size=8)
        literal_keys = [v for v in (structure or {}).get("literals", []) if type(v) is str and len(v) <= 8 and all(c in contract.get("alphabet", "ab01") for c in v)]
        if literal_keys:
            keys = st.one_of(keys, st.sampled_from(literal_keys))
        result = st.dictionaries(keys, ints, **sizes)
    elif kind == "state_trace":
        action = st.fixed_dictionaries({"op": st.sampled_from(contract.get("actions", ["push", "pop", "peek"])), "value": ints})
        result = st.lists(action, **sizes)
    else:
        @st.composite
        def graphs(draw):
            n = draw(st.integers(0, contract.get("max_nodes", 6)))
            if not n:
                return {"n": 0, "edges": []}
            edge = st.lists(st.integers(0, n - 1), min_size=2, max_size=2)
            return {"n": n, "edges": draw(st.lists(edge, **sizes))}
        result = graphs()
    return result.filter(lambda point: validate_input(point, contract))


def common_operators(kind):
    base = ("identity", "boundary", "adjacent")
    if kind in ("int", "float"):
        return base + ("negate",)
    if kind.startswith("sequence_"):
        return base + ("negate", "delete", "append", "duplicate", "reverse", "constantize", "rotate")
    if kind == "text":
        return base + ("delete", "append", "duplicate", "reverse", "constantize", "rotate")
    if kind == "mapping":
        return base + ("delete", "append", "key_alias", "constantize")
    if kind == "state_trace":
        return ("identity", "trace_delete", "trace_duplicate", "reverse", "rotate", "append")
    if kind == "graph":
        return ("identity", "graph_edge_delete", "graph_self_loop", "reverse", "append")
    return ()


def apply_edit(point, operator, contract, structure=None):
    """Deterministic public edit. None means rejected, never a negative label."""
    if operator not in OPERATORS:
        raise ValueError("unknown COMMON_PRIOR operator")
    if not validate_input(point, contract):
        return None
    result, kind = deepcopy(point), contract["kind"]
    lo, hi = contract.get("low", -16), contract.get("high", 16)
    literals = [x for x in (structure or {}).get("literals", []) if type(x) in (int, float) and math.isfinite(x) and lo <= x <= hi]
    pivot = literals[0] if literals else (0 if lo <= 0 <= hi else lo)
    if kind == "float":
        pivot = float(pivot)
    if kind in ("int", "sequence_int", "mapping", "state_trace"):
        pivot = int(pivot)
    if operator == "identity":
        pass
    elif type(result) in (int, float):
        if operator == "boundary":
            result = pivot
        elif operator == "adjacent":
            result = math.nextafter(result, math.inf) if type(result) is float else result + 1
        elif operator == "negate":
            result = -result
    elif kind in ("sequence_int", "sequence_float", "text", "state_trace"):
        if operator in ("delete", "trace_delete"):
            result = result[:-1]
        elif operator in ("duplicate", "trace_duplicate"):
            result = result + result[-1:] if result else result
        elif operator == "reverse":
            result = result[::-1]
        elif operator == "rotate":
            result = result[1:] + result[:1]
        elif operator == "constantize" and result:
            result = result[0] * len(result) if kind == "text" else [deepcopy(result[0]) for _ in result]
        elif operator == "append":
            value = contract.get("alphabet", "ab01")[0] if kind == "text" else ({"op": contract.get("actions", ["push"])[0], "value": pivot} if kind == "state_trace" else pivot)
            result = result + (value if kind == "text" else [value])
        elif operator == "boundary" and result:
            result = contract.get("alphabet", "ab01")[0] * len(result) if kind == "text" else [pivot for _ in result]
        elif operator == "adjacent" and result and kind != "text" and kind != "state_trace":
            result[0] = math.nextafter(float(result[0]), math.inf) if kind == "sequence_float" else result[0] + 1
        elif operator == "negate" and kind.startswith("sequence_"):
            result = [-x for x in result]
    elif kind == "mapping":
        if operator == "delete" and result:
            result.pop(sorted(result)[-1])
        elif operator in ("append", "key_alias"):
            keys = sorted(result)
            key = (keys[0] + contract.get("alphabet", "ab01")[0]) if keys else contract.get("alphabet", "ab01")[0]
            result[key] = result[keys[0]] if keys and operator == "key_alias" else pivot
        elif operator in ("boundary", "constantize"):
            result = {k: pivot for k in result}
        elif operator == "adjacent" and result:
            result[sorted(result)[0]] += 1
    elif kind == "graph":
        if operator == "graph_edge_delete":
            result["edges"] = result["edges"][:-1]
        elif operator == "graph_self_loop" and result["n"]:
            result["edges"].append([0, 0])
        elif operator == "reverse":
            result["edges"] = [[v, u] for u, v in result["edges"]]
        elif operator == "append" and result["n"] > 1:
            result["edges"].append([0, result["n"] - 1])
    return result if validate_input(result, contract) else None


def input_identity(point):
    def ordered(value):
        if type(value) is dict:
            return ["mapping", [[key, ordered(item)] for key, item in value.items()]]
        if type(value) is list:
            return ["sequence", [ordered(item) for item in value]]
        if type(value) is float:
            return ["float", value.hex()]
        if value is None or type(value) in (str, int, bool):
            return [type(value).__name__, value]
        raise ValueError("input identity supports bounded JSON values only")
    return digest({"ordered_input": ordered(point)})


def validate_online_parameters(contract, method, seed, budget, shrink_budget, max_seconds, mold):
    # All methods load the same public runtime modules before Hypothesis mines
    # module constants. Only D receives actual Source-learned data.
    from .online_mold import validate_mold
    from . import recursive_observe, recursive_policy  # same data-only imports for opt-in/off
    contract = validate_contract(contract)
    if type(method) is not str or method.removeprefix("E9_") not in ("A", "B", "C", "D"):
        raise ValueError("method must be A/B/C/D")
    method = method.removeprefix("E9_")
    if type(seed) is not int or not 0 <= seed < 2**32 or type(budget) is not int or not 3 <= budget <= 10000:
        raise ValueError("bounded seed and call budget required")
    if type(shrink_budget) is not int or not 0 <= shrink_budget <= budget // 2:
        raise ValueError("shrinking is a bounded part of the total call budget")
    if type(max_seconds) not in (int, float) or not math.isfinite(max_seconds) or not 0 < max_seconds <= 3600:
        raise ValueError("bounded positive wall limit required")
    if method != "D" and mold is not None:
        raise ValueError("only D receives Source-learned Mold")
    if mold is not None:
        validate_mold(mold)
    return contract, method


def validate_online_config(config):
    """The same whitelist runs before transport and inside the fresh worker."""
    required = {"contract", "structure", "method", "seed", "budget", "shrink_budget", "mold", "replays", "max_seconds", "_started"}
    if type(config) is not dict or not required <= set(config) or set(config)-required-{"diagnostics", "selector"}:
        raise ValueError("only public online configuration fields may cross")
    validate_online_parameters(*(config[key] for key in ("contract", "method", "seed", "budget", "shrink_budget", "max_seconds", "mold")))
    if "diagnostics" in config:
        from .recursive_observe import validate_public_diagnostics
        validate_public_diagnostics(config["diagnostics"])
        if config["method"] != "C":
            raise ValueError("paired diagnostics require unmodified C transport")
    if "selector" in config:
        from .recursive_policy import validate_selector
        if config["method"] != "D" or config["mold"] is None:
            raise ValueError("selector requires explicit D and frozen Mold")
        selector = validate_selector(config["selector"], mold_digest=config["mold"]["artifact_digest"])
        if selector["input_contract_digest"] is not None and selector["input_contract_digest"] != digest(config["contract"]):
            raise ValueError("selector input contract identity mismatch")
    structure = config["structure"]
    fields = {"schema", "mode", "status", "literals", "comparisons", "branches", "loops", "calls",
              "state_changes", "dependencies", "parameters", "limitations", "contract"}
    if type(structure) is not dict or not fields <= set(structure) or set(structure)-fields-{"source_sha256", "analysis_scope"}:
        raise ValueError("unsupported MRI field; evaluator information cannot cross")
    if structure["schema"] != "tomolab-online-mri-v1" or structure["mode"] not in ("structural", "black_box") or structure["status"] not in ("UNKNOWN", "UNSUPPORTED", "BLACK_BOX_FALLBACK", "PARTIAL", "SUPPORTED_BOUNDED_OBSERVATION") or structure["contract"] != config["contract"]:
        raise ValueError("MRI mode, scope or public contract mismatch")
    def text(value, length=256):
        return type(value) is str and len(value) <= length
    def line(value):
        return type(value) is int and 0 <= value <= 10**8
    for name in ("branches", "loops", "state_changes"):
        if type(structure[name]) is not list or len(structure[name]) > 1024 or not all(line(v) for v in structure[name]):
            raise ValueError("bounded public MRI locations required")
    for name in ("dependencies", "parameters", "limitations"):
        if type(structure[name]) is not list or len(structure[name]) > 128 or not all(text(v) for v in structure[name]):
            raise ValueError("bounded public MRI names required")
    if type(structure["literals"]) is not list or len(structure["literals"]) > 64:
        raise ValueError("bounded public target literals required")
    for value in structure["literals"]:
        if type(value) not in (int, float, str) or type(value) is str and not text(value, 64) or type(value) in (int, float) and (not math.isfinite(value) or abs(value) > 10**12):
            raise ValueError("unsupported public literal")
    if type(structure["calls"]) is not list or len(structure["calls"]) > 1024 or any(type(row) is not dict or set(row) != {"line", "name"} or not line(row["line"]) or not text(row["name"]) for row in structure["calls"]):
        raise ValueError("bounded public call descriptions required")
    if type(structure["comparisons"]) is not list or len(structure["comparisons"]) > 1024:
        raise ValueError("bounded public comparisons required")
    for row in structure["comparisons"]:
        required_row = {"line", "status", "distance_scope"}
        if type(row) is not dict or not required_row <= set(row) or set(row)-required_row-{"parameter", "operator", "literal"} or not line(row["line"]):
            raise ValueError("unsupported public comparison field")
        if row["status"] == "SUPPORTED":
            if set(row) != required_row | {"parameter", "operator", "literal"} or row["parameter"] not in structure["parameters"] or row["operator"] not in ("==", "!=", "<", "<=", ">", ">=") or row["distance_scope"] != "STATIC_INPUT_TO_LITERAL_ONLY" or type(row["literal"]) not in (int, float) or not math.isfinite(row["literal"]) or abs(row["literal"]) > 10**12:
                raise ValueError("unsupported scalar comparison contract")
        elif row["status"] != "UNKNOWN" or set(row) != required_row or row["distance_scope"] != "NOT_COMPUTED":
            raise ValueError("unsupported comparison must remain UNKNOWN")
    if "source_sha256" in structure and (not text(structure["source_sha256"], 64) or len(structure["source_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in structure["source_sha256"])):
        raise ValueError("public target source digest required")
    if "analysis_scope" in structure and structure["analysis_scope"] != "AST_SYNTAX_AND_ROOT_LINE_TRACE_NOT_GENERAL_PYTHON_SEMANTICS":
        raise ValueError("unsupported MRI analysis scope")
    if type(config["replays"]) is not list or len(config["replays"]) > 2048 or any(not validate_input(p, config["contract"]) for p in config["replays"]):
        raise ValueError("only bounded in-domain approved replay inputs may cross")
    if config["method"] not in ("C", "D") and config["replays"]:
        raise ValueError("A/B do not receive Source experience")
    if type(config["_started"]) not in (int, float) or not math.isfinite(config["_started"]) or not 0 <= config["_started"] < 10**12:
        raise ValueError("bounded host monotonic start required")
    if len(canonical(config).encode())+1 > 8_000_000:
        raise ValueError("online configuration exceeds existing transport bound")
    return config


def validate_online_observation(observation, *, request_id, point, contract):
    fields = {"feedback", "target_calls", "oracle_calls", "cost", "observation_id", "reference_match"}
    if type(observation) is not dict or set(observation) != fields or type(observation["observation_id"]) is not int or observation["observation_id"] != request_id:
        raise ValueError("private evaluator output cannot enter online feedback")
    feedback = observation["feedback"]
    fields = {"status", "input_digest", "coverage", "branch_distance", "contract_checked"}
    if type(feedback) is not dict or not fields <= set(feedback) or set(feedback)-fields-{"exception_type", "exception_location"}:
        raise ValueError("unsupported online feedback field")
    if feedback["status"] not in ("PASS", "FAILURE", "INVALID_INPUT", "EXECUTION_ERROR", "ORACLE_ERROR", "UNKNOWN") or feedback["input_digest"] != input_identity(point) or feedback["contract_checked"] != digest(contract):
        raise ValueError("online feedback identity or status mismatch")
    coverage = feedback["coverage"]
    if type(coverage) is not list or len(coverage) > 4096 or any(type(v) is not int or not 0 <= v <= 10**8 for v in coverage):
        raise ValueError("bounded public root-line signature required")
    value = feedback["branch_distance"]
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 10**15):
        raise ValueError("bounded supported branch distance required")
    value = feedback.get("exception_type")
    if value is not None and (type(value) is not str or len(value) > 256):
        raise ValueError("bounded public exception type required")
    value = feedback.get("exception_location")
    if value is not None and (type(value) is not int or not 0 <= value <= 10**8):
        raise ValueError("bounded public exception location required")
    for key in ("target_calls", "oracle_calls"):
        if type(observation[key]) is not int or observation[key] != (0 if feedback["status"] == "INVALID_INPUT" else 1):
            raise ValueError("actual single-entry counters required")
    cost = observation["cost"]
    if type(cost) is not dict or set(cost) != {"target_seconds", "oracle_seconds", "instrumentation_seconds"} or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 10**9 for v in cost.values()):
        raise ValueError("bounded measured evaluator costs required")
    if observation["reference_match"] is not None and type(observation["reference_match"]) is not bool:
        raise ValueError("only a host-checked reproduction boolean is permitted")
    return observation
