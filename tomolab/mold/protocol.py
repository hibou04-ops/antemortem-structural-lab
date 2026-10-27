"""Typed public messages checked before transport and again in the worker.

This is a data boundary, not protection against a malicious evaluator host.
Oracle outputs, target code, file paths and model scores have no message fields.
The diagnostic action is the explicit exception for a harmless host sentinel.
"""
from __future__ import annotations

from copy import deepcopy

from .schema import exact_keys, integer, normalize_evidence, validate_spec

MAX_MESSAGE = 8_000_000
PROTOCOL = "tomolab-generator-protocol-v2"

FIELDS = {
    "init": (("action", "spec"), ("seed", "strategy", "solver")),
    "propose": (("action",), ()),
    "observe": (("action", "evidence"), ()),
    "freeze": (("action",), ()),
    "snapshot": (("action",), ()),
    "transfer": (("action", "snapshot", "spec"), ("seed", "budget", "solver")),
    "diagnose": (("action", "host_sentinel"), ()),
    "close": (("action",), ()),
}


def validate_request(message, spec=None):
    """Return detached, validated data; reject forbidden data before sending it."""
    if not isinstance(message, dict) or not isinstance(message.get("action"), str):
        raise ValueError("request must contain an action")
    action = message["action"]
    if action not in FIELDS:
        raise ValueError("unknown action or forbidden request field")
    required, optional = FIELDS[action]
    try:
        exact_keys(message, required, optional)
    except ValueError as exc:
        raise ValueError("missing or forbidden request field") from exc
    clean = deepcopy(message)
    if action in ("init", "transfer"):
        clean["spec"] = validate_spec(message["spec"])
        if "seed" in message:
            integer(message["seed"], 0, 2**32 - 1, "seed")
        if "solver" in message and message["solver"] not in ("enumeration", "z3"):
            raise ValueError("unsupported solver")
    if action == "init" and message.get("strategy", "mold") not in ("mold", "uniform"):
        raise ValueError("unsupported strategy")
    if action == "transfer":
        # Reconstruct derived state before transmitting any external snapshot.
        # A valid digest alone does not establish that its fields are public.
        from .engine import MoldEngine
        MoldEngine.from_snapshot(message["snapshot"])
        if "budget" in message:
            integer(message["budget"], 1, 4225, "budget")
    if action == "observe":
        if spec is None:
            raise ValueError("init required")
        clean["evidence"] = normalize_evidence(message["evidence"], spec)
    if action == "diagnose":
        sentinel = message["host_sentinel"]
        if not isinstance(sentinel, str) or not 1 <= len(sentinel) <= 4096 or "\x00" in sentinel:
            raise ValueError("invalid host sentinel path")
    return clean
