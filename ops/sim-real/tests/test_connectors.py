"""End to end on the real connectors in simulation. Skipped where they are not installed.

Set SIMREAL_OPENTRONS_FLEX_PYTHON and SIMREAL_UR5E_PYTHON to the interpreters of the two
connector environments to run these.
"""

import pytest
from academy.simreal import bindings, compiler, fdl, report
from academy_sim_real import launch, runner

INSTALLED = launch.installations()
needs_both = pytest.mark.skipif(
    set(INSTALLED) != set(bindings.PROFILES), reason="connector installations not configured"
)
FLEX = {
    "id": "flex",
    "library": {"collection": "chemlab", "id": "opentrons_flex_single_5_1000ul"},
}
BENCH = {
    "bench": {"width": 2.4, "depth": 1.6},
    "placements": [{"device": "flex", "x": 0.79, "z": 0.21, "yaw": -90}],
}


def compiled(data):
    plan = compiler.compile_workflow(compiler.Workflow.model_validate(data))
    assert plan["valid"], plan["problems"]
    return plan


def flex_only(steps):
    return {
        "schema": compiler.WORKFLOW,
        "name": "Flex alone",
        "devices": [FLEX],
        "layout": BENCH,
        "labware": [],
        "steps": [{"kind": "command", "device": "flex", **s} for s in steps],
    }


@needs_both
@pytest.mark.parametrize("key", sorted(bindings.PROFILES))
async def test_the_installed_connector_is_the_pinned_release(key, tmp_path):
    from academy_sim_real.importer import FULL

    async with launch.running(key, INSTALLED[key], tmp_path, options=FULL[key]) as live:
        pinned = {f["id"]: f["sha256"] for f in bindings.manifest(key)["features"]}
        assert {i: fdl.digest(x) for i, x in live.served.items()} == pinned


@needs_both
async def test_the_example_runs_on_both_connectors_and_the_world_agrees(tmp_path):
    plan = compiled(compiler.example())
    found = await runner.run_plan(plan, INSTALLED, workdir=tmp_path)
    assert found["outcome"] == "passed", found["reason"]
    assert [s["status"] for s in found["steps"]] == ["done"] * len(plan["steps"])
    assert found["world"] == plan["steps"][-1]["world"]
    moves = [s for s in found["steps"] if s["command"] == "RunContinuousMotion"]
    # The arm's simulator runs faster than the clock and says how long the move takes.
    assert len(moves) == 7 and all(s["device_s"] > s["wall_s"] for s in moves)
    kept = report.check(plan, found)
    # Seven arm moves at 20°/s take well over a minute of instrument time.
    assert kept["outcome"] == "passed" and kept["device_s"] > 60
    assert kept["connectors"]["flex"]["features"] >= 10


@needs_both
async def test_what_only_the_connector_knows_stops_the_run_there(tmp_path):
    """The world model tracks plates, not pipettes; the Flex simulator knows it has none."""
    shaker = {"feature": "HeaterShakerController", "parameters": {}}
    steps = [
        {"id": "close", **shaker, "command": "CloseLatch"},
        {"id": "shake", **shaker, "command": "SetSpeed", "parameters": {"Speed": 500}},
        {"id": "stop", **shaker, "command": "StopShaking"},
        {
            "id": "aspirate",
            "feature": "MotionController",
            "command": "Aspirate",
            "parameters": {"Mount": "left", "Volume": 50.0, "Rate": 1.0},
        },
        {"id": "open", **shaker, "command": "OpenLatch"},
    ]
    workflow = flex_only(steps)
    workflow["devices"][0] = {**FLEX, "options": {"modules": ["heater_shaker"]}}
    plan = compiled(workflow)
    found = await runner.run_plan(plan, INSTALLED, workdir=tmp_path)
    assert found["outcome"] == "failed" and found["stopped_at"] == "aspirate"
    assert [s["status"] for s in found["steps"]] == ["done", "done", "done", "failed"]
    assert found["steps"][-1]["error_type"] == "PipetteNotAttachedError"
    # An observable command is waited for: the shaker answered with its own state.
    assert found["steps"][1]["response"]["Response0"]["Target"] == 500
    kept = report.check(plan, found)
    assert kept["outcome"] == "failed" and "No pipette is attached" in kept["reason"]


@needs_both
def test_the_planner_and_the_arm_connector_agree_on_where_the_tool_is():
    """The bench planner and the connector each hold UR5e kinematics; a path planned with
    one is run by the other, so the two must place the tool the same."""
    import json
    import math
    import random
    import subprocess

    from academy import workcell_layout as bench

    rng = random.Random(7)
    # Inside the joint limits the connector accepts (elbow under 155°).
    poses = [[rng.uniform(-2.5, 2.5) for _ in range(6)] for _ in range(12)]
    script = (
        "import json,sys;from unitelabs.ur5e_connector.io.kinematics import forward;"
        f"print(json.dumps([[forward(q,[0,0,{bench.TOOL!r},0,0,0])[i][3] for i in range(3)] "
        "for q in json.loads(sys.argv[1])]))"
    )
    answer = subprocess.run(
        [str(INSTALLED["ur5e"].python), "-c", script, json.dumps(poses)],
        capture_output=True,
        text=True,
        check=True,
    )
    theirs = json.loads(answer.stdout)
    identity = [[float(i == j) for j in range(4)] for i in range(4)]
    ours = [bench.points(q, identity)[-1] for q in poses]
    # The planner's bench frame differs from the arm's base frame by a rigid motion, so
    # distances between tool points are what both must agree on.
    for i in range(len(poses)):
        for j in range(i):
            assert math.dist(ours[i], ours[j]) == pytest.approx(
                math.dist(theirs[i], theirs[j]), abs=1e-6
            )
