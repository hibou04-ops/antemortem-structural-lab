"""New reviewed bounded scalar EFSM mutations for E6 software QA.

These are authored faults, not discovered real-project vulnerabilities. They do
not import or reuse any consumed E1--E5 final fixture. State is plain JSON data.
"""
from copy import deepcopy

ARGUMENT = {"kind": "int", "min": -2, "max": 2}
STATE = {"kind": "int", "min": -32, "max": 32}


def _v(role):
    return {"var": "pre:" + role}


def _op(op, *args):
    return {"op": op, "args": list(args)}


def _cmp(op, left, right):
    return {"op": op, "left": left, "right": right}


def _when(condition, yes, no):
    return {"op": "if", "condition": condition, "then": yes, "else": no}


def checkpoint_model(state, action, argument):
    result = dict(state)
    if action == "credit":
        result["balance"] = state["balance"] + argument
    elif action == "save":
        result["saved"] = state["balance"]
        result["valid"] = 1
    elif action == "restore" and state["valid"] == 1:
        result["balance"] = state["saved"]
    return result


def checkpoint_target(state, action, argument):
    result = dict(state)
    if action == "credit":
        result["balance"] += argument
    elif action == "save":
        result["saved"] = result["balance"]
        result["valid"] = 1
    elif action == "restore" and state["valid"]:
        result["balance"] = 0
    return result


def overwrite_model(state, action, argument):
    result = dict(state)
    if action == "stage":
        result.update(pending=argument, armed=1)
    elif action == "commit" and state["armed"] == 1:
        result.update(current=state["pending"], armed=0)
    return result


def overwrite_target(state, action, argument):
    result = dict(state)
    if action == "stage":
        result["pending"], result["armed"] = argument, 1
    elif action == "commit" and result["armed"]:
        result["current"] += result["pending"]
        result["armed"] = 0
    return result


def multiplicity_model(state, action, argument):
    result = dict(state)
    if action == "insert":
        result["count"] = state["count"] + 1
    elif action == "remove" and state["count"] > 0:
        result["count"] = state["count"] - 1
    return result


def multiplicity_target(state, action, argument):
    result = dict(state)
    if action == "insert":
        result["count"] += 1
    elif action == "remove":
        result["count"] = 0
    return result


def lease_model(state, action, argument):
    result = dict(state)
    if action == "acquire" and state["active"] == 0:
        result.update(active=1, payload=argument)
    elif action == "release" and state["active"] == 1:
        result.update(active=0, archived=state["payload"], payload=0)
    return result


def lease_target(state, action, argument):
    result = dict(state)
    if action == "acquire" and not result["active"]:
        result["active"] = 1
        result["payload"] = result["archived"] if result["archived"] else argument
    elif action == "release" and result["active"]:
        result["archived"] = result["payload"]
        result["payload"], result["active"] = 0, 0
    return result


def undo_model(state, action, argument):
    result = dict(state)
    if action == "change":
        result.update(value=state["value"] + argument, last=state["value"],
                      older=state["last"], depth=min(2, state["depth"] + 1))
    elif action == "undo" and state["depth"] > 0:
        result.update(value=state["last"], last=state["older"], older=0, depth=state["depth"] - 1)
    return result


def undo_target(state, action, argument):
    result = dict(state)
    if action == "change":
        result["older"], result["last"] = result["last"], result["value"]
        result["value"] += argument
        result["depth"] = min(2, result["depth"] + 1)
    elif action == "undo" and result["depth"]:
        result["value"] = result["older"]
        result["last"], result["older"] = result["older"], 0
        result["depth"] -= 1
    return result


def difference_control(a, b):
    from tomolab.mold.relations import feature
    return feature("difference", a, b)


def difference_reference(a, b):
    return a - b


def normalization_control(value):
    from tomolab.claim import _normalize
    return _normalize(value)


def normalization_reference(value):
    text = value.rstrip()
    if text.endswith("."):
        text = text[:-1]
    return " ".join(text.split())


def _action(name, effects, preconditions=(), dependencies=()):
    return {"name": name, "role": name, "preconditions": list(preconditions),
            "effects": effects, "postconditions": [], "dependencies": list(dependencies)}


def _contract(states, actions):
    return {"schema": "tomolab-temporal-contract-v1", "disabled_action": "NO_OP",
            "state": [{"name": name, "role": name, "type": deepcopy(type_), "initial": initial}
                      for name, type_, initial in states],
            "actions": actions,
            "invariants": [{"id": "state-match", "predicate": True}]}


def _stateful(case_id, family, initial, model, target, actions, *, bounds=None):
    bounds = bounds or {}
    states = [(key, bounds.get(key, STATE), value) for key, value in initial.items()]
    return {"case_id": case_id, "family_id": family, "kind": "stateful", "expected_fault": True,
            "public_contract_id": "api-" + case_id.removeprefix("dev-") + "-v1",
            "initial": initial, "model_step": model, "target_step": target,
            "temporal_contract": _contract(states, actions), "max_steps": 8,
            "argument_type": deepcopy(ARGUMENT), "origin": "NEW_REVIEWED_AUTHORED_SCALAR_EFSM_MUTATION"}


BOOL_INT = {"kind": "int", "min": 0, "max": 1}
COUNT = {"kind": "int", "min": 0, "max": 8}
DEPTH = {"kind": "int", "min": 0, "max": 2}
CASES = [
    _stateful("dev-checkpoint", "snapshot-restoration", {"balance": 0, "saved": 0, "valid": 0}, checkpoint_model, checkpoint_target,
              [_action("credit", {"balance": _op("add", _v("balance"), {"var": "arg"})}),
               _action("save", {"saved": _v("balance"), "valid": 1}),
               _action("restore", {"balance": _v("saved")}, [_cmp("eq", _v("valid"), 1)], ["save"])], bounds={"valid": BOOL_INT}),
    _stateful("dev-overwrite", "staged-overwrite-order", {"current": 0, "pending": 0, "armed": 0}, overwrite_model, overwrite_target,
              [_action("stage", {"pending": {"var": "arg"}, "armed": 1}),
               _action("commit", {"current": _v("pending"), "armed": 0},
                       [_cmp("eq", _v("armed"), 1)], ["stage"])], bounds={"armed": BOOL_INT}),
    _stateful("dev-multiplicity", "remove-one-multiplicity", {"count": 0}, multiplicity_model, multiplicity_target,
              [_action("insert", {"count": _op("add", _v("count"), 1)}),
               _action("remove", {"count": _op("sub", _v("count"), 1)}, [_cmp("gt", _v("count"), 0)], ["insert"])],
              bounds={"count": COUNT}),
    _stateful("dev-lease", "lease-reuse-stale-value", {"active": 0, "payload": 0, "archived": 0}, lease_model, lease_target,
              [_action("acquire", {"active": 1, "payload": {"var": "arg"}}, [_cmp("eq", _v("active"), 0)]),
               _action("release", {"active": 0, "payload": 0, "archived": _v("payload")},
                       [_cmp("eq", _v("active"), 1)], ["acquire"])], bounds={"active": BOOL_INT}),
    _stateful("dev-undo", "lifo-undo-order", {"value": 0, "last": 0, "older": 0, "depth": 0}, undo_model, undo_target,
              [_action("change", {"value": _op("add", _v("value"), {"var": "arg"}),
                                  "older": _v("last"), "last": _v("value"),
                                  "depth": _when(_cmp("lt", _v("depth"), 2), _op("add", _v("depth"), 1), 2)}),
               _action("undo", {"value": _v("last"), "last": _v("older"), "older": 0,
                                "depth": _op("sub", _v("depth"), 1)}, [_cmp("gt", _v("depth"), 0)], ["change"])],
              bounds={"depth": DEPTH}),
    {"case_id": "control-difference", "family_id": "project-difference-control", "kind": "static", "expected_fault": False,
     "public_contract_id": "api-difference-v1",
     "target": difference_control, "oracle": difference_reference,
     "inputs": [("a", "left", {"kind": "int", "min": -16, "max": 16}), ("b", "right", {"kind": "int", "min": -16, "max": 16})],
     "origin": "EXISTING_PROJECT_CLEAN_CONTROL"},
    {"case_id": "control-normalization", "family_id": "project-text-control", "kind": "static", "expected_fault": False,
     "public_contract_id": "api-text-normalization-v1",
     "target": normalization_control, "oracle": normalization_reference,
     "inputs": [("value", "text", {"kind": "str", "alphabet": "AaB .\t\n", "min_size": 0, "max_size": 8})],
     "origin": "EXISTING_PROJECT_CLEAN_CONTROL"},
]


def case_by_id(case_id):
    return next(case for case in CASES if case["case_id"] == case_id)


def public_trace_result(case_id, trace, target=False):
    case = case_by_id(case_id)
    state = deepcopy(case["initial"])
    callback = case["target_step"] if target else case["model_step"]
    rows = []
    for action, argument in trace:
        state = callback(state, action, argument)
        rows.append(dict(state))
    return rows


PUBLIC_TRACE_MODEL = """def reference(trace):
    current = initial_state()
    observed = []
    for action, argument in trace:
        current = step_model(current, action, argument)
        observed.append(project_state(current))
    return observed
"""
