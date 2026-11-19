"""Discrete state twin of a teaching workcell: bookkeeping, lookahead and sync.

The twin keeps the mock command contract's samples, slots and consumables and adds what
an executor also reports between steps: which sample each arm's gripper holds, whether
an enclosure door is open, which instruments are still busy, and where every instrument
stands on the bench. It is synthetic bookkeeping, never evidence of physical execution.

A state is plain JSON:

    samples     key -> location, site, vessel, volume_ul, temperature_c, mixed
    stock       device id -> consumable name -> count left
    gripper     arm id -> key of the sample it holds, "" when empty
    doors       enclosed device id -> "closed" | "open"
    busy        device id -> seconds until it is idle
    placements  twin id -> x, z (m) and yaw (°) on the bench
    elapsed_s   synthetic seconds since the run started
"""

from copy import deepcopy

from .mock_contract import PlanError, apply_step, start_state

# Contract layers of a refusal, as the reason a twin gives for blocking a step.
CODES = {
    "consumable": "consumable_empty",
    "volume": "volume_overflow",
    "state": "labware_missing",
    "resource": "slot_conflict",
    "container": "wrong_container",
    "constraint": "outside_limits",
}


class TwinFault(Exception):
    """A step the twin predicts will fail from the state it starts in."""

    def __init__(self, step, code, message):
        super().__init__(message)
        self.step = step
        self.code = code

    def describe(self):
        return {"step": self.step, "code": self.code, "message": str(self)}


def arms(twins):
    return sorted(t["id"] for t in twins.values() if "transfer" in t["spec"]["operations"])


def enclosed(twins):
    """Instruments entered from a side sit behind a door the executor opens per transfer."""
    return sorted(t["id"] for t in twins.values() if t["spec"].get("access") == "front")


def initial(twins, layout):
    """The state a workflow declares before its first step."""
    contract = start_state(twins)
    return {
        "samples": {},
        "stock": contract["stock"],
        "gripper": {arm: "" for arm in arms(twins)},
        "doors": {device: "closed" for device in enclosed(twins)},
        "busy": {t: 0.0 for t in sorted(twins)},
        "placements": {
            p["twin_id"]: {"x": p["x"], "z": p["z"], "yaw": p["yaw"]}
            for p in (layout or {}).get("placements", [])
        },
        "elapsed_s": 0.0,
    }


def _contract(state):
    samples = {
        key: {
            "location": s["location"],
            "site": s["site"],
            "vessel": s["vessel"],
            "volume": s["volume_ul"],
            "temperature": s["temperature_c"],
            "mixed": s["mixed"],
        }
        for key, s in state["samples"].items()
    }
    occupied = {}
    for key, s in samples.items():
        if s["location"] and s["site"]:
            occupied.setdefault(s["location"], {})[s["site"]] = key
    return {
        "samples": samples,
        "occupied": occupied,
        "stock": deepcopy(state["stock"]),
        "elapsed": state["elapsed_s"],
    }


def layout_of(state, layout):
    """The saved layout with every instrument where the state says it stands."""
    if not layout:
        return None
    placements = []
    for p in layout["placements"]:
        at = state["placements"].get(p["twin_id"], {})
        placements.append({**p, **{k: at[k] for k in ("x", "z", "yaw") if k in at}})
    return {**layout, "placements": placements}


def advance(twins, state, step, number):
    """(state after `step`, its contract trace entry); raises TwinFault instead."""
    operation = step["operation"]

    def name(device):
        return twins[device]["spec"]["name"] if device in twins else "an instrument"

    label = f"Step {number}"
    stations = (
        [step["device_id"], step["source_id"], step["target_id"]]
        if operation == "transfer"
        else [step["device_id"]]
    )
    for device in stations:
        if state["busy"].get(device, 0) > 0:
            raise TwinFault(
                number,
                "instrument_busy",
                f"{label}: {name(device)} is busy for {state['busy'][device]:g} s more",
            )
    if operation == "transfer":
        held = state["gripper"].get(step["device_id"])
        if held:
            raise TwinFault(
                number,
                "gripper_holding",
                f"{label}: {name(step['device_id'])}'s gripper already holds {held}",
            )
    elif operation != "load":
        if state["doors"].get(step["device_id"]) == "open":
            raise TwinFault(
                number,
                "door_open",
                f"{label}: {name(step['device_id'])}'s door is open",
            )
        sample = state["samples"].get(step.get("sample") or "sample")
        if operation != "wait" and sample and sample["volume_ul"] <= 0:
            raise TwinFault(
                number,
                "volume_empty",
                f"{label}: {step.get('sample') or 'the sample'} holds no liquid",
            )
    contract = _contract(state)
    try:
        entry = apply_step(twins, contract, step, number)
    except PlanError as exc:
        raise TwinFault(number, CODES.get(exc.layer, exc.layer), str(exc)) from None
    after = deepcopy(state)
    after["samples"] = {
        key: {
            "location": s["location"],
            "site": s["site"],
            "vessel": s["vessel"],
            "volume_ul": s["volume"],
            "temperature_c": s["temperature"],
            "mixed": s["mixed"],
        }
        for key, s in contract["samples"].items()
    }
    after["stock"] = contract["stock"]
    after["elapsed_s"] = contract["elapsed"]
    return after, entry


def lookahead(twins, state, steps, cursor, horizon):
    """Simulate the next `horizon` steps from a synced state.

    Returns the steps checked and the first predicted failure, if any; nothing past the
    first failure is simulated, since its state would be a guess.
    """
    checked = []
    for index in range(cursor, min(len(steps), cursor + horizon)):
        try:
            state, _ = advance(twins, state, steps[index], index + 1)
        except TwinFault as fault:
            return {"checked": checked, "failure": fault.describe()}
        checked.append(index + 1)
    return {"checked": checked, "failure": None}


FIELDS = ("samples", "stock", "gripper", "doors", "busy", "placements", "elapsed_s")


def sync(observed):
    """The twin's state after taking in an executor's observation.

    Every field the executor reports replaces the twin's; an observation missing a field
    is refused, since a partial sync would leave the twin's bookkeeping inconsistent.
    """
    missing = [f for f in FIELDS if f not in observed]
    if missing:
        raise ValueError(f"Observation is missing {', '.join(missing)}")
    return deepcopy({f: observed[f] for f in FIELDS})


def change(before, after):
    """Fields that differ between two states, as (field, before, after) triples."""
    a, b = flatten(before), flatten(after)
    return [
        {"field": key, "before": a.get(key), "after": b.get(key)}
        for key in sorted(set(a) | set(b))
        if a.get(key) != b.get(key) and key != "elapsed_s"
    ]


def flatten(state):
    """field path -> scalar, e.g. ``samples.sample.volume_ul`` or ``stock.<id>.Tips``."""
    out = {"elapsed_s": state["elapsed_s"]}
    for key, sample in state["samples"].items():
        for field, value in sample.items():
            out[f"samples.{key}.{field}"] = value
    for device, items in state["stock"].items():
        for item, count in items.items():
            out[f"stock.{device}.{item}"] = count
    for group in ("gripper", "doors", "busy"):
        for device, value in state[group].items():
            out[f"{group}.{device}"] = value
    for twin, at in state["placements"].items():
        for axis, value in at.items():
            out[f"placements.{twin}.{axis}"] = value
    return out
