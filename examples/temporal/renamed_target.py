"""Same reviewed failure mechanism in renamed deque operations."""
from collections import deque


class Subject:
    def __init__(self):
        self.entries = deque()

    def step(self, action, argument):
        if action == "offer":
            self.entries.appendleft(argument)
        elif action == "take":
            if len(self.entries) != 1:
                self.entries.popleft()
        elif action == "wipe":
            self.entries = deque()
        else:
            raise ValueError("undeclared action")

    def snapshot(self):
        return {"size":len(self.entries)}


def make_subject():
    return Subject()
