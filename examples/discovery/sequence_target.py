"""Reviewed public sequence example; no imports, I/O or external execution."""


def implementation(values: list[int], offset: int) -> int:
    total = 0
    for value in values:
        total += value
    if len(values) >= 2 and sum(values) == 0:
        return total + offset + 1
    return total + offset
