"""Loopback-only SiLA 2 servers for exported teaching workcells.

Each device is one SiLA Server with its own Feature Definition, TLS certificate and
Defined Execution Errors; parameter constraints are checked by the SiLA framework.

Run the exported bundle with: python mock_sila.py workspace.json --run
No SDK is imported by the web application or Lambda.
"""

import argparse
import json
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID
from xml.etree import ElementTree as ET

if __package__:
    from .mock_contract import PlanError, execute_mock
else:
    from mock_contract import PlanError, execute_mock

# SiLA parameter -> field of a teaching step.
FIELDS = {
    "Sample": "sample",
    "VolumeMicroliters": "value",
    "DurationSeconds": "value",
    "TargetTemperature": "value",
    "Site": "site",
    "SourceStation": "source_id",
    "TargetStation": "target_id",
    "SourceSite": "source_site",
    "TargetSite": "target_site",
}
# Refusal layer of the teaching contract -> Defined Execution Error and its description.
ERRORS = {
    "state": (
        "InvalidState",
        "The workcell state does not allow this command, for example the sample is elsewhere.",
    ),
    "container": ("VesselNotAccepted", "The station does not accept this sample's vessel."),
    "volume": ("VolumeLimitExceeded", "The sample volume exceeds the station's limit."),
    "resource": ("SlotUnavailable", "The requested slot does not exist or is not free."),
    "constraint": (
        "OperatingLimitExceeded",
        "The value is outside the station's operating limits.",
    ),
    "consumable": ("ConsumableDepleted", "A consumable the command uses has run out."),
}
NS = {"s": "http://www.sila-standard.org"}


def signatures(xml):
    """Parameter identifiers of every command in a Feature Definition, in call order."""
    return {
        command.findtext("s:Identifier", namespaces=NS): [
            p.findtext("s:Identifier", namespaces=NS) for p in command.findall("s:Parameter", NS)
        ]
        for command in ET.fromstring(xml).findall("s:Command", NS)
    }


def argument(parameter, step):
    """The value a teaching step gives one SiLA parameter."""
    value = step.get(FIELDS[parameter])
    if FIELDS[parameter] == "value":
        return float(value)
    return str(value or ("sample" if parameter == "Sample" else ""))


def refusal(xml, step):
    """Why SiLA refuses a step before it runs, as (contract layer, reason), else None.

    This is the part of the contract a Feature Definition states by itself: the command
    exists and every parameter is within its constraints. It needs no SiLA SDK.
    """
    name = step["operation"].capitalize()
    command = next(
        (
            c
            for c in ET.fromstring(xml).findall("s:Command", NS)
            if c.findtext("s:Identifier", namespaces=NS) == name
        ),
        None,
    )
    if command is None:
        return "state", f"has no {name} command"
    for parameter in command.findall("s:Parameter", NS):
        identifier = parameter.findtext("s:Identifier", namespaces=NS)
        rules = parameter.find(".//s:Constraints", NS)
        value = argument(identifier, step)
        pattern = rules.findtext("s:Pattern", namespaces=NS)
        if pattern:
            if not re.fullmatch(pattern, value):
                layer = "resource" if identifier.endswith("Site") else "state"
                return layer, f"accepts a {name} {identifier} matching {pattern}"
            continue
        low = float(rules.findtext("s:MinimalInclusive", namespaces=NS))
        high = float(rules.findtext("s:MaximalInclusive", namespaces=NS))
        if not low <= value <= high:
            unit = rules.findtext("s:Unit/s:Label", namespaces=NS)
            layer = "volume" if identifier.startswith("Volume") else "constraint"
            return layer, f"accepts a {name} {identifier} of {low:g}–{high:g} {unit}"
    return None


class MockWorkcell:
    """Samples and one serialized command history shared by all device servers."""

    def __init__(self, twins):
        self.twins = {t["id"]: t for t in twins}
        self.steps = []
        self.trace = []
        self.lock = threading.RLock()

    def command(self, device_id, operation, params):
        step = {
            "device_id": device_id,
            "operation": operation,
            "source_id": None,
            "target_id": None,
            "value": 1,
            **{FIELDS[name]: value for name, value in params.items()},
        }
        if operation == "transfer" and step["source_id"] == step["target_id"]:
            raise PlanError("state", "A transfer requires different stations")
        with self.lock:
            if len(self.steps) >= 48:
                raise PlanError("state", "This teaching run supports at most 48 commands")
            steps = [*self.steps, step]
            trace = execute_mock(self.twins, steps)
            # Failed commands never consume resources or alter the command history.
            self.steps, self.trace = steps, trace
            return trace[-1]

    def property(self, device_id, name, consumables):
        with self.lock:
            state = self.trace[-1] if self.trace else {}
            # The first sample on this device, in load order.
            here = next(
                (s for s in state.get("samples", {}).values() if s["location"] == device_id),
                None,
            )
            if name == "SampleLoaded":
                return here is not None
            if name == "TemperatureC":
                return float(here["temperature_c"]) if here else 20.0
            if name == "VolumeMicroliters":
                return float(here["volume_ul"]) if here else 0.0
            item = consumables[name]
            return state.get("consumables", {}).get(device_id, {}).get(item["name"], item["stock"])


@contextmanager
def serve(manifest, port=50520, discovery=False):
    """Start one TLS SiLA Server per device, backed exclusively by synthetic state."""
    from sila2.framework import Feature
    from sila2.framework.errors.defined_execution_error import DefinedExecutionError
    from sila2.framework.errors.undefined_execution_error import UndefinedExecutionError
    from sila2.server import FeatureImplementationBase, SilaServer
    from sila2.server.encryption import generate_self_signed_certificate

    twins = manifest["twins"]
    if not 1 <= len(twins) <= 12 or not 1024 <= port <= 65535 - len(twins):
        raise ValueError("Choose 1–12 devices and an unprivileged port range")
    runtime = MockWorkcell(twins)
    servers = []
    endpoints = {}
    try:
        for index, twin in enumerate(twins):
            server = SilaServer(
                server_name=twin["spec"]["name"],
                server_type="AcademySyntheticTwin",
                server_description="Loopback teaching mock. No physical hardware.",
                server_version="1.0",
                server_vendor_url="https://github.com/AccelerationConsortium/digital-twin-onboarding",
                server_uuid=twin["id"],
                max_grpc_workers=2,
                max_child_task_workers=2,
            )
            implementation = FeatureImplementationBase(server)
            identifier = manifest["features"][twin["id"]]["identifier"]
            xml = manifest["features"][twin["id"]]["xml"]
            # Loading the definition validates it against the SiLA 2 FeatureDefinition.xsd.
            feature = Feature(xml)

            def command(operation, names, twin_id, feature):
                # Observable commands also receive the execution `instance`.
                def call(*args, metadata=None, instance=None):
                    if instance:
                        instance.begin_execution()
                    try:
                        entry = runtime.command(
                            twin_id, operation, dict(zip(names, args, strict=True))
                        )
                    except PlanError as exc:
                        node = feature.defined_execution_errors.get(
                            ERRORS.get(exc.layer, [None])[0]
                        )
                        if node is None:
                            raise UndefinedExecutionError(str(exc)) from exc
                        raise DefinedExecutionError(node, str(exc)) from exc
                    if operation == "read":
                        readout = entry["measurement"]
                        return (
                            float(readout["temperature_c"]),
                            float(readout["volume_ul"]),
                            readout["mixed"],
                        )
                    return None

                return call

            for name, names in signatures(xml).items():
                setattr(implementation, name, command(name.lower(), names, twin["id"], feature))
            items = {
                f"Consumable{i + 1}Remaining": c for i, c in enumerate(twin["spec"]["consumables"])
            }

            def getter(name, twin_id, consumables):
                return lambda metadata=None: runtime.property(twin_id, name, consumables)

            for name in ("SampleLoaded", "TemperatureC", "VolumeMicroliters", *items):
                setattr(implementation, f"get_{name}", getter(name, twin["id"], items))
            server.set_feature_implementation(feature, implementation)
            # An untrusted certificate carrying the server UUID, as SiLA asks of a server
            # without a CA-issued one; discovery announces it so clients can trust it.
            key, certificate = generate_self_signed_certificate(UUID(twin["id"]), "127.0.0.1")
            server.start(
                "127.0.0.1",
                port + index,
                private_key=key,
                cert_chain=certificate,
                ca_for_discovery=certificate,
                enable_discovery=discovery,
            )
            servers.append(server)
            endpoints[twin["id"]] = {
                "port": port + index,
                "feature": identifier,
                "ca": certificate.decode(),
            }
        yield runtime, endpoints
    finally:
        for server in reversed(servers):
            server.stop(grace_period=1)


def call(client, endpoint, xml, step, number=1):
    """Send one teaching step as its SiLA command and return the command's responses."""
    name = step["operation"].capitalize()
    names = signatures(xml).get(name)
    if names is None:
        raise ValueError(f"Step {number}: {endpoint['feature']} has no {name} command")

    result = getattr(getattr(client, endpoint["feature"]), name)(
        **{parameter: argument(parameter, step) for parameter in names}
    )
    if hasattr(result, "get_responses"):  # an observable command execution
        while not result.done:
            time.sleep(0.01)
        return result.get_responses()
    return result


def run_workflow(manifest, endpoints):
    from sila2.client import SilaClient

    clients = {}
    try:
        for device_id, endpoint in endpoints.items():
            clients[device_id] = SilaClient(
                "127.0.0.1", endpoint["port"], root_certs=endpoint["ca"].encode()
            )
        for number, step in enumerate(manifest["steps"], 1):
            device_id = step["device_id"]
            call(
                clients[device_id],
                endpoints[device_id],
                manifest["features"][device_id]["xml"],
                step,
                number,
            )
    finally:
        for client in clients.values():
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--port", type=int, default=50520)
    parser.add_argument(
        "--run", action="store_true", help="Run the saved workflow through SiLA gRPC, then stop"
    )
    parser.add_argument(
        "--no-discovery", action="store_true", help="Do not announce the servers over mDNS"
    )
    args = parser.parse_args()
    manifest = json.loads(args.workspace.read_text())
    # A served workcell is discoverable, as SiLA recommends; a one-off run needs no announcement.
    discovery = not args.run and not args.no_discovery
    with serve(manifest, args.port, discovery) as (runtime, endpoints):
        if args.run:
            if not manifest["steps"]:
                raise ValueError("Save a workflow before exporting a runnable workcell")
            run_workflow(manifest, endpoints)
            print(
                json.dumps(
                    {"evidence": "synthetic", "transport": "sila2_grpc", "trace": runtime.trace},
                    indent=2,
                )
            )
        else:
            print(json.dumps({"evidence": "synthetic", "endpoints": endpoints}), flush=True)
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
