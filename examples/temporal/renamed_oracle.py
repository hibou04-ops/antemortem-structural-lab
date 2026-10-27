"""Independent renamed reference; only declared public actions are enabled."""
class Model:
    def __init__(self):
        self.occupancy = 0

    def step(self, action, argument):
        if action == "offer":
            self.occupancy += 1
        elif action == "take":
            self.occupancy -= 1
        elif action == "wipe":
            self.occupancy = 0
        else:
            raise ValueError("undeclared action")

    def snapshot(self):
        return {"size":self.occupancy}


def make_subject():
    return Model()
