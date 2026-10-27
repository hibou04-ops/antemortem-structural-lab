"""Finite, public-data state contracts and trace abstraction; no callbacks or I/O.

This first EFSM subset uses bounded numeric state projections and simultaneous
assignments.  Contracts describe an approved model, not arbitrary Python state.
"""
from copy import deepcopy
from functools import lru_cache
import json

from .schema import (canonical, digest, identifier, integer, keys, normalize_evidence,
                     validate_inputs, validate_spec, validate_type, validate_value)
from .predicates import _interpret, predicate_roles, validate_predicate

SCHEMA = "tomolab-temporal-contract-v1"


def trace_layout(spec):
    name, action_type, argument_type = _trace_layout_cached(canonical(spec))
    return name, deepcopy(action_type), deepcopy(argument_type)


@lru_cache(maxsize=64)
def _trace_layout_cached(encoded):
    spec = validate_spec(json.loads(encoded))
    if len(spec["inputs"]) != 1:
        raise ValueError("temporal contract requires one declared trace input")
    item = spec["inputs"][0]
    trace = item["type"]
    if (trace["kind"] != "list" or trace["items"]["kind"] != "tuple"
            or len(trace["items"]["items"]) != 2):
        raise ValueError("trace must be a list of (action, argument) tuples")
    action_type, argument_type = trace["items"]["items"]
    if action_type["kind"] != "str" or "choices" not in action_type:
        raise ValueError("trace actions require explicit finite choices")
    if argument_type["kind"] not in {"int", "float"}:
        raise ValueError("initial temporal EFSM supports bounded numeric arguments")
    return item["name"], action_type, argument_type


def _types(contract, spec):
    _, _, arg = trace_layout(spec)
    result = {"arg": arg, "previous-argument": arg,
              "step": {"kind": "int", "min": 0, "max": 16}}
    roles = [a["role"] for a in contract["actions"]]
    labels = ["START", *roles]
    result["previous-action"] = {"kind": "str", "alphabet": "".join(sorted(set("".join(labels)))),
                                 "min_size": min(map(len, labels)), "max_size": max(map(len, labels)),
                                 "choices": labels}
    for state in contract["state"]:
        for prefix in ("pre:", "post:"):
            result[prefix + state["role"]] = state["type"]
    for role in roles:
        result["seen:" + role] = {"kind": "int", "min": 0, "max": 16}
    return result


def _predicate_spec(predicate, types):
    used = sorted(predicate_roles(predicate))
    if any(role not in types for role in used) or len(used) > 6:
        raise ValueError("predicate references undeclared roles or exceeds six variables")
    # Reuse E5's actual typed grammar and interpreter, with only referenced roles.
    inputs = [{"name": "v" + str(i), "role": role, "type": types[role]}
              for i, role in enumerate(used)]
    if not inputs:
        inputs = [{"name": "unused", "role": "unused", "type": {"kind": "int", "min": 0, "max": 0}}]
    return {"schema": "tomolab-discovery-spec-v1", "task_id": "temporal-expression",
            "inputs": inputs, "contract": {"id": "temporal-expression", "operation": "pure-expression",
                "preconditions": [], "invariants": ["expression"], "state_model": "finite",
                "graph_signature": "UNKNOWN"}}


def _validate_predicate(predicate, types):
    return validate_predicate(predicate, _predicate_spec(predicate, types))


def _expression_kind(expression, types, depth=0):
    if depth > 12:
        raise ValueError("conditional expression exceeds depth")
    if isinstance(expression, dict) and expression.get("op") == "if":
        keys(expression, ("op", "condition", "then", "else"))
        _validate_predicate(expression["condition"], types)
        left = _expression_kind(expression["then"], types, depth+1)
        right = _expression_kind(expression["else"], types, depth+1)
        if left != right and {left, right} != {"int", "float"}:
            raise ValueError("conditional branches have incompatible types")
        return "float" if "float" in (left, right) else left
    # E5 validates all arithmetic semantics, arity and constants. Conditional
    # branches may contain standard expressions; arbitrary executable syntax is rejected.
    wrapped = {"op": "eq", "left": expression, "right": expression}
    _validate_predicate(wrapped, types)
    if type(expression) is bool:
        return "bool"
    if type(expression) in (int, float, str):
        return type(expression).__name__
    if "var" in expression:
        return types[expression["var"]]["kind"]
    op = expression["op"]
    if op in {"eq", "ne", "lt", "le", "gt", "ge", "and", "or", "not"}:
        return "bool"
    if op in {"len", "mod"}:
        return "int"
    return "float" if any(_expression_kind(arg, types, depth+1) == "float" for arg in expression["args"]) else "int"


def validate_temporal_contract(contract, spec):
    spec = validate_spec(spec)
    _, action_type, _ = trace_layout(spec)
    keys(contract, ("schema", "state", "actions", "invariants"), ("disabled_action",))
    if contract["schema"] != SCHEMA:
        raise ValueError("unsupported temporal contract")
    if contract.get("disabled_action", "REJECT") not in {"REJECT", "NO_OP"}:
        raise ValueError("disabled action policy must be explicit supported semantics")
    if not isinstance(contract["state"], list) or not 1 <= len(contract["state"]) <= 4:
        raise ValueError("1..4 bounded numeric state projections required")
    for field in contract["state"]:
        keys(field, ("name", "role", "type", "initial"))
        identifier(field["name"]); identifier(field["role"])
        if len(field["role"]) > 64:
            raise ValueError("state role exceeds bound")
        type_ = validate_type(field["type"])
        if type_["kind"] not in {"int", "float"}:
            raise ValueError("temporal EFSM state must be numeric projections")
        validate_value(field["initial"], type_)
    if any(len({f[key] for f in contract["state"]}) != len(contract["state"]) for key in ("name", "role")):
        raise ValueError("state names and roles must be bijective")
    if not isinstance(contract["actions"], list) or not 1 <= len(contract["actions"]) <= 16:
        raise ValueError("1..16 actions required")
    for action in contract["actions"]:
        keys(action, ("name", "role", "preconditions", "effects", "postconditions", "dependencies"))
        identifier(action["name"]); identifier(action["role"])
        if len(action["role"]) > 32:
            raise ValueError("action role exceeds bound")
    names = [a["name"] for a in contract["actions"]]
    roles = [a["role"] for a in contract["actions"]]
    if len(set(names)) != len(names) or len(set(roles)) != len(roles) or set(names) != set(action_type["choices"]):
        raise ValueError("action names/roles must bijectively cover trace choices")
    types = _types(contract, spec)
    state_types = {f["role"]: f["type"] for f in contract["state"]}
    for action in contract["actions"]:
        for field in ("preconditions", "postconditions"):
            if not isinstance(action[field], list) or len(action[field]) > 16:
                raise ValueError("bounded action conditions required")
            for predicate in action[field]:
                _validate_predicate(predicate, types)
                if field == "preconditions" and any(r.startswith("post:") for r in predicate_roles(predicate)):
                    raise ValueError("preconditions cannot inspect future state")
        if (not isinstance(action["dependencies"], list) or any(not isinstance(r, str) for r in action["dependencies"])
                or len(set(action["dependencies"])) != len(action["dependencies"]) or set(action["dependencies"]) - set(roles)):
            raise ValueError("dependencies must be declared action roles")
        if not isinstance(action["effects"], dict) or set(action["effects"]) - set(state_types):
            raise ValueError("effects must assign declared state roles")
        for role, expression in action["effects"].items():
            # Simultaneous assignments must not depend on partially assigned post-state.
            if any(r.startswith("post:") for r in predicate_roles(expression)):
                raise ValueError("effects require pre-state references")
            kind = _expression_kind(expression, types)
            if kind not in {state_types[role]["kind"], "int" if state_types[role]["kind"] == "float" else "int"}:
                raise ValueError("effect type differs from state type")
    if not isinstance(contract["invariants"], list) or not 1 <= len(contract["invariants"]) <= 16:
        raise ValueError("1..16 state invariants required")
    for invariant in contract["invariants"]:
        keys(invariant, ("id", "predicate")); identifier(invariant["id"])
        _validate_predicate(invariant["predicate"], types)
    if len({i["id"] for i in contract["invariants"]}) != len(contract["invariants"]):
        raise ValueError("duplicate invariant ID")
    # A state-only invariant already false at initialization is a contradictory
    # public model, not a target failure or a valid empty trace.
    start = initial_state(contract)
    _, _, arg_type = trace_layout(spec)
    context = _context(start, arg_type["min"], 0, None, contract)
    for invariant in contract["invariants"]:
        refs = predicate_roles(invariant["predicate"])
        if all(r.startswith(("pre:", "post:")) for r in refs) and not _interpret(invariant["predicate"], context):
            raise ValueError("initial state contradicts a declared state invariant")
    if len(canonical(contract)) > 48000:
        raise ValueError("temporal contract exceeds bound")
    result = deepcopy(contract)
    result.setdefault("disabled_action", "REJECT")
    return result


def initial_state(contract):
    return {field["role"]: (float(field["initial"]) if field["type"]["kind"] == "float" else deepcopy(field["initial"]))
            for field in contract["state"]}


def _context(state, argument, index, previous, contract, post=None):
    previous = previous or {}
    counts = previous.get("counts", {})
    values = {"arg": argument, "step": index,
              "previous-action": previous.get("role", "START"),
              "previous-argument": previous.get("argument", argument)}
    for role, value in state.items():
        values["pre:"+role] = value
        values["post:"+role] = (post or state)[role]
    values.update({"seen:"+a["role"]: counts.get(a["role"], 0) for a in contract["actions"]})
    return values


def _expression(expression, context):
    if isinstance(expression, dict) and expression.get("op") == "if":
        branch = "then" if _interpret(expression["condition"], context) else "else"
        return _expression(expression[branch], context)
    return _interpret(expression, context)


def apply_action(state, action, argument, index, previous, contract, spec):
    """Apply the approved public model, never target code. Raises on invalid trace."""
    _, _, argument_type = trace_layout(spec)
    validate_value(argument, argument_type)
    if argument_type["kind"] == "float":
        argument = float(argument)
    keys(state, [field["role"] for field in contract["state"]])
    for field in contract["state"]:
        validate_value(state[field["role"]], field["type"])
    matches = [item for item in contract["actions"] if item["name"] == action]
    if len(matches) != 1:
        raise ValueError("undeclared action")
    declared = matches[0]
    context = _context(state, argument, index, previous, contract)
    enabled = (all(context["seen:"+role] for role in declared["dependencies"])
               and all(_interpret(predicate, context) for predicate in declared["preconditions"]))
    if not enabled and contract.get("disabled_action", "REJECT") == "REJECT":
        raise ValueError("action precondition/dependency failed")
    after = deepcopy(state)
    if enabled:
        for role, expression in declared["effects"].items():
            after[role] = _expression(expression, context)
    for field in contract["state"]:
        validate_value(after[field["role"]], field["type"])
        if field["type"]["kind"] == "float":
            after[field["role"]] = float(after[field["role"]])
    post_context = _context(state, argument, index, previous, contract, after)
    if enabled and not all(_interpret(p, post_context) for p in declared["postconditions"]):
        raise ValueError("public model postcondition failed")
    if not all(_interpret(i["predicate"], post_context) for i in contract["invariants"]):
        raise ValueError("public model invariant failed")
    counts = {a["role"]: (previous or {}).get("counts", {}).get(a["role"], 0) for a in contract["actions"]}
    counts[declared["role"]] += 1
    return {"index": index, "action": action, "role": declared["role"], "argument": deepcopy(argument),
            "pre": deepcopy(state), "post": after, "context": post_context, "counts": counts, "enabled": bool(enabled),
            "previous_action": (previous or {}).get("role", "START"),
            "previous_argument": (previous or {}).get("argument", argument)}


def available_actions(state, argument, index, previous, contract, spec):
    result = []
    for action in contract["actions"]:
        try:
            row = apply_action(state, action["name"], argument, index, previous, contract, spec)
        except (ValueError, ArithmeticError, TypeError, KeyError):
            continue
        if row["enabled"]:
            result.append(action["name"])
    return result


def simulate_trace(inputs, spec, contract):
    """Pure bounded trace replay against the supplied, already reviewed model IR."""
    inputs = validate_inputs(inputs, spec)
    name, _, _ = trace_layout(spec)
    state, previous, rows = initial_state(contract), None, []
    for index, (action, argument) in enumerate(inputs[name]):
        try:
            row = apply_action(state, action, argument, index, previous, contract, spec)
        except (ValueError, ArithmeticError, TypeError, KeyError) as error:
            return {"valid": False, "first_invalid_index": index, "reason": str(error),
                    "transitions": rows, "state": state}
        rows.append(row); state, previous = row["post"], row
    return {"valid": True, "first_invalid_index": None, "transitions": rows, "state": state}


def normalize_temporal_evidence(evidence, spec, contract):
    keys(evidence, ("kind", "evidence_id", "inputs", "invariant", "category", "signature", "first_failure_index"))
    base = normalize_evidence({k: v for k, v in evidence.items() if k != "first_failure_index"}, spec)
    replay = simulate_trace(base["inputs"], spec, contract)
    if not replay["valid"]:
        raise ValueError("evidence trace violates the public model contract")
    first = evidence["first_failure_index"]
    if base["kind"] == "FAILURE":
        integer(first, 0, len(replay["transitions"])-1)
    elif first is not None:
        raise ValueError("refutation must not identify a failing transition")
    base["first_failure_index"] = first
    return base


def temporal_hypotheses(contract, spec):
    """Relational action contexts; no learned concrete input or state coordinates."""
    _, _, argument_type = trace_layout(spec)
    relations = {}
    def add(action, kind, predicate):
        _validate_predicate(predicate, _types(contract, spec))
        relation = {"term": {"kind": "temporal", "roles": [spec["inputs"][0]["role"]],
                    "action": action, "relation_kind": kind, "predicate": predicate}, "operator": "eq", "value": 1}
        relations["TEMP-" + digest(relation)[:20]] = relation
    for action in contract["actions"]:
        role = action["role"]
        add(role, "action", True)
        for state in contract["state"]:
            before, after = {"var": "pre:"+state["role"]}, {"var": "post:"+state["role"]}
            for op in ("eq", "lt", "gt"):
                add(role, "effect", {"op": op, "left": after, "right": before})
                add(role, "resource", {"op": op, "left": {"var": "arg"}, "right": before})
            for value in (0, 1):
                for op in ("eq", "gt"):
                    add(role, "pre-state-boundary", {"op": op, "left": before, "right": value})
        for prior in contract["actions"]:
            add(role, "adjacent-order", {"op": "eq", "left": {"var": "previous-action"}, "right": prior["role"]})
            add(role, "prior-order", {"op": "gt", "left": {"var": "seen:"+prior["role"]}, "right": 0})
        add(role, "same-argument", {"op": "and", "args": [
            {"op": "gt", "left": {"var": "step"}, "right": 0},
            {"op": "eq", "left": {"var": "arg"}, "right": {"var": "previous-argument"}}]})
        for predicate in action["preconditions"]:
            add(role, "declared-guard", predicate)
        for op in ("eq", "lt", "gt"):
            add(role, "neutral-argument-boundary", {"op": op, "left": {"var": "arg"}, "right": 0})
    return relations


def temporal_holds(relation, replay, first_failure_index=None):
    term = relation["term"]
    rows = replay["transitions"] if first_failure_index is None else replay["transitions"][first_failure_index:first_failure_index+1]
    return any(row["role"] == term["action"] and bool(_interpret(term["predicate"], row["context"])) for row in rows)
