"""Where every plate is, across instruments: the state no single connector holds.

Each connector simulates its own instrument. What they share is the labware: a plate the
arm sets down on the Flex is at once in the arm's (now empty) gripper, on a deck slot, and
later in the Flex's own deck ledger. This model keeps the physical place of every plate
and what each ledger records, applies the effect of every command to both, and refuses a
command whose effect the world does not allow. It is bookkeeping, not physics.
"""

import json
from copy import deepcopy

GRIPPER = "gripper"
JOINT_TOLERANCE_DEG = 0.1


class WorldError(ValueError):
    """A command whose effect the world state does not allow."""

    def __init__(self, layer, message):
        super().__init__(message)
        self.layer = layer


def start(devices, labware):
    """The world before any step.

    `devices` maps a device id to {"connector": key or None, "name", "sites": [...],
    "options": {...}}; `labware` is a list of {"id", "width_mm", "device", "site"}.
    """
    world = {
        "labware": {},
        "ledgers": {},
        "arms": {},
        "flags": {},
        "elapsed_s": 0.0,
    }
    for key, device in devices.items():
        if device["connector"] == "opentrons-flex":
            world["ledgers"][key] = {}
            world["flags"][key] = {}
            slot = device["options"].get("module_slots", {}).get("heater_shaker")
            if slot:
                world["flags"][key]["latch_slot"] = slot
        if device["connector"] == "ur5e":
            world["arms"][key] = {
                "holding": None,
                "at": None,
                "degrees": list(device["options"]["start_degrees"]),
            }
    for item in labware:
        device = devices.get(item["device"])
        if device is None:
            raise WorldError("state", f"{item['id']} starts on an unknown device")
        if device["sites"] and item["site"] not in device["sites"]:
            raise WorldError("resource", f"{device['name']} has no slot {item['site']}")
        if _at(world, item["device"], item["site"]):
            raise WorldError(
                "resource", f"Two plates start in slot {item['site']} of {device['name']}"
            )
        world["labware"][item["id"]] = {
            "device": item["device"],
            "site": item["site"],
            "width_mm": item["width_mm"],
        }
        # A plate that starts on an instrument with a deck ledger is already recorded there.
        if item["device"] in world["ledgers"]:
            world["ledgers"][item["device"]][item["site"]] = item["id"]
    return world


def _at(world, device, site):
    """The plate physically at a slot, or None."""
    return next(
        (k for k, v in world["labware"].items() if v["device"] == device and v["site"] == site),
        None,
    )


def _blocked(world, names, device, site):
    """Why a gripper cannot reach into a slot right now, or None."""
    flags = world["flags"].get(device, {})
    if flags.get("latch_slot") == site and flags.get("latch") == "closed":
        return f"the Heater-Shaker latch on {names[device]} slot {site} is closed"
    if flags.get("shaking") and flags.get("latch_slot") == site:
        return f"the Heater-Shaker on {names[device]} slot {site} is shaking"
    return None


def apply(world, effect, names):
    """Advance `world` in place by one effect; raise WorldError when it is not allowed."""
    do = effect["do"]
    if do == "arm_move":
        arm = world["arms"][effect["arm"]]
        arm["degrees"] = list(effect["degrees"])
        arm["at"] = effect.get("at")
        world["elapsed_s"] += effect.get("seconds", 0.0)
    elif do == "grip":
        arm = world["arms"][effect["arm"]]
        if arm["holding"]:
            raise WorldError("state", f"{names[effect['arm']]} already holds {arm['holding']}")
        if not arm["at"]:
            raise WorldError("state", f"{names[effect['arm']]} is not at a grasp point")
        device, site = arm["at"]["device"], arm["at"]["site"]
        plate = _at(world, device, site)
        if plate is None:
            raise WorldError("state", f"No plate is in slot {site} of {names[device]} to grip")
        reason = _blocked(world, names, device, site)
        if reason:
            raise WorldError("state", f"{plate} cannot be gripped: {reason}")
        arm["holding"] = plate
        world["labware"][plate].update(device=effect["arm"], site=GRIPPER)
    elif do == "release":
        arm = world["arms"][effect["arm"]]
        if not arm["holding"]:
            raise WorldError("state", f"{names[effect['arm']]} holds nothing to release")
        if not arm["at"]:
            raise WorldError(
                "state", f"{names[effect['arm']]} would drop {arm['holding']} in mid-air"
            )
        device, site = arm["at"]["device"], arm["at"]["site"]
        other = _at(world, device, site)
        if other:
            raise WorldError("resource", f"Slot {site} of {names[device]} already holds {other}")
        reason = _blocked(world, names, device, site)
        if reason:
            raise WorldError("state", f"{arm['holding']} cannot be set down: {reason}")
        world["labware"][arm["holding"]].update(device=device, site=site)
        arm["holding"] = None
    elif do == "ledger_add":
        ledger = world["ledgers"][effect["device"]]
        site, plate = effect["site"], effect["labware"]
        if site in ledger:
            raise WorldError(
                "resource",
                f"{names[effect['device']]} already records {ledger[site]} in slot {site}",
            )
        if _at(world, effect["device"], site) != plate:
            raise WorldError(
                "state",
                f"{names[effect['device']]} would record {plate} in slot {site}, "
                "but it is not there",
            )
        ledger[site] = plate
    elif do == "ledger_remove":
        ledger = world["ledgers"][effect["device"]]
        site, plate = effect["site"], effect["labware"]
        if ledger.get(site) != plate:
            raise WorldError(
                "state",
                f"{names[effect['device']]} records {ledger.get(site) or 'nothing'} in slot "
                f"{site}, not {plate}",
            )
        if _at(world, effect["device"], site) == plate:
            raise WorldError(
                "state",
                f"{plate} is still in slot {site} of {names[effect['device']]}; "
                "release it from the ledger after it is taken",
            )
        del ledger[site]
    elif do == "move":
        device, plate = effect["device"], effect["labware"]
        source, target = effect["source"], effect["target"]
        ledger = world["ledgers"][device]
        if _at(world, device, source) != plate or ledger.get(source) != plate:
            raise WorldError("state", f"{plate} is not in slot {source} of {names[device]}")
        if _at(world, device, target) or target in ledger:
            raise WorldError("resource", f"Slot {target} of {names[device]} is not free")
        for site in (source, target):
            reason = _blocked(world, names, device, site)
            if reason:
                raise WorldError("state", f"{plate} cannot be moved: {reason}")
        world["labware"][plate]["site"] = target
        del ledger[source]
        ledger[target] = plate
    elif do == "require":
        # A rule of the instrument its simulator does not enforce.
        value = world["flags"].get(effect["device"], {}).get(effect["name"])
        if value != effect["value"] and not (value is None and effect.get("unset_ok")):
            raise WorldError("state", effect["message"])
    elif do == "flag":
        world["flags"].setdefault(effect["device"], {})[effect["name"]] = effect["value"]
    elif do != "none":
        raise WorldError("state", f"Unknown effect {do}")
    return world


def predict(world, steps, names):
    """The world after each step of a plan, and the first step the world refuses.

    Returns (states, problem): one snapshot per accepted step, and None or
    {"step", "layer", "message"} for the step that was refused.
    """
    world = deepcopy(world)
    states = []
    for step in steps:
        try:
            for effect in step.get("effects", []):
                apply(world, effect, names)
        except WorldError as exc:
            return states, {"step": step["id"], "layer": exc.layer, "message": str(exc)}
        states.append(snapshot(world))
    return states, None


def snapshot(world):
    """The part of the world a report keeps after a step."""
    return {
        "labware": {
            k: {"device": v["device"], "site": v["site"]} for k, v in world["labware"].items()
        },
        "ledgers": deepcopy(world["ledgers"]),
        "arms": {
            k: {
                "holding": v["holding"],
                "at": v["at"],
                "degrees": [round(d, 4) for d in v["degrees"]],
            }
            for k, v in world["arms"].items()
        },
        "flags": deepcopy(world["flags"]),
        "elapsed_s": round(world["elapsed_s"], 2),
    }


# --- what a connector reports back, compared with the world ------------------------------

READBACK = {
    "opentrons-flex": [
        ("ca.accelerationconsortium/robots/LabwareMovementController/v1", "DeckState"),
    ],
    "ur5e": [
        ("io.unitelabs/robot/PlateGripperController/v1", "GripperState"),
        ("io.unitelabs/robot/RobotController/v1", "JointPositions"),
    ],
}


# Commands whose response says how long the instrument took; the UR5e simulator runs
# faster than the clock, so its own figure is the duration, not the time waited.
DURATION = {
    ("io.unitelabs/robot/RobotController/v1", "RunContinuousMotion"): ("Receipt", "duration"),
}


def device_seconds(feature, command, response):
    """The duration a connector reported for a command, or None when it reports none."""
    found = DURATION.get((feature, command))
    if not found:
        return None
    try:
        value = json.loads(response[found[0]])[found[1]]
    except (KeyError, TypeError, ValueError):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def expected(world, device, connector):
    """What the world says a connector should report after a step."""
    if connector == "opentrons-flex":
        return {"ledger": dict(sorted(world["ledgers"][device].items()))}
    arm = world["arms"][device]
    return {"holding": arm["holding"] is not None, "degrees": [round(d, 4) for d in arm["degrees"]]}


def observed(connector, readings):
    """A connector's own readings, in the same shape as `expected`.

    `readings` maps (feature, property) to the value a SiLA client read.
    """
    if connector == "opentrons-flex":
        state = readings[READBACK[connector][0]]
        if not state["Valid"]:
            return {"ledger": None}
        return {
            "ledger": dict(
                sorted(
                    (entry["LocationIdentifier"], entry["LabwareIdentifier"])
                    for entry in state["OccupiedLocations"]
                )
            )
        }
    grip, joints = (readings[key] for key in READBACK[connector])
    return {
        "holding": grip == "HOLDING",
        # The connector reports radians.
        "degrees": [round(v * 57.29577951308232, 4) for v in joints],
    }


def differences(device, want, got):
    """Fields where a connector's report departs from the world, as readable lines."""
    found = []
    for key, value in want.items():
        seen = got.get(key)
        if key == "degrees":
            if seen is None or any(
                abs(a - b) > JOINT_TOLERANCE_DEG for a, b in zip(value, seen, strict=True)
            ):
                found.append(
                    {"device": device, "field": "joints", "expected": value, "observed": seen}
                )
        elif seen != value:
            found.append({"device": device, "field": key, "expected": value, "observed": seen})
    return found
