"""Adaptive stress testing: search the endurance perturbations for the likeliest failure.

The endurance run draws every cycle's perturbations at random, so a failure that needs a
2.5σ drift in the right direction shows up about once in a few hundred cycles. Here an
adversary steers the draws instead. Each perturbation of every instrument and transfer
(drift x, z and yaw; pick and place error x and z; labware mass; arm speed) is one
dimension of a vector z in units of its nominal σ, so the nominal distribution is a
standard normal on z, cut at ±3σ as in the endurance run.

Search. The cross-entropy method: one Gaussian over z per failure family (collision,
grip, tracking, limit). Every iteration samples each, simulates the samples, and refits
each Gaussian to the samples that score best for its family. It is policy search
without a network: the policy is the Gaussian.

Objective, the adaptive-stress-testing reward. A cycle that fails scores by its
log-likelihood under the nominal distribution, -|z|²/2, so the search prefers the most
probable failure. A cycle that holds scores by its log-likelihood less ALPHA times its
distance to failure: the margin it has left as a share of the nominal plan's (clearance
above the planner's safety distance, grip margin above 1, tracking headroom, torque and
joint-limit headroom), which gives the search a gradient toward failure. A found
failure is then pulled toward the origin along its ray while it still fails.

Probability. |z| of a failure is its Mahalanobis distance from the nominal cycle, and
Φ(-|z|) the first-order (FORM) estimate of its probability: the chance that a random
cycle crosses a flat boundary through that point. The share of |z|² each dimension
carries says which perturbations matter.

Iteration k samples from the random stream "seed:adversary:k" and the whole search
state travels in the response, so a resumed search equals a one-shot one. Synthetic
teaching result: no physical robot, gripper or labware has been run, and it is not
Isaac/GPU validation.
"""

import math
import random
import time

from fastapi import HTTPException
from pydantic import ConfigDict, Field

from . import arm_simulation, endurance
from .mock_contract import PlanError
from .models import StrictModel
from .workcell_layout import NOMINAL_SPEED

TRUNCATE = endurance.TRUNCATE
ALPHA = 100.0  # nats per unit of normalised distance to failure
SMOOTH = 0.7  # weight of the refitted Gaussian against the previous one
MIN_STD = 0.2
SHRINK = 0.2  # first step toward the origin for a found failure, as a share of |z|
MAX_SHRINK = 0.5
MIN_SHRINK = 0.01
SWEEP = 2  # dimensions of a found failure halved in turn per iteration
MAX_REACH = 1.5  # the furthest an outward step multiplies a closest cycle
FAMILIES = {
    "collision": ("collision",),
    "grip": ("slip", "drop"),
    "tracking": ("tracking",),
    "limit": ("limit", "ik"),
}
FAMILY_OF = {mode: family for family, modes in FAMILIES.items() for mode in modes}
DRIVERS = 3
MAX_BUDGET = 2000
MAX_DIMS = 400


def _dim(kind, label, sigma, unit, twin_id=None, step=None):
    return {
        "kind": kind,
        "twin_id": twin_id,
        "step": step,
        "label": label,
        "sigma": sigma,
        "unit": unit,
    }


def dimensions(twins, layout, transfers, arms, noise):
    """The search dimensions: every perturbation with a nonzero σ, in drawing order."""
    dims = []
    for p in layout["placements"]:
        twin = p["twin_id"]
        if twin in arms:  # the arms are the reference the others drift from
            continue
        name = twins[twin]["spec"]["name"]
        dims.append(_dim("drift_x", f"{name} drift x", noise["drift_mm"], "mm", twin_id=twin))
        dims.append(_dim("drift_z", f"{name} drift z", noise["drift_mm"], "mm", twin_id=twin))
        dims.append(_dim("drift_yaw", f"{name} turn", noise["drift_deg"], "°", twin_id=twin))
    for t in transfers:
        step = t["step"]
        for where in ("pick", "place"):
            for axis in ("x", "z"):
                label = f"Step {step} {where} error {axis}"
                dims.append(_dim(f"{where}_{axis}", label, noise["pose_mm"], "mm", step=step))
        dims.append(_dim("mass", f"Step {step} labware mass", noise["mass_pct"], "%", step=step))
        dims.append(_dim("speed", f"Step {step} arm speed", noise["speed_pct"], "%", step=step))
    return [d for d in dims if d["sigma"] > 0]


def perturb(dims, z, layout, transfers, arms):
    """(drift, moves) in the shape `endurance.perturbation` returns, at z σ per dimension."""
    drift = {
        p["twin_id"]: [0.0, 0.0, 0.0] for p in layout["placements"] if p["twin_id"] not in arms
    }
    moves = {
        t["step"]: {"pick": [0.0, 0.0], "place": [0.0, 0.0], "mass": 1.0, "speed": 1.0}
        for t in transfers
    }
    for dim, value in zip(dims, z, strict=True):
        value = max(-TRUNCATE, min(TRUNCATE, value)) * dim["sigma"]
        kind = dim["kind"]
        if kind.startswith("drift_"):
            index = ("x", "z", "yaw").index(kind[6:])
            drift[dim["twin_id"]][index] = value if index == 2 else value / 1000
        elif kind in ("mass", "speed"):
            moves[dim["step"]][kind] = max(0.2, 1 + value / 100)
        else:
            where, axis = kind.split("_")
            moves[dim["step"]][where][0 if axis == "x" else 1] = value / 1000
    return {k: tuple(v) for k, v in drift.items()}, [moves[t["step"]] for t in transfers]


def _phi(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _share(left, nominal_left):
    """Margin left as a share of the nominal plan's, 0 at failure."""
    return max(0.0, left) / nominal_left if nominal_left > 1e-9 else 1.0


def distances(record, summaries, nominal):
    """Normalised distance to failure per family: 1 on the nominal plan, 0 at failure."""
    failed = {FAMILY_OF[f["mode"]] for f in record["failures"]}
    by_step = {n["step"]: n for n in nominal}
    out = {family: (0.0 if family in failed else 1.0) for family in FAMILIES}
    safety, tracking = arm_simulation.SAFETY, arm_simulation.TRACKING_LIMIT_DEG
    for s in summaries:
        n = by_step.get(s["step"])
        if n is None:
            continue
        grip, grip_nominal = s["grasp"]["margin"], n["grasp"]["margin"]
        found = {
            "collision": _share(s["clearance_m"] - safety, n["clearance_m"] - safety),
            "grip": _share(grip - 1, grip_nominal - 1) if grip and grip_nominal else 1.0,
            "tracking": _share(tracking - s["tracking_deg"], tracking - n["tracking_deg"]),
            "limit": min(
                _share(1 - s["torque_ratio"], 1 - n["torque_ratio"]),
                _share(s["joint_headroom_rad"], n["joint_headroom_rad"]),
            ),
        }
        for family, value in found.items():
            if family not in failed:
                out[family] = min(out[family], value)
    return {k: round(v, 4) for k, v in out.items()}


def _norm(z):
    return math.sqrt(sum(v * v for v in z))


def _score(sample, family):
    """Rank key: a failure of the family first, then likelihood less distance to failure."""
    if family in sample["failed"]:
        return (1, sample["loglik"])
    return (0, sample["loglik"] - ALPHA * sample["distance"][family])


class Search:
    """The compiled workflow, its nominal cycle and the evaluation of one perturbation."""

    def __init__(self, twins, layout, steps, noise, grip, speed):
        self.twins, self.layout, self.speed = twins, layout, speed
        self.transfers = endurance.nominal(twins, layout, steps)
        self.params = endurance.parameters(self.transfers, grip)
        self.cell = endurance.Cell(twins, layout, self.transfers)
        self.dims = dimensions(twins, layout, self.transfers, self.cell.arms, noise)
        record, self.nominal, _, _ = self.run([0.0] * len(self.dims))
        self.nominal_ok = record["ok"]

    def run(self, z, keep=False):
        drift, moves = perturb(self.dims, z, self.layout, self.transfers, self.cell.arms)
        record, summaries, details = endurance.run_perturbed(
            self.cell, self.transfers, self.params, drift, moves, self.speed, keep
        )
        return record, summaries, details, (drift, moves)

    def evaluate(self, z):
        # Rounded first, so the σ values reported replay exactly this cycle.
        z = [round(max(-TRUNCATE, min(TRUNCATE, v)), 6) for v in z]
        record, summaries, _, _ = self.run(z)
        return {
            "z": z,
            "loglik": -0.5 * sum(v * v for v in z),
            "failed": sorted({FAMILY_OF[f["mode"]] for f in record["failures"]}),
            "failures": record["failures"],
            "distance": distances(record, summaries, self.nominal),
            "clearance_m": record["clearance_m"],
            "margin": record["margin"],
        }


def start_state(search, seed, budget, population, key):
    d = len(search.dims)
    return {
        "key": key,
        "iteration": 0,
        "simulated": 1,  # the nominal cycle
        "seed": seed,
        "budget": budget,
        "population": population,
        "gaussians": {f: {"mean": [0.0] * d, "std": [1.0] * d} for f in FAMILIES},
        "best": {},  # failure mode -> its likeliest cycle so far
        "closest": {},  # family -> the cycle nearest to it without failing it
        "shrink": {},  # failure mode -> the next step toward the origin
        "sweep": {},  # failure mode -> the next dimension to halve
        "pending": None,  # the cycles planned for this iteration and those already run
    }


def _keep(state, sample):
    sims = state["simulated"]
    for f in sample["failures"]:
        best = state["best"].get(f["mode"])
        if best is None or sample["loglik"] > best["loglik"]:
            state["best"][f["mode"]] = {
                **sample,
                "failure": f,
                "first_at": best["first_at"] if best else sims,
                "best_at": sims,
            }
    for family in FAMILIES:
        near = state["closest"].get(family)
        if family not in sample["failed"] and (
            near is None or _score(sample, family) > _score(near, family)
        ):
            state["closest"][family] = sample


def _open(state):
    """Families with a closest cycle and no failure found yet."""
    found = {FAMILY_OF[m] for m in state["best"]}
    return [f for f in FAMILIES if f in state["closest"] and f not in found]


def _shares(state):
    """Cycles per family: a few each; the rest to the family nearest an unfound failure,
    and to refining the failures found, in turns."""
    floor = max(1, state["population"] // (2 * len(FAMILIES)))
    shares = dict.fromkeys(FAMILIES, floor)
    rest = state["population"] - floor * len(FAMILIES)
    open_ = _open(state)
    turns = sorted({FAMILY_OF[m] for m in state["best"]})
    if open_ and state["iteration"]:
        turns = [min(open_, key=lambda f: (state["closest"][f]["distance"][f], f)), *turns]
    for i in range(rest):
        shares[(turns or list(FAMILIES))[i % len(turns or FAMILIES)]] += 1
    return shares


def plan(state):
    """The cycles of the next iteration, all drawn before any of them runs."""
    rng = random.Random(f"{state['seed']}:adversary:{state['iteration']}")
    cycles = []
    for family, count in _shares(state).items():
        g = state["gaussians"][family]
        for _ in range(count):
            z = [rng.gauss(m, s) for m, s in zip(g["mean"], g["std"], strict=True)]
            cycles.append({"z": z, "shrink": None})
    # Step each open family's closest cycle out along its ray to where its margin,
    # shrinking linearly from the nominal plan's, would reach zero.
    for family in _open(state):
        near = state["closest"][family]
        reach = 1 / max(1 - near["distance"][family], 1 / MAX_REACH)
        if reach > 1.01:
            cycles.append({"z": [v * reach for v in near["z"]], "shrink": None})
    # Pull each found failure toward the origin along its ray, and halve some of its
    # dimensions (a random half; all but the largest one or two; one or two in turn),
    # which drops the ones the failure does not need.
    for mode in sorted(state["best"]):
        z = state["best"][mode]["z"]
        step = state["shrink"].get(mode, SHRINK)
        if step >= MIN_SHRINK:
            cycles.append({"z": [v * (1 - step) for v in z], "shrink": mode})
        cycles.append({"z": [v / 2 if rng.random() < 0.5 else v for v in z], "shrink": None})
        order = sorted(range(len(z)), key=lambda i: (-abs(z[i]), i))
        for keep in (1, 2):
            kept = set(order[:keep])
            cycles.append(
                {"z": [v if i in kept else v / 2 for i, v in enumerate(z)], "shrink": None}
            )
        turn = state["sweep"].get(mode, 0)
        for k in range(SWEEP):
            i = (turn + k) % len(z)
            cycles.append({"z": [v / 2 if j == i else v for j, v in enumerate(z)], "shrink": None})
        state["sweep"][mode] = (turn + SWEEP) % len(z)
    return {"cycles": cycles, "done": []}


def advance(search, state):
    """Run the iteration's next planned cycle; refit once all of them have run."""
    if state["pending"] is None:
        state["pending"] = plan(state)
    pending = state["pending"]
    planned = pending["cycles"][len(pending["done"])]
    sample = search.evaluate(planned["z"])
    state["simulated"] += 1
    pending["done"].append(sample)
    _keep(state, sample)
    mode = planned["shrink"]
    if mode:
        held = state["best"][mode]["z"] == sample["z"]
        step = state["shrink"].get(mode, SHRINK)
        state["shrink"][mode] = min(MAX_SHRINK, step * 1.5) if held else step / 2
    if len(pending["done"]) == len(pending["cycles"]):
        refit(state, pending["done"])
        state["pending"] = None
        state["iteration"] += 1


def refit(state, samples):
    """Refit each family's Gaussian to its best cycles, its best so far among them."""
    elites = max(2, len(samples) // 4)
    for family in FAMILIES:
        found = [b for m, b in state["best"].items() if FAMILY_OF[m] == family]
        near = [state["closest"][family]] if family in state["closest"] else []
        pool = samples + (found or near)
        top = sorted(pool, key=lambda s, f=family: _score(s, f), reverse=True)[:elites]
        g = state["gaussians"][family]
        for i in range(len(g["mean"])):
            values = [s["z"][i] for s in top]
            mean = sum(values) / len(values)
            std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
            g["mean"][i] = round(SMOOTH * mean + (1 - SMOOTH) * g["mean"][i], 6)
            g["std"][i] = round(max(MIN_STD, SMOOTH * std + (1 - SMOOTH) * g["std"][i]), 6)


def _perturbation(search, z):
    """The perturbation at z in physical units, keyed by instrument and step."""
    drift, moves = perturb(search.dims, z, search.layout, search.transfers, search.cell.arms)
    names = {t: search.twins[t]["spec"]["name"] for t in drift}
    return {
        "drift": [
            {
                "twin_id": t,
                "name": names[t],
                "dx_mm": round(dx * 1000, 2),
                "dz_mm": round(dz * 1000, 2),
                "dyaw_deg": round(dyaw, 3),
            }
            for t, (dx, dz, dyaw) in drift.items()
        ],
        "moves": [
            {
                "step": t["step"],
                "pick_error_mm": [round(v * 1000, 2) for v in m["pick"]],
                "place_error_mm": [round(v * 1000, 2) for v in m["place"]],
                "mass_factor": round(m["mass"], 3),
                "speed_factor": round(m["speed"], 3),
            }
            for t, m in zip(search.transfers, moves, strict=True)
        ],
    }


def _drivers(search, z):
    """The dimensions carrying the most of |z|², with their share of it."""
    total = sum(v * v for v in z) or 1.0
    ranked = sorted(range(len(z)), key=lambda i: (-z[i] * z[i], i))[:DRIVERS]
    return [
        {
            **{k: search.dims[i][k] for k in ("kind", "twin_id", "step", "label", "unit")},
            "sigma": round(z[i], 2),
            "value": round(z[i] * search.dims[i]["sigma"], 3),
            "share": round(z[i] * z[i] / total, 3),
        }
        for i in ranked
        if z[i]
    ]


def _odds(distance):
    p = _phi(-distance)
    return {
        "distance_sigma": round(distance, 3),
        "log_likelihood": round(-0.5 * distance * distance, 3),
        "probability": float(f"{p:.3g}"),
        "monte_carlo_cycles": round(1 / p) if p > 0 else None,
    }


def summary(search, state):
    """What the search has found so far, in physical units and in σ.

    Each failure is a clean scenario (mode, step, segment, perturbation by instrument and
    step, probability) that a fault drill or a tolerance analysis can start from.
    """
    found = []
    for mode in endurance.MODES:
        best = state["best"].get(mode)
        if not best:
            continue
        f = best["failure"]
        found.append(
            {
                "mode": mode,
                "family": FAMILY_OF[mode],
                "step": f["step"],
                "segment": f["segment"],
                "message": f["message"],
                **_odds(_norm(best["z"])),
                "sigma": best["z"],
                "drivers": _drivers(search, best["z"]),
                "perturbation": _perturbation(search, best["z"]),
                "first_found_at": best["first_at"],
                "best_found_at": best["best_at"],
            }
        )
    found.sort(key=lambda f: f["distance_sigma"])
    reached = {f["family"] for f in found}
    closest = []
    for family in FAMILIES:
        near = state["closest"].get(family)
        if family in reached or not near:
            continue
        closest.append(
            {
                "family": family,
                "margin_left": near["distance"][family],
                "clearance_m": near["clearance_m"],
                "grip_margin": near["margin"],
                "distance_sigma": round(_norm(near["z"]), 3),
                "sigma": near["z"],
                "drivers": _drivers(search, near["z"]),
                "perturbation": _perturbation(search, near["z"]),
            }
        )
    return {
        "dimensions": search.dims,
        "nominal_ok": search.nominal_ok,
        "simulated": state["simulated"],
        "iterations": state["iteration"],
        "budget": state["budget"],
        "failures": found,
        "closest": closest,
    }


def _going(state, budget):
    """Until the budget is spent, and then to the end of the iteration under way."""
    return state["simulated"] < budget or state["pending"] is not None


def adversary(
    twins,
    layout,
    steps,
    budget=400,
    population=16,
    state=None,
    seed=0,
    noise=None,
    grip=None,
    speed=NOMINAL_SPEED,
    seconds=None,
):
    """One chunk of the search: cycles until the budget or the time cap, at least one.

    An iteration may span chunks; its cycles are planned before the first one runs.
    Resume by sending `next` back as `state` until it is None.
    """
    endurance._require()
    noise, grip = endurance._settings(noise, grip)
    key = endurance._key(twins, layout, steps, noise, grip, speed, seed, budget, population)
    deadline = time.monotonic() + (endurance.CHUNK_SECONDS if seconds is None else seconds)
    search = Search(twins, layout, steps, noise, grip, speed)
    if not search.dims:
        raise PlanError("constraint", "Set a perturbation above zero to search")
    if state is None:
        state = start_state(search, seed, budget, population, key)
    elif state.get("key") != key:
        raise PlanError("constraint", "The workflow or settings changed; start the search again")
    first = True
    while _going(state, budget) and (first or time.monotonic() < deadline):
        advance(search, state)
        first = False
    return {
        "engine": arm_simulation.describe(speed),
        "synthetic": True,
        "method": "cross-entropy adaptive stress test",
        "seed": seed,
        "noise": noise,
        **summary(search, state),
        "next": state if _going(state, budget) else None,
    }


def replay(twins, layout, steps, sigma, seed=0, noise=None, grip=None, speed=NOMINAL_SPEED):
    """The cycle at these σ values again, in the endurance replay's shape."""
    endurance._require()
    noise, grip = endurance._settings(noise, grip)
    search = Search(twins, layout, steps, noise, grip, speed)
    if len(sigma) != len(search.dims):
        raise PlanError("constraint", "The workflow or settings changed; start the search again")
    record, summaries, details, (drift, moves) = search.run(list(sigma), keep=True)
    return {
        "engine": arm_simulation.describe(speed),
        "synthetic": True,
        "seed": seed,
        "sigma": list(sigma),
        **endurance.replay_view(twins, search.transfers, record, summaries, details, drift, moves),
    }


# The HTTP side: request bodies and the owner-scoped handlers main.py registers.
class SearchState(StrictModel):
    """The state a previous chunk returned; its key decides whether it still fits."""

    model_config = ConfigDict(extra="allow")
    key: str = Field(min_length=64, max_length=64)
    iteration: int = Field(ge=0, le=MAX_BUDGET)
    simulated: int = Field(ge=1, le=2 * MAX_BUDGET)


class AdversaryRun(endurance.EnduranceSettings):
    budget: int = Field(default=400, ge=20, le=MAX_BUDGET)
    population: int = Field(default=16, ge=8, le=48)
    state: SearchState | None = None


class AdversaryReplay(endurance.EnduranceSettings):
    sigma: list[float] = Field(max_length=MAX_DIMS)


def _invalid(message="The search state is not valid"):
    return HTTPException(422, {"message": message, "layer": "constraint"})


def _finite(state):
    for g in state.get("gaussians", {}).values():
        for v in [*g.get("mean", []), *g.get("std", [])]:
            if not isinstance(v, int | float) or not math.isfinite(v) or abs(v) > 10:
                return False
    return True


def run_chunk(service, owner, data):
    """Read-only chunk of the likeliest-failure search on the owner's saved workflow."""
    twins, layout, steps = endurance._workflow(service, owner, data)
    state = data.state.model_dump() if data.state else None
    if state is not None and not _finite(state):
        raise _invalid()
    try:
        return adversary(
            twins,
            layout,
            steps,
            data.budget,
            data.population,
            state,
            **endurance._settings_of(data),
        )
    except PlanError as exc:
        raise HTTPException(422, {"message": str(exc), "layer": exc.layer}) from exc
    except (AttributeError, KeyError, TypeError, ValueError, IndexError) as exc:
        raise _invalid() from exc


def run_replay(service, owner, data):
    """A found cycle of the owner's workflow again, in detail."""
    twins, layout, steps = endurance._workflow(service, owner, data)
    if any(not math.isfinite(v) or abs(v) > TRUNCATE for v in data.sigma):
        raise _invalid("Each σ value lies within ±3")
    try:
        return replay(twins, layout, steps, data.sigma, **endurance._settings_of(data))
    except PlanError as exc:
        raise HTTPException(422, {"message": str(exc), "layer": exc.layer}) from exc
