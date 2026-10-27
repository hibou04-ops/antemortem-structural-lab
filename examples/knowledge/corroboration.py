"""A separately written form of the same authored functional failure."""
def implementation(lo, hi):
    if hi < lo:
        return lo-hi
    return hi-lo
