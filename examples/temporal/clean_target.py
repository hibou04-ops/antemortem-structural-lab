"""Reviewed clean control with ordinary list semantics."""
class Subject:
    def __init__(self):
        self.values = []

    def step(self, action, argument):
        if action == "push":
            self.values += [argument]
        elif action == "pop":
            self.values = self.values[:-1]
        elif action == "clear":
            self.values = []
        else:
            raise ValueError("undeclared action")

    def snapshot(self):
        return {"size":len(self.values)}


def make_subject():
    return Subject()
