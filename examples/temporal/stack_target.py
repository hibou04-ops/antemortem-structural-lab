"""Reviewed E5 last-element regression; not a new independent research defect."""
class Subject:
    def __init__(self):
        self.items = []

    def step(self, action, argument):
        if action == "push":
            self.items.append(argument)
        elif action == "pop":
            if len(self.items) > 1:
                self.items.pop()
        elif action == "clear":
            self.items.clear()
        else:
            raise ValueError("undeclared action")

    def snapshot(self):
        return {"size":len(self.items)}


def make_subject():
    return Subject()
