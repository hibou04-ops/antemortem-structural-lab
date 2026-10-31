"""Public structure inspection and single-execution, line-only observation.

No AST is rewritten. Comparisons, iterators, user operators and expressions are
never re-evaluated for instrumentation. Static distance supports scalar builtin
numeric input versus a literal only; everything else stays UNKNOWN.
"""
import ast
from copy import deepcopy
import hashlib
import inspect
import math
import sys
import textwrap
import time

from .online_schema import input_identity, validate_contract, validate_input
from .schema import digest


def _literal(node):
    if isinstance(node, ast.Constant) and type(node.value) in (int, float, str, bool, type(None)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant) and type(node.operand.value) in (int, float):
        return -node.operand.value
    return None


def inspect_target(target, contract, *, mode="structural"):
    validate_contract(contract)
    if mode not in ("structural", "black_box"):
        raise ValueError("mode must be structural or black_box")
    result = dict(schema="tomolab-online-mri-v1", mode=mode, status="UNKNOWN", literals=[],
                  comparisons=[], branches=[], loops=[], calls=[], state_changes=[], dependencies=[],
                  parameters=[], limitations=[], contract=deepcopy(contract))
    if mode == "black_box":
        result.update(status="BLACK_BOX_FALLBACK", limitations=["STRUCTURE_NOT_REQUESTED"])
        return result
    if not inspect.isfunction(target):
        result.update(status="UNSUPPORTED", limitations=["NATIVE_OR_DYNAMIC_CALLABLE; use explicit black_box fallback"])
        return result
    try:
        lines, first = inspect.getsourcelines(target)
        source = textwrap.dedent("".join(lines))
        module = ast.parse(source)
    except (OSError, TypeError, SyntaxError, IndentationError):
        result.update(status="UNSUPPORTED", limitations=["SOURCE_UNAVAILABLE; use explicit black_box fallback"])
        return result
    functions = [n for n in module.body if isinstance(n, ast.FunctionDef)]
    if len(functions) != 1:
        result.update(status="UNSUPPORTED", limitations=["one synchronous Python function required"])
        return result
    fn = functions[0]
    result["source_sha256"] = hashlib.sha256(source.encode()).hexdigest()
    result["parameters"] = [arg.arg for arg in fn.args.args]
    if len(result["parameters"]) != 1 or fn.args.vararg or fn.args.kwarg:
        result["limitations"].append("single JSON argument only")
    unsupported = (ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom, ast.Lambda,
                   ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)
    ops = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}
    literals = []
    signed_operands = {id(node.operand) for node in ast.walk(fn)
                       if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
                       and isinstance(node.operand, ast.Constant)
                       and type(node.operand.value) in (int, float)}
    for node in ast.walk(fn):
        line = getattr(node, "lineno", 1) + first - 1
        if isinstance(node, unsupported):
            result["limitations"].append(type(node).__name__ + ":UNSUPPORTED")
        signed_literal = (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
                          and isinstance(node.operand, ast.Constant)
                          and type(node.operand.value) in (int, float))
        if signed_literal or isinstance(node, ast.Constant) and id(node) not in signed_operands and type(node.value) in (int, float, str):
            value = _literal(node) if signed_literal else node.value
            if type(value) is str and len(value) > 64:
                continue
            if type(value) in (int, float) and (not math.isfinite(value) or abs(value) > 10**12):
                continue
            if value not in literals:
                literals.append(value)
        if isinstance(node, (ast.If, ast.IfExp, ast.While)):
            result["branches"].append(line)
        if isinstance(node, (ast.For, ast.While, ast.comprehension)):
            result["loops"].append(line)
        if isinstance(node, ast.Call):
            call = node.func.id if isinstance(node.func, ast.Name) else (node.func.attr if isinstance(node.func, ast.Attribute) else "UNKNOWN")
            result["calls"].append(dict(line=line, name=call))
            if call in ("exec", "eval", "getattr", "setattr", "__import__"):
                result["limitations"].append("DYNAMIC_CALL:UNKNOWN")
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
            result["state_changes"].append(line)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            result["dependencies"].append(node.id)
        if isinstance(node, ast.Compare):
            row = dict(line=line, status="UNKNOWN", distance_scope="NOT_COMPUTED")
            if len(node.ops) == len(node.comparators) == 1 and type(node.ops[0]) in ops:
                literal = _literal(node.comparators[0])
                if isinstance(node.left, ast.Name) and node.left.id in result["parameters"] and type(literal) in (int, float) and contract["kind"] in ("int", "float"):
                    row.update(status="SUPPORTED", parameter=node.left.id, operator=ops[type(node.ops[0])],
                               literal=literal, distance_scope="STATIC_INPUT_TO_LITERAL_ONLY")
            result["comparisons"].append(row)
            if row["status"] == "UNKNOWN":
                result["limitations"].append("NONSCALAR_OR_EFFECTFUL_COMPARISON_DISTANCE:UNKNOWN")
    result["literals"] = literals[:64]
    result["dependencies"] = sorted(set(result["dependencies"]))[:64]
    result["limitations"] = sorted(set(result["limitations"]))
    result["status"] = "PARTIAL" if result["limitations"] else "SUPPORTED_BOUNDED_OBSERVATION"
    result["analysis_scope"] = "AST_SYNTAX_AND_ROOT_LINE_TRACE_NOT_GENERAL_PYTHON_SEMANTICS"
    return result


def _snapshot(value, depth=0):
    if depth > 8:
        raise ValueError("unsupported output depth")
    if value is None:
        return dict(type="none", value=None)
    if type(value) in (bool, int, str):
        if type(value) is int and value.bit_length() > 4096 or type(value) is str and len(value) > 65536:
            raise ValueError("unsupported output resource size")
        return dict(type=type(value).__name__, value=value)
    if type(value) is float:
        if math.isnan(value):
            return dict(type="float", value="NAN")
        if math.isinf(value):
            return dict(type="float", value="POS_INF" if value > 0 else "NEG_INF")
        return dict(type="float", value=value)
    if type(value) in (list, tuple):
        if len(value) > 4096:
            raise ValueError("unsupported output resource size")
        return dict(type=type(value).__name__, value=[_snapshot(v, depth + 1) for v in value])
    if type(value) is dict and all(type(k) is str for k in value):
        if len(value) > 4096:
            raise ValueError("unsupported output resource size")
        return dict(type="dict", value={k: _snapshot(v, depth + 1) for k, v in value.items()})
    raise ValueError("UNSUPPORTED non-JSON output; reviewed normalization adapter required")


def _capture(fn, point, *, tracing, trace_code=None):
    lines, code = [], trace_code if trace_code is not None else getattr(fn, "__code__", None)
    previous = sys.gettrace()
    def trace(frame, event, arg):
        if frame.f_code is code:
            if event == "line":
                lines.append(frame.f_lineno)
            return trace
        return None
    started = time.perf_counter()
    active_trace = tracing and code is not None and previous is None
    try:
        if active_trace:
            sys.settrace(trace)
        try:
            value = fn(point)
        except (MemoryError, ImportError, OSError, RecursionError) as exc:
            capture = dict(kind="execution_error", exception_type=type(exc).__module__ + "." + type(exc).__qualname__)
        except Exception as exc:
            capture = dict(kind="exception", exception_type=type(exc).__module__ + "." + type(exc).__qualname__)
        else:
            try:
                capture = dict(kind="return", value=_snapshot(value))
            except ValueError:
                capture = dict(kind="unknown", reason="UNSUPPORTED_OUTPUT")
    finally:
        if active_trace:
            sys.settrace(previous)
    return capture, sorted(set(lines)), time.perf_counter() - started


def _equal(left, right, comparison):
    if left["type"] != right["type"]:
        return False
    kind, a, b = left["type"], left["value"], right["value"]
    if kind == "float":
        if a == "NAN" or b == "NAN":
            return comparison.get("nan_equal", False) and a == b
        if type(a) is str or type(b) is str or a == 0 or b == 0:
            return a == b
        return math.isclose(a, b, abs_tol=comparison.get("absolute", 0), rel_tol=comparison.get("relative", 0))
    if kind in ("list", "tuple"):
        return len(a) == len(b) and all(_equal(x, y, comparison) for x, y in zip(a, b))
    if kind == "dict":
        return a.keys() == b.keys() and all(_equal(a[k], b[k], comparison) for k in a)
    return a == b


def observe(target, oracle, point, contract, structure=None, *, tracing=True, trace_target=None):
    """Oracle output remains host-private; feedback is the only policy input."""
    started = time.perf_counter()
    for fn in (target, oracle):
        if not callable(fn) or inspect.iscoroutinefunction(fn) or inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn):
            raise ValueError("reviewed synchronous non-generator callables required")
        if inspect.iscoroutinefunction(getattr(fn, "__call__", None)):
            raise ValueError("async callable objects are UNSUPPORTED")
    if not validate_input(point, contract):
        return dict(feedback=dict(status="INVALID_INPUT", input_digest=input_identity(point), coverage=[],
                                  branch_distance=None, contract_checked=digest(contract)),
                    private_outcome=None, target_calls=0, oracle_calls=0,
                    cost=dict(target_seconds=0.0, oracle_seconds=0.0, instrumentation_seconds=0.0))
    # Independent copies prevent a mutating target from changing its reference
    # input or the next candidate. Stateful targets reset from each full trace.
    # The host may point line tracing at the reviewed upstream function called
    # by a thin adapter. It does not call that function a second time.
    trace_code = getattr(trace_target, "__code__", None) if trace_target is not None else None
    active_tracing = tracing and (trace_target is None or trace_code is not None)
    actual, lines, target_seconds = _capture(target, deepcopy(point), tracing=active_tracing, trace_code=trace_code)
    expected, _, oracle_seconds = _capture(oracle, deepcopy(point), tracing=False)
    comparison = contract.get("comparison", {})
    if expected["kind"] == "exception" and expected["exception_type"] not in comparison.get("expected_exceptions", []):
        status = "ORACLE_ERROR"
    elif actual["kind"] == "execution_error" or expected["kind"] == "execution_error":
        status = "EXECUTION_ERROR"
    elif actual["kind"] == "unknown" or expected["kind"] == "unknown":
        status = "UNKNOWN"
    elif actual["kind"] == expected["kind"] == "return":
        status = "PASS" if _equal(actual["value"], expected["value"], comparison) else "FAILURE"
    elif actual["kind"] == expected["kind"] == "exception" and comparison.get("exception_policy", "match_type") == "match_type":
        status = "PASS" if actual["exception_type"] == expected["exception_type"] else "FAILURE"
    else:
        status = "FAILURE"
    distances = []
    if type(point) in (int, float):
        for guard in (structure or {}).get("comparisons", []):
            if guard.get("status") == "SUPPORTED":
                distances.append(min(abs(point - guard["literal"]), 1e15))
    private = dict(actual=actual, expected=expected)
    feedback = dict(status=status, input_digest=input_identity(point), contract_checked=digest(contract),
                    coverage=lines, branch_distance=min(distances) if distances else None,
                    exception_type=actual.get("exception_type"), exception_location=lines[-1] if lines and actual["kind"] == "exception" else None)
    return dict(feedback=feedback, private_outcome=private, semantic_digest=digest(private),
                target_calls=1, oracle_calls=1,
                observation_scope="EXISTING_TRACE_PRESERVED_NO_OWN_LINE_TRACE" if active_tracing and sys.gettrace() is not None else ("UPSTREAM_ROOT_LINE_TRACE" if active_tracing and trace_target is not None else ("ROOT_LINE_TRACE" if active_tracing and getattr(target, "__code__", None) is not None else "BLACK_BOX_EXECUTION")),
                cost=dict(target_seconds=target_seconds, oracle_seconds=oracle_seconds,
                          instrumentation_seconds=max(0.0, time.perf_counter()-started-target_seconds-oracle_seconds)))
