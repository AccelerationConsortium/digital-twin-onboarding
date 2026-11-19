"""Grasp stability and endurance runs of a workflow's transfers in the MuJoCo bench."""

import itertools

import pytest
from academy import arm_simulation, endurance, examples
from academy.mock_contract import PlanError

needs_mujoco = pytest.mark.skipif(not arm_simulation.available(), reason="MuJoCo not installed")
QUIET = {k: 0.0 for k in endurance.NOISE}


@pytest.fixture(scope="module")
def cell():
    counter = itertools.count()
    twins, steps, layout = examples.build(
        examples.EXAMPLES["flex-reader"], lambda: f"twin-{next(counter)}"
    )
    return {t["id"]: t for t in twins}, layout, steps


def grasp(cell, **grip):
    twins, layout, steps = cell
    return endurance.stress(twins, layout, steps, cycles=1, grip=grip)["nominal"][0]


@needs_mujoco
def test_the_nominal_grasp_reports_its_margin_and_where_it_is_least(cell):
    held = grasp(cell)
    # A 55 g plate in a 20 N grip with pads of friction 0.4: the pads can supply 16 N,
    # and about the plate's weight (0.54 N) plus the accelerations is needed.
    assert held["available_n"] == 16.0
    assert 0.54 <= held["required_n"] < 0.7
    assert held["margin"] == pytest.approx(16.0 / held["required_n"], rel=0.02)
    assert not held["slip"] and held["drop"] is None and held["slip_mm"] == 0
    assert held["worst_segment"] in [s["label"] for s in held["segments"]]
    # Only the three segments with the plate in the gripper are watched.
    assert [s["label"].split()[0] for s in held["segments"]] == ["Lift", "Transit", "Lower"]


@needs_mujoco
def test_heavier_labware_or_slicker_pads_slip_sooner(cell):
    margins = [grasp(cell, labware_kg=kg)["margin"] for kg in (0.5, 1.0, 1.4)]
    assert margins[0] > margins[1] > margins[2] > 1
    slick = [grasp(cell, labware_kg=1.0, friction=mu)["margin"] for mu in (0.6, 0.4, 0.2)]
    assert slick[0] > slick[1] > slick[2]
    # Past what the pads can hold the plate breaks away, slides and leaves the gripper;
    # the heavier one gets there no later.
    heavy, heavier = (grasp(cell, labware_kg=kg) for kg in (1.7, 3.0))
    for held in (heavy, heavier):
        assert held["slip"] and held["margin"] < 1 and held["drop"]
        assert held["slip_mm"] == endurance.GRIP["hold_depth_m"] * 1000
    assert heavier["drop"]["at_s"] <= heavy["drop"]["at_s"]
    assert heavier["breakaway"]["at_s"] <= heavy["breakaway"]["at_s"]
    # A firmer grip holds the same plate again.
    assert not grasp(cell, labware_kg=1.7, grip_force_n=40)["slip"]


@needs_mujoco
def test_values_say_where_they_came_from(cell):
    twins, layout, steps = cell
    first = endurance.stress(twins, layout, steps, cycles=1, grip={"friction": 0.6})
    params = first["parameters"]
    assert params["gripper"]["friction"] == {"value": 0.6, "basis": "run"}
    assert params["gripper"]["grip_force_n"]["basis"] == "default"
    assert "friction" not in params["defaults"] and "grip_force_n" in params["defaults"]
    # The vessel and its liquid come from the workflow; the empty plate's mass is a default.
    (plate,) = params["labware"]
    assert plate["vessel"] == "plate" and plate["liquid_ul"] == 150
    assert plate["kg"] == pytest.approx(0.055 + 150e-6, abs=1e-4) and plate["kg_basis"] == "default"


@needs_mujoco
def test_without_noise_every_cycle_repeats_the_plan(cell):
    twins, layout, steps = cell
    run = endurance.stress(twins, layout, steps, cycles=3, noise=QUIET, seconds=60)
    records = run["results"]
    assert [r["cycle"] for r in records] == [0, 1, 2]
    assert all({**r, "cycle": 0} == {**records[0], "cycle": 0} for r in records)
    assert records[0]["ok"] and records[0]["margin"] == run["nominal"][0]["margin"]
    assert records[0]["seconds"] == run["nominal"][0]["seconds"]


@needs_mujoco
def test_a_seed_reproduces_its_cycles_and_any_one_can_be_replayed(cell):
    twins, layout, steps = cell
    first = endurance.stress(twins, layout, steps, cycles=4, seed=7, seconds=60)["results"]
    again = endurance.stress(twins, layout, steps, cycles=4, seed=7, seconds=60)["results"]
    other = endurance.stress(twins, layout, steps, cycles=4, seed=8, seconds=60)["results"]
    assert first == again and first != other
    # The noisy cycles differ from one another.
    assert len({r["seconds"] for r in first}) > 1
    replayed = endurance.replay(twins, layout, steps, 2, seed=7)
    assert replayed["record"] == first[2]
    (motion,) = replayed["motions"]
    assert len(motion["frames"]) == len(motion["joints"]) > 10
    assert {d["twin_id"] for d in replayed["drift"]} == {
        p["twin_id"] for p in layout["placements"]
    } - {motion["actor_id"]}


@needs_mujoco
def test_a_run_resumes_chunk_by_chunk_and_in_lanes(cell):
    twins, layout, steps = cell
    whole = endurance.stress(twins, layout, steps, cycles=5, seed=3, seconds=60)
    assert whole["next"] is None and len(whole["results"]) == 5
    # With no time per chunk every chunk still advances one cycle, then hands back `next`.
    chunks, start = [], 0
    while start is not None:
        chunk = endurance.stress(twins, layout, steps, cycles=5, start=start, seed=3, seconds=0)
        assert ("nominal" in chunk) == (start == 0)
        chunks.append(chunk)
        start = chunk["next"]
    assert [len(c["results"]) for c in chunks] == [1] * 5
    assert [r for c in chunks for r in c["results"]] == whole["results"]
    # Lanes over separate ranges add up to the same run.
    lanes = [
        endurance.stress(twins, layout, steps, cycles=5, start=a, stop=b, seed=3, seconds=60)
        for a, b in ((0, 2), (2, 5))
    ]
    assert [lane["next"] for lane in lanes] == [None, None]
    assert [r for lane in lanes for r in lane["results"]] == whole["results"]


@needs_mujoco
def test_large_drift_is_caught_as_a_collision_with_its_cycle(cell):
    twins, layout, steps = cell
    rough = {**endurance.NOISE, "drift_mm": 20, "drift_deg": 5, "pose_mm": 10}
    run = endurance.stress(twins, layout, steps, cycles=12, noise=rough, seconds=60)
    failed = [r for r in run["results"] if not r["ok"]]
    assert failed and all(f["mode"] in endurance.MODES for r in failed for f in r["failures"])
    first = failed[0]["failures"][0]
    assert first["mode"] == "collision" and first["message"].startswith("Step 3: the ")
    assert (
        endurance.replay(twins, layout, steps, failed[0]["cycle"], noise=rough)["record"]
        == failed[0]
    )


@needs_mujoco
def test_a_plate_too_heavy_for_the_grip_is_a_drop_in_every_cycle(cell):
    twins, layout, steps = cell
    run = endurance.stress(twins, layout, steps, cycles=3, grip={"labware_kg": 3.0}, seconds=60)
    assert all(r["failures"][0]["mode"] == "drop" for r in run["results"])
    assert (
        "slides out of the gripper during lift from" in run["results"][0]["failures"][0]["message"]
    )


def test_without_mujoco_a_stress_run_says_why(cell, monkeypatch):
    monkeypatch.setattr(arm_simulation, "mujoco", None)
    twins, layout, steps = cell
    with pytest.raises(PlanError, match="need the MuJoCo simulation"):
        endurance.stress(twins, layout, steps, cycles=3)


@needs_mujoco
def test_the_api_runs_the_owners_saved_workflow_only(client, app):
    from fastapi.testclient import TestClient

    opened = client.put("/api/twins/examples/flex-reader", json={"expected_version": 0})
    layout = opened.json()["layout"]
    body = {**layout, "cycles": 2, "seed": 5, "noise": {"pose_mm": 0.5}}
    response = client.post("/api/twins/layout/endurance", json=body)
    assert response.status_code == 200, response.text
    chunk = response.json()
    assert chunk["cycles"] == 2 and chunk["seed"] == 5 and chunk["noise"]["pose_mm"] == 0.5
    assert chunk["engine"]["engine"] == "mujoco" and len(chunk["nominal"]) == 1
    cycle = chunk["results"][-1]["cycle"]
    replayed = client.post(
        "/api/twins/layout/endurance/replay",
        json={**layout, "cycle": cycle, "seed": 5, "noise": {"pose_mm": 0.5}},
    )
    assert replayed.status_code == 200 and replayed.json()["record"] == chunk["results"][-1]
    # Bounds are enforced before any simulation runs.
    too_many = client.post("/api/twins/layout/endurance", json={**layout, "cycles": 50_000})
    assert too_many.status_code == 422
    backwards = client.post(
        "/api/twins/layout/endurance", json={**layout, "cycles": 5, "start": 3, "stop": 2}
    )
    assert backwards.status_code == 422
    with TestClient(app) as other:
        other.post("/api/auth/guest", json={"name": "Grace"})
        # Another learner's instruments are not found, and an empty bench is refused.
        assert other.post("/api/twins/layout/endurance", json=body).status_code == 404
        empty = {"bench": layout["bench"], "placements": [], "cycles": 2}
        assert other.post("/api/twins/layout/endurance", json=empty).status_code == 409


def test_a_workflow_without_a_layout_is_refused_clearly():
    counter = itertools.count()
    # This example has no layout yet: its shaker is out of the arm's reach.
    twins, steps, layout = examples.build(
        examples.EXAMPLES["flex-shaker-reader"], lambda: f"twin-{next(counter)}"
    )
    assert layout is None
    with pytest.raises(PlanError, match="Place the workflow's instruments"):
        endurance.stress({t["id"]: t for t in twins}, layout, steps, cycles=1)
