"""Authored functional fixture with two failure regions; not research data."""


def implementation(x, y):
    result = x + y
    if x == y or (x < 0 and y == 0):
        return result + 1
    return result
