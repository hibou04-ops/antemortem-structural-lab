"""Authored functional fixture: mistakenly treats a reversed interval as width."""
def implementation(start, stop):
    return abs(stop-start)
