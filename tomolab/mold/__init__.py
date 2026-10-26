"""Typed, bounded structural mold learning; independent truth stays outside."""
from .engine import MoldEngine, transfer
from .relations import solve
from .schema import default_spec, normalize_evidence

__all__ = ["MoldEngine", "transfer", "solve", "default_spec", "normalize_evidence"]
