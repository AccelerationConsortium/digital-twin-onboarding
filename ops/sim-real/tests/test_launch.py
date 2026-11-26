"""The runner starts nothing it cannot show to be the pinned release in simulation."""

import json
import sys
from pathlib import Path

import pytest
from academy.simreal import bindings
from academy_sim_real import launch, runner

FAKE = Path(__file__).with_name("fake_connector.py")
SIMULATION = "org.silastandard/core/SimulationController/v1"


@pytest.fixture
def fake(monkeypatch):
    """The UR5e binding, started as a stand-in server that only has a simulation switch."""
    profile = {
        **bindings.PROFILES["ur5e"],
        "argv": ["{python}", str(FAKE), "{config}"],
    }
    monkeypatch.setitem(bindings.PROFILES, "ur5e", profile)
    return launch.Installation(Path(sys.executable))


async def test_a_connector_that_does_not_report_simulation_gets_no_commands(
    fake, tmp_path, monkeypatch
):
    monkeypatch.setenv("FAKE_SIMULATING", "0")
    with pytest.raises(launch.LaunchError, match="does not report simulation; nothing was sent"):
        async with launch.running("ur5e", fake, tmp_path):
            pytest.fail("the connector was handed out")


async def test_a_feature_that_was_never_pinned_is_drift(fake, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_EXTRA", "1")
    with pytest.raises(launch.LaunchError, match="org.example/test/Extra/v1 is not in the pinned"):
        async with launch.running("ur5e", fake, tmp_path):
            pytest.fail("the connector was handed out")


async def test_a_simulating_subset_of_the_pinned_release_starts_and_stops(fake, tmp_path):
    # The stand-in words its simulation switch differently, so the digest check is off.
    async with launch.running("ur5e", fake, tmp_path, device="arm", pinned=False) as connector:
        assert connector.device == "arm" and SIMULATION in connector.served
        assert await connector.read(SIMULATION, "SimulationMode") is True
        process = connector.process
    assert process.returncode is not None
    config = json.loads((tmp_path / "config.json").read_text())
    assert config["simulation_mode"] is True and config["sila_server"]["hostname"] == "127.0.0.1"


def test_a_changed_definition_is_drift():
    pinned = bindings.manifest("ur5e")
    file = next(f for f in pinned["features"] if f["id"] == SIMULATION)["file"]
    xml = (bindings.ROOT / "ur5e" / file).read_text()
    assert launch.drift("ur5e", {SIMULATION: xml}) == []
    assert launch.drift("ur5e", {SIMULATION: xml.replace("simulation", "Simulation", 1)}) == [
        f"{SIMULATION} differs from the pinned release"
    ]


def test_installations_come_from_arguments_or_the_environment(tmp_path):
    python = tmp_path / "python"
    python.write_text("")
    found = launch.installations(
        [f"ur5e={python}:{tmp_path}"], {"SIMREAL_OPENTRONS_FLEX_PYTHON": str(python)}
    )
    assert found["ur5e"].source == tmp_path and found["opentrons-flex"].source is None
    with pytest.raises(launch.LaunchError):
        launch.installations(["centrifuge=/usr/bin/python"], {})
    with pytest.raises(launch.LaunchError, match="No interpreter"):
        launch.installations([f"ur5e={tmp_path / 'missing'}"], {})


def test_arguments_take_values_from_earlier_responses():
    responses = {"a.prepare": {"Plan": json.dumps({"id": "p-1", "duration": 3})}}
    made = runner.resolve(
        {
            "PlanId": {"$response": "a.prepare", "path": ["Plan", "id"]},
            "RequestId": {"$uuid": True},
            "ExpiresAtUnixSeconds": {"$expires_in": 20},
            "Speed": 20,
            "Nested": {"Keep": [1, {"$uuid": True}]},
        },
        responses,
    )
    assert made["PlanId"] == "p-1" and made["Speed"] == 20
    assert len(made["RequestId"]) == 36 and made["RequestId"] != made["Nested"]["Keep"][1]
    assert 15 < made["ExpiresAtUnixSeconds"] - __import__("time").time() <= 20
    assert runner._plain(
        {"Receipt": json.dumps({"duration": 3.5, "trajectory": [[0] * 6] * 9})}
    ) == {"Receipt": {"duration": 3.5}}


async def test_a_plan_changed_after_compiling_is_not_run():
    with pytest.raises(launch.LaunchError, match="valid compiled plan"):
        await runner.run_plan({"schema": "simreal.plan/1", "valid": False}, {})
    plan = {"schema": "simreal.plan/1", "valid": True, "steps": [], "digest": "0" * 64}
    with pytest.raises(launch.LaunchError, match="changed after it was compiled"):
        await runner.run_plan(plan, {})


# --- the same plan on an instrument's own connector ---------------------------------

FLEX_ONLY = {
    "schema": "simreal.workflow/1",
    "name": "Warm the shaker",
    "devices": [
        {
            "id": "flex",
            "library": {"collection": "chemlab", "id": "opentrons_flex_single_5_1000ul"},
            "options": {"modules": ["heater_shaker"]},
        }
    ],
    "layout": {"bench": {"width": 2.4, "depth": 1.6}, "placements": []},
    "labware": [],
    "steps": [
        {
            "id": "warm",
            "kind": "command",
            "device": "flex",
            "feature": "HeaterShakerController",
            "command": "SetTemperature",
            "parameters": {"Temperature": 37.0},
        }
    ],
}


@pytest.fixture(scope="module")
def flex_plan():
    from academy.simreal import compiler

    plan = compiler.compile_workflow(compiler.Workflow.model_validate(FLEX_ONLY))
    assert plan["valid"], plan["problems"]
    return plan


def passed(plan):
    return {
        "schema": runner.REPORT,
        "evidence": "simulation",
        "plan_digest": plan["digest"],
        "outcome": "passed",
    }


@pytest.fixture
async def standing(tmp_path, monkeypatch):
    """A stand-in connector somebody else started, as an instrument's connector is."""
    import asyncio
    import os
    import socket

    started = []

    async def start(simulating):
        port = launch.free_port()
        config = tmp_path / f"standing-{port}.json"
        config.write_text(json.dumps({"sila_server": {"port": port}}))
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(FAKE),
            str(config),
            env={**os.environ, "FAKE_SIMULATING": "1" if simulating else "0"},
        )
        started.append(process)
        for _ in range(200):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                return process, port
            except OSError:
                await asyncio.sleep(0.1)
        pytest.fail("the stand-in connector did not start")

    monkeypatch.setitem(
        bindings.PROFILES, "ur5e", {**bindings.PROFILES["ur5e"], "real": {"port": 1}}
    )
    yield start
    for process in started:
        if process.returncode is None:
            process.terminate()
            await process.wait()


async def test_an_instrument_connector_is_joined_and_left_running(standing):
    process, port = await standing(simulating=False)
    async with launch.attached("ur5e", f"127.0.0.1:{port}", device="arm", pinned=False) as found:
        assert found.process is None and found.host == "127.0.0.1" and found.port == port
        assert await found.read(SIMULATION, "SimulationMode") is False
    assert process.returncode is None


async def test_a_simulating_connector_is_not_taken_for_an_instrument(standing):
    _, port = await standing(simulating=True)
    with pytest.raises(launch.LaunchError, match="reports simulation, not an instrument"):
        async with launch.attached("ur5e", f"127.0.0.1:{port}", pinned=False):
            pytest.fail("the connector was handed out")


async def test_an_instrument_connector_is_held_to_the_pinned_release(standing, monkeypatch):
    monkeypatch.setenv("FAKE_EXTRA", "1")
    _, port = await standing(simulating=False)
    with pytest.raises(launch.LaunchError, match="org.example/test/Extra/v1 is not in the pinned"):
        async with launch.attached("ur5e", f"127.0.0.1:{port}"):
            pytest.fail("the connector was handed out")


def test_only_a_connector_with_a_real_run_has_an_instrument_address():
    assert launch.address("opentrons-flex", "10.0.0.5") == ("10.0.0.5", 50051)
    assert launch.address("opentrons-flex", "flex.local:50052") == ("flex.local", 50052)
    with pytest.raises(launch.LaunchError, match="host\\[:port\\]"):
        launch.address("opentrons-flex", "10.0.0.5:http")
    with pytest.raises(launch.LaunchError, match="UR5e arm connector has no real run"):
        launch.address("ur5e", "10.0.0.6")


def test_a_real_run_names_every_instrument_of_the_plan(flex_plan):
    assert runner.instruments(flex_plan, ["flex=10.0.0.5"]) == {"flex": "10.0.0.5"}
    with pytest.raises(launch.LaunchError, match="Give the address of flex's connector"):
        runner.instruments(flex_plan, [])
    with pytest.raises(launch.LaunchError, match="device=host"):
        runner.instruments(flex_plan, ["reader=10.0.0.5"])


async def test_an_instrument_takes_a_plan_only_after_it_passed_in_simulation(flex_plan):
    where = {"flex": f"127.0.0.1:{launch.free_port()}"}
    for rehearsal in (
        None,
        {**passed(flex_plan), "outcome": "failed"},
        {**passed(flex_plan), "plan_digest": "0" * 64},
        {**passed(flex_plan), "evidence": runner.INSTRUMENT},
    ):
        with pytest.raises(launch.LaunchError, match="only after that plan passed in simulation"):
            await runner.run_real(flex_plan, where, rehearsal)
    with pytest.raises(launch.LaunchError, match="No Opentrons Flex connector answers"):
        await runner.run_real(flex_plan, where, passed(flex_plan))


async def test_a_real_run_stops_at_a_connector_that_is_not_the_instrument(standing, flex_plan):
    _, port = await standing(simulating=False)
    # Something answers there, but not a Flex: it cannot say whether it simulates.
    with pytest.raises(launch.LaunchError, match="cannot be shown to be driving an instrument"):
        await runner.run_real(flex_plan, {"flex": f"127.0.0.1:{port}"}, passed(flex_plan))


def test_the_command_line_sends_nothing_without_a_simulation(flex_plan, tmp_path, capsys):
    from academy_sim_real import cli

    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(flex_plan))
    assert cli.main(["run", str(plan), "--real", "flex=10.0.0.5"]) == 2
    assert "No installation given for the opentrons-flex connector" in capsys.readouterr().err
    assert cli.main(["run", str(plan), "--real", "arm=10.0.0.5"]) == 2


async def test_an_instrument_is_not_told_about_a_simulated_scene(flex_plan):
    sent = []

    class Flex:
        key = "opentrons-flex"

        async def read(self, feature, name):
            return {"Valid": True, "OccupiedLocations": []}

        async def execute(self, feature, command, arguments):
            sent.append(command)
            return {}

    scene = {**flex_plan["steps"][0], "id": "scene", "simulation_only": True}
    plan = {**flex_plan, "steps": [scene, *flex_plan["steps"]]}
    for simulated, commands in ((False, ["SetTemperature"]), (True, ["SetTemperature"] * 2)):
        sent.clear()
        report = runner._report(plan, runner.INSTRUMENT)
        await runner._steps(plan, {"flex": Flex()}, report, simulated=simulated)
        assert sent == commands and report["outcome"] == "passed"
        assert [s["status"] for s in report["steps"]] == [
            "done" if simulated else "skipped",
            "done",
        ]
