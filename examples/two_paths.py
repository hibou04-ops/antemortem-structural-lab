"""Two competing static targets. Jev may help or hurt target choice."""

def implementation(x: int, y: int) -> int:
    if x == 17:
        if y == -3:
            return x + y + 1
    if x == -14:
        if y == 11:
            return x + y - 2
    return x + y


def reference(x: int, y: int) -> int:
    return x + y
