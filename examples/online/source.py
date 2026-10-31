"""Authored Source for the installed functional CLI example, not research evidence."""
def implementation(values: list[int]) -> int:
    if len(values) == 0:
        return 1
    return sum(values)
