"""Offline only: a Gymnasium-style environment around one endurance cycle, for PPO trials.

Not imported by the backend and not packaged in the Lambda. Gymnasium is optional: with
it installed the class is a `gymnasium.Env` with Box spaces; without it the same
reset/step API works on plain lists.

An episode is one cycle. The action is the perturbation vector in σ (one entry per
dimension of `academy.adversary.dimensions`, cut at ±3); the observation is each
failure family's distance to failure on the last cycle. The reward is the adaptive
stress testing reward the cross-entropy search ranks by: the action's log-likelihood
under the nominal distribution, less ALPHA times the closest family's distance to
failure when the cycle holds. Synthetic teaching model only.

    uv run python scripts/ast-env.py flex-reader --drift-mm 10 --episodes 5
"""

import argparse
import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "backend"))

from academy import adversary, endurance, examples  # noqa: E402

try:
    import gymnasium
    import numpy as np
except ImportError:  # the plain API below needs neither
    gymnasium = None

Base = gymnasium.Env if gymnasium else object


class CycleEnv(Base):
    def __init__(self, twins, layout, steps, noise=None, grip=None, speed=20):
        noise, grip = endurance._settings(noise, grip)
        self.search = adversary.Search(twins, layout, steps, noise, grip, speed)
        self.families = list(adversary.FAMILIES)
        size = len(self.search.dims)
        if gymnasium:
            t = adversary.TRUNCATE
            self.action_space = gymnasium.spaces.Box(-t, t, (size,), dtype=np.float64)
            self.observation_space = gymnasium.spaces.Box(0.0, 1.0, (len(self.families),))
        self.size = size

    def observation(self, sample=None):
        if sample is None:
            return [1.0] * len(self.families)
        return [sample["distance"][f] for f in self.families]

    def reset(self, seed=None, options=None):
        return self.observation(), {}

    def step(self, action):
        sample = self.search.evaluate([float(v) for v in action])
        failed = bool(sample["failed"])
        reward = sample["loglik"]
        if not failed:
            reward -= adversary.ALPHA * min(sample["distance"].values())
        info = {"failures": sample["failures"], "sigma": sample["z"]}
        return self.observation(sample), reward, True, False, info


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("example", choices=sorted(examples.EXAMPLES))
    parser.add_argument("--drift-mm", type=float, default=endurance.NOISE["drift_mm"])
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    counter = itertools.count()
    twins, steps, layout = examples.build(
        examples.EXAMPLES[args.example], lambda: f"twin-{next(counter)}"
    )
    env = CycleEnv({t["id"]: t for t in twins}, layout, steps, noise={"drift_mm": args.drift_mm})
    rng = random.Random(args.seed)
    for episode in range(args.episodes):
        env.reset(seed=args.seed + episode)
        action = [rng.gauss(0, 1) for _ in range(env.size)]
        obs, reward, *_, info = env.step(action)
        modes = [f["mode"] for f in info["failures"]] or "held"
        print(f"episode {episode}: reward {reward:.2f}, distances {obs}, {modes}")


if __name__ == "__main__":
    main()
