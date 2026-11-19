"""What the 3D view draws and what the planner checks are the same solid shapes."""

import itertools
import math

import pytest
from academy import workcell_layout as wl
from academy.collision import _measured, shapes
from academy.examples import EXAMPLES, build
from academy.library import COLLECTIONS
from academy.workcell_models import catalog

ENTRIES = [(c, key, a) for c, assets in COLLECTIONS.items() for key, a in assets.items()]
TOL = 1e-6


def _twin(collection, key, asset):
    return {
        "id": key,
        "spec": asset["spec"],
        "source": f"{collection}_asset",
        "asset": {"id": key, "mesh": asset.get("mesh")},
    }


@pytest.mark.parametrize(("collection", "key", "asset"), ENTRIES, ids=lambda v: str(v)[:40])
def test_every_solid_shape_stands_inside_the_footprint(collection, key, asset):
    """The footprint check is then enough to keep two instruments apart in 3D too."""
    spec = asset["spec"]
    x0, x1, z0, z1 = wl.footprint(spec)
    height = wl.top(spec)
    for (cx, cy, cz), (hx, hy, hz) in shapes(_twin(collection, key, asset)):
        assert x0 - TOL <= cx - hx and cx + hx <= x1 + TOL, key
        assert z0 - TOL <= cz - hz and cz + hz <= z1 + TOL, key
        assert -TOL <= cy - hy and cy + hy <= height + TOL, key


@pytest.mark.parametrize(
    "key", [k for k, a in COLLECTIONS["chemlab"].items() if (a.get("mesh") or {}).get("kind")]
)
def test_measured_boxes_span_the_model_they_were_measured_from(key):
    """Every drawn ChemLab model has measured boxes, and they reach every face of its
    bounding box, so scaled to the planning envelope they cover the model drawn in it."""
    boxes = _measured().get(key)
    assert boxes, f"{key} is drawn but has no measured collision boxes"
    lo = [min(b[i] - b[i + 3] for b in boxes) for i in range(3)]
    hi = [max(b[i] + b[i + 3] for b in boxes) for i in range(3)]
    for low, high, want in zip(lo, hi, ((-0.5, 0.5), (0.0, 1.0), (-0.5, 0.5)), strict=True):
        assert low == pytest.approx(want[0], abs=0.02) and high == pytest.approx(want[1], abs=0.02)


def _examples():
    counter = itertools.count()
    for key, case in EXAMPLES.items():
        if case["placements"] is None:
            continue
        twins, steps, layout = build(case, lambda: f"t{next(counter)}")
        yield key, {t["id"]: t for t in twins}, steps, layout


@pytest.mark.parametrize("example", list(_examples()), ids=lambda e: e[0])
def test_the_arm_waits_in_a_pose_clear_of_every_instrument(example):
    _, twins, steps, layout = example
    motions = wl.plan_workflow(twins, layout, steps, keep_frames=True)
    rests = wl.rest_poses(twins, layout, motions)
    arms = [t for t in twins.values() if "transfer" in t["spec"]["operations"]]
    assert set(rests) == {t["id"] for t in arms}
    for arm in arms:
        planner = wl.Planner(twins, layout, arm)
        assert planner.measure(rests[arm["id"]])[0] >= wl.SAFETY


def test_the_drawn_home_pose_is_used_only_where_it_is_clear():
    """The home pose the 3D view used to draw reached into an instrument on these benches."""
    found = {key: (twins, layout) for key, twins, _, layout in _examples()}
    for key in ("ot2-incubator-fridge", "balance-oven"):
        twins, layout = found[key]
        arm = next(t for t in twins.values() if "transfer" in t["spec"]["operations"])
        assert wl.Planner(twins, layout, arm).measure(wl.HOME)[0] < 0


def _shield_cell(turn=0.4):
    """A UR5e and a thin shield across the gripper's swing between two poses."""
    arm = {"id": "arm", "spec": catalog()["ur5e-2f140"]["spec"], "source": "workcell_asset"}
    a = [0.0, -math.pi / 2, math.pi / 2, -math.pi / 2, -math.pi / 2, 0.0]
    b, m = [turn, *a[1:]], [turn / 2, *a[1:]]
    base = wl.mount(arm["spec"], {"x": 0, "z": 0, "yaw": 0})
    pm = wl.points(m, base)
    mid = wl._add(pm[-2], wl._sub(pm[-1], pm[-2]), 0.5)
    pa, pb = wl.points(a, base)[-1], wl.points(b, base)[-1]
    yaw = math.degrees(math.atan2(pb[0] - pa[0], pb[2] - pa[2]))
    shield = {
        "id": "shield",
        "source": "template",
        "spec": {
            "name": "Thin shield",
            "parts": [{"size": [0.05, 0.05, 0.004], "position": [0, mid[1], 0], "color": "#888"}],
        },
    }
    layout = {
        "bench": {"width": 2, "depth": 2},
        "placements": [
            {"twin_id": "arm", "x": 0, "z": 0, "yaw": 0, "access": "top"},
            {"twin_id": "shield", "x": mid[0], "z": mid[2], "yaw": yaw, "access": "top"},
        ],
    }
    return wl.Planner({"arm": arm, "shield": shield}, layout, arm), a, b


def test_an_arm_move_is_checked_along_its_whole_swing_not_only_at_its_samples():
    planner, a, b = _shield_cell()
    # Both ends are clear of the shield; the gripper passes through it on the way.
    assert planner.measure(a)[0] > wl.SAFETY and planner.measure(b)[0] > wl.SAFETY
    path, hit, _ = planner.edge(a, b, step=0.5)
    assert path is None
    assert (hit[1], hit[2]) == ("gripper", "Thin shield")


def test_a_tracked_tool_path_is_checked_between_its_ik_solutions(monkeypatch):
    planner, a, b = _shield_cell(0.3)
    assert planner.measure(a)[0] > wl.SAFETY and planner.measure(b)[0] > wl.SAFETY
    # The tool path's ends; the solver jumps straight from one pose to the other.
    monkeypatch.setattr(planner, "ik", lambda point, rotation, seed: b)
    path = (lambda t: (None, [(1, 0, 0), (0, 1, 0), (0, 0, 1)]), 0.0)
    joints, hit, _ = planner.follow(a, path)
    assert joints is None and hit[2] == "Thin shield"


def test_a_preview_returns_where_each_arm_waits(client):
    from test_layout import placed_cell, placements, preview

    reader, heater, arm, _, _ = placed_cell(client)
    result = preview(client, placements(reader, heater, arm))
    assert result["error"] is None
    assert len(result["rest"][arm]) == 6


# Twin ids a workspace once got for the sealer example: seeding the sampled path with them
# gave a path the MuJoCo replay refused, so one learner's workflow failed and another's not.
UNLUCKY_IDS = [
    "3794ba82-0bc7-410a-85fb-5343e551747e",
    "a075ef22-e200-4a79-a775-664088de693d",
    "84607536-4b0c-4e22-84ba-0054413fbebc",
    "0f7560c1-7f63-407f-ac6e-86270ce74c2f",
]


def _sealer_workflow(ids):
    twins, steps, layout = build(EXAMPLES["flex-sealer-reader"], iter(ids).__next__)
    load, mix, *rest = steps
    return {t["id"]: t for t in twins}, layout, [load, mix, *rest]


def test_a_workflow_plans_the_same_whatever_ids_its_twins_got():
    names = [f"twin-{n}" for n in range(4)]
    plans = [
        wl.plan_workflow(*_sealer_workflow(ids))
        for ids in (UNLUCKY_IDS, names, list(reversed(UNLUCKY_IDS)))
    ]
    paths = [[(m["planner"], m["length_m"], m["seconds"]) for m in plan] for plan in plans]
    assert paths[0] == paths[1] == paths[2]
