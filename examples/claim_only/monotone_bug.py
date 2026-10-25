"""Trusted synthetic target; violates nondecreasing-in-x at a guarded boundary."""


def implementation(x: int, y: int) -> int:
    if x >= 19:
        if y <= -12:
            return x + y - 2
    return x + y
