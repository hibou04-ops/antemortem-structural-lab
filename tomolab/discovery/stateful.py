"""Caller-side Hypothesis state machines for explicitly trusted callbacks."""
from copy import deepcopy
import math
import time

from hypothesis import HealthCheck, seed as hypothesis_seed, settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, run_state_machine_as_test

from .hypothesis_adapter import BudgetExhausted,type_strategy
from .schema import canonical,identifier,integer,validate_type


def trace_spec(actions, argument_type, *, task_id="state-trace", max_steps=8,
               name="trace", role="transitions", state_model="declared-state-v1"):
    """A public typed action trace usable by the ordinary discovery loop.

    Actions and argument types are data. Implementations and model callbacks
    remain in run_trace/evaluate_trace on the evaluator side.
    """
    from .schema import validate_spec
    if not isinstance(actions, (list, tuple)) or not 1 <= len(actions) <= 16:
        raise ValueError("1..16 declared action names required")
    for action in actions:
        identifier(action)
        if len(action) > 32:
            raise ValueError("trace action names must be at most 32 characters")
    if len(set(actions)) != len(actions):
        raise ValueError("duplicate trace action")
    argument_type = validate_type(argument_type)
    integer(max_steps, 1, 16)
    action_type = {"kind": "str", "alphabet": "".join(sorted(set("".join(actions)))),
                   "min_size": min(map(len, actions)), "max_size": max(map(len, actions)),
                   "choices": list(actions)}
    return validate_spec({"schema": "tomolab-discovery-spec-v1", "task_id": task_id,
                          "inputs": [{"name": name, "role": role,
                                      "type": {"kind": "list", "items": {"kind": "tuple", "items": [action_type, argument_type]},
                                               "min_size": 0, "max_size": max_steps}}],
                          "contract": {"id": state_model, "operation": "bounded-state-transitions",
                                       "preconditions": ["declared-actions"], "invariants": ["state-and-output-match"],
                                       "state_model": state_model, "graph_signature": "UNKNOWN"}})


def _trace_protocol(operations, trace):
    if not isinstance(operations, dict) or not 1 <= len(operations) <= 16:
        raise ValueError("bounded declared operations required")
    for name, operation in operations.items():
        identifier(name)
        if not isinstance(operation, dict) or set(operation) != {"arguments", "target", "model"}:
            raise ValueError("operation fields must be arguments, target and model")
        validate_type(operation["arguments"])
        if not callable(operation["target"]) or not callable(operation["model"]):
            raise ValueError("trusted operation callbacks required")
    if not isinstance(trace, (list, tuple)) or len(trace) > 16:
        raise ValueError("trace must contain at most 16 transitions")
    from .schema import validate_value
    clean = []
    for row in trace:
        if not isinstance(row, (list, tuple)) or len(row) != 2 or row[0] not in operations:
            raise ValueError("unknown action or invalid transition shape")
        validate_value(row[1], operations[row[0]]["arguments"])
        clean.append((row[0], deepcopy(row[1])))
    return clean


def evaluate_trace(target_factory, model_factory, operations, trace, *, snapshot, trusted_execution=False):
    """Replay a finite typed trace against a trusted implementation and model.

    Every transition compares outputs/exception types and projected states.
    Snapshot or factory errors propagate as evaluator errors. This function
    does not search, learn, claim isolation, or send anything to a Generator.
    """
    if trusted_execution is not True:
        raise PermissionError("explicit trusted execution required for state callbacks")
    if not all(callable(fn) for fn in (target_factory, model_factory, snapshot)):
        raise ValueError("trusted factories and state projection required")
    clean = _trace_protocol(operations, trace)
    target, model = target_factory(), model_factory()
    rows = []
    first_failure = None
    started, cpu = time.perf_counter(), time.process_time()

    def invoke(callback, subject, argument):
        try:
            value = callback(subject, argument)
        except Exception as exc:
            return {"kind": "exception", "type": type(exc).__name__}
        canonical(value)
        return {"kind": "return", "value": deepcopy(value)}

    for index, (action, argument) in enumerate(clean):
        operation = operations[action]
        actual = invoke(operation["target"], target, deepcopy(argument))
        expected = invoke(operation["model"], model, deepcopy(argument))
        actual_state, expected_state = snapshot(target), snapshot(model)
        canonical(actual_state), canonical(expected_state)
        mismatch = actual != expected or actual_state != expected_state
        if mismatch and first_failure is None:
            first_failure = index
        rows.append({"index": index, "action": action, "argument": deepcopy(argument),
                     "actual": actual, "expected": expected, "actual_state": deepcopy(actual_state),
                     "expected_state": deepcopy(expected_state), "failed": mismatch})
    return {"schema": "tomolab-state-trace-v1", "failed": first_failure is not None,
            "status": "STATE_VIOLATION" if first_failure is not None else "NOT_REFUTED_ON_TRACE",
            "first_failure_index": first_failure, "records": rows,
            "transition_calls": len(rows), "target_transition_calls": len(rows), "model_transition_calls": len(rows),
            "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu,
            "target_execution": "TRUSTED_EVALUATOR_NOT_SANDBOXED"}


class _StateViolation(AssertionError):
    """Only an observed model/implementation disagreement is a finding."""


def run_stateful(target_factory,model_factory,operations,*,snapshot,budget=256,seed=7,max_examples=20,steps=16,time_budget=10):
    """operations maps name to {arguments: type DSL, target: fn, model: fn}.

    Each transition compares return/exception category and caller-defined state.
    Callbacks run with caller privileges; use the external execution boundary.
    """
    integer(budget,1,10000)
    integer(seed,0,2**32-1)
    integer(max_examples,1,1000)
    integer(steps,1,100)
    if not isinstance(operations,dict) or not 1<=len(operations)<=16 or type(time_budget) not in (int,float) or not math.isfinite(time_budget) or not 0<time_budget<=3600:
        raise ValueError("bounded operations and time required")
    if not all(callable(fn) for fn in (target_factory,model_factory,snapshot)):
        raise ValueError("trusted factories and state projection required")
    for name,operation in operations.items():
        identifier(name)
        if not isinstance(operation,dict) or set(operation)!={"arguments","target","model"} or not callable(operation["target"]) or not callable(operation["model"]):
            raise ValueError("trusted operation callbacks required")
        validate_type(operation["arguments"])
    started,cpu=time.perf_counter(),time.process_time()
    rows=[]
    witnesses=[]
    def invoke(fn,state,arg):
        try:
            return {"kind":"return","value":fn(state,arg)}
        except Exception as error:
            return {"kind":"exception","type":type(error).__name__}
    class Machine(RuleBasedStateMachine):
        def __init__(self):
            super().__init__()
            self.target=target_factory()
            self.model=model_factory()
            self.trace=[]
        @rule(action=st.sampled_from(sorted(operations)),data=st.data())
        def transition(self,action,data):
            if len(rows)>=budget or time.perf_counter()-started>=time_budget:
                raise BudgetExhausted()
            op=operations[action]
            argument=data.draw(type_strategy(op["arguments"]),label=action)
            self.trace.append({"action":action,"argument":deepcopy(argument)})
            actual=invoke(op["target"],self.target,deepcopy(argument))
            expected=invoke(op["model"],self.model,deepcopy(argument))
            observed_state=snapshot(self.target)
            expected_state=snapshot(self.model)
            mismatch=actual!=expected or observed_state!=expected_state
            row={"call":len(rows)+1,"trace":deepcopy(self.trace),"failed":mismatch,
                 "elapsed_seconds":time.perf_counter()-started,"category":"state_violation" if mismatch else "refutation"}
            rows.append(row)
            if mismatch:
                witnesses.append(deepcopy(self.trace))
                raise _StateViolation("state-transition invariant violated")
    Machine=hypothesis_seed(seed)(Machine)
    stop="COMPLETE"
    try:
        run_state_machine_as_test(Machine,settings=settings(max_examples=max_examples,stateful_step_count=steps,
                                  deadline=None,database=None,suppress_health_check=list(HealthCheck),report_multiple_bugs=False))
    except BudgetExhausted:
        stop="RESOURCE_BUDGET"
    except _StateViolation:
        stop="COUNTEREXAMPLE_SHRUNK"
    return {"schema":"tomolab-stateful-receipt-v1","status":"COUNTEREXAMPLE_FOUND" if witnesses else "NOT_REFUTED_WITHIN_BUDGET",
            "stop":stop,"oracle_calls":len(rows),"records":rows,
            "witness":min(witnesses,key=lambda x:(len(x),len(canonical(x)),canonical(x))) if witnesses else None,
            "wall_seconds":time.perf_counter()-started,"cpu_seconds":time.process_time()-cpu,
            "target_transition_calls":len(rows),"model_transition_calls":len(rows),
            "target_execution":"TRUSTED_CALLER_NOT_SANDBOXED"}
