"""Grasp stability and endurance runs of a workflow's transfers in the MuJoCo bench.

`arm_simulation` replays each planned transfer once. Here the labware is a body of its
own in the gripper and every transfer is repeated many times with small, seeded
perturbations, to see whether the grasp holds and the path still clears.

Grasp model. MuJoCo computes the wrench the fingers must apply to make the labware
follow the simulated motion (its mass, inertia and offset from the finger centre, under
gravity and the arm's accelerations). Two flat pads squeezing with the grip force hold
it by Coulomb friction: the pads can supply a force tangential to them up to
2 * friction * grip, a torque about the grip axis up to that force times two thirds of
the pad radius, a force along the grip axis up to twice the grip before a finger lifts
off, and a tipping torque up to 2 * grip * pad radius. Utilisation is the largest share
of those limits in use (friction and torsion combined on an ellipse), and the safety
margin its inverse. Past 1 the labware breaks away and slides with kinetic friction
(KINETIC of the static value) until the pads catch it again; sliding further than
the pads overlap it is a drop. A parallel gripper centres the labware along its grip
axis as it closes, so only an offset across the pads remains.

Endurance run. Each cycle repeats every transfer with: instruments drifted off their
placement (x, z and yaw), the pick and place points located with some error (the arm
retargets to where it believes the labware is, by inverse kinematics from the planned
pose), the labware mass and the arm speed varied. Cycle k uses the random stream
seeded with "seed:k", so any cycle can be rerun alone. All noise zero repeats the
nominal plan exactly.

Labware and gripper values come from the workflow where it states them (the vessel and
its liquid volume) and otherwise from the documented defaults below; the result says
which defaults were used. None of this is a measurement: no physical robot, gripper or
plate has been run, and it is not Isaac/GPU validation.
"""

import hashlib
import json
import math
import random
import time
from collections import OrderedDict

from fastapi import HTTPException
from pydantic import Field, model_validator

from . import arm_simulation
from .mock_contract import PlanError, execute_mock, transfer_sites
from .models import StrictModel
from .simple_twins import LayoutDraft
from .workcell_layout import (
    DWELL,
    GRIPPER,
    NOMINAL_SPEED,
    TOOL,
    frames,
    plan_transfer,
    points,
    validate_layout,
)

if arm_simulation.available():
    import mujoco
    import numpy as np

# Empty vessel mass (kg) and size (m): along the grip axis, along the tool axis, across.
VESSELS = {
    "plate": (0.055, (0.0855, 0.0144, 0.1278)),  # ANSI/SLAS 96-well polystyrene plate
    "reservoir": (0.10, (0.0855, 0.044, 0.1278)),  # SBS-footprint reservoir
    "vial": (0.020, (0.028, 0.061, 0.028)),  # 20 mL glass scintillation vial
    "tube": (0.007, (0.017, 0.12, 0.017)),  # 15 mL conical tube
    "none": (0.055, (0.0855, 0.0144, 0.1278)),
}
LIQUID_KG_PER_UL = 1e-6  # water
# A Robotiq 2F-140 at a light plate grip: its force setting spans about 10–125 N.
GRIP = {
    "grip_force_n": 20.0,
    "friction": 0.4,  # dry urethane pad on polystyrene, a cautious value
    "pad_radius_m": 0.011,  # a 22 mm wide fingertip pad
    "hold_depth_m": 0.010,  # how far the labware may slide before it leaves the pads
}
GRIPPER_KG = 1.0  # the gripper alone; arm_simulation's 1.1 kg payload includes a plate
KINETIC = 0.8  # kinetic friction as a share of static
SLIP_REPORT_M = 1e-4  # slides shorter than this are reported as 0 mm

NOISE = {"pose_mm": 1.0, "drift_mm": 2.0, "drift_deg": 0.3, "mass_pct": 10.0, "speed_pct": 10.0}
TRUNCATE = 3.0  # perturbations are Gaussian, cut at this many sigma
RETARGET_RAD = 0.35  # a retargeted pose further than this from the plan is another branch

CHUNK_SECONDS = 6.0
PLAN_CACHE = 8
HELD = (1, 2, 3)  # lift from the source, transit, lower into the target
MODES = ("ik", "limit", "collision", "tracking", "drop", "slip")

_plans = OrderedDict()


def available():
    return arm_simulation.available()


def _key(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _travel(joints):
    marks = [0.0]
    for a, b in zip(joints, joints[1:], strict=False):
        marks.append(marks[-1] + max(abs(x - y) for x, y in zip(a, b, strict=True)))
    return marks


def nominal(twins, layout, steps):
    """Every transfer's planned path at full resolution, cached per workflow and layout."""
    key = _key(twins, layout, steps)
    if key in _plans:
        _plans.move_to_end(key)
        return _plans[key]
    validate_layout(twins, layout)
    trace = execute_mock(twins, steps)
    sites = transfer_sites(twins, steps)
    transfers = []
    for index, step in enumerate(steps):
        if step["operation"] != "transfer":
            continue
        planned = plan_transfer(twins, layout, index + 1, step, sites[index + 1])
        chain = planned["_chain"]
        transfers.append(
            {
                "step": index + 1,
                "actor_id": planned["actor_id"],
                "source_id": planned["source_id"],
                "target_id": planned["target_id"],
                "arm": planned["arm"],
                "planner": chain["planner"],
                "segments": [
                    (label, joints, (ignore or {}).get(GRIPPER, set()))
                    for label, joints, ignore in chain["segments"]
                ],
                "vessel": trace[index]["vessel"],
                "volume_ul": trace[index]["volume_ul"],
            }
        )
    if not transfers:
        raise PlanError("geometry", "Save a workflow with a transfer step first")
    _plans[key] = transfers
    while len(_plans) > PLAN_CACHE:
        _plans.popitem(last=False)
    return transfers


def parameters(transfers, grip):
    """The labware and gripper values a run uses, and where each came from."""
    grip = grip or {}
    labware = []
    for t in transfers:
        empty, size = VESSELS.get(t["vessel"], VESSELS["none"])
        liquid = t["volume_ul"] * LIQUID_KG_PER_UL
        given = grip.get("labware_kg")
        labware.append(
            {
                "step": t["step"],
                "vessel": t["vessel"],
                "size_m": size,
                "liquid_ul": t["volume_ul"],
                "kg": round(given if given is not None else empty + liquid, 4),
                "kg_basis": "run" if given is not None else "default",
            }
        )
    gripper = {}
    for name, default in GRIP.items():
        given = grip.get(name)
        gripper[name] = {
            "value": default if given is None else given,
            "basis": "default" if given is None else "run",
        }
    defaults = [k for k, v in gripper.items() if v["basis"] == "default"]
    if any(item["kg_basis"] == "default" for item in labware):
        defaults.append("labware_kg")
    return {"labware": labware, "gripper": gripper, "defaults": defaults}


def _box_inertia(mass, size):
    n, t, b = size  # local x = grip axis, y = across, z = tool axis
    return (
        mass * (b * b + t * t) / 12,
        mass * (n * n + t * t) / 12,
        mass * (n * n + b * b) / 12,
    )


class Cell:
    """Compiled benches, one per arm, with the labware as a body in each gripper."""

    def __init__(self, twins, layout, transfers):
        self.twins, self.layout = twins, layout
        self.arms = {t["actor_id"] for t in transfers}
        self.benches = {}
        for t in transfers:
            if t["actor_id"] in self.benches:
                continue
            planner, actor = t["planner"], twins[t["actor_id"]]
            reach = planner.arm.d[5] + TOOL
            # Its frame is the grasp frame of the planner: x the grip axis, z the tool axis.
            held = (
                f'<body name="labware" pos="0 {reach:.6g} 0" quat="-1 1 0 0">'
                '<inertial pos="0 0 0" mass="0.1" diaginertia="1e-4 1e-4 1e-4"/></body>'
            )
            boxes = arm_simulation.layout_boxes(twins, layout, actor)
            bench = arm_simulation.Bench(
                planner.arm, planner.base, TOOL, boxes, held=held, gripper_kg=GRIPPER_KG
            )
            body = bench.model.body("labware").id
            geoms = [
                mujoco.mj_name2id(bench.model, mujoco.mjtObj.mjOBJ_GEOM, f"box:{n}")
                for n in range(len(boxes))
            ]
            self.benches[t["actor_id"]] = (bench, body, geoms, actor)

    def drift(self, shifts):
        """Move every instrument's boxes by {twin id: (dx, dz, dyaw deg)}."""
        placements = []
        for p in self.layout["placements"]:
            dx, dz, dyaw = shifts.get(p["twin_id"], (0.0, 0.0, 0.0))
            placements.append({**p, "x": p["x"] + dx, "z": p["z"] + dz, "yaw": p["yaw"] + dyaw})
        moved = {**self.layout, "placements": placements}
        for bench, _, geoms, actor in self.benches.values():
            for geom, box in zip(
                geoms, arm_simulation.layout_boxes(self.twins, moved, actor), strict=True
            ):
                bench.model.geom_pos[geom] = box["pos"]
                bench.model.geom_quat[geom] = box["quat"]


class Grasp:
    """Watches the labware in the gripper during the held segments of one transfer."""

    def __init__(self, bench, body, mass, size, offset, gripper):
        self.model, self.data, self.body = bench.model, bench.data, body
        self.mass = mass
        self.inertia = _box_inertia(mass, size)
        self.offset = offset
        self.model.body_ipos[body] = (0.0, offset, 0.0)
        g = {k: v["value"] for k, v in gripper.items()}
        grip, mu = g["grip_force_n"], g["friction"]
        self.available = 2 * mu * grip  # tangential friction both pads can supply
        self.torsion = self.available * 2 * g["pad_radius_m"] / 3
        self.opening = 2 * grip
        self.tilt = 2 * grip * g["pad_radius_m"]
        self.depth = g["hold_depth_m"]
        self.acc, self.vel = np.zeros(6), np.zeros(6)
        self.sliding, self.speed, self.slid = False, 0.0, 0.0
        self.drop = self.breakaway = None
        self.segments = []
        self.hold(False)

    def hold(self, held, label=None):
        held = held and not self.drop
        self.model.body_mass[self.body] = self.mass if held else 0.0
        self.model.body_inertia[self.body] = self.inertia if held else 0.0
        if held:
            self.segments.append(
                {"label": label, "use": 0.0, "at_s": 0.0, "required_n": 0.0, "limit": None}
            )

    def observe(self, now):
        if self.drop:
            return
        model, data = self.model, self.data
        mujoco.mj_rnePostConstraint(model, data)
        mujoco.mj_objectAcceleration(model, data, mujoco.mjtObj.mjOBJ_BODY, self.body, self.acc, 1)
        mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, self.body, self.vel, 1)
        # Linear acceleration in the accelerometer convention already contains gravity.
        m, (ix, iy, iz), r = self.mass, self.inertia, self.offset
        ax, ay, az, fx, fy, fz = (float(v) for v in self.acc)
        wx, wy, wz = (float(v) for v in self.vel[:3])
        fx, fy, fz = m * fx, m * fy, m * fz
        # Euler's equations about the centre of mass, moved to the finger centre, which
        # the labware's centre is `r` across from (along local y).
        mx = ix * ax + (iz - iy) * wy * wz + r * fz
        my = iy * ay + (ix - iz) * wz * wx
        mz = iz * az + (iy - ix) * wx * wy - r * fx
        sliding = math.hypot(fy, fz) / self.available
        turning = abs(mx) / self.torsion
        shares = {
            "friction" if sliding >= turning else "torsion": math.hypot(sliding, turning),
            "opening": abs(fx) / self.opening,
            "tilt": math.hypot(my, mz) / self.tilt,
        }
        limit = max(shares, key=shares.get)
        use = shares[limit]
        segment = self.segments[-1]
        if use > segment["use"]:
            segment.update(
                use=use, at_s=round(now, 2), required_n=use * self.available, limit=limit
            )
        # Past breakaway the labware slides until kinetic friction stops it again.
        if use > 1 and not self.sliding:
            self.sliding = True
            self.breakaway = self.breakaway or {"segment": segment["label"], "at_s": round(now, 2)}
        if self.sliding:
            dt = arm_simulation.TIMESTEP
            self.speed = max(0.0, self.speed + (use - KINETIC) * self.available / self.mass * dt)
            self.slid += self.speed * dt
            self.sliding = self.speed > 0
            if self.slid > self.depth:
                # Out of the pads: the gripper carries nothing from here on.
                self.drop = {"segment": segment["label"], "at_s": round(now, 2)}
                self.slid = self.depth
                self.hold(False)

    def report(self):
        worst = max(self.segments, key=lambda s: s["use"])
        use = worst["use"]
        return {
            "margin": round(1 / use, 2) if use else None,
            "required_n": round(worst["required_n"], 2),
            "available_n": round(self.available, 2),
            "limit": worst["limit"],
            "worst_segment": worst["label"],
            "slip": use > 1,
            "breakaway": self.breakaway,
            "slip_mm": round(self.slid * 1000, 1) if self.slid > SLIP_REPORT_M else 0.0,
            "drop": self.drop,
            "segments": [
                {
                    "label": s["label"],
                    "margin": round(1 / s["use"], 2) if s["use"] else None,
                    "at_s": s["at_s"],
                }
                for s in self.segments
            ],
        }


def _gauss(rng, sigma):
    return max(-TRUNCATE * sigma, min(TRUNCATE * sigma, rng.gauss(0.0, sigma))) if sigma else 0.0


def perturbation(seed, cycle, layout, transfers, arms, noise):
    """The cycle's perturbations, drawn in a fixed order from its own random stream."""
    rng = random.Random(f"{seed}:{cycle}")
    drift = {}
    for p in layout["placements"]:
        shift = (
            _gauss(rng, noise["drift_mm"] / 1000),
            _gauss(rng, noise["drift_mm"] / 1000),
            _gauss(rng, noise["drift_deg"]),
        )
        if p["twin_id"] not in arms:  # the arms are the reference the others drift from
            drift[p["twin_id"]] = shift
    moves = []
    for _ in transfers:
        pose = [_gauss(rng, noise["pose_mm"] / 1000) for _ in range(4)]
        moves.append(
            {
                "pick": pose[:2],
                "place": pose[2:],
                "mass": max(0.2, 1 + _gauss(rng, noise["mass_pct"] / 100)),
                "speed": max(0.2, 1 + _gauss(rng, noise["speed_pct"] / 100)),
            }
        )
    return drift, moves


def _moved(point, placement, shift):
    """A world point carried with an instrument moved by (dx, dz, dyaw)."""
    dx, dz, dyaw = shift
    c, s = math.cos(math.radians(dyaw)), math.sin(math.radians(dyaw))
    x, z = point[0] - placement["x"], point[2] - placement["z"]
    return [placement["x"] + c * x + s * z + dx, point[1], placement["z"] - s * x + c * z + dz]


def _retarget(planner, joints, placement, shift, error):
    """The approach `joints` bent to end at the drifted station, located with `error`.

    Returns (joints, grasp frame, None) or (None, None, why).
    """
    end = joints[-1]
    tip = frames(end, planner.base, planner.arm)[7]
    columns = [[tip[r][k] for r in range(3)] for k in range(3)]
    if not any(shift) and not any(error):
        return joints, columns, None
    point = _moved([tip[r][3] for r in range(3)], placement, shift)
    point = [point[0] + error[0], point[1], point[2] + error[1]]
    origin = {"x": 0.0, "z": 0.0}
    rotation = [_moved(v, origin, (0.0, 0.0, shift[2])) for v in columns]
    q = planner.ik(point, rotation, end)
    if q is None or max(abs(a - b) for a, b in zip(q, end, strict=True)) > RETARGET_RAD:
        return None, None, "no inverse-kinematics solution near the planned pose"
    delta = [a - b for a, b in zip(q, end, strict=True)]
    marks = _travel(joints)
    total = marks[-1] or 1.0
    bent = [
        [v + d * m / total for v, d in zip(qj, delta, strict=True)]
        for qj, m in zip(joints, marks, strict=True)
    ]
    if any(abs(v) > lim for qj in bent for v, lim in zip(qj, planner.arm.limits, strict=True)):
        return None, None, "the corrected path passes a joint limit"
    return bent, rotation, None


def _during(label):
    return f"during {label[:1].lower()}{label[1:]}"


def _failure(mode, step, segment, message):
    return {"mode": mode, "step": step, "segment": segment, "message": f"Step {step}: {message}"}


def run_transfer(cell, transfer, drift, move, labware, gripper, speed, keep=False):
    """One perturbed run of a transfer: (summary, failure or None, detail or None)."""
    bench, body, _, _ = cell.benches[transfer["actor_id"]]
    planner, step = transfer["planner"], transfer["step"]
    places = {p["twin_id"]: p for p in cell.layout["placements"]}
    segments = list(transfer["segments"])
    lower_src, lower_tgt = segments[0], segments[3]
    picked, pick_frame, why = _retarget(
        planner,
        lower_src[1],
        places[transfer["source_id"]],
        drift.get(transfer["source_id"], (0.0, 0.0, 0.0)),
        move["pick"],
    )
    placed, _, why_place = (
        (None, None, None)
        if why
        else _retarget(
            planner,
            lower_tgt[1],
            places[transfer["target_id"]],
            drift.get(transfer["target_id"], (0.0, 0.0, 0.0)),
            move["place"],
        )
    )
    if why or why_place:
        where = lower_src[0] if why else lower_tgt[0]
        mode = "limit" if "limit" in (why or why_place) else "ik"
        return None, _failure(mode, step, where, f"{why or why_place} {_during(where)}"), None
    segments[0] = (lower_src[0], picked, lower_src[2])
    segments[1] = (segments[1][0], picked[::-1], segments[1][2])
    segments[3] = (lower_tgt[0], placed, lower_tgt[2])
    segments[4] = (segments[4][0], placed[::-1], segments[4][2])
    # The labware sits where it is; the fingers close where the arm believes it is.
    world = [-move["pick"][0], 0.0, -move["pick"][1]]
    across = sum(a * b for a, b in zip(world, pick_frame[1], strict=True))
    grasp = Grasp(bench, body, labware["kg"] * move["mass"], labware["size_m"], across, gripper)
    run_speed = speed * move["speed"]
    out = bench._begin(segments[0][1][0])
    for index, (label, joints, touching) in enumerate(segments):
        held = index in HELD
        grasp.hold(held, label)
        duration, at = arm_simulation._profile(joints, run_speed, bench.rated)
        bench._follow(out, label, at, duration, touching, observe=grasp.observe if held else None)
    grasp.hold(False)
    out = bench._rounded(out, 2 * DWELL)
    held = grasp.report()
    hit = out["collision"]
    if out["torque_ratio"] > 1:
        failure = _failure(
            "limit",
            step,
            None,
            f"the {planner.arm.name} needs {out['torque_ratio']:.1f}× its rated joint torque",
        )
    elif hit:
        failure = _failure(
            "collision",
            step,
            hit["segment"],
            f"the {hit['link']} hits {hit['blocked_by']} {_during(hit['segment'])}",
        )
    elif out["tracking_deg"] > arm_simulation.TRACKING_LIMIT_DEG:
        failure = _failure(
            "tracking",
            step,
            None,
            f"the {planner.arm.name} strays {out['tracking_deg']:.1f}° from the path",
        )
    elif held["drop"]:
        segment = held["drop"]["segment"]
        failure = _failure(
            "drop",
            step,
            segment,
            f"the {labware['vessel']} slides out of the gripper {_during(segment)}",
        )
    elif held["slip"]:
        segment = held["worst_segment"]
        failure = _failure(
            "slip",
            step,
            segment,
            f"the {labware['vessel']} slips {held['slip_mm']} mm in the gripper {_during(segment)}",
        )
    else:
        failure = None
    summary = {
        "step": step,
        "seconds": out["seconds"],
        "clearance_m": out["clearance_m"],
        "tracking_deg": out["tracking_deg"],
        "torque_ratio": out["torque_ratio"],
        "speed": round(run_speed, 1),
        "labware_kg": round(grasp.mass, 4),
        "grasp_offset_mm": round(across * 1000, 2),
        "grasp": held,
    }
    detail = None
    if keep:
        joints = [
            q for n, (_, part, _) in enumerate(segments) for q in (part if not n else part[1:])
        ]
        thin = max(1, math.ceil(len(joints) / 90))
        kept = joints[::thin] + ([joints[-1]] if (len(joints) - 1) % thin else [])
        detail = {
            "step": step,
            "actor_id": transfer["actor_id"],
            "source_id": transfer["source_id"],
            "target_id": transfer["target_id"],
            "arm": transfer["arm"],
            "frames": [
                [[round(v, 4) for v in p] for p in points(q, planner.base, planner.arm)]
                for q in kept
            ],
            "joints": [[round(v, 4) for v in q] for q in kept],
        }
    return summary, failure, detail


def run_cycle(cell, transfers, params, cycle, seed, noise, speed, keep=False):
    drift, moves = perturbation(seed, cycle, cell.layout, transfers, cell.arms, noise)
    cell.drift(drift)
    summaries, failures, details = [], [], []
    for transfer, move, labware in zip(transfers, moves, params["labware"], strict=True):
        summary, failure, detail = run_transfer(
            cell, transfer, drift, move, labware, params["gripper"], speed, keep
        )
        if summary:
            summaries.append(summary)
        if failure:
            failures.append(failure)
        if detail:
            details.append(detail)
    margins = [s["grasp"]["margin"] for s in summaries if s["grasp"]["margin"]]
    record = {
        "cycle": cycle,
        "ok": not failures,
        "seconds": round(sum(s["seconds"] for s in summaries), 1),
        "clearance_m": min((s["clearance_m"] for s in summaries), default=None),
        "margin": min(margins, default=None),
        "failures": failures,
    }
    return record, summaries, details, (drift, moves)


def _settings(noise, grip):
    noise = {**NOISE, **{k: v for k, v in (noise or {}).items() if v is not None}}
    return noise, {k: v for k, v in (grip or {}).items() if v is not None}


def _require():
    if not available():
        raise PlanError(
            "constraint",
            "Stress runs need the MuJoCo simulation, which is not installed on this server",
        )


def stress(
    twins,
    layout,
    steps,
    cycles,
    start=0,
    stop=None,
    seed=0,
    noise=None,
    grip=None,
    speed=NOMINAL_SPEED,
    seconds=CHUNK_SECONDS,
):
    """One chunk of the endurance run: cycles from `start` until `stop` or the time cap.

    The client resumes from `next` until it is None. The first chunk also carries the
    values used and the nominal grasp of every transfer.
    """
    _require()
    noise, grip = _settings(noise, grip)
    stop = cycles if stop is None else min(stop, cycles)
    deadline = time.monotonic() + seconds
    transfers = nominal(twins, layout, steps)
    params = parameters(transfers, grip)
    cell = Cell(twins, layout, transfers)
    result = {
        "engine": arm_simulation.describe(speed),
        "cycles": cycles,
        "seed": seed,
        "noise": noise,
    }
    if start == 0:
        zero = {k: 0.0 for k in NOISE}
        _, summaries, _, _ = run_cycle(cell, transfers, params, 0, seed, zero, speed)
        result["parameters"] = params
        result["nominal"] = [
            {
                "step": s["step"],
                "seconds": s["seconds"],
                "clearance_m": s["clearance_m"],
                "labware_kg": s["labware_kg"],
                **s["grasp"],
            }
            for s in summaries
        ]
    results = []
    cycle = start
    while cycle < stop and (cycle == start or time.monotonic() < deadline):
        record, _, _, _ = run_cycle(cell, transfers, params, cycle, seed, noise, speed)
        results.append(record)
        cycle += 1
    result["results"] = results
    result["next"] = cycle if cycle < stop else None
    return result


def replay(twins, layout, steps, cycle, seed=0, noise=None, grip=None, speed=NOMINAL_SPEED):
    """One cycle of a run again, with its perturbations and the arm's path to draw."""
    _require()
    noise, grip = _settings(noise, grip)
    transfers = nominal(twins, layout, steps)
    params = parameters(transfers, grip)
    cell = Cell(twins, layout, transfers)
    record, summaries, details, (drift, moves) = run_cycle(
        cell, transfers, params, cycle, seed, noise, speed, keep=True
    )
    names = {t: twins[t]["spec"]["name"] for t in drift}
    return {
        "engine": arm_simulation.describe(speed),
        "seed": seed,
        "record": record,
        "transfers": summaries,
        "motions": details,
        "drift": [
            {
                "twin_id": twin_id,
                "name": names[twin_id],
                "dx_mm": round(dx * 1000, 2),
                "dz_mm": round(dz * 1000, 2),
                "dyaw_deg": round(dyaw, 3),
            }
            for twin_id, (dx, dz, dyaw) in drift.items()
        ],
        "moves": [
            {
                "step": t["step"],
                "pick_error_mm": [round(v * 1000, 2) for v in m["pick"]],
                "place_error_mm": [round(v * 1000, 2) for v in m["place"]],
                "mass_factor": round(m["mass"], 3),
                "speed_factor": round(m["speed"], 3),
            }
            for t, m in zip(transfers, moves, strict=True)
        ],
    }


# The HTTP side: request bodies and the owner-scoped handlers main.py registers.
MAX_CYCLES = 5000


class Noise(StrictModel):
    pose_mm: float = Field(default=NOISE["pose_mm"], ge=0, le=10)
    drift_mm: float = Field(default=NOISE["drift_mm"], ge=0, le=20)
    drift_deg: float = Field(default=NOISE["drift_deg"], ge=0, le=5)
    mass_pct: float = Field(default=NOISE["mass_pct"], ge=0, le=50)
    speed_pct: float = Field(default=NOISE["speed_pct"], ge=0, le=50)


class GripValues(StrictModel):
    """Values set for this run in place of the defaults; left out, the default stands."""

    grip_force_n: float | None = Field(default=None, ge=1, le=200)
    friction: float | None = Field(default=None, ge=0.05, le=1.5)
    labware_kg: float | None = Field(default=None, ge=0.001, le=5)


class EnduranceSettings(LayoutDraft):
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    speed: float = Field(default=NOMINAL_SPEED, ge=5, le=90)
    noise: Noise = Field(default_factory=Noise)
    grip: GripValues = Field(default_factory=GripValues)


class EnduranceRun(EnduranceSettings):
    cycles: int = Field(default=500, ge=1, le=MAX_CYCLES)
    start: int = Field(default=0, ge=0, lt=MAX_CYCLES)
    # Where this lane of the run ends; lanes over separate ranges may run side by side.
    stop: int | None = Field(default=None, ge=1, le=MAX_CYCLES)

    @model_validator(mode="after")
    def ordered(self):
        if self.start >= self.cycles or (self.stop is not None and self.stop <= self.start):
            raise ValueError("Start before the last cycle and stop after the start")
        return self


class EnduranceReplay(EnduranceSettings):
    cycle: int = Field(ge=0, lt=MAX_CYCLES)


def _workflow(service, owner, data):
    record = service.get(owner)
    layout = service.placed(record, data)
    if not layout or not record["steps"]:
        raise HTTPException(409, "Save a workflow and place its instruments first")
    return {t["id"]: t for t in record["twins"]}, layout, record["steps"]


def _settings_of(data):
    return {
        "seed": data.seed,
        "speed": data.speed,
        "noise": data.noise.model_dump(),
        "grip": data.grip.model_dump(),
    }


def run_chunk(service, owner, data):
    """Read-only chunk of an endurance run of the owner's saved workflow."""
    twins, layout, steps = _workflow(service, owner, data)
    try:
        return stress(
            twins, layout, steps, data.cycles, data.start, data.stop, **_settings_of(data)
        )
    except PlanError as exc:
        raise HTTPException(422, {"message": str(exc), "layer": exc.layer}) from exc


def run_replay(service, owner, data):
    """One cycle of the owner's endurance run again, in detail."""
    twins, layout, steps = _workflow(service, owner, data)
    try:
        return replay(twins, layout, steps, data.cycle, **_settings_of(data))
    except PlanError as exc:
        raise HTTPException(422, {"message": str(exc), "layer": exc.layer}) from exc
