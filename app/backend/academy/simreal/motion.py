"""Turn one plate transfer on a bench layout into the arm connector's waypoint chains.

The bench planner already finds a collision-free path for a transfer and runs it in its
MuJoCo bench. Here that path is cut where the gripper has to act, so a chain ends exactly
at a grasp point: travel to the source, lower into it (grip), lift and carry and lower
into the target (release), retreat. Each part is one `PrepareActionChainAtSpeed` chain.
"""

import math

from .. import workcell_layout as bench
from ..mock_contract import PlanError

LOWER, CARRY, RETREAT = "lower", "carry", "retreat"
MIN_TRAVEL_DEG = 0.5  # the connector refuses a chain that moves less


def _reduce(planner, label, joints, ignore):
    """The fewest waypoints whose straight joint-space segments stay collision-free."""
    kept, i = [], 0
    while i < len(joints) - 1:
        j = len(joints) - 1
        while (
            j > i + 1 and planner.edge(joints[i], joints[j], ignore, bench.EXPORT_STEP)[0] is None
        ):
            j -= 1
        kept.append(joints[j])
        i = j
    return [
        {
            "name": (label if len(kept) == 1 else f"{label} {n}/{len(kept)}")[:60],
            "degrees": [round(math.degrees(v), 4) for v in q],
            # Every waypoint holds, so the connector's segments are rest-to-rest and
            # follow exactly the straight lines that were checked.
            "hold": bench.HOLD,
        }
        for n, q in enumerate(kept, 1)
    ]


def _travel(planner, start, goal, label):
    """Dense joints from where the arm is to where the transfer starts."""
    dense, _, _ = planner.edge(start, goal)
    if dense is None:
        upright = [[q[0], -math.pi / 2, 0.0, q[3], q[4], q[5]] for q in (start, goal)]
        legs = [
            planner.edge(a, b) for a, b in zip([start, *upright], [*upright, goal], strict=True)
        ]
        if all(leg[0] is not None for leg in legs):
            dense = [q for leg in legs for q in leg[0]]
    # A sampled search that finds nothing says little; a few other samples are tried.
    for attempt in range(bench.RRT_TRIES):
        if dense is None:
            dense = planner.rrt_connect(start, goal, f"{label}:{attempt}")
    if dense is None:
        raise PlanError(
            "geometry", f"{label}: the arm has no collision-free way from where it stands"
        )
    return [start, *dense]


def _chain(name, rows, start_degrees, speed, at=None):
    seconds, previous = 0.0, [math.radians(v) for v in start_degrees]
    for row in rows:
        q = [math.radians(v) for v in row["degrees"]]
        seconds += bench._seconds(previous, q, speed) + row["hold"]
        previous = q
    if len(rows) > bench.CHAIN_LIMIT:
        raise PlanError(
            "geometry",
            f"{name} needs {len(rows)} waypoints; the UR5e connector accepts {bench.CHAIN_LIMIT}",
        )
    if seconds > bench.CHAIN_SECONDS:
        raise PlanError(
            "constraint",
            f"{name} needs about {seconds:.0f} s at {speed:g}°/s; the connector allows "
            f"{bench.CHAIN_SECONDS} s per chain. Choose a higher speed.",
        )
    return {
        "name": name,
        "waypoints": rows,
        "end_degrees": rows[-1]["degrees"],
        "at": at,
        "seconds": round(seconds, 1),
    }


def plan_transfer(twins, layout, label, arm, source, target, start_degrees, speed):
    """The chains of one transfer and what the planner measured.

    `source` and `target` are (device id, site); `start_degrees` is where the arm stands.
    Raises PlanError('geometry' or 'constraint') when the layout does not allow it.
    """
    if bench.arm_for(twins[arm]["spec"]).key != "ur5e":
        raise PlanError("state", "Sim–Real plans arm paths for the UR5e connector only")
    step = {
        "device_id": arm,
        "operation": "transfer",
        "source_id": source[0],
        "target_id": target[0],
    }
    planned = bench.plan_checked(twins, layout, label, step, (source[1], target[1]))
    planner = planned["_chain"]["planner"]
    lower, lift, transit, place, retreat = planned["_chain"]["segments"]
    chains = []
    start = [math.radians(v) for v in start_degrees]
    reference = lower[1][0]
    if (
        max(abs(math.degrees(a - b)) for a, b in zip(start, reference, strict=True))
        >= MIN_TRAVEL_DEG
    ):
        dense = _travel(planner, start, reference, f"{label} travel")
        chains.append(
            _chain(
                "travel",
                _reduce(planner, "Travel to the source", dense, None),
                start_degrees,
                speed,
            )
        )
    at = [math.degrees(v) for v in reference]
    for name, parts, grasp in (
        (LOWER, [lower], {"device": source[0], "site": source[1]}),
        (CARRY, [lift, transit, place], {"device": target[0], "site": target[1]}),
        (RETREAT, [retreat], None),
    ):
        rows = [
            row
            for part_label, joints, ignore in parts
            if len(joints) > 1
            for row in _reduce(planner, part_label, joints, ignore)
        ]
        chains.append(_chain(name, rows, at, speed, grasp))
        at = rows[-1]["degrees"]
    return {
        "chains": chains,
        "clearance_m": planned["clearance_m"],
        "planner": planned["planner"],
        "simulation": planned.get("simulation"),
        "seconds": round(sum(c["seconds"] for c in chains), 1),
    }
