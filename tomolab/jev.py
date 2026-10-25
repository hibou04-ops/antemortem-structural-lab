"""Optional TypeSafe Jev / Vercel Jev decision routing.

Only bounded numeric probe metadata is sent. No repository paths/source/secrets.
Jev ranks probes; it is never a truth oracle and cannot authorize execution.

Direct TypeSafe contract: POST https://api.typesafe.ai/v1/systemone,
    model=jev-latest, TYPESAFE_API_KEY.
Vercel AI Gateway contract: POST https://ai-gateway.vercel.sh/v1/evaluate,
    model=typesafe-ai/jev, AI_GATEWAY_API_KEY.

Both accept choice questions but use different billing/authentication routes.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import urllib.request
from typing import Any, Literal

from .model import Proposal

Provider = Literal["auto", "typesafe", "vercel"]

ENDPOINTS = {
    "typesafe": "https://api.typesafe.ai/v1/systemone",
    "vercel": "https://ai-gateway.vercel.sh/v1/evaluate",
}
MODELS = {
    "typesafe": "jev-latest",
    "vercel": "typesafe-ai/jev",
}
ENV_KEYS = {
    "typesafe": "TYPESAFE_API_KEY",
    "vercel": "AI_GATEWAY_API_KEY",
}


class JevError(RuntimeError):
    """Errors must never include credentials or remote response bodies."""


@dataclass(frozen=True)
class Route:
    provider: str
    endpoint: str
    model: str
    key: str


def resolve_route(*, provider: Provider = "auto", key: str | None = None) -> Route:
    """Choose exactly one billing route; NEVER retry on the other provider.

    Direct TypeSafe is preferred when both credentials exist. Caller can force
    the provider to eliminate ambiguity. Explicit ``key`` is useful for tests;
    callers using a key should specify a provider to avoid ambiguity.
    """
    if provider not in ("auto", "typesafe", "vercel"):
        raise ValueError("jev provider must be auto, typesafe, or vercel")
    selected = provider
    if selected == "auto":
        if os.environ.get("TYPESAFE_API_KEY"):
            selected = "typesafe"
        elif os.environ.get("AI_GATEWAY_API_KEY"):
            selected = "vercel"
        elif key:
            selected = "typesafe"
        else:
            raise JevError("no Jev credential set (TYPESAFE_API_KEY or AI_GATEWAY_API_KEY)")
    credential = key or os.environ.get(ENV_KEYS[selected])
    if not credential:
        raise JevError(f"missing credential for {selected} Jev route: {ENV_KEYS[selected]}")
    return Route(selected, ENDPOINTS[selected], MODELS[selected], credential)


def _make_request(
    candidates: list[Proposal], summary: dict[str, Any], *, provider: str = "vercel",
) -> dict[str, Any]:
    """The v0.1.0 default remains the Vercel contract for compatibility."""
    if provider not in MODELS:
        raise ValueError("unknown Jev request provider")
    if not 2 <= len(candidates) <= 8:
        raise ValueError("Jev choice requires 2–8 candidates")
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
        "model": MODELS[provider],
        "state": safe_state,
        "questions": {
            "next": {
                "type": "choice",
                "instructions": (
                    "Choose the next safe offline numeric probe most likely to cover "
                    "a previously unobserved branch. This is prioritization, "
                    "not a correctness verdict."
                ),
                "criteria": {
                    f"p{i}": (
                        f"Probe {i}; origin {p.origin}; "
                        f"previously unseen branch target {p.guard_line is not None}"
                    ) for i, p in enumerate(candidates)
                },
            }
        },
    }


def choose(
    candidates: list[Proposal], summary: dict[str, Any], *,
    key: str | None = None, provider: Provider = "auto",
) -> int:
    """Return allowlisted selection from exactly one Jev API provider.

    Authentication, remote HTTP and response-shape failures raise JevError.
    No provider fallback occurs on failure and exception content is redacted.
    """
    route = resolve_route(provider=provider, key=key)
    body = _make_request(candidates, summary, provider=route.provider)
    request = urllib.request.Request(
        route.endpoint,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {route.key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as resp:
            data = json.loads(resp.read(32768).decode("utf-8"))
        answer = data["answers"]["next"]
        choice = answer["choice"]
        allowed = {f"p{i}" for i in range(len(candidates))}
        if not isinstance(choice, str) or choice not in allowed:
            raise ValueError("choice not in allowlist")
        return int(choice[1:])
    except Exception as exc:
        # Deliberately discard server bodies, URLs and exception messages.
        raise JevError(f"{route.provider} Jev request failed ({type(exc).__name__})") from None
