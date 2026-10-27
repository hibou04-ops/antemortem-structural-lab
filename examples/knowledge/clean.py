"""Correct public control for directed interval width."""
def implementation(left, right):
    difference = right-left
    return difference if difference > 0 else 0
