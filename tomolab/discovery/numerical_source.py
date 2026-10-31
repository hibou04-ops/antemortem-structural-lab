# SPDX-License-Identifier: Apache-2.0
# Original Pearson code: Copyright (c) 2026 Kyunghoon Gwak <hibouaile04@gmail.com>
"""Reviewed, pinned Source-only numerical fixture and preserved Oracle adapter.

The production function and result type below retain the original function
AST. They are deliberately unpatched so development recipes can be checked
against the historical Source. This module is host-only; generator workers
receive neither the function nor Oracle outputs. It never imports omega_lock.

The exact math helpers retain the separately reviewed E7 helper AST. A
Source-only adapter preserves R1's finite-JSON comparison (boolean and None
exact; finite numeric output tolerances 1e-10 absolute and 1e-8 relative).
No comparison epsilon, degeneracy rule or exception policy is changed.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
import math
from typing import Literal

from .qualified_comparison import equivalent

PearsonStatus = Literal["OK", "EMPTY", "LENGTH_MISMATCH", "ZERO_VARIANCE_X", "ZERO_VARIANCE_Y"]

_SOURCE_IDENTITY = {
    "repository": "hibou04-ops/omega-lock",
    "revision": "14ff508b2974298305d74c1c90bb43d3c0c13b82",
    "path": "src/omega_lock/walk_forward.py",
    "function": "pearson_result",
    "source_blob": "98c9d7eb5651aabd7074b184a544e2c34b04b8ab",
    "source_file_sha256": "25e8b722b824f15d9607b28158533e618afaf4cb9c80783df5084f3f5265fd1a",
    "function_ast_serialization_runtime": "CPython 3.12",
    "function_ast_sha256": {
        "PearsonResult": "087d9d5087041d3286cb2a90e6d33d58de69a7d556cac33f62390856702b6204",
        "pearson_result": "b5f7c457f2c8ef0c9f5da9d1a35075f167da0d6dd32cab6e03f9205c3e5f8ede",
    },
    "reviewed_extraction_sha256": "a87f8b23fb526cea8f7e55961c40051c67e0c690acf34a2a096f442dc01b6272",
    "oracle_semantic_sha256": "67f5677cb06220ea835620f4ef1ea6cf04fcb990a2c990c15b3d2b5dad4d88e9",
    "reviewed_math_helper_sha256": "14412b88f5dd0ef5d46b0c461ea47679be32eb28f160af74f487fa90b8c95139",
    "oracle_helper_source": "scripts/evaluate-e7.py at E8-R1 e10699f602fb8757098e0ba675b44e54828f960c",
    "scope": "HISTORICAL_SOURCE_DEVELOPMENT_ONLY_NOT_CURRENT_RELEASE_OR_EXTERNAL_GENERALIZATION",
    "production_code_modified": False,
}


def source_identity():
    """Return provenance without callbacks, original inputs or private paths."""
    return deepcopy(_SOURCE_IDENTITY)


def comparison_policy():
    """The existing R1 numeric comparison; no new epsilon or tolerance."""
    return {"kind": "FINITE_JSON", "absolute_tolerance": 1e-10,
            "relative_tolerance": 1e-8, "undefined": "EXECUTION_ERROR",
            "exceptions": "EXECUTION_ERROR"}


@dataclass(frozen=True)
class PearsonResult:
    """Structured Pearson outcome.

    Reviewer P1: ``pearson()`` previously collapsed every failure mode
    to ``0.0`` — a degenerate "could not compute" was indistinguishable
    from a measured "no correlation". Both situations failed KC-4 by
    falling under ``pearson_min``, but the artifact reader couldn't tell
    whether the run produced bad evidence or no evidence.

    ``value`` is None when status != OK; the caller must inspect status
    before comparing against a numeric threshold.
    """

    value: float | None
    status: PearsonStatus

    @property
    def computable(self) -> bool:
        return self.status == "OK"


def pearson_result(xs: list[float], ys: list[float]) -> PearsonResult:
    """Structured Pearson with explicit degeneracy categories."""
    n = len(xs)
    if n == 0:
        return PearsonResult(value=None, status="EMPTY")
    if n != len(ys):
        return PearsonResult(value=None, status="LENGTH_MISMATCH")
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = (sum((x - mx) ** 2 for x in xs)) ** 0.5
    dy = (sum((y - my) ** 2 for y in ys)) ** 0.5
    if dx == 0:
        return PearsonResult(value=None, status="ZERO_VARIANCE_X")
    if dy == 0:
        return PearsonResult(value=None, status="ZERO_VARIANCE_Y")
    return PearsonResult(value=num / (dx * dy), status="OK")


def exact_centered(values):
 """Exact binary-float centering; never infer zero from rounded arithmetic."""
 xs=[Fraction.from_float(float(x)) for x in values]
 if not xs:raise ValueError('exact centering requires nonempty values')
 mean=sum(xs,Fraction(0))/len(xs)
 centered=[x-mean for x in xs]
 return centered,sum((x*x for x in centered),Fraction(0))


def rational_sqrt(value):
 """Approximate only the final square root, after exact sign/zero decisions."""
 value=Fraction(value)
 if value<0:raise ValueError('square root requires nonnegative rational')
 with localcontext() as context:
  context.prec=100
  return float((Decimal(value.numerator)/Decimal(value.denominator)).sqrt())


def exact_correlation(a,b,epsilon=Fraction(0)):
 if len(a)!=len(b) or not a:raise ValueError('aligned nonempty series required')
 da,va=exact_centered(a);db,vb=exact_centered(b);epsilon=Fraction(epsilon)
 ca=va<epsilon if epsilon else va==0;cb=vb<epsilon if epsilon else vb==0
 if ca or cb:return None,ca,cb
 covariance=sum((x*y for x,y in zip(da,db)),Fraction(0))
 magnitude=rational_sqrt(covariance*covariance/(va*vb))
 return -magnitude if covariance<0 else magnitude,False,False


def target_result(point):
    """Run only the pinned reviewed Source; callers enforce the domain first."""
    result = pearson_result(point["a"], point["b"])
    return {"computable": result.computable, "value": result.value}


def oracle_result(point):
    """Preserve the reviewed exact-input Oracle and exact-zero decision."""
    value, left_constant, right_constant = exact_correlation(point["a"], point["b"], Fraction(0))
    return {"computable": not (left_constant or right_constant), "value": value}


def compare_results(actual, expected):
    """Exceptions/nonfinite results raise; they are never negative evidence."""
    return equivalent(actual, expected, comparison_policy())


def public_numerical_features(point):
    """Input/public-arithmetic features; no target or Oracle output required.

    These features diagnose centering behavior. They do not label failure,
    supply hidden expected outputs, or assert bitwise invariance under a
    transformation. Recipe generation separately rechecks its full domain.
    """
    result = {}
    for name in ("a", "b"):
        values = point[name]
        if not values or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError("nonempty finite numerical input required")
        rounded_mean = sum(values) / len(values)
        result[name] = {
            "all_equal": all(v == values[0] for v in values),
            "count": len(values),
            "range": max(values) - min(values),
            "scale": max(abs(v) for v in values),
            "maximum_ulp": max(math.ulp(v) for v in values),
            "public_centering_residual_nonzero": any(v - rounded_mean != 0 for v in values),
        }
    return result


def classify_mechanism(point, actual, expected):
    """A reviewed Source diagnostic, not an independent defect counter."""
    if compare_results(actual, expected):
        return "NO_FAILURE"
    features = public_numerical_features(point)
    centered_constant = any(row["all_equal"] and row["public_centering_residual_nonzero"]
                            for row in features.values())
    if expected["computable"] is False and actual["computable"] is True and centered_constant:
        return "CONSTANT_CENTERING_ROUNDOFF_MISCLASSIFIES_DEGENERACY"
    return "OTHER_REQUIRES_REVIEW"


def evaluate_point(point):
    """One Source/Oracle pair. The host validates domain before this call.

    Raises on execution/Oracle errors; no exception becomes a normal label.
    Generator code must not import or receive this host-only evaluator.
    """
    source = pearson_result(point["a"], point["b"])
    actual = {"computable": source.computable, "value": source.value}
    expected = oracle_result(point)
    return {"actual": actual, "expected": expected,
            "failed": not compare_results(actual, expected), "source_status": source.status,
            "mechanism": classify_mechanism(point, actual, expected)}
