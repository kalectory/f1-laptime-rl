class Policy:
    def __init__(self, track, car): pass
    def act(self, obs):
        if obs["t"] > 1: raise ValueError("boom")
        return 0.0, 1.0, 0.0
