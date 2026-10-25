"""Trusted synthetic target; deliberately violates input-swap symmetry."""


def implementation(x: int, y: int) -> int:
    if x == 17:
        if y == -3:
            return x + y + 1
    return x + y
