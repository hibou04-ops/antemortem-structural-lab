"""Trusted, public demonstration with one deliberately injected defect."""


def implementation(x: int, y: int) -> int:
    return x + y + (1 if x - y == 3 else 0)
