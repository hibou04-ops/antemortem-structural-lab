"""Typed, auditable records for the experimental cross-modal engine."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Guard:
    line: int
    name: str
    op: str
    constant: int
    body_line: int
    ancestors: tuple[int, ...] = ()

    def satisfy(self) -> int:
        if self.op in ("==", ">=", "<="):
            return self.constant
        if self.op in ("!=", ">"):
            return self.constant + 1
        if self.op == "<":
            return self.constant - 1
        raise ValueError(f"unsupported guard operator: {self.op}")

    def test(self, value: int) -> bool:
        return {
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
            ">=": lambda a, b: a >= b,
            "<=": lambda a, b: a <= b,
            ">": lambda a, b: a > b,
            "<": lambda a, b: a < b,
        }[self.op](value, self.constant)


@dataclass(frozen=True)
class Inspection:
    source_file: str
    source_sha256: str
    function: str
    parameters: tuple[str, ...]
    guards: tuple[Guard, ...]
    limitations: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Proposal:
    inputs: tuple[int, ...]
    reason: str
    origin: str  # static | feedback | random
    guard_line: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Observation:
    inputs: tuple[int, ...]
    actual: Any
    expected: Any
    actual_type: str
    expected_type: str
    traced_lines: tuple[int, ...]
    reached_guards: tuple[int, ...]
    taken_guards: tuple[int, ...]
    contradicts_oracle: bool
    reason: str
    origin: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExperimentResult:
    schema: str
    mode: str
    source: dict[str, Any]
    oracle_function: str
    budget: int
    seed: int
    observations: list[Observation] = field(default_factory=list)
    meta_disagreements: list[dict[str, Any]] = field(default_factory=list)
    decision_provider: str = "off"
    decision_calls: int = 0
    decision_fallbacks: int = 0
    status: str = "NO_COUNTEREXAMPLE_FOUND"

    def as_dict(self) -> dict[str, Any]:
        cases = [o.as_dict() for o in self.observations]
        findings = [o.as_dict() for o in self.observations if o.contradicts_oracle]
        reached = sorted({line for o in self.observations for line in o.reached_guards})
        taken = sorted({line for o in self.observations for line in o.taken_guards})
        return {
            "schema": self.schema,
            "mode": self.mode,
            "source": self.source,
            "oracle_function": self.oracle_function,
            "oracle_scope": "user-supplied executable reference; not independent universal truth",
            "budget": self.budget,
            "seed": self.seed,
            "call_count": len(self.observations),
            "status": self.status,
            "decision_provider": self.decision_provider,
            "decision_calls": self.decision_calls,
            "decision_fallbacks": self.decision_fallbacks,
            "observed_guards": reached,
            "taken_guards": taken,
            "structural_model_disagreements": self.meta_disagreements,
            "findings": findings,
            "observations": cases,
        }
