"""Static structural IR. Parsing never imports or executes the analyzed source.

The literal-free graph is a necessary structural correspondence check, not a
semantic equivalence proof. Callers must approve the public contract and IR.
"""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from .predicates import compile_guard, predicate_id, predicate_roles, validate_public_ir

MAX_SOURCE_BYTES = 262144
MAX_AST_NODES = 10000
UNSUPPORTED = (ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom,
               ast.Global, ast.Nonlocal, ast.Import, ast.ImportFrom)
MUTATORS = {"append", "extend", "insert", "pop", "remove", "clear", "update",
            "setdefault", "sort", "reverse", "add", "discard"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _annotation(node):
    if node is None:
        return "UNKNOWN"
    if isinstance(node, ast.Name) and node.id in {"int", "float", "str", "bool", "list", "dict", "tuple", "None"}:
        return node.id
    if isinstance(node, ast.Constant) and node.value is None:
        return "None"
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in {"list", "dict", "tuple"}:
        items = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
        return {"kind": node.value.id, "items": [_annotation(item) for item in items]}
    return "UNKNOWN"


def analyze_source(source, function="implementation", roles=None):
    if not isinstance(source, str) or len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("source must be text within 256 KiB")
    if not isinstance(function, str) or not function.isidentifier():
        raise ValueError("function must be a single identifier")
    tree = ast.parse(source)
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        raise ValueError("AST exceeds node budget")
    matches = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function]
    if len(matches) != 1:
        raise ValueError("exactly one top-level target function is required")
    target = matches[0]
    arguments = [*target.args.posonlyargs, *target.args.args, *target.args.kwonlyargs]
    names = [argument.arg for argument in arguments]
    supplied_roles = roles is not None
    roles = {name: f"argument-{index}" for index, name in enumerate(names)} if roles is None else dict(roles)
    if set(roles) != set(names) or len(set(roles.values())) != len(names):
        raise ValueError("roles must map each parameter bijectively")
    if any(not isinstance(role, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", role) for role in roles.values()):
        raise ValueError("invalid semantic role")
    local_names = {}
    for node in ast.walk(target):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id not in roles:
            local_names.setdefault(node.id, f"local-{len(local_names)}")

    def name_of(name):
        return roles.get(name, local_names.get(name, "global:" + name))

    def normalize(node):
        if isinstance(node, ast.Constant):
            return {"node": "Constant", "type": type(node.value).__name__}
        if isinstance(node, ast.Name):
            return {"node": "Name", "role": name_of(node.id), "context": type(node.ctx).__name__}
        if isinstance(node, ast.arg):
            return {"node": "arg", "role": name_of(node.arg), "annotation": _annotation(node.annotation)}
        if isinstance(node, ast.AST):
            result = {"node": type(node).__name__}
            for key, value in ast.iter_fields(node):
                if key in {"name", "type_comment", "decorator_list", "returns"}:
                    continue
                if key == "body" and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    value = [item for item in value if not (isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str))]
                if key == "annotation":
                    result[key] = _annotation(value)
                elif isinstance(value, list):
                    result[key] = [normalize(item) for item in value]
                elif isinstance(value, ast.AST):
                    result[key] = normalize(value)
                elif key in {"attr", "arg"}:
                    # Method and keyword names are structural operators. Literal
                    # values and source variable spellings are not included.
                    result[key] = value
                elif value is not None:
                    result[key] = type(value).__name__
            return result
        return type(node).__name__

    graph = normalize(target)
    target_nodes = list(ast.walk(target))
    unsupported = sorted({type(n).__name__ for n in target_nodes if isinstance(n, UNSUPPORTED)})
    if target.decorator_list:
        unsupported.append("decorated-function")
    if target.args.vararg or target.args.kwarg:
        unsupported.append("variadic-arguments")
    if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)) and n is not target for n in target_nodes):
        unsupported.append("nested-executable-definition")
    calls, effects, dependencies = [], [], []
    for node in target_nodes:
        if isinstance(node, ast.Call):
            callee = (name_of(node.func.id) if isinstance(node.func, ast.Name)
                      else "method:" + node.func.attr if isinstance(node.func, ast.Attribute) else "dynamic-call")
            calls.append(callee)
            if isinstance(node.func, ast.Attribute) and node.func.attr in MUTATORS:
                effects.append({"kind": "mutation-call", "operation": node.func.attr,
                                "dependencies": sorted({name_of(n.id) for n in ast.walk(node.func.value) if isinstance(n, ast.Name)})})
            if callee == "dynamic-call":
                unsupported.append("dynamic-call")
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            reads = sorted({name_of(n.id) for n in ast.walk(node.value) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}) if node.value else []
            for assignment in targets:
                writes = sorted({name_of(n.id) for n in ast.walk(assignment) if isinstance(n, ast.Name)})
                dependencies.append({"writes": writes, "reads": reads, "kind": type(node).__name__})
                if isinstance(assignment, (ast.Attribute, ast.Subscript)):
                    effects.append({"kind": "container-write", "dependencies": writes})
    parameters = [{"name": argument.arg, "role": roles[argument.arg], "annotation": _annotation(argument.annotation)} for argument in arguments]
    predicates, origins, rejections = [], [], []
    for node in target_nodes:
        if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert)):
            try:
                predicate=compile_guard(node.test, roles)
                if not isinstance(predicate, dict) or predicate.get("op") not in {"eq","ne","lt","le","gt","ge","and","or","not"} or not predicate_roles(predicate):
                    raise ValueError("guard is not a supported Boolean expression")
                if predicate not in predicates and len(predicates)<64:
                    origins.append({"index":len(predicates),"kind":type(node).__name__,"line":getattr(node,"lineno",0)})
                    predicates.append(predicate)
            except ValueError:
                if len(rejections)<128:
                    rejections.append({"kind":type(node).__name__,"line":getattr(node,"lineno",0),"reason":"UNSUPPORTED_GUARD_SYNTAX"})
    constraint_graph={"nodes":[{"id":predicate_id(p),"kind":"public-ast-guard"} for p in predicates],
                      "edges":[{"from":predicate_id(p),"to":role,"kind":"depends-on-role"} for p in predicates for role in sorted(predicate_roles(p))]}
    result={"schema": "tomolab-structural-ir-v1", "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "function": function, "parameters": parameters, "return_annotation": _annotation(target.returns),
            "semantic_roles": "DECLARED" if supplied_roles else "POSITIONAL_ONLY",
            "graph": graph, "graph_signature": _digest(graph),
            "control": dict(Counter(type(n).__name__ for n in target_nodes if isinstance(n, (ast.If, ast.IfExp, ast.For, ast.While, ast.Try, ast.Match)))),
            "operators": sorted({type(n).__name__ for n in target_nodes if isinstance(n, (ast.operator, ast.cmpop, ast.boolop, ast.unaryop))}),
            "calls": sorted(set(calls)), "dependencies": dependencies, "state_effects": effects,
            "exception_conditions": [normalize(n.exc) for n in target_nodes if isinstance(n, ast.Raise)],
            "unsupported": sorted(set(unsupported)), "status": "SUPPORTED_STATIC_IR" if not unsupported else "PARTIAL_STATIC_IR",
            "claim": "syntactic correspondence only; constants omitted; no semantic or purity proof",
            "predicates":predicates,"predicate_origins":origins,"predicate_rejections":rejections,
            "constraint_graph":constraint_graph}
    return validate_public_ir(result)


def analyze_file(path, function="implementation", roles=None):
    path = Path(path)
    data = path.read_bytes()
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError("source exceeds 256 KiB")
    return analyze_source(data.decode("utf-8"), function, roles)


# Compatibility export; generators import the pure transfer module directly.
from .transfer import validate_transfer  # noqa: E402
