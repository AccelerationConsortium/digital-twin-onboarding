"""Sim–Real: pinned connector vocabulary, the world model, compilation and kept runs."""

import json
from copy import deepcopy

import pytest
from academy.simreal import bindings, compiler, fdl, report, world

FLEX, UR5E = "opentrons-flex", "ur5e"
SHAKER = "ca.accelerationconsortium/modules/HeaterShakerController/v3"
GRIPPER = "io.unitelabs/robot/PlateGripperController/v1"
NAMES = {"flex": "Flex", "arm": "Arm", "reader": "Reader"}


def workflow(**changes):
    data = compiler.example()
    data.update(changes)
    return data


def compiled(data):
    return compiler.compile_workflow(compiler.Workflow.model_validate(data))


@pytest.fixture(scope="module")
def plan():
    return compiled(compiler.example())


# --- feature definitions -------------------------------------------------------------------


def test_pinned_definitions_match_their_digests_and_identifiers():
    for key in (FLEX, UR5E):
        manifest = bindings.manifest(key)
        features = bindings.features(key)  # raises when a file drifted from its digest
        assert {f["id"] for f in manifest["features"]} == set(features)
        assert manifest["package_version"] and manifest["server"]["version"]
    assert SHAKER in bindings.features(FLEX) and GRIPPER in bindings.features(UR5E)


def test_arguments_are_checked_as_the_connector_would():
    shaker = bindings.feature(FLEX, "HeaterShakerController")
    assert fdl.check_arguments(shaker, "SetTemperature", {"Temperature": 37.0}) == []
    assert fdl.check_arguments(shaker, "SetTemperature", {"Temperature": 150}) == [
        "Temperature must be at most 95 °C; got 150"
    ]
    assert fdl.check_arguments(shaker, "SetSpeed", {"Speed": 500.5}) == ["Speed must be integer"]
    assert fdl.check_arguments(shaker, "SetSpeed", {}) == ["SetSpeed needs Speed"]
    assert fdl.check_arguments(shaker, "SetSpeed", {"Speed": 500, "Rpm": 1}) == [
        "SetSpeed has no parameter Rpm"
    ]
    assert fdl.check_arguments(shaker, "Spin", {}) == ["HeaterShakerController has no command Spin"]
    gripper = bindings.feature(UR5E, GRIPPER)
    grip = {"WidthMillimeters": 85.48, "ForceNewtons": 20, "ExpectedSimulationMode": True}
    assert fdl.check_arguments(gripper, "GripPlate", grip) == []
    assert fdl.check_arguments(gripper, "GripPlate", {**grip, "WidthMillimeters": 20}) == [
        "WidthMillimeters must be at least 60 mm; got 20"
    ]
    assert fdl.check_arguments(gripper, "GripPlate", {**grip, "ExpectedSimulationMode": 1}) == [
        "ExpectedSimulationMode must be boolean"
    ]
    handoff = bindings.feature(FLEX, "DeckHandoffController")
    call = {"LocationIdentifier": " A1", "LabwareIdentifier": "plate", "Source": "arm"}
    assert (
        "LocationIdentifier must match" in fdl.check_arguments(handoff, "RegisterLabware", call)[0]
    )


def test_structures_and_lists_are_checked_by_element():
    kind = {
        "kind": "list",
        "item": {
            "kind": "structure",
            "fields": [
                {"name": "X", "type": {"kind": "basic", "basic": "Real"}},
                {
                    "name": "Mode",
                    "type": {
                        "kind": "constrained",
                        "base": {"kind": "basic", "basic": "String"},
                        "constraints": {"Set": ["A", "B"]},
                    },
                },
            ],
        },
    }
    feature = {
        "identifier": "F",
        "types": {},
        "commands": {"Go": {"parameters": [{"name": "Points", "type": kind}]}},
    }
    assert fdl.check_arguments(feature, "Go", {"Points": [{"X": 1, "Mode": "A"}]}) == []
    assert fdl.check_arguments(
        feature, "Go", {"Points": [{"X": 1, "Mode": "A"}, {"X": "1", "Mode": "C", "Y": 0}]}
    ) == [
        "Points[1] has no element Y",
        "Points[1].X must be real",
        "Points[1].Mode must be one of A, B",
    ]
    with pytest.raises(fdl.FeatureError):
        fdl.parse("<Feature/>")


def test_a_binding_is_found_from_the_library_and_options_are_checked():
    assert bindings.for_library("chemlab", "opentrons_flex_single_5_1000ul") == FLEX
    assert bindings.for_library("workcell", "ur5e-2f140") == UR5E
    assert bindings.for_library("chemlab", "bmg_clariostarplus") is None
    for bad in (
        {"modules": ["centrifuge"]},
        {"handoff": ["E1"]},
        {"module_slots": {"heater_shaker": "D1"}},
        {"speed": 1},
    ):
        with pytest.raises(bindings.BindingError):
            bindings.options(FLEX, bad)
    with pytest.raises(bindings.BindingError, match="starts in its own pose"):
        bindings.options(UR5E, {"start_degrees": [0, 0, 0, 0, 0, 0]})
    files = bindings.launch_files(FLEX, 50001, "Flex", bindings.options(FLEX, {"handoff": ["D1"]}))
    assert files["config.json"]["use_simulator"] is True
    assert files["handoff.json"]["locations"] == ["D1"]
    assert bindings.launch_files(UR5E, 50002, "Arm", {})["config.json"]["simulation_mode"] is True


# --- world -----------------------------------------------------------------------------------


def start():
    devices = {
        "flex": {"connector": FLEX, "name": "Flex", "sites": ["D1", "D2"], "options": {}},
        "reader": {"connector": None, "name": "Reader", "sites": [], "options": {}},
        "arm": {
            "connector": UR5E,
            "name": "Arm",
            "sites": [],
            "options": {"start_degrees": [0.0] * 6},
        },
    }
    plate = {"id": "plate", "device": "flex", "site": "D1", "width_mm": 85.48}
    return world.start(devices, [plate])


def at(device, site=""):
    return {
        "do": "arm_move",
        "arm": "arm",
        "degrees": [1.0] * 6,
        "at": {"device": device, "site": site},
    }


def test_a_plate_is_followed_from_ledger_to_gripper_to_another_instrument():
    state = start()
    assert state["ledgers"] == {"flex": {"D1": "plate"}}
    for effect in (
        at("flex", "D1"),
        {"do": "grip", "arm": "arm"},
        {"do": "ledger_remove", "device": "flex", "site": "D1", "labware": "plate"},
        at("reader"),
        {"do": "release", "arm": "arm"},
    ):
        world.apply(state, effect, NAMES)
    assert state["labware"]["plate"] == {"device": "reader", "site": "", "width_mm": 85.48}
    assert state["ledgers"] == {"flex": {}} and state["arms"]["arm"]["holding"] is None
    assert world.expected(state, "flex", FLEX) == {"ledger": {}}
    assert world.expected(state, "arm", UR5E) == {"holding": False, "degrees": [1.0] * 6}


@pytest.mark.parametrize(
    ("effects", "reason"),
    [
        ([{"do": "grip", "arm": "arm"}], "not at a grasp point"),
        ([at("flex", "D2"), {"do": "grip", "arm": "arm"}], "No plate is in slot D2"),
        ([at("flex", "D1"), {"do": "release", "arm": "arm"}], "holds nothing"),
        (
            [{"do": "ledger_remove", "device": "flex", "site": "D1", "labware": "plate"}],
            "still in slot D1",
        ),
        (
            [{"do": "ledger_add", "device": "flex", "site": "D2", "labware": "plate"}],
            "it is not there",
        ),
        (
            [
                at("flex", "D1"),
                {"do": "grip", "arm": "arm"},
                {"do": "arm_move", "arm": "arm", "degrees": [2.0] * 6},
                {"do": "release", "arm": "arm"},
            ],
            "in mid-air",
        ),
        (
            [
                {"do": "flag", "device": "flex", "name": "latch_slot", "value": "D1"},
                {"do": "flag", "device": "flex", "name": "latch", "value": "closed"},
                at("flex", "D1"),
                {"do": "grip", "arm": "arm"},
            ],
            "latch on Flex slot D1 is closed",
        ),
    ],
)
def test_the_world_refuses_effects_that_cannot_happen(effects, reason):
    state = start()
    with pytest.raises(world.WorldError, match=reason):
        for effect in effects:
            world.apply(state, effect, NAMES)


def test_connector_readings_are_compared_with_the_world():
    state = start()
    deck = {
        "Valid": True,
        "OccupiedLocations": [{"LocationIdentifier": "D1", "LabwareIdentifier": "plate"}],
    }
    seen = world.observed(FLEX, {world.READBACK[FLEX][0]: deck})
    assert world.differences("flex", world.expected(state, "flex", FLEX), seen) == []
    empty = world.observed(
        FLEX, {world.READBACK[FLEX][0]: {"Valid": True, "OccupiedLocations": []}}
    )
    assert world.differences("flex", world.expected(state, "flex", FLEX), empty) == [
        {"device": "flex", "field": "ledger", "expected": {"D1": "plate"}, "observed": {}}
    ]
    grip, joints = world.READBACK[UR5E]
    arm = world.observed(UR5E, {grip: "HOLDING", joints: [0.0, 0.0, 0.0, 0.0, 0.0, 0.01]})
    found = world.differences("arm", world.expected(state, "arm", UR5E), arm)
    assert [d["field"] for d in found] == ["holding", "joints"]
    receipt = {"Receipt": json.dumps({"duration": 35.4})}
    assert world.device_seconds(joints[0], "RunContinuousMotion", receipt) == 35.4
    assert world.device_seconds(grip[0], "GripPlate", {"OpeningMillimeters": 85.48}) is None


# --- compilation -----------------------------------------------------------------------------


def test_the_example_compiles_into_connector_commands(plan):
    assert plan["valid"] and plan["problems"] == [] and plan["evidence"] == "simulation"
    commands = [(s["device"], s["command"]) for s in plan["steps"]]
    assert commands[0] == ("flex", "SetTemperature")
    first = [
        c for (_, c), s in zip(commands, plan["steps"], strict=True) if s["source"] == "to-reader"
    ]
    assert first == [
        "PrepareActionChainAtSpeed",
        "RunContinuousMotion",  # travel from the simulator's start pose
        "PrepareActionChainAtSpeed",
        "RunContinuousMotion",  # lower into the Flex
        "SetSimulatedObject",
        "GripPlate",
        "PrepareActionChainAtSpeed",
        "RunContinuousMotion",  # lift, carry, lower into the reader
        "ReleaseLabware",  # the Flex forgets the plate once it is away
        "ReleasePlate",
        "PrepareActionChainAtSpeed",
        "RunContinuousMotion",  # retreat
    ]
    # Every command is one the pinned connector defines and would accept.
    devices = {d["id"]: d for d in plan["devices"]}
    for step in plan["steps"]:
        feature = bindings.features(devices[step["device"]]["connector"])[step["feature"]]
        literal = {k: v for k, v in step["arguments"].items() if not isinstance(v, dict)}
        problems = fdl.check_arguments(feature, step["command"], literal)
        assert all(" needs " in p for p in problems), (step["id"], problems)
    # The arm touches Flex slot D1, so that slot is a handoff slot of the simulated Flex,
    # and the plate that starts there is in its deck ledger.
    assert devices["flex"]["options"]["handoff"] == ["D1"]
    assert devices["flex"]["options"]["occupancy"] == {"D1": "assay-plate"}
    # The plate ends where it started and both ledgers agree.
    assert plan["steps"][-1]["world"]["labware"] == {
        "assay-plate": {"device": "flex", "site": "D1"}
    }
    assert plan["steps"][-1]["world"]["ledgers"] == {"flex": {"D1": "assay-plate"}}
    assert [m["simulation"]["engine"] for m in plan["motions"]] == ["mujoco", "mujoco"]
    assert plan["digest"] == compiler.digest(plan)
    assert set(plan["connectors"]) == {FLEX, UR5E}


def test_a_plan_keeps_its_identity_through_a_browser(plan):
    def as_javascript(value):
        # JSON.parse then JSON.stringify writes 20.0 as 20.
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, dict):
            return {k: as_javascript(v) for k, v in value.items()}
        if isinstance(value, list):
            return [as_javascript(v) for v in value]
        return value

    returned = json.loads(json.dumps(as_javascript(plan)))
    assert compiler.digest(returned) == plan["digest"]
    returned["steps"][0]["arguments"]["Temperature"] = 38
    assert compiler.digest(returned) != plan["digest"]


def test_only_the_simulated_scene_is_marked_simulation_only(plan):
    assert {s["command"] for s in plan["steps"] if s.get("simulation_only")} == {
        "SetSimulatedObject"
    }


def step(**fields):
    return {
        "id": "x",
        "kind": "command",
        "device": "flex",
        "feature": "HeaterShakerController",
        **fields,
    }


@pytest.mark.parametrize(
    ("change", "layer", "reason"),
    [
        (
            {"steps": [step(command="SetTemperature", parameters={"Temperature": 150})]},
            "constraint",
            "Temperature must be at most 95 °C",
        ),
        ({"steps": [step(command="Spin")]}, "constraint", "has no command Spin"),
        (
            {"steps": [step(feature="CentrifugeController", command="Spin")]},
            "state",
            "no feature CentrifugeController",
        ),
        (
            {"steps": [step(device="reader", command="Read")]},
            "state",
            "has no connector, so it takes no commands",
        ),
        (
            {
                "steps": [
                    step(device="arm", feature="SimulationController", command="StartRealMode")
                ]
            },
            "state",
            "never switches a connector out of simulation",
        ),
        (
            {
                "steps": [
                    step(
                        device="arm",
                        feature="RobotController",
                        command="MoveJoint",
                        parameters={"Joint": "Base", "DeltaDegrees": 5, "RequestId": "a"},
                    )
                ]
            },
            "state",
            "moves through transfer steps",
        ),
        (
            {
                "steps": [
                    step(
                        feature="DeckHandoffController",
                        command="ReleaseLabware",
                        parameters={
                            "LocationIdentifier": "D1",
                            "LabwareIdentifier": "assay-plate",
                            "Destination": "arm",
                        },
                    )
                ]
            },
            "state",
            "still in slot D1",
        ),
        (
            {
                "steps": [
                    {
                        "id": "x",
                        "kind": "transfer",
                        "arm": "arm",
                        "labware": "other-plate",
                        "to": {"device": "reader"},
                    }
                ]
            },
            "state",
            "no plate other-plate",
        ),
        (
            {
                "steps": [
                    {
                        "id": "x",
                        "kind": "transfer",
                        "arm": "arm",
                        "labware": "assay-plate",
                        "to": {"device": "flex", "site": "E9"},
                    }
                ]
            },
            "resource",
            "has no slot E9",
        ),
    ],
)
def test_a_wrong_workflow_compiles_to_a_named_problem(change, layer, reason):
    found = compiled(workflow(**change))
    assert not found["valid"]
    assert found["problems"][0]["layer"] == layer and reason in found["problems"][0]["message"]


def test_heater_shaker_rules_its_simulator_does_not_enforce_are_kept():
    shake = step(id="shake", command="SetSpeed", parameters={"Speed": 500})
    found = compiled(workflow(steps=[step(id="open", command="OpenLatch"), shake]))
    assert found["problems"] == [
        {
            "step": "shake",
            "layer": "state",
            "message": "Liquid handler (Opentrons Flex): close the Heater-Shaker latch before shaking",
        }
    ]
    closed = [step(id="close", command="CloseLatch"), shake]
    assert compiled(workflow(steps=closed))["valid"]
    opened = compiled(workflow(steps=[*closed, step(id="open", command="OpenLatch")]))
    assert "stop shaking before opening" in opened["problems"][0]["message"]
    stopped = [
        *closed,
        step(id="stop", command="StopShaking"),
        step(id="open", command="OpenLatch"),
    ]
    assert compiled(workflow(steps=stopped))["valid"]


def test_an_arm_that_starts_inside_an_instrument_is_reported():
    data = workflow()
    data["layout"]["placements"][0]["yaw"] = 0
    found = compiled(data)
    assert found["problems"] == [
        {
            "step": None,
            "layer": "geometry",
            "message": "UR5e arm starts its simulation with its gripper inside Liquid handler "
            "(Opentrons Flex). Turn or move the arm on the bench.",
        }
    ]


def test_a_second_plate_cannot_be_set_down_on_an_occupied_slot():
    data = workflow()
    data["labware"].append({"id": "other-plate", "device": "flex", "site": "D2"})
    data["steps"] = [
        {
            "id": "x",
            "kind": "transfer",
            "arm": "arm",
            "labware": "other-plate",
            "to": {"device": "flex", "site": "D1"},
        }
    ]
    found = compiled(data)
    assert not found["valid"] and "already holds assay-plate" in found["problems"][0]["message"]
    assert found["problems"][0]["step"] == "x"


def test_cycles_are_unrolled_and_later_cycles_skip_the_first_travel():
    data = workflow(cycles=2)
    data["steps"] = data["steps"][1:3]
    found = compiled(data)
    assert found["valid"], found["problems"]
    first = [s["id"] for s in found["steps"] if s["cycle"] == 1]
    second = [s["id"] for s in found["steps"] if s["cycle"] == 2]
    assert first[0] == "c1.to-reader.travel.prepare"
    # After one round the arm waits above the Flex, where the next round starts.
    assert second[0] == "c2.to-reader.lower.prepare" and len(second) == len(first) - 2


def test_workflow_ids_and_devices_are_validated():
    data = workflow()
    data["devices"].append(deepcopy(data["devices"][0]))
    with pytest.raises(ValueError, match="every device its own id"):
        compiler.Workflow.model_validate(data)
    unknown = workflow()
    unknown["devices"][1]["library"]["id"] = "nope"
    assert "Unknown library entry" in compiled(unknown)["problems"][0]["message"]
    wrong = workflow()
    wrong["devices"][1]["connector"] = UR5E
    assert "does not drive" in compiled(wrong)["problems"][0]["message"]


# --- reports and routes ----------------------------------------------------------------------


def passed(plan):
    devices = {d["id"]: d for d in plan["devices"] if d["connector"]}
    return {
        "schema": report.REPORT,
        "evidence": "simulation",
        "plan_digest": plan["digest"],
        "outcome": "passed",
        "stopped_at": None,
        "reason": None,
        "started_at": 1.0,
        "wall_s": 20.0,
        "connectors": {
            key: {
                "connector": d["connector"],
                "package_version": "1",
                "commit": None,
                "dirty": None,
                "features": plan["connectors"][d["connector"]]["features"],
            }
            for key, d in devices.items()
        },
        "steps": [
            {
                "id": s["id"],
                "cycle": 1,
                "device": s["device"],
                "command": s["command"],
                "status": "done",
                "wall_s": 0.1,
            }
            for s in plan["steps"]
        ],
        "cycles": [{"cycle": 1, "steps": len(plan["steps"]), "wall_s": 2.4, "device_s": 150.0}],
        "world": plan["steps"][-1]["world"],
    }


def test_a_report_is_kept_only_for_its_own_plan_and_pinned_connectors(plan):
    record = report.check(plan, passed(plan))
    assert record["outcome"] == "passed" and record["device_s"] == 150
    assert record["connectors"]["arm"]["connector"] == UR5E

    other = passed(plan)
    other["plan_digest"] = "0" * 64
    short = passed(plan)
    short["steps"] = short["steps"][:-1]
    reordered = passed(plan)
    reordered["steps"][0], reordered["steps"][1] = reordered["steps"][1], reordered["steps"][0]
    drifted = passed(plan)
    drifted["connectors"]["arm"]["features"] = {GRIPPER: "0" * 64}
    for bad, reason in (
        (other, "another plan"),
        (short, "completes every step"),
        (reordered, "in order"),
        (drifted, "was not compiled against"),
    ):
        with pytest.raises(report.ReportError, match=reason):
            report.check(plan, bad)
    edited = deepcopy(plan)
    edited["steps"][0]["arguments"]["Temperature"] = 60
    with pytest.raises(report.ReportError, match="changed after it was compiled"):
        report.check(edited, passed(plan))


def test_routes_list_connectors_compile_and_keep_runs(client, plan):
    found = client.get("/api/sim-real/v1/connectors").json()
    assert found["evidence"] == "simulation"
    by_key = {c["key"]: c for c in found["connectors"]}
    assert by_key[UR5E]["imported"] and by_key[FLEX]["library"] == [
        {"collection": "chemlab", "id": "opentrons_flex_single_5_1000ul"}
    ]
    gripper = next(
        f for f in by_key[UR5E]["features"] if f["identifier"] == "PlateGripperController"
    )
    assert {"name": "WidthMillimeters", "type": "Real (60–140 mm)"} in next(
        c for c in gripper["commands"] if c["name"] == "GripPlate"
    )["parameters"]

    example = client.get("/api/sim-real/v1/example").json()
    bad = {**example, "steps": [step(command="SetTemperature", parameters={"Temperature": 150})]}
    answer = client.post("/api/sim-real/v1/compile", json=bad)
    assert answer.status_code == 200 and not answer.json()["valid"]
    assert (
        client.post("/api/sim-real/v1/compile", json={**example, "schema": "x"}).status_code == 422
    )

    run_id = "5c5b2f3a-6f0e-4c53-9d5e-0b1c7c1a9d11"
    body = {"run_id": run_id, "plan": plan, "report": passed(plan)}
    kept = client.post("/api/sim-real/v1/runs", json=body)
    assert kept.status_code == 201 and kept.json()["outcome"] == "passed"
    assert (
        client.post("/api/sim-real/v1/runs", json=body).json()["kept_at"] == kept.json()["kept_at"]
    )
    listed = client.get("/api/sim-real/v1/runs").json()["runs"]
    assert [r["run_id"] for r in listed] == [run_id] and listed[0]["steps"] == len(plan["steps"])
    assert client.get(f"/api/sim-real/v1/runs/{run_id}").json()["steps"][0]["status"] == "done"
    forged = {**body, "run_id": "6c5b2f3a-6f0e-4c53-9d5e-0b1c7c1a9d11"}
    forged["report"] = {**forged["report"], "plan_digest": "0" * 64}
    assert client.post("/api/sim-real/v1/runs", json=forged).status_code == 422
    assert client.delete(f"/api/sim-real/v1/runs/{run_id}").status_code == 204
    assert client.get(f"/api/sim-real/v1/runs/{run_id}").status_code == 404
    assert client.get("/api/sim-real/v1/runs").json()["runs"] == []
