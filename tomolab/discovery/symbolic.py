"""Bounded integration of CrossHair and Z3; no symbolic claim is an Oracle verdict."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
from importlib.metadata import version
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def _safe_literal(node, depth=0):
    if depth > 5:
        raise ValueError("counterexample exceeds depth budget")
    if isinstance(node, ast.Constant) and (node.value is None or type(node.value) in (int, float, str, bool)):
        value = node.value
        if isinstance(value, str) and len(value) > 4096:
            raise ValueError("counterexample string exceeds budget")
        if type(value) is int and value.bit_length() > 256:
            raise ValueError("counterexample integer exceeds budget")
        if type(value) is float and not math.isfinite(value):
            raise ValueError("nonfinite counterexample unsupported")
        return value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _safe_literal(node.operand, depth + 1)
        if type(value) not in (int, float):
            raise ValueError("invalid unary literal")
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) <= 128:
        values = [_safe_literal(item, depth + 1) for item in node.elts]
        return tuple(values) if isinstance(node, ast.Tuple) else values
    if isinstance(node, ast.Dict) and len(node.keys) <= 128:
        values = {}
        for key, value in zip(node.keys, node.values):
            key = _safe_literal(key, depth + 1)
            if type(key) not in (str, int, bool):
                raise ValueError("unsupported dictionary key")
            values[key] = _safe_literal(value, depth + 1)
        return values
    raise ValueError("diagnostic candidate is not a supported literal")


def extract_candidates(diagnostics, function, parameter_names):
    """Parse only a complete AST Call with bounded literal arguments; never eval."""
    candidates = []
    for diagnostic in diagnostics:
        message = diagnostic.get("message", "")
        marker = "when calling "
        if marker not in message:
            continue
        tail = message.split(marker, 1)[1]
        # CrossHair may append a result explanation after the call. Search only
        # closing parentheses and accept the first syntactically complete call.
        for end, char in enumerate(tail):
            if char != ")":
                continue
            try:
                node = ast.parse(tail[:end + 1], mode="eval").body
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != function:
                    continue
                if len(node.args) > len(parameter_names) or any(keyword.arg is None for keyword in node.keywords):
                    continue
                values = dict(zip(parameter_names, [_safe_literal(arg) for arg in node.args]))
                for keyword in node.keywords:
                    if keyword.arg not in parameter_names or keyword.arg in values:
                        raise ValueError("invalid diagnostic arguments")
                    values[keyword.arg] = _safe_literal(keyword.value)
                if set(values) == set(parameter_names) and values not in candidates:
                    candidates.append(values)
                break
            except (SyntaxError, ValueError, TypeError):
                continue
    return candidates


def check_contract(path, function=None, *, timeout_seconds=5.0, trusted_execution=False,
                   analysis_kind="PEP316", per_condition_seconds=None):
    """Run actual CrossHair in a bounded child process on caller-trusted code.

    CrossHair needs source access. It is a separate capability stratum from a
    black-box generator. Its internal target-call count is not exposed by this
    CLI and is UNKNOWN; do not claim an equal-Oracle-call comparison.
    """
    if not trusted_execution:
        raise PermissionError("CrossHair executes Python; explicit trust or outer isolation required")
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0.1 <= timeout_seconds <= 300:
        raise ValueError("timeout_seconds must be 0.1..300")
    if analysis_kind not in ("PEP316", "asserts"):
        raise ValueError("only PEP316 and asserts are integrated")
    if importlib.util.find_spec("crosshair") is None:
        raise ValueError("CrossHair requires the discovery package extra")
    source = Path(path).resolve(strict=True)
    raw = source.read_bytes()
    if len(raw) > 262144:
        raise ValueError("source exceeds 256 KiB")
    parsed = ast.parse(raw.decode("utf-8"))
    functions = [item for item in parsed.body if isinstance(item, ast.FunctionDef)]
    if function is not None:
        matches = [item for item in functions if item.name == function]
        if len(matches) != 1:
            raise ValueError("exactly one top-level function required")
        selected = matches[0]
        target = str(source) + ":" + str(selected.lineno)
    else:
        selected = functions[0] if len(functions) == 1 else None
        target = str(source)
    source_hash = hashlib.sha256(raw).hexdigest()
    condition_time = timeout_seconds if per_condition_seconds is None else per_condition_seconds
    if type(condition_time) not in (int, float) or not math.isfinite(condition_time) or not 0.01 <= condition_time <= timeout_seconds:
        raise ValueError("per-condition time must be positive and within wall budget")
    command = [sys.executable, "-I", "-m", "crosshair", "check", target, "--analysis_kind", analysis_kind,
               "--report_all", "--per_condition_timeout", str(condition_time),
               "--per_path_timeout", str(min(1.0, condition_time))]
    environment = {key:value for key,value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}}
    environment["PYTHONIOENCODING"] = "utf-8"
    started = time.perf_counter()
    timed_out = False
    try:
        result = subprocess.run(command, cwd=source.parent, env=environment,
                                text=True, encoding="utf-8", capture_output=True, timeout=timeout_seconds)
        stdout, stderr, code = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        stdout = stdout.decode("utf-8", "replace") if isinstance(stdout, bytes) else stdout
        stderr = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr
        code = None
    elapsed = time.perf_counter() - started
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise ValueError("analyzed source changed during execution")
    diagnostics = []
    for line in stdout[:131072].splitlines():
        match = re.match(r"^(.*):(\d+):\s*(error|warning|info):\s*(.*)$", line)
        if match:
            diagnostics.append({"line":int(match[2]), "severity":match[3], "message":match[4][:4096]})
    if timed_out:
        status = "UNKNOWN_TIMEOUT"
    elif code == 1:
        status = "SYMBOLIC_COUNTEREXAMPLE_CANDIDATE"
    elif code == 0 and not diagnostics:
        status = "UNKNOWN_NOT_ANALYZED"
    elif code == 0:
        status = "NO_COUNTEREXAMPLE_WITHIN_BUDGET"
    else:
        status = "UNKNOWN_TOOL_ERROR"
    candidates = extract_candidates(diagnostics, selected.name,
                                    [p.arg for p in [*selected.args.posonlyargs, *selected.args.args]]) if selected else []
    return {"schema":"tomolab-crosshair-receipt-v1", "status":status, "tool":"CrossHair",
            "tool_version":version("crosshair-tool"), "source_sha256":source_hash,
            "function":function, "analysis_kind":analysis_kind, "timeout_seconds":timeout_seconds,
            "per_condition_seconds":condition_time, "wall_seconds":elapsed, "exit_code":code,
            "diagnostics":diagnostics, "candidates":candidates, "candidate_validation":"INDEPENDENT_ORACLE_REQUIRED",
            "stderr_excerpt":stderr[-4096:], "isolation":"TRUSTED_CHILD_PROCESS_NOT_SECURITY_SANDBOX",
            "source_access":True, "oracle_calls":None, "oracle_call_budget":"NOT_OBSERVABLE_WITH_CROSSHAIR_CLI",
            "cpu_seconds":None, "peak_rss_bytes":None,
            "claim":"tool output is not independent defect confirmation or general correctness proof"}


def solve_relations(variables, relations, *, timeout_ms=1000):
    """Z3 consistency/witness check over a validated integer relation DSL.

    variables: {'x': {'kind':'int','min':-10,'max':10}}
    terms: integer, {'var':'x'}, or {'op':'add'|'sub'|'mul','args':[term,term]}
    relations: {'op':'eq'|'ne'|'le'|'lt'|'ge'|'gt','left':term,'right':term}
    """
    import z3
    if not isinstance(variables, dict) or not 1 <= len(variables) <= 8:
        raise ValueError("1..8 integer variables required")
    if not isinstance(relations, list) or not 1 <= len(relations) <= 32:
        raise ValueError("1..32 relations required")
    if type(timeout_ms) is not int or not 1 <= timeout_ms <= 10000:
        raise ValueError("invalid solver timeout")
    symbols = {}
    solver = z3.Solver()
    solver.set(timeout=timeout_ms)
    for name, domain in variables.items():
        if not isinstance(name,str) or not name.isidentifier() or not isinstance(domain,dict) or set(domain) != {"kind","min","max"}:
            raise ValueError("invalid variable declaration")
        if domain["kind"] != "int" or any(type(domain[k]) is not int for k in ("min","max")) or not -10**9 <= domain["min"] <= domain["max"] <= 10**9:
            raise ValueError("only bounded exact integers are supported")
        symbols[name] = z3.Int(name)
        solver.add(symbols[name] >= domain["min"], symbols[name] <= domain["max"])

    def term(value, depth=0):
        if depth > 6:
            raise ValueError("expression exceeds depth budget")
        if type(value) is int and abs(value) <= 10**9:
            return z3.IntVal(value)
        if not isinstance(value,dict):
            raise ValueError("invalid term")
        if set(value) == {"var"} and value["var"] in symbols:
            return symbols[value["var"]]
        if set(value) != {"op","args"} or value["op"] not in ("add","sub","mul") or not isinstance(value["args"],list) or len(value["args"]) != 2:
            raise ValueError("unsupported term")
        left,right = [term(item,depth+1) for item in value["args"]]
        return {"add":lambda:left+right,"sub":lambda:left-right,"mul":lambda:left*right}[value["op"]]()

    for relation in relations:
        if not isinstance(relation,dict) or set(relation) != {"op","left","right"} or relation["op"] not in ("eq","ne","le","lt","ge","gt"):
            raise ValueError("invalid relation")
        left,right = term(relation["left"]),term(relation["right"])
        solver.add({"eq":left==right,"ne":left!=right,"le":left<=right,"lt":left<right,"ge":left>=right,"gt":left>right}[relation["op"]])
    result = solver.check()
    status = "SAT" if result == z3.sat else "UNSAT" if result == z3.unsat else "UNKNOWN"
    return {"status":status,"witness":{name:solver.model().eval(symbol,model_completion=True).as_long() for name,symbol in symbols.items()} if result == z3.sat else None,
            "backend":"Z3","timeout_ms":timeout_ms,"scope":"declared bounded integer DSL; no target-code correctness claim"}
