"""Instrument connectors Sim–Real can run in simulation, and what is pinned about each.

A binding is one connector release as it described itself: `connectors/<key>/manifest.json`
lists the SiLA features a running connector returned, with the SHA-256 of each Feature
Definition, next to the definitions themselves. `ops/sim-real` writes these files from a
live connector; nothing here is typed by hand except the profile, which says how to start
the connector in simulation and how to tell that it is simulating.
"""

import json
from functools import cache
from pathlib import Path

from . import fdl

ROOT = Path(__file__).with_name("connectors")
SCHEMA = "simreal.connector/1"
SBS_WIDTH_MM = 85.48  # an SBS/ANSI microplate across its long sides
SBS_LENGTH_MM = 127.76

FLEX_MODULES = (
    "heater_shaker",
    "flex_stacker",
    "absorbance_reader",
    "temperature_module",
    "thermocycler",
    "gripper",
)
FLEX_SLOTS = [f"{row}{column}" for row in "ABCD" for column in "123"]

PROFILES = {
    "opentrons-flex": {
        "name": "Opentrons Flex",
        "kind": "liquid-handler",
        "repository": "SissiFeng/otflex-asms",
        "package": "unitelabs-opentrons-flex",
        "library": [("chemlab", "opentrons_flex_single_5_1000ul")],
        # How the connector's own simulator is started and recognised. The Flex chooses its
        # backend at startup, so there is no SiLA command to switch it.
        "argv": [
            "{bin}/connector",
            "start",
            "--app",
            "unitelabs.opentrons_flex:create_app",
            "-cfg",
            "{config}",
        ],
        "simulating": {
            "feature": "ca.accelerationconsortium/robots/MotionController/v2",
            "property": "IsSimulating",
        },
        "simulator": "Opentrons 9.0.0 OT3 hardware simulator and module simulators",
        "startup_seconds": 90,
    },
    "ur5e": {
        "name": "UR5e arm",
        "kind": "arm",
        "repository": "AccelerationConsortium/ur5e-sila-connector",
        "package": "unitelabs-ur5e-connector",
        "library": [("workcell", "ur5e-2f140")],
        "argv": ["{python}", "-m", "unitelabs.ur5e_connector", "--config-path", "{config}"],
        "simulating": {
            "feature": "org.silastandard/core/SimulationController/v1",
            "property": "SimulationMode",
        },
        "simulator": "Connector's kinematic joint interpolation and simulated plate gripper",
        "startup_seconds": 30,
        # Joint pose (degrees) the connector's simulator starts in.
        "start_degrees": [0.0, -85.9437, -85.9437, 0.0, 85.9437, 0.0],
    },
}


class BindingError(ValueError):
    """A connector binding is missing, or a workflow asks it for something it cannot do."""


def flex_options(options):
    """Checked simulation options of a Flex: modules, handoff slots, deck ledger, gripper plans."""
    options = options or {}
    unknown = set(options) - {"modules", "handoff", "occupancy", "plans", "module_slots"}
    if unknown:
        raise BindingError(f"Unknown Flex option {sorted(unknown)[0]}")
    modules = list(options.get("modules", []))
    if any(m not in FLEX_MODULES for m in modules) or len(set(modules)) != len(modules):
        raise BindingError(f"Flex modules are {', '.join(FLEX_MODULES)}, each at most once")
    handoff = list(options.get("handoff", []))
    occupancy = dict(options.get("occupancy", {}))
    slots = dict(options.get("module_slots", {}))
    for slot in [*handoff, *occupancy, *slots.values()]:
        if slot not in FLEX_SLOTS:
            raise BindingError(f"The Flex deck has no slot {slot}")
    if len(set(handoff)) != len(handoff):
        raise BindingError("List each handoff slot once")
    if any(m not in modules for m in slots):
        raise BindingError("Give a slot only to a module the Flex carries")
    plans = list(options.get("plans", []))
    if any(not isinstance(p, dict) or not p.get("identifier") for p in plans):
        raise BindingError("Every gripper plan needs an identifier")
    return {
        "modules": modules,
        "handoff": handoff,
        "occupancy": occupancy,
        "plans": plans,
        "module_slots": slots,
    }


def ur5e_options(options):
    options = options or {}
    unknown = set(options) - {"start_degrees"}
    if unknown:
        raise BindingError(f"Unknown UR5e option {sorted(unknown)[0]}")
    start = options.get("start_degrees", PROFILES["ur5e"]["start_degrees"])
    if (
        not isinstance(start, list)
        or len(start) != 6
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in start)
    ):
        raise BindingError("start_degrees is six joint angles in degrees")
    if [round(v, 2) for v in start] != [round(v, 2) for v in PROFILES["ur5e"]["start_degrees"]]:
        # The connector's simulator always starts in its own pose; another one would only
        # make the plan disagree with what the connector then reports.
        raise BindingError("The UR5e simulator starts in its own pose; leave start_degrees out")
    return {"start_degrees": [float(v) for v in start]}


OPTIONS = {"opentrons-flex": flex_options, "ur5e": ur5e_options}


def options(key, raw):
    """The checked simulation options of one device."""
    profile(key)
    return OPTIONS[key](raw)


def launch_files(key, port, name, opts):
    """Configuration files that start a connector in simulation on a loopback port.

    Returned as {file name: JSON content}; `config.json` is the one the connector is given.
    Paths between files are relative names, resolved by the runner into its work directory.
    """
    server = {"hostname": "127.0.0.1", "port": port, "tls": False, "name": name}
    if key == "ur5e":
        return {
            "config.json": {
                "simulation_mode": True,
                "sila_server": server,
                "cloud_server_endpoint": [],
                "discovery": None,
            }
        }
    files = {
        "config.json": {
            "sila_server": server,
            "cloud_server_endpoint": None,
            "discovery": None,
            "use_simulator": True,
            "simulated_modules": opts["modules"],
            "with_robot_server": False,
            # The deck ledger is always on: it is what handoffs and gripper plans update.
            "labware_movement_config": "{workdir}/labware.json",
        },
        "labware.json": {
            "schema_version": 1,
            "state_file": "{workdir}/deck-state.json",
            "initial_occupancy": opts["occupancy"],
            "plans": opts["plans"],
        },
    }
    if opts["handoff"]:
        files["config.json"]["deck_handoff_config"] = "{workdir}/handoff.json"
        files["handoff.json"] = {
            "schema_version": 1,
            "locations": opts["handoff"],
            "ledger_file": None,
        }
    return files


def profile(key):
    found = PROFILES.get(key)
    if found is None:
        raise BindingError(f"No connector binding named {key}")
    return found


@cache
def manifest(key):
    """The pinned description of a connector release, or None before one was imported."""
    profile(key)
    path = ROOT / key / "manifest.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if data.get("schema") != SCHEMA or data.get("key") != key:
        raise BindingError(f"{path} is not a {SCHEMA} manifest for {key}")
    return data


@cache
def features(key):
    """Every pinned feature of a connector, parsed, by fully qualified identifier."""
    pinned = manifest(key)
    if pinned is None:
        raise BindingError(
            f"The {profile(key)['name']} connector has not been imported; run "
            f"`academy-sim-real import {key}`"
        )
    found = {}
    for entry in pinned["features"]:
        xml = (ROOT / key / entry["file"]).read_text()
        if fdl.digest(xml) != entry["sha256"]:
            raise BindingError(f"{entry['file']} no longer matches its pinned digest")
        feature = fdl.parse(xml)
        if feature["id"] != entry["id"]:
            raise BindingError(f"{entry['file']} is {feature['id']}, pinned as {entry['id']}")
        found[feature["id"]] = feature
    return found


def feature(key, name):
    """One feature by fully qualified identifier, or by its bare identifier when unambiguous."""
    found = features(key)
    if name in found:
        return found[name]
    matches = [f for f in found.values() if f["identifier"] == name]
    if len(matches) == 1:
        return matches[0]
    raise BindingError(f"The {profile(key)['name']} connector has no feature {name}")


def for_library(collection, entry):
    """The connector that drives a library instrument, or None when there is none yet."""
    return next(
        (key for key, p in PROFILES.items() if (collection, entry) in p["library"]),
        None,
    )


def catalog():
    """Every binding with its pinned release and command vocabulary."""
    out = []
    for key, p in PROFILES.items():
        pinned = manifest(key)
        entry = {
            "key": key,
            "name": p["name"],
            "kind": p["kind"],
            "repository": p["repository"],
            "simulator": p["simulator"],
            "library": [{"collection": c, "id": i} for c, i in p["library"]],
            "imported": pinned is not None,
        }
        if pinned:
            entry.update(
                {k: pinned[k] for k in ("source", "package_version", "server", "imported_at")}
            )
            entry["features"] = [
                {
                    "id": f["id"],
                    "identifier": f["identifier"],
                    "sha256": f["sha256"],
                    "commands": [
                        {
                            "name": name,
                            "observable": c["observable"],
                            "parameters": [
                                {"name": q["name"], "type": fdl.summary(q["type"], f["types"])}
                                for q in c["parameters"]
                            ],
                            "errors": c["errors"],
                        }
                        for name, c in f["commands"].items()
                    ],
                    "properties": sorted(f["properties"]),
                }
                for f in features(key).values()
            ]
        out.append(entry)
    return out
