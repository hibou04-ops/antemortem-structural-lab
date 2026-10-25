"""Behavioral casting against an explicitly supplied oracle; trusted code only."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Callable

from .model import Inspection, Observation, Proposal


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load trusted module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_trusted_functions(
    path: Path, function: str, oracle: str, oracle_path: Path | None = None
) -> tuple[Callable, Callable]:
    """EXECUTES local Python. Caller must explicitly opt in; no sandbox is provided."""
    module = _load_module(path, "_tomolab_trusted_target")
    oracle_module = (_load_module(oracle_path, "_tomolab_trusted_reference")
                     if oracle_path is not None and oracle_path.resolve() != path.resolve() else module)
    a, b = getattr(module, function), getattr(oracle_module, oracle)
    if not callable(a) or not callable(b):
        raise TypeError("implementation and oracle must be callable")
    return a, b


def _capture(fn: Callable, args: tuple[int, ...], *, tracing: bool):
    lines: list[int] = []
    code = fn.__code__
    prior = sys.gettrace()

    def tracer(frame, event, arg):
        if frame.f_code is code:
            if event == "line":
                lines.append(frame.f_lineno)
            return tracer
        return None

    try:
        if tracing:
            sys.settrace(tracer)
        try:
            return "return", fn(*args), tuple(lines)
        except Exception as exc:  # Record errors, not a proof of bad behavior.
            return "exception", f"{type(exc).__name__}: {exc}", tuple(lines)
    finally:
        if tracing:
            sys.settrace(prior)


def observe(impl: Callable, oracle: Callable, ins: Inspection, probe: Proposal) -> Observation:
    actual_type, actual, lines = _capture(impl, probe.inputs, tracing=True)
    expected_type, expected, _ = _capture(oracle, probe.inputs, tracing=False)
    executed = set(lines)
    reached = tuple(g.line for g in ins.guards if g.line in executed)
    taken = tuple(g.line for g in ins.guards if g.line in executed and g.body_line in executed)
    mismatch = (actual_type != expected_type or actual != expected)
    return Observation(probe.inputs, actual, expected, actual_type, expected_type,
                       lines, reached, taken, mismatch, probe.reason, probe.origin)
