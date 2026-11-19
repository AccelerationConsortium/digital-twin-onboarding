"""The state twin runs alongside and ahead of mock execution: lookahead, motion, divergence."""

from itertools import count
from uuid import UUID, uuid4

import pytest
from academy import examples, state_twin
from academy.mock_contract import execute_mock
from academy.run_monitor import MockExecutor, command, counterfactual, divergence, start


def ids():
    numbers = count(1)
    return lambda: UUID(int=next(numbers))


def workcell(mixes=4):
    """Flex (tips) → sealer → reader, with `mixes` mixes on the Flex first."""
    twins, steps, layout = examples.build(examples.EXAMPLES["flex-sealer-reader"], ids())
    flex, sealer, reader, arm = (t["id"] for t in twins)
    load, mix, *rest = steps
    steps = [load, *[dict(mix) for _ in range(mixes)], *rest]
    return {t["id"]: t for t in twins}, steps, layout, (flex, sealer, reader, arm)


def begin(faults=(), mixes=4, horizon=3):
    twins, steps, layout, names = workcell(mixes)
    executor = MockExecutor.start(twins, layout, [dict(f) for f in faults])
    run = start(twins, steps, layout, [], executor, horizon)
    return run, twins, executor, names


def go(run, twins, executor, name):
    return command(run, twins, executor, name)


def test_clean_run_completes_without_divergence_and_stays_synthetic():
    run, twins, executor, _ = begin()
    assert run["status"] == "ready" and run["initial"]["divergence"] == []
    go(run, twins, executor, "run")
    assert run["status"] == "completed", run["pause"]
    assert run["cursor"] == len(run["steps"])
    assert all(entry["divergence"] == [] for entry in run["trace"])
    assert run["pauses"] == []
    assert run["evidence"] == "synthetic" and run["physical_execution"] is False
    assert executor.physical is False
    # The twin agrees with the contract the plan was checked against.
    final = execute_mock(twins, run["steps"])[-1]
    assert run["twin"]["samples"]["sample"]["volume_ul"] == final["volume_ul"]
    flex = run["steps"][0]["device_id"]
    assert run["twin"]["stock"][flex] == final["consumables"][flex]


def test_sync_replaces_state_and_refuses_partial_observations():
    run, twins, executor, (flex, *_) = begin()
    observed = executor.observe()
    observed["stock"][flex]["Pipette tips"] = 7
    synced = state_twin.sync(observed)
    assert synced["stock"][flex]["Pipette tips"] == 7
    observed["stock"][flex]["Pipette tips"] = 1
    assert synced["stock"][flex]["Pipette tips"] == 7  # a copy, not a view
    del observed["gripper"]
    with pytest.raises(ValueError, match="gripper"):
        state_twin.sync(observed)


def test_lookahead_blocks_the_step_that_runs_out_and_not_earlier():
    run, twins, executor, (flex, *_) = begin()
    state = state_twin.sync(executor.observe())
    state["stock"][flex]["Pipette tips"] = 2
    look = state_twin.lookahead(twins, state, run["steps"], 0, 12)
    # Steps 2 and 3 use the last two tips; step 4 is the first that cannot run.
    assert look["checked"] == [1, 2, 3]
    assert look["failure"]["step"] == 4 and look["failure"]["code"] == "consumable_empty"
    assert state_twin.lookahead(twins, state, run["steps"], 0, 2)["failure"] is None


def test_tip_shortfall_diverges_then_blocks_before_the_empty_step():
    shortfall = {"kind": "tip_shortfall", "consumable": "Pipette tips", "actual": 3}
    twins, *_ = workcell()
    flex = next(iter(twins))
    run, twins, executor, _ = begin([{**shortfall, "device_id": flex}])
    # The rack is not counted until it is used, so the run starts as declared.
    assert run["status"] == "ready"
    go(run, twins, executor, "step")
    go(run, twins, executor, "step")
    assert run["status"] == "paused" and run["pause"]["layer"] == "divergence"
    assert run["pause"]["step"] == 2
    [difference] = run["pause"]["fields"]
    assert difference == {
        "field": f"stock.{flex}.Pipette tips",
        "expected": 95,
        "observed": 2,
        "delta": -93,
    }
    assert "Pipette tips: expected 95, observed 2" in run["pause"]["message"]
    with pytest.raises(Exception, match="Resume"):
        go(run, twins, executor, "step")
    go(run, twins, executor, "resume")
    # Synced: two tips left for steps 3 and 4, so step 5 is predicted to fail...
    assert run["status"] == "ready"
    assert run["prediction"]["failure"]["step"] == 5
    go(run, twins, executor, "step")
    assert run["status"] == "ready" and run["cursor"] == 3  # ...but not blocked early
    go(run, twins, executor, "step")
    assert run["status"] == "blocked" and run["cursor"] == 4
    assert run["pause"] | {"message": ""} == {
        "kind": "predicted",
        "layer": "lookahead",
        "step": 5,
        "code": "consumable_empty",
        "message": "",
        "fields": [],
    }
    # Nothing was executed past the block; the executor still has no tips to spare.
    assert executor.world["stock"][flex]["Pipette tips"] == 0
    go(run, twins, executor, "resume")
    assert run["status"] == "blocked"
    with pytest.raises(Exception, match="Resume"):
        go(run, twins, executor, "run")


def test_door_left_open_blocks_only_the_step_on_that_instrument():
    twins, *_ = workcell()
    reader = list(twins)[2]
    run, twins, executor, _ = begin([{"kind": "door_open", "step": 1, "device_id": reader}])
    go(run, twins, executor, "step")
    assert run["status"] == "paused"
    assert run["pause"]["fields"][0]["field"] == f"doors.{reader}"
    go(run, twins, executor, "resume")
    go(run, twins, executor, "run")
    # Every step up to the read ran; the read on the open reader is the one held.
    assert run["status"] == "blocked"
    assert run["pause"]["step"] == len(run["steps"]) and run["pause"]["code"] == "door_open"
    assert run["cursor"] == len(run["steps"]) - 1


def test_stuck_gripper_is_a_divergence_and_the_next_step_finds_no_sample():
    run, twins, executor, (flex, sealer, reader, arm) = begin(
        [{"kind": "gripper_stuck", "step": 6}]
    )
    go(run, twins, executor, "run")
    assert run["status"] == "paused" and run["pause"]["step"] == 6
    fields = {d["field"] for d in run["pause"]["fields"]}
    assert {f"gripper.{arm}", "samples.sample.location", "samples.sample.site"} <= fields
    go(run, twins, executor, "resume")
    assert run["status"] == "blocked" and run["pause"]["step"] == 7
    assert run["pause"]["code"] == "labware_missing"


def test_volume_loss_beyond_tolerance_pauses_and_small_noise_does_not():
    run, twins, executor, _ = begin([{"kind": "volume_loss", "step": 1, "loss_ul": 20}])
    go(run, twins, executor, "step")
    assert run["status"] == "paused"
    assert run["pause"]["fields"] == [
        {"field": "samples.sample.volume_ul", "expected": 150, "observed": 130, "delta": -20}
    ]
    expected = state_twin.sync(executor.observe())
    noisy = state_twin.sync(expected)
    noisy["samples"]["sample"]["volume_ul"] += 0.3
    assert divergence(expected, noisy) == []


def test_motion_check_uses_the_observed_layout():
    twins, steps, layout, (flex, sealer, reader, arm) = workcell(mixes=1)
    at = next(p for p in layout["placements"] if p["twin_id"] == sealer)
    # Pushed onto the arm's base: the planner refuses the layout before the transfer.
    shift = {"kind": "layout_shift", "step": 0, "twin_id": sealer, "dx": -at["x"], "dz": -at["z"]}
    run, twins, executor, _ = begin([shift], mixes=1)
    assert run["status"] == "paused" and run["pause"]["step"] == 0
    go(run, twins, executor, "resume")
    go(run, twins, executor, "run")
    assert run["status"] == "blocked" and run["pause"]["layer"] == "motion"
    assert run["pause"]["step"] == 3 and run["cursor"] == 2


def test_small_shift_replans_the_transfer_and_continues():
    twins, steps, layout, (flex, sealer, reader, arm) = workcell(mixes=1)
    shift = {"kind": "layout_shift", "step": 0, "twin_id": reader, "dx": 0.0, "dz": 0.005}
    run, twins, executor, _ = begin([shift], mixes=1)
    assert run["status"] == "ready"  # within the 1 cm placement tolerance
    go(run, twins, executor, "run")
    assert run["status"] == "completed", run["pause"]
    transfers = [e for e in run["trace"] if e["operation"] == "transfer"]
    assert [e["motion"]["replanned"] for e in transfers] == [True, True]


def test_ghost_shows_the_next_move_from_the_twin():
    run, twins, executor, (flex, sealer, reader, arm) = begin(mixes=1)
    go(run, twins, executor, "step")
    go(run, twins, executor, "step")
    ghost = run["next"]
    assert ghost["step"] == 3 and ghost["operation"] == "transfer"
    assert (ghost["source_id"], ghost["target_id"]) == (flex, sealer)
    assert ghost["motion"]["path"] and ghost["motion"]["joints"]
    assert {c["field"] for c in ghost["changes"]} >= {"samples.sample.location"}


def blocked_by_tips():
    twins, *_ = workcell()
    flex = next(iter(twins))
    fault = {"kind": "tip_shortfall", "device_id": flex, "consumable": "Pipette tips", "actual": 3}
    run, twins, executor, _ = begin([fault])
    go(run, twins, executor, "run")
    go(run, twins, executor, "resume")
    go(run, twins, executor, "run")
    assert run["status"] == "blocked" and run["pause"]["step"] == 5
    return run, flex


def test_counterfactual_replay_is_deterministic_and_answers_the_question():
    run, flex = blocked_by_tips()
    refill = {"stock": {flex: {"Pipette tips": 96}}}
    first = counterfactual(run, refill)
    assert first == counterfactual(run, refill)
    assert first["original"]["status"] == "blocked"
    assert first["replay"]["status"] == "completed" and first["avoided"] is True
    assert first["evidence"] == "synthetic" and first["physical_execution"] is False
    assert first["assumption"].startswith("Steps after step 4 never ran")
    # As recorded (three tips), the replay reproduces the divergence and the block.
    same = counterfactual(run, {})
    assert same["replay"]["status"] == "blocked" and same["avoided"] is False
    assert [(s["step"], s["code"]) for s in same["stops"]] == [
        (2, "diverged"),
        (5, "consumable_empty"),
    ]
    # Four tips are just enough; three are not.
    assert counterfactual(run, {"stock": {flex: {"Pipette tips": 4}}})["avoided"] is True
    assert counterfactual(run, {"stock": {flex: {"Pipette tips": 3}}})["avoided"] is False
    with pytest.raises(ValueError):
        counterfactual(run, {"step_values": {99: 1.0}})


def test_counterfactual_can_move_an_instrument_back():
    twins, steps, layout, (flex, sealer, reader, arm) = workcell(mixes=1)
    at = next(p for p in layout["placements"] if p["twin_id"] == sealer)
    shift = {"kind": "layout_shift", "step": 0, "twin_id": sealer, "dx": -at["x"], "dz": -at["z"]}
    run, twins, executor, _ = begin([shift], mixes=1)
    go(run, twins, executor, "resume")
    go(run, twins, executor, "run")
    assert run["status"] == "blocked"
    back = {"placements": {sealer: {"x": at["x"], "z": at["z"], "yaw": at["yaw"]}}}
    result = counterfactual(run, back)
    assert result["avoided"] is True and result["replay"]["status"] == "completed"


# --- API: owner-scoped, versioned, bound to the saved workcell revision -----------------


def open_workcell(client, mixes=4):
    opened = client.put("/api/twins/examples/flex-sealer-reader", json={"expected_version": 0})
    assert opened.status_code == 200, opened.text
    catalog = opened.json()
    load, mix, *rest = catalog["steps"]
    saved = client.put(
        "/api/twins/workflow",
        json={
            "expected_version": catalog["version"],
            "steps": [load, *[mix] * mixes, *rest],
        },
    )
    assert saved.status_code == 200, saved.text
    return saved.json()


def test_api_runs_monitored_mock_and_rejects_stale_commands(client):
    catalog = open_workcell(client)
    flex = catalog["steps"][0]["device_id"]
    body = {
        "run_id": str(uuid4()),
        "expected_version": catalog["version"],
        "faults": [
            {"kind": "tip_shortfall", "device_id": flex, "consumable": "Pipette tips", "actual": 3}
        ],
    }
    stale = client.post("/api/twin-runs", json={**body, "expected_version": 999})
    assert stale.status_code == 409
    created = client.post("/api/twin-runs", json=body)
    assert created.status_code == 200, created.text
    run = created.json()
    assert run["version"] == 1 and run["physical_execution"] is False
    assert run["executor"]["kind"] == "mock"
    assert client.post("/api/twin-runs", json=body).json() == run
    # The workspace itself is not changed by binding a run to it.
    assert client.get("/api/twins").json()["version"] == catalog["version"]
    url = f"/api/twin-runs/{run['run_id']}"
    first = client.post(url + "/commands", json={"expected_version": 1, "command": "run"})
    assert first.status_code == 200 and first.json()["status"] == "paused"
    again = client.post(url + "/commands", json={"expected_version": 1, "command": "resume"})
    assert again.status_code == 409
    resumed = client.post(url + "/commands", json={"expected_version": 2, "command": "resume"})
    done = client.post(
        url + "/commands", json={"expected_version": resumed.json()["version"], "command": "run"}
    ).json()
    assert done["status"] == "blocked" and done["pause"]["step"] == 5
    assert client.get(url).json() == done
    replay = client.post(url + "/counterfactual", json={"stock": {flex: {"Pipette tips": 96}}})
    assert replay.status_code == 200 and replay.json()["avoided"] is True
    assert client.get(url).json() == done  # a replay changes nothing
    listed = client.get("/api/twin-runs").json()
    assert [r["run_id"] for r in listed] == [run["run_id"]]
    stopped = client.post(url + "/commands", json={"expected_version": 4, "command": "stop"})
    assert stopped.json()["status"] == "stopped"


def test_api_validates_faults_and_scopes_runs_to_their_owner(client, app):
    catalog = open_workcell(client, mixes=1)
    flex = catalog["steps"][0]["device_id"]
    bad = [
        {"kind": "tip_shortfall", "device_id": flex, "consumable": "Pipette tips", "actual": 96},
        {"kind": "tip_shortfall", "device_id": flex, "consumable": "Nothing", "actual": 1},
        {"kind": "gripper_stuck", "step": 1},
        {"kind": "door_open", "step": 1, "device_id": str(uuid4())},
    ]
    for fault in bad:
        response = client.post(
            "/api/twin-runs",
            json={
                "run_id": str(uuid4()),
                "expected_version": catalog["version"],
                "faults": [fault],
            },
        )
        assert response.status_code == 422, fault
    run = client.post(
        "/api/twin-runs", json={"run_id": str(uuid4()), "expected_version": catalog["version"]}
    ).json()
    from fastapi.testclient import TestClient

    with TestClient(app) as other:
        assert other.post("/api/auth/guest", json={"name": "Grace"}).status_code == 200
        assert other.get(f"/api/twin-runs/{run['run_id']}").status_code == 404
        assert other.get("/api/twin-runs").json() == []
