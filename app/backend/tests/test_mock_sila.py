"""Exercise the exported bundle across actual loopback SiLA gRPC calls."""

import json
import socket
import subprocess
import sys
from copy import deepcopy
from uuid import uuid4

import pytest

pytest.importorskip("sila2")

from academy.mock_contract import execute_mock  # noqa: E402
from academy.mock_sila import ERRORS, FIELDS, call, run_workflow, serve, signatures  # noqa: E402
from academy.simple_twins import TEMPLATES, connector_package, sila_feature  # noqa: E402
from sila2.client import SilaClient  # noqa: E402
from sila2.framework import Feature  # noqa: E402
from sila2.framework.errors.defined_execution_error import DefinedExecutionError  # noqa: E402
from sila2.framework.errors.validation_error import ValidationError  # noqa: E402


def connect(endpoint):
    return SilaClient("127.0.0.1", endpoint["port"], root_certs=endpoint["ca"].encode())


def workcell():
    twins = [
        {"id": str(uuid4()), "confirmed": True, "mode": "mock", "spec": deepcopy(TEMPLATES[key])}
        for key in ("liquid-handler", "heater", "reader", "transfer-arm")
    ]
    handler, heater, reader, arm = [t["id"] for t in twins]

    def step(device_id, operation, value=1, source_id=None, target_id=None):
        return dict(
            device_id=device_id,
            operation=operation,
            value=value,
            source_id=source_id,
            target_id=target_id,
        )

    steps = [
        step(handler, "load", 150),
        step(handler, "mix", 5),
        step(arm, "transfer", source_id=handler, target_id=heater),
        step(heater, "heat", 42),
        step(arm, "transfer", source_id=heater, target_id=reader),
        step(reader, "read"),
    ]
    package = connector_package(twins[0], {"twins": twins, "steps": steps})
    return package, json.loads(package["files"]["workspace.json"])


def port_range(count):
    # Reserve a candidate range for the duration of selection; servers then bind it.
    for base in range(52000, 62000, count):
        sockets = []
        try:
            for i in range(count):
                sock = socket.socket()
                sockets.append(sock)
                sock.bind(("127.0.0.1", base + i))
            return base
        except OSError:
            continue
        finally:
            for sock in sockets:
                sock.close()
    raise RuntimeError("No free local test port range")


def test_every_template_feature_is_a_valid_sila_definition_of_its_operations():
    for spec in TEMPLATES.values():
        xml = sila_feature({"spec": spec})
        feature = Feature(xml)  # validates against the SiLA 2 FeatureDefinition.xsd
        commands = signatures(xml)
        # One command per operation the instrument offers, each parameter a step field.
        assert list(commands) == [o.capitalize() for o in spec["operations"]]
        assert all(name in FIELDS for names in commands.values() for name in names)
        assert set(feature._observable_commands) == set(commands) & {
            "Transfer",
            "Mix",
            "Heat",
            "Wait",
        }
        assert set(feature.defined_execution_errors) <= {name for name, _ in ERRORS.values()}


def test_network_workflow_matches_web_contract_and_properties():
    _, manifest = workcell()
    with serve(manifest, port_range(4)) as (runtime, endpoints):
        run_workflow(manifest, endpoints)
        assert runtime.trace == execute_mock(
            {t["id"]: t for t in manifest["twins"]}, manifest["steps"]
        )
        reader = manifest["twins"][2]["id"]
        endpoint = endpoints[reader]
        with connect(endpoint) as client:
            feature = getattr(client, endpoint["feature"])
            assert feature.SampleLoaded.get() is True
            assert feature.TemperatureC.get() == 42
            assert feature.VolumeMicroliters.get() == 150
            readout = feature.Read(Sample="sample")
            assert (readout.TemperatureC, readout.VolumeMicroliters, readout.Mixed) == (
                42,
                150,
                True,
            )
        # Startup, discovery and execution create no physical adapter.
        assert len(runtime.steps) == 7


def test_refusals_are_defined_errors_and_leave_state_and_consumables_unchanged():
    _, manifest = workcell()
    manifest["steps"] = manifest["steps"][:2]
    with serve(manifest, port_range(4)) as (runtime, endpoints):
        run_workflow(manifest, endpoints)
        before = deepcopy(runtime.trace)
        heater = manifest["twins"][1]["id"]
        endpoint = endpoints[heater]
        xml = manifest["features"][heater]["xml"]
        heat = {"device_id": heater, "operation": "heat", "value": 37}
        with connect(endpoint) as client:
            with pytest.raises(DefinedExecutionError, match="transfer the sample") as refusal:
                call(client, endpoint, xml, heat)
            assert refusal.value.identifier == "InvalidState"
            # The feature carries the heater's own limits; SiLA refuses the value itself.
            limit = manifest["twins"][1]["spec"]["limits"]["max_temp_c"]
            with pytest.raises(ValidationError):
                call(client, endpoint, xml, {**heat, "value": limit + 1})
            with pytest.raises(ValueError, match="has no Mix command"):
                call(client, endpoint, xml, {**heat, "operation": "mix"})
        assert runtime.trace == before and len(runtime.steps) == 2


def test_exported_bundle_runs_outside_the_repository(tmp_path):
    package, _ = workcell()
    for name, text in package["files"].items():
        (tmp_path / name).write_text(text)
    result = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "mock_sila.py"),
            str(tmp_path / "workspace.json"),
            "--run",
            "--port",
            str(port_range(4)),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["transport"] == "sila2_grpc"
    assert receipt["evidence"] == "synthetic"
    assert receipt["trace"][-1]["measurement"] == {
        "kind": "synthetic_state_readout",
        "temperature_c": 42,
        "volume_ul": 150,
        "mixed": True,
    }
