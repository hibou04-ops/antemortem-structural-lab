"""Independent explicit branch reference for the public demo contract."""
def reference(lo, hi):
    if hi <= lo:
        return 0
    return hi-lo
