"""Reviewed bounded stack trace with a deliberately incorrect pop transition."""


def implementation(trace: list[tuple[str, int]]) -> list[int]:
    stack = []
    for action, value in trace:
        if action == "push":
            stack.append(value)
        elif action == "pop" and stack:
            if len(stack) > 1:
                stack.pop()
    return stack
