"""Known injected bug when x < -9 and y == 14."""

def implementation(x: int, y: int) -> int:
    if x < -9:
        if y == 14:
            return x + y + 3
    return x + y


def reference(x: int, y: int) -> int:
    return x + y
