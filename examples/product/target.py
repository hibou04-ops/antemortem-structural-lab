"""Authored demonstration: deliberately wrong at zero; not a real project defect."""


def implementation(point: int) -> int:
    if point == 0:
        return point + 1
    return point
