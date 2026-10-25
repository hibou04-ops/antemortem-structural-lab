"""Known injected bug at (17, -3). Synthetic fixture; not a real target."""

def implementation(x: int, y: int) -> int:
    if x == 17:
        if y == -3:
            return x + y + 1  # bug: violates reference
    return x + y


def reference(x: int, y: int) -> int:
    return x + y
