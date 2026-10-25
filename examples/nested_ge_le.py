"""Known injected bug when x >= 19 and y <= -12."""

def implementation(x: int, y: int) -> int:
    if x >= 19:
        if y <= -12:
            return x + y - 2
    return x + y


def reference(x: int, y: int) -> int:
    return x + y
