"""Optional Jev routing; no network calls unless explicitly enabled.

Only narrow numeric/guard metadata is transmitted; no source code or secrets.
Jev ranks experiments, never establishes correctness or overrides an oracle.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from .model import Proposal

ENDPOINT = "https://ai-gateway.vercel.sh/v1/evaluate"


class JevError(RuntimeError):
    pass


def _make_request(candidates: list[Proposal], summary: dict[str, Any]) -> dict[str, Any]:
    if not 2 <= len(candidates) <= 8:
        raise ValueError("Jev choice requires 2–8 candidates")
    # No filename, repo, source or any detailed finding is sent outside.
    safe_state = {
        "tested": int(summary.get("tested", 0)),
        "observed_guards": int(summary.get("observed_guards", 0)),
        "candidates": [
            {"id": f"p{i}", "origin": p.origin,
             "guard_line": p.guard_line is not None,
             "input_values": list(p.inputs)}
            for i, p in enumerate(candidates)
        ],
    }
    return {
        "model": "typesafe-ai/jev",
        "state": safe_state,
        "questions": {
            "next": {
                "type": "choice",
                "instructions": "Select the next safe offline numeric probe most likely to cover a previously unobserved branch. This is prioritization, not a correctness verdict.",
                "criteria": {f"p{i}": f"Probe {i}; origin {p.origin}; previously unseen branch target {p.guard_line is not None}" for i, p in enumerate(candidates)},
            }
        },
    }


def choose(candidates: list[Proposal], summary: dict[str, Any], *, key: str | None = None) -> int:
    """Return candidate index from authenticated Jev API; invalid replies raise."""
    key = key or os.environ.get("AI_GATEWAY_API_KEY")
    if not key:
        raise JevError("AI_GATEWAY_API_KEY missing; Jev mode is not active")
    body = _make_request(candidates, summary)
    request = urllib.request.Request(
        ENDPOINT, data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as resp:
            data = json.loads(resp.read(32768).decode("utf-8"))
        choice = data["answers"]["next"]["choice"]
        if not isinstance(choice, str) or choice not in {f"p{i}" for i in range(len(candidates))}:
            raise ValueError("choice not in allowlist")
        return int(choice[1:])
    except Exception as exc:
        raise JevError(f"Jev request/response failed: {type(exc).__name__}") from exc
