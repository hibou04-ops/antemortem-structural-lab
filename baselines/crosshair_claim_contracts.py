"""CrossHair no-reference baseline with SAME relational obligations.

Run from the project root:
    python -m crosshair check --analysis_kind=asserts baselines/crosshair_claim_contracts.py

IMPORTANT: The leading assert is a PRECONDITION. A *non-assert statement*
separates it from the later assert, which is the actual postcondition.
"""
from examples.claim_only import monotone_bug, shift_bug, sum_clean, symmetry_bug


def symmetry_claim(x: int, y: int) -> None:
    assert -25 <= x <= 25 and -25 <= y <= 25
    a = symmetry_bug.implementation(x, y)
    b = symmetry_bug.implementation(y, x)
    assert a == b


def shift_claim(x: int, y: int) -> None:
    assert -24 <= x <= 25 and -25 <= y <= 25
    a = shift_bug.implementation(x - 1, y)
    b = shift_bug.implementation(x, y)
    assert b == a + 1


def monotone_claim(x: int, y: int) -> None:
    assert -24 <= x <= 25 and -25 <= y <= 25
    a = monotone_bug.implementation(x - 1, y)
    b = monotone_bug.implementation(x, y)
    assert b >= a


def clean_symmetry_claim(x: int, y: int) -> None:
    assert -25 <= x <= 25 and -25 <= y <= 25
    a = sum_clean.implementation(x, y)
    b = sum_clean.implementation(y, x)
    assert a == b


def clean_shift_claim(x: int, y: int) -> None:
    assert -24 <= x <= 25 and -25 <= y <= 25
    a = sum_clean.implementation(x - 1, y)
    b = sum_clean.implementation(x, y)
    assert b == a + 1


def clean_monotone_claim(x: int, y: int) -> None:
    assert -24 <= x <= 25 and -25 <= y <= 25
    a = sum_clean.implementation(x - 1, y)
    b = sum_clean.implementation(x, y)
    assert b >= a
