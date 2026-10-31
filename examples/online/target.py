"""Separate authored implementation; empty-input handling is intentionally defective."""
def implementation(values: list[int]) -> int:
    result = 1
    for index, value in enumerate(values):
        if index == 0:
            result = 0
        result += value
    return result
