"""Reference stack model, evaluated independently on the same bounded trace."""


def reference(trace: list[tuple[str, int]]) -> list[int]:
    state = []
    for operation, argument in trace:
        if operation == "push":
            state = state + [argument]
        elif operation == "pop":
            state = state[:-1]
    return state
