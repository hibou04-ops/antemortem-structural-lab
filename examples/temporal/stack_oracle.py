"""Independent scalar reference for the explicitly declared size invariant."""
class Model:
    def __init__(self):
        self.count = 0

    def step(self, action, argument):
        if action == "push":
            self.count += 1
        elif action == "pop":
            self.count -= 1
        elif action == "clear":
            self.count = 0
        else:
            raise ValueError("undeclared action")

    def snapshot(self):
        return {"size":self.count}


def make_subject():
    return Model()
