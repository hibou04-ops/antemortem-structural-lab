"""Negative control: implementation and oracle agree for every input."""

def implementation(x: int, y: int) -> int:
    if x == 17:
        if y == -3:
            return x + y
    return x + y


def reference(x: int, y: int) -> int:
    return x + y
