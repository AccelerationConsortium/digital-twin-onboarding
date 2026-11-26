"""Compile a Sim–Real workflow into the exact SiLA calls its connectors will receive.

A workflow names devices from the instrument library, where the plates start, and steps.
A step is either one command of a connector, written in the connector's own vocabulary
(feature, command, parameters), or a plate transfer by the arm. Compiling checks every
command against the connector's pinned Feature Definition, plans every transfer on the
bench layout and cuts it into waypoint chains with gripper and ledger commands, and then
runs the whole plan through the world model. The result is a plan a runner can send to
connectors one command at a time, with what the world should look like after each.
"""

import hashlib
import json
import math
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .. import workcell_layout as bench
from ..library import COLLECTIONS
from ..mock_contract import PlanError
from ..models import StrictModel
from ..simple_twins import Bench
from . import bindings, fdl, motion, world

WORKFLOW = "simreal.workflow/1"
PLAN = "simreal.plan/1"
EVIDENCE = "simulation"
MAX_TRANSFERS = 12  # in a workflow's steps; cycles repeat them
# Across all cycles. A run's kept report has a line for each, and has to fit one stored item.
MAX_COMMANDS = 1200

Id = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,23}$")]
LabwareId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")]
SiteKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9-]{0,8}$")]

FLEX = "opentrons-flex"
UR5E = "ur5e"
ROBOT = "io.unitelabs/robot/RobotController/v1"
GRIPPER = "io.unitelabs/robot/PlateGripperController/v1"
HANDOFF = "ca.accelerationconsortium/robots/DeckHandoffController/v1"
MOVEMENT = "ca.accelerationconsortium/robots/LabwareMovementController/v1"
SHAKER = "ca.accelerationconsortium/modules/HeaterShakerController/v3"

# Arm commands a workflow may not send itself: they move the arm in ways the plan does
# not track, or leave simulation. Transfers issue the motion commands they need.
REFUSED = {
    (UR5E, "SimulationController"): "Sim–Real never switches a connector out of simulation",
    (UR5E, "RobotController"): "The arm moves through transfer steps, which plan its path",
    (UR5E, "PlateGripperController"): "The gripper acts inside transfer steps",
}


class LibraryRef(StrictModel):
    collection: str = Field(min_length=1, max_length=20)
    id: str = Field(min_length=1, max_length=80)


class Device(StrictModel):
    id: Id
    library: LibraryRef
    # The connector that drives it; left out, the one bound to the library entry, if any.
    connector: str | None = None
    options: dict = {}


class Placement(StrictModel):
    device: Id
    x: float = Field(ge=-2, le=2)
    z: float = Field(ge=-1.5, le=1.5)
    yaw: float = Field(ge=-180, le=180)
    access: Literal["top", "front"] = "top"


class Layout(StrictModel):
    bench: Bench
    placements: list[Placement] = Field(max_length=12)


class Labware(StrictModel):
    id: LabwareId
    device: Id
    site: SiteKey = ""
    # Across the gripper fingers; an SBS plate gripped on its long sides.
    width_mm: float = Field(default=bindings.SBS_WIDTH_MM, ge=60, le=140)


class Place(StrictModel):
    device: Id
    site: SiteKey = ""


class Transfer(StrictModel):
    id: Id
    kind: Literal["transfer"]
    arm: Id
    labware: LabwareId
    to: Place
    speed: float = Field(default=20, ge=1, le=40)
    force_newtons: float = Field(default=20, ge=5, le=60)


class Command(StrictModel):
    id: Id
    kind: Literal["command"]
    device: Id
    feature: str = Field(min_length=1, max_length=200)
    command: str = Field(min_length=1, max_length=100)
    parameters: dict = {}


class Workflow(StrictModel):
    # `schema` shadows a pydantic attribute, so the wire name is an alias.
    format: Literal["simreal.workflow/1"] = Field(alias="schema")
    name: str = Field(min_length=1, max_length=80)
    devices: list[Device] = Field(min_length=1, max_length=12)
    layout: Layout
    labware: list[Labware] = Field(max_length=24)
    steps: list[Annotated[Transfer | Command, Field(discriminator="kind")]] = Field(
        min_length=1, max_length=64
    )
    cycles: int = Field(default=1, ge=1, le=50)

    @model_validator(mode="after")
    def unique(self):
        for label, ids in (
            ("device", [d.id for d in self.devices]),
            ("labware", [item.id for item in self.labware]),
            ("step", [s.id for s in self.steps]),
            ("placement", [p.device for p in self.layout.placements]),
        ):
            if len(set(ids)) != len(ids):
                raise ValueError(f"Give every {label} its own id")
        return self


def _devices(workflow):
    """Resolved devices: library spec, connector binding and checked options."""
    found = {}
    for device in workflow.devices:
        entry = COLLECTIONS.get(device.library.collection, {}).get(device.library.id)
        if entry is None:
            raise bindings.BindingError(
                f"Unknown library entry {device.library.collection}:{device.library.id}"
            )
        bound = bindings.for_library(device.library.collection, device.library.id)
        connector = device.connector or bound
        if connector and connector != bound:
            raise bindings.BindingError(
                f"The {connector} connector does not drive {entry['spec']['name']}"
            )
        if device.options and not connector:
            raise bindings.BindingError(f"{device.id} has no connector to take options")
        found[device.id] = {
            "id": device.id,
            "name": entry["spec"]["name"],
            "library": device.library.model_dump(),
            "connector": connector,
            "spec": deepcopy(entry["spec"]),
            "sites": [s["key"] for s in entry["spec"].get("sites", [])],
            "options": bindings.options(connector, device.options) if connector else {},
        }
    return found


def _pinned(devices):
    """The connector releases a plan was compiled against."""
    pinned = {}
    for key in sorted({d["connector"] for d in devices.values() if d["connector"]}):
        manifest = bindings.manifest(key)
        if manifest is None:
            raise bindings.BindingError(
                f"The {bindings.profile(key)['name']} connector has not been imported"
            )
        pinned[key] = {
            "package": manifest["package"],
            "package_version": manifest["package_version"],
            "source": manifest["source"],
            "features": {f["id"]: f["sha256"] for f in manifest["features"]},
        }
    return pinned


def _effects(device, feature, command, arguments):
    """What a workflow's own command does to the world; unknown commands change nothing."""
    key, options = device["connector"], device["options"]
    if (
        key == FLEX
        and feature["id"] == HANDOFF
        and command in ("RegisterLabware", "ReleaseLabware")
    ):
        return [
            {
                "do": "ledger_add" if command == "RegisterLabware" else "ledger_remove",
                "device": device["id"],
                "site": arguments["LocationIdentifier"],
                "labware": arguments["LabwareIdentifier"],
            }
        ]
    if key == FLEX and feature["id"] == MOVEMENT and command == "MoveLabware":
        plan = next(
            (p for p in options["plans"] if p["identifier"] == arguments["PlanIdentifier"]), None
        )
        if plan is None:
            raise world.WorldError(
                "state",
                f"{device['name']} has no gripper plan {arguments['PlanIdentifier']}; "
                "list it in the device's plans",
            )
        return [
            {
                "do": "move",
                "device": device["id"],
                "labware": plan["labware_identifier"],
                "source": plan["source"]["identifier"],
                "target": plan["destination"]["identifier"],
            }
        ]
    if key == FLEX and feature["id"] == SHAKER:
        flags = {
            "OpenLatch": [("latch", "open")],
            "CloseLatch": [("latch", "closed")],
            "SetSpeed": [("shaking", True)],
            "StopShaking": [("shaking", False)],
        }.get(command, [])
        # The Heater-Shaker refuses to shake with its latch not closed and to open the
        # latch while shaking; Opentrons' module simulator accepts both, so the world
        # keeps the rule.
        rules = {
            "SetSpeed": {
                "name": "latch",
                "value": "closed",
                "message": f"{device['name']}: close the Heater-Shaker latch before shaking",
            },
            "OpenLatch": {
                "name": "shaking",
                "value": False,
                "unset_ok": True,
                "message": f"{device['name']}: stop shaking before opening the Heater-Shaker latch",
            },
        }
        required = (
            [{"do": "require", "device": device["id"], **rules[command]}]
            if command in rules
            else []
        )
        return required + [
            {"do": "flag", "device": device["id"], "name": name, "value": value}
            for name, value in flags
        ]
    return []


def _motion_steps(prefix, arm, chain, speed):
    """Prepare and run one waypoint chain; the arm is where the chain ends afterwards."""
    prepare = f"{prefix}.{chain['name']}.prepare"
    return [
        {
            "id": prepare,
            "device": arm,
            "feature": ROBOT,
            "command": "PrepareActionChainAtSpeed",
            "arguments": {
                "WaypointsJson": json.dumps(chain["waypoints"], separators=(",", ":")),
                "Speed": speed,
                "ExpectedSimulationMode": True,
            },
            "effects": [],
        },
        {
            "id": f"{prefix}.{chain['name']}.run",
            "device": arm,
            "feature": ROBOT,
            "command": "RunContinuousMotion",
            "arguments": {
                "PlanId": {"$response": prepare, "path": ["Plan", "id"]},
                "RequestId": {"$uuid": True},
                "ExpectedSimulationMode": True,
                "ExpiresAtUnixSeconds": {"$expires_in": 20},
                "RemoteControlConfirmed": False,
            },
            "effects": [
                {
                    "do": "arm_move",
                    "arm": arm,
                    "degrees": chain["end_degrees"],
                    "at": chain["at"],
                    "seconds": chain["seconds"],
                }
            ],
        },
    ]


def _site(device, site, label):
    """The slot a transfer uses on a device; a device without drawn slots has one."""
    if device["sites"]:
        if site not in device["sites"]:
            raise world.WorldError(
                "resource",
                f"{label}: {device['name']} has no slot {site or '(none given)'}",
            )
        return site
    if site:
        raise world.WorldError("resource", f"{label}: {device['name']} has no named slots")
    return ""


def _transfer(step, prefix, devices, twins, layout, state, cache):
    """The commands of one plate transfer, from the current world state."""
    label = f"Step {step.id}"
    arm = devices.get(step.arm)
    if arm is None or arm["connector"] != UR5E:
        raise world.WorldError("state", f"{label}: {step.arm} is not an arm with a connector")
    plate = state["labware"].get(step.labware)
    if plate is None:
        raise world.WorldError("state", f"{label}: there is no plate {step.labware}")
    if plate["site"] == world.GRIPPER:
        raise world.WorldError("state", f"{label}: {step.labware} is already in a gripper")
    target_device = devices.get(step.to.device)
    if target_device is None:
        raise world.WorldError("state", f"{label}: unknown device {step.to.device}")
    source = (plate["device"], plate["site"])
    target = (step.to.device, _site(target_device, step.to.site, label))
    if source == target:
        raise world.WorldError("state", f"{label}: {step.labware} is already there")
    for device in (devices[source[0]], target_device):
        if "transfer" in device["spec"]["operations"]:
            raise world.WorldError("state", f"{label}: a plate cannot rest on {device['name']}")
    # What the world would refuse anyway is said before a path is searched for.
    other = next(
        (
            k
            for k, v in state["labware"].items()
            if (v["device"], v["site"]) == target and k != step.labware
        ),
        None,
    )
    if other:
        raise world.WorldError(
            "resource",
            f"{label}: slot {target[1]} of {target_device['name']} already holds {other}",
        )
    if state["arms"][step.arm]["holding"]:
        raise world.WorldError("state", f"{label}: {arm['name']} already holds a plate")
    start = state["arms"][step.arm]["degrees"]
    key = (step.arm, source, target, tuple(round(v, 3) for v in start), step.speed)
    if key not in cache:
        cache[key] = motion.plan_transfer(
            twins,
            layout,
            label,
            step.arm,
            (source[0], source[1] or None),
            (target[0], target[1] or None),
            start,
            step.speed,
        )
    planned = cache[key]
    steps = []
    for chain in planned["chains"]:
        chain = {
            **chain,
            "at": chain["at"]
            and {"device": chain["at"]["device"], "site": chain["at"]["site"] or ""},
        }
        steps += _motion_steps(prefix, step.arm, chain, step.speed)
        if chain["name"] == motion.LOWER:
            steps += [
                {
                    "id": f"{prefix}.scene",
                    "device": step.arm,
                    "feature": GRIPPER,
                    "command": "SetSimulatedObject",
                    "arguments": {"WidthMillimeters": plate["width_mm"]},
                    "effects": [],
                    # Tells the simulated fingers what the world put at the grasp point;
                    # a real gripper feels it instead.
                    "simulation_only": True,
                },
                {
                    "id": f"{prefix}.grip",
                    "device": step.arm,
                    "feature": GRIPPER,
                    "command": "GripPlate",
                    "arguments": {
                        "WidthMillimeters": plate["width_mm"],
                        "ForceNewtons": step.force_newtons,
                        "ExpectedSimulationMode": True,
                    },
                    "effects": [{"do": "grip", "arm": step.arm}],
                },
            ]
        if chain["name"] == motion.CARRY:
            if devices[source[0]]["connector"] == FLEX:
                steps.append(
                    {
                        "id": f"{prefix}.release-ledger",
                        "device": source[0],
                        "feature": HANDOFF,
                        "command": "ReleaseLabware",
                        "arguments": {
                            "LocationIdentifier": source[1],
                            "LabwareIdentifier": step.labware,
                            "Destination": step.arm,
                        },
                        "effects": [
                            {
                                "do": "ledger_remove",
                                "device": source[0],
                                "site": source[1],
                                "labware": step.labware,
                            }
                        ],
                    }
                )
            steps.append(
                {
                    "id": f"{prefix}.release",
                    "device": step.arm,
                    "feature": GRIPPER,
                    "command": "ReleasePlate",
                    "arguments": {
                        "OpeningMillimeters": min(140.0, round(plate["width_mm"] + 30, 2)),
                        "ExpectedSimulationMode": True,
                    },
                    "effects": [{"do": "release", "arm": step.arm}],
                }
            )
    if target_device["connector"] == FLEX:
        steps.append(
            {
                "id": f"{prefix}.register-ledger",
                "device": target[0],
                "feature": HANDOFF,
                "command": "RegisterLabware",
                "arguments": {
                    "LocationIdentifier": target[1],
                    "LabwareIdentifier": step.labware,
                    "Source": step.arm,
                },
                "effects": [
                    {
                        "do": "ledger_add",
                        "device": target[0],
                        "site": target[1],
                        "labware": step.labware,
                    }
                ],
            }
        )
    for item in steps:
        item["source"] = step.id
    return steps, {
        "step": prefix,
        "arm": step.arm,
        "labware": step.labware,
        "from": {"device": source[0], "site": source[1]},
        "to": {"device": target[0], "site": target[1]},
        **{k: planned[k] for k in ("clearance_m", "planner", "simulation", "seconds")},
    }


def _command(step, prefix, devices):
    label = f"Step {step.id}"
    device = devices.get(step.device)
    if device is None:
        raise world.WorldError("state", f"{label}: unknown device {step.device}")
    if not device["connector"]:
        raise world.WorldError(
            "state", f"{label}: {device['name']} has no connector, so it takes no commands"
        )
    feature = bindings.feature(device["connector"], step.feature)
    refused = REFUSED.get((device["connector"], feature["identifier"]))
    if refused:
        raise world.WorldError("state", f"{label}: {refused}")
    problems = fdl.check_arguments(feature, step.command, step.parameters)
    if problems:
        raise world.WorldError("constraint", f"{label}: {problems[0]}")
    return {
        "id": prefix,
        "source": step.id,
        "device": step.device,
        "feature": feature["id"],
        "command": step.command,
        "arguments": step.parameters,
        "effects": _effects(device, feature, step.command, step.parameters),
    }


def _handoff(workflow, devices):
    """Every Flex slot the arm touches becomes a handoff slot of that Flex's simulation."""
    where = {item.id: (item.device, item.site) for item in workflow.labware}
    for step in workflow.steps:
        if step.kind != "transfer" or step.labware not in where:
            continue
        for device, site in (where[step.labware], (step.to.device, step.to.site)):
            found = devices.get(device)
            if found and found["connector"] == FLEX and site in found["sites"]:
                if site not in found["options"]["handoff"]:
                    found["options"]["handoff"].append(site)
        where[step.labware] = (step.to.device, step.to.site)


def _layout(workflow, devices):
    placed = {p.device for p in workflow.layout.placements}
    for device in placed - set(devices):
        raise bindings.BindingError(f"The layout places an unknown device {device}")
    return {
        "bench": workflow.layout.bench.model_dump(),
        "placements": [
            {
                "twin_id": p.device,
                "x": p.x,
                "z": p.z,
                "yaw": p.yaw,
                "access": p.access,
                "kept": False,
            }
            for p in workflow.layout.placements
        ],
    }


def compile_workflow(workflow):
    """A plan for a workflow, with `problems` naming why it would not run; never raises
    for a workflow that is merely wrong."""
    problems = []

    def fail(step, layer, message):
        problems.append({"step": step, "layer": layer, "message": message})

    try:
        devices = _devices(workflow)
        _handoff(workflow, devices)
        pinned = _pinned(devices)
        layout = _layout(workflow, devices)
    except bindings.BindingError as exc:
        return {
            "schema": PLAN,
            "evidence": EVIDENCE,
            "name": workflow.name,
            "valid": False,
            "problems": [{"step": None, "layer": "state", "message": str(exc)}],
            "steps": [],
            "motions": [],
        }
    names = {key: d["name"] for key, d in devices.items()}
    twins = {
        key: {"id": key, "spec": d["spec"], "confirmed": True, "mode": "mock"}
        for key, d in devices.items()
    }
    labware = [item.model_dump() for item in workflow.labware]
    # The Flex starts with the plates that begin on it already in its deck ledger.
    for item in labware:
        device = devices.get(item["device"])
        if device and device["connector"] == FLEX:
            device["options"]["occupancy"][item["site"]] = item["id"]
    steps, motions, initial, state = [], [], None, None
    try:
        bench.validate_layout(twins, layout)
        initial = world.start(devices, labware)
        state = deepcopy(initial)
        for arm, record in state["arms"].items():
            if arm not in {p["twin_id"] for p in layout["placements"]}:
                raise world.WorldError("geometry", f"Place {names[arm]} on the bench")
            planner = bench.Planner(twins, layout, twins[arm])
            gap, link, obstacle = planner.measure([math.radians(v) for v in record["degrees"]])
            if gap < bench.SAFETY:
                raise world.WorldError(
                    "geometry",
                    f"{names[arm]} starts its simulation with its {link} inside {obstacle}. "
                    "Turn or move the arm on the bench.",
                )
    except (PlanError, world.WorldError) as exc:
        fail(None, exc.layer, str(exc))
    if not problems and sum(s.kind == "transfer" for s in workflow.steps) > MAX_TRANSFERS:
        fail(
            None,
            "constraint",
            f"A workflow's steps hold at most {MAX_TRANSFERS} transfers; cycles repeat them",
        )
    cache = {}
    if not problems:
        for cycle in range(1, workflow.cycles + 1):
            for step in workflow.steps:
                prefix = step.id if workflow.cycles == 1 else f"c{cycle}.{step.id}"
                try:
                    if step.kind == "transfer":
                        made, measured = _transfer(
                            step, prefix, devices, twins, layout, state, cache
                        )
                        motions.append(measured)
                    else:
                        made = [_command(step, prefix, devices)]
                    for item in made:
                        item["cycle"] = cycle
                        for effect in item["effects"]:
                            world.apply(state, effect, names)
                        item["world"] = world.snapshot(state)
                    steps += made
                    if len(steps) > MAX_COMMANDS:
                        # Said as soon as it is known, before the remaining cycles are planned.
                        steps = steps[:MAX_COMMANDS]
                        fail(
                            None,
                            "constraint",
                            f"{workflow.cycles} cycles of this workflow need more than "
                            f"{MAX_COMMANDS} commands, the most a plan holds. Run fewer cycles.",
                        )
                except bindings.BindingError as exc:
                    fail(step.id, "state", f"Step {step.id}: {exc}")
                except (PlanError, world.WorldError) as exc:
                    fail(step.id, exc.layer, str(exc))
                if problems:
                    break
            if problems:
                break
    plan = {
        "schema": PLAN,
        "evidence": EVIDENCE,
        "name": workflow.name,
        "valid": not problems,
        "problems": problems,
        "cycles": workflow.cycles,
        "devices": [
            {k: d[k] for k in ("id", "name", "library", "connector", "options")}
            for d in devices.values()
        ],
        "connectors": pinned,
        "labware": labware,
        "layout": layout,
        "world": world.snapshot(initial) if initial else None,
        "steps": steps,
        "motions": motions,
        # What this plan does not establish.
        "limits": [
            "Arm paths use nominal UR5e kinematics, capsule links and box instruments; "
            "no calibration.",
            "The plate gripper is simulated; no gripper hardware is chosen.",
            "The world model tracks plate custody, not liquids or chemistry.",
        ],
    }
    plan["digest"] = digest(plan)
    return plan


def _canonical(value):
    """JSON data with whole numbers as integers.

    A plan travels through browsers and files, where 20.0 comes back as 20; its identity
    must not depend on which of the two a parser chose.
    """
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def digest(plan):
    """The identity of a plan: what is sent, to which pinned connectors, from which start."""
    core = {
        "schema": plan["schema"],
        "devices": plan.get("devices"),
        "connectors": plan.get("connectors"),
        "labware": plan.get("labware"),
        "layout": plan.get("layout"),
        "steps": [
            {k: s[k] for k in ("id", "device", "feature", "command", "arguments", "effects")}
            for s in plan["steps"]
        ],
    }
    text = json.dumps(_canonical(core), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def example():
    """A small cell that compiles: a plate goes from the Flex to a plate reader and back."""
    return {
        "schema": WORKFLOW,
        "name": "Flex to plate reader and back",
        "devices": [
            {
                "id": "flex",
                "library": {"collection": "chemlab", "id": "opentrons_flex_single_5_1000ul"},
                "options": {"modules": ["heater_shaker"]},
            },
            {"id": "reader", "library": {"collection": "chemlab", "id": "bmg_clariostarplus"}},
            {"id": "arm", "library": {"collection": "workcell", "id": "ur5e-2f140"}},
        ],
        "layout": {
            "bench": {"width": 2.4, "depth": 1.6},
            "placements": [
                {"device": "arm", "x": 0.0, "z": 0.0, "yaw": 180},
                {"device": "flex", "x": 0.79, "z": 0.21, "yaw": -90},
                {"device": "reader", "x": -0.7, "z": 0.21, "yaw": 90, "access": "front"},
            ],
        },
        "labware": [{"id": "assay-plate", "device": "flex", "site": "D1"}],
        "steps": [
            {
                "id": "warm",
                "kind": "command",
                "device": "flex",
                "feature": "HeaterShakerController",
                "command": "SetTemperature",
                "parameters": {"Temperature": 37.0},
            },
            {
                "id": "to-reader",
                "kind": "transfer",
                "arm": "arm",
                "labware": "assay-plate",
                "to": {"device": "reader"},
            },
            {
                "id": "to-flex",
                "kind": "transfer",
                "arm": "arm",
                "labware": "assay-plate",
                "to": {"device": "flex", "site": "D1"},
            },
            {
                "id": "cool",
                "kind": "command",
                "device": "flex",
                "feature": "HeaterShakerController",
                "command": "DeactivateHeater",
                "parameters": {},
            },
        ],
        "cycles": 1,
    }
