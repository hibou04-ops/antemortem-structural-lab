"""Same approved operation structure with different public parameter names."""


def implementation(sequence: list[int], delta: int) -> int:
    result = 0
    for item in sequence:
        result += item
    if len(sequence) >= 2 and sum(sequence) == 0:
        return result + delta + 1
    return result + delta
