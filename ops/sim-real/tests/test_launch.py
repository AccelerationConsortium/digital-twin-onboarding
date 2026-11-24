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
