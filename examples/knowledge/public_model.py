"""Approved public contract model, not an inspection of a hidden target."""
def reference(start: int, stop: int) -> int:
    if start > stop:
        return 0
    return stop-start
