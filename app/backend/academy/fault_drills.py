"""Fault drills: respond to an instrument fault in the middle of a run.

A synthetic workflow runs on a teaching twin; at one step a fault fires. The learner then
picks what to do, one action at a time, against a timer: the response time, any unsafe
action and whether the recovery came in the right order are kept. A fault either can be
recovered and the run resumed, or the run must stop and an operator be called.

Faults come in families keyed by what an instrument can do (tips, liquid, a gripper,
motion, an enclosure, labware, a connection), never by a list of instruments: a twin's
capabilities are read from its spec, so a new instrument gets every family it can meet,
and one can also declare its families in `DECLARED`. Where the SiLA mock connectors'
command contract refuses the same fault, the refusal is produced by running that
contract, so a person here and an agent in the sandbox meet the same message.

A checkride is a short exam of drills chosen at random; a passed one is included in the
signed cloud lab training record. Operators can turn a real incident into a drill for
their lab. Everything is synthetic teaching: no instrument or hardware is ever reached.
"""

import hashlib
import random
import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import Depends, HTTPException, Request
from pydantic import Field, model_validator

from .auth import identify, identify_operator, operator_claims
from .mock_contract import PlanError, execute_mock
from .models import StrictModel
from .simple_twins import TEMPLATES
from .store import Conflict

RULES = "fault-drills/1"
KEY = "fault-drills"
LAB_KEY = "fault-drills#lab"
KEEP_DRILLS = 30
KEEP_CHECKRIDES = 10
LAB_LIMIT = 40
STEP_SECONDS = 1.0  # how long each synthetic step runs before the next
LIMIT_SECONDS = 60  # from the fault to the end of the response
CHECKRIDE_SIZE = 3
ENDINGS = {"resume": "Resume the run", "operator": "Stop the run and call the operator"}
SHARED_UNSAFE = [
    ("restart", "Restart the run from the first step without finding the cause"),
    ("silence", "Silence the alarm and let the run carry on"),
]

# An instrument may name the families that apply to it instead of having them read from
# its spec: {template or registered key: [family, ...]}.
DECLARED: dict[str, list[str]] = {}
# Instruments registered from elsewhere: {key: twin spec}.
REGISTERED: dict[str, dict] = {}


def register(key, spec, families=None):
    """Add an instrument to the drills; `families` overrides what its spec implies."""
    REGISTERED[key] = deepcopy(spec)
    if families is not None:
        DECLARED[key] = list(families)


def now():
    return datetime.now(UTC)


def stamp(moment):
    return moment.isoformat(timespec="milliseconds")


def capabilities(spec):
    """What a twin can do, read from its spec, as the keys fault families require."""
    operations = set(spec["operations"])
    found = {"connected"}
    if any("tip" in c["name"].lower() for c in spec.get("consumables", [])):
        found |= {"tips", "liquid"}
    if operations & {"aspirate", "dispense"}:
        found.add("liquid")
    if "transfer" in operations:
        found |= {"gripper", "motion", "enclosure"}
    if "load" in operations and spec["container"]["vessel"] != "none":
        found |= {"labware", "enclosure"}
    return found


def _step(label, text):
    return {"id": label, "text": text}


# requires: a capability; at: the operation the fault fires on (else the middle step);
# nth: which occurrence of it. recovery is in order; the run then resumes or stops.
FAMILIES = {
    "tips": {
        "title": "Tips run out or a tip is not picked up",
        "requires": "tips",
        "at": "tips",
        "nth": 1,
        "resumable": True,
        "recovery": [
            _step("pause", "Pause the run"),
            _step("reload", "Load a full tip rack in the tip slot"),
            _step("confirm", "Confirm the new rack so the instrument's tip count starts again"),
        ],
        "unsafe": [
            _step("reuse", "Reuse the last tip for the remaining steps"),
            _step("by-hand", "Push a tip onto the pipette by hand while it is running"),
        ],
        "why": "Nothing was drawn without a tip, so the run can go on once tips are back "
        "and the instrument knows the rack is full.",
    },
    "liquid": {
        "title": "Aspiration fails: a clog or air in the tip",
        "requires": "liquid",
        "at": "liquid",
        "nth": 0,
        "resumable": True,
        "recovery": [
            _step("pause", "Pause the run"),
            _step("inspect", "Check the tip and the liquid level in the source"),
            _step("new-tip", "Discard the tip and take a fresh one"),
            _step("mark", "Mark the affected well as uncertain in the run log"),
        ],
        "unsafe": [
            _step("blow-out", "Blow the clog out into the destination well"),
            _step("lower", "Drive the tip lower until it reaches liquid"),
        ],
        "why": "The volume moved at that step is unknown. A fresh tip lets the run go on; "
        "the well is marked so its result is not trusted unseen.",
    },
    "gripper": {
        "title": "The gripper drops or misgrips a plate",
        "requires": "gripper",
        "at": "transfer",
        "nth": 1,
        "resumable": False,
        "recovery": [
            _step("hold", "Keep the run stopped where it is"),
            _step("leave", "Leave the dropped plate where it fell"),
            _step("record", "Note the step and where the plate landed"),
        ],
        "unsafe": [
            _step("pick-up", "Reach in and put the plate back on the gripper"),
            _step("retry", "Send the gripper to grip the plate again"),
        ],
        "why": "A dropped plate may have spilled and the deck is no longer where the run "
        "expects it; an operator has to clear it before anything moves.",
    },
    "door": {
        "title": "A door or enclosure is opened mid-run",
        "requires": "enclosure",
        "at": None,
        "nth": 0,
        "resumable": True,
        "recovery": [
            _step("hands", "Make sure no one is reaching into the work area"),
            _step("close", "Close the door"),
            _step("acknowledge", "Acknowledge the interlock on the instrument"),
        ],
        "unsafe": [
            _step("defeat", "Tape the door switch so it reads closed"),
            _step("reach", "Adjust the plate by hand while the door is open"),
        ],
        "why": "The interlock paused motion before anyone could be hurt; once the area is "
        "clear and the door closed, the run can carry on from where it paused.",
    },
    "collision": {
        "title": "The arm collides or makes a protective stop",
        "requires": "motion",
        "at": "transfer",
        "nth": 0,
        "resumable": False,
        "recovery": [
            _step("hold", "Leave the protective stop engaged"),
            _step("clear", "Keep everyone clear of the arm"),
            _step("record", "Note the step, the arm's position and what it touched"),
        ],
        "unsafe": [
            _step("jog", "Jog the arm free yourself"),
            _step("reset", "Reset the stop and run the move again"),
        ],
        "why": "A collision can bend a gripper or shift the arm's calibration; it must be "
        "inspected before it moves again.",
    },
    "offline": {
        "title": "The instrument goes offline or times out",
        "requires": "connected",
        "at": None,
        "nth": 0,
        "resumable": False,
        "recovery": [
            _step("wait", "Stop sending commands"),
            _step("status", "Check the instrument's own screen for its state"),
            _step("record", "Note the last step that was confirmed"),
        ],
        "unsafe": [
            _step("resend", "Send the last command again"),
            _step("power", "Power the instrument off and on"),
        ],
        "why": "Whether the last step happened is unknown, so resuming could repeat or skip "
        "it; an operator decides from the instrument's own state.",
    },
    "labware": {
        "title": "The wrong labware is detected",
        "requires": "labware",
        "at": "load",
        "nth": 0,
        "resumable": True,
        "recovery": [
            _step("pause", "Pause before anything uses it"),
            _step("swap", "Replace it with the labware the workflow names"),
            _step("rescan", "Let the instrument check the labware again"),
        ],
        "unsafe": [
            _step("force", "Press the labware into place so it seats"),
            _step("ignore", "Tell the instrument to accept it as it is"),
        ],
        "why": "Nothing has touched the wrong labware yet; with the right one in place and "
        "checked, the run can go on.",
    },
}
LAYERS = {"tips": "consumable", "labware": "container", "offline": "state"}

LINES = {
    "load": "Load the {vessel} on the {name}",
    "mix": "Mix the {vessel} for 30 s",
    "heat": "Heat the {vessel} to {temp:g} °C",
    "read": "Read the {vessel}",
    "wait": "Hold for 60 s",
    "transfer": "Move the {vessel} with the {name}",
    "aspirate": "Aspirate 100 µL",
    "dispense": "Dispense 100 µL",
}


def instruments():
    """Every drill instrument: the twin templates, then any registered ones."""
    found = {}
    for key, spec in {**TEMPLATES, **REGISTERED}.items():
        caps = capabilities(spec)
        families = DECLARED.get(key) or [
            f for f, family in FAMILIES.items() if family["requires"] in caps
        ]
        found[key] = {"key": key, "spec": spec, "families": [f for f in families if f in FAMILIES]}
    return found


def _instrument(key):
    found = instruments().get(key)
    if found is None:
        raise HTTPException(422, "Choose one of the instruments offered")
    return found


def workflow(spec):
    """A short synthetic run of what the twin can do: load, its work twice, a hold."""
    operations = spec["operations"]
    cycle = [o for o in operations if o not in {"load", "wait"}] or ["wait"]
    steps = (["load"] if "load" in operations else []) + cycle
    steps += (["wait"] if "wait" in operations else []) + cycle
    return steps


def _tip_operation(spec):
    return next(
        (c["used_by"] for c in spec.get("consumables", []) if "tip" in c["name"].lower()), None
    )


def fault_step(spec, family):
    """The 1-based step a family's fault fires on."""
    steps = workflow(spec)
    rule = FAMILIES[family]
    wanted = rule["at"]
    if wanted == "tips":
        wanted = _tip_operation(spec)
    elif wanted == "liquid":
        wanted = next((o for o in steps if o in {"aspirate", "dispense", "mix"}), None)
    hits = [i for i, o in enumerate(steps) if o == wanted]
    if hits:
        return hits[min(rule["nth"], len(hits) - 1)] + 1
    return len(steps) // 2 + 1


def lines(spec):
    vessel = spec["container"]["vessel"]
    vessel = "plate" if vessel == "none" else vessel
    limits = spec["limits"]
    temp = min(max(37, limits["min_temp_c"]), limits["max_temp_c"])
    return [
        LINES[o].format(vessel=vessel, name=spec["name"].lower(), temp=temp) for o in workflow(spec)
    ]


def _device(label, spec):
    return {
        "id": str(uuid5(NAMESPACE_URL, f"academy-drill:{label}")),
        "spec": spec,
        "confirmed": True,
        "mode": "mock",
    }


def _mock_step(device, operation, spec, **extra):
    limits = spec["limits"]
    value = {
        "load": min(100, spec["container"]["max_volume_ul"] or 100),
        "heat": min(max(37, limits["min_temp_c"]), limits["max_temp_c"]),
    }.get(operation, 30)
    return {
        "device_id": device["id"],
        "operation": operation,
        "value": value,
        "sample": "sample",
        "source_id": None,
        "target_id": None,
        "site": "",
        "source_site": "",
        "target_site": "",
        **extra,
    }


def contract_refusal(spec, family):
    """What the mock connectors' command contract refuses with for this fault, if it does.

    The same contract the agent sandbox runs; None when the contract has no such refusal
    (it does not model doors, grippers or collisions) or the twin cannot be set up for it.
    """
    try:
        steps = workflow(spec)
        at = fault_step(spec, family)
        if family == "tips":
            twin = _device("instrument", deepcopy(spec))
            used = _tip_operation(spec)
            for item in twin["spec"]["consumables"]:
                if item["used_by"] == used:
                    # Enough for the uses before the fault, none for the one it fires on.
                    item["stock"] = item["per_use"] * steps[: at - 1].count(used)
            plan = [_mock_step(twin, o, spec) for o in steps[:at]]
            execute_mock({twin["id"]: twin}, plan)
        elif family == "labware":
            wrong = "tube" if spec["container"]["vessel"] != "tube" else "plate"
            staging = deepcopy(spec)
            staging.update(name="Staging rack", operations=["load"], consumables=[])
            staging["container"] = {**staging["container"], "vessel": wrong}
            rack = _device("staging", staging)
            twin = _device("instrument", deepcopy(spec))
            arm = _device("arm", deepcopy(TEMPLATES["transfer-arm"]))
            plan = [
                _mock_step(rack, "load", staging),
                _mock_step(
                    arm, "transfer", arm["spec"], source_id=rack["id"], target_id=twin["id"]
                ),
            ]
            execute_mock({d["id"]: d for d in (rack, twin, arm)}, plan)
        elif family == "offline":
            # The steps before run on the twin; at the fault it no longer answers as a
            # confirmed device, which is how the contract refuses an unreachable one.
            twin = _device("instrument", deepcopy(spec))
            gone = {**_device("unreachable", deepcopy(spec)), "confirmed": False}
            plan = [_mock_step(twin, o, spec) for o in steps[: at - 1]]
            plan.append(_mock_step(gone, steps[at - 1], spec))
            execute_mock({twin["id"]: twin, gone["id"]: gone}, plan)
        else:
            return None
    except PlanError as exc:
        # Only the refusal this fault causes counts, not one the setup ran into first.
        where = 2 if family == "labware" else at
        if exc.layer != LAYERS[family] or not str(exc).startswith(f"Step {where}:"):
            return None
        return {"layer": exc.layer, "message": str(exc)}
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return None


SYMPTOMS = {
    "tips": "The {name} stops at step {step}: the pipette finds no tip to pick up.",
    "liquid": "At step {step} the {name}'s pressure trace is flat: no liquid came up.",
    "gripper": "At step {step} the {name} reports a lost grip; a plate is on the deck "
    "beside its target slot.",
    "door": "At step {step} the enclosure door around the {name} opens; motion stops and "
    "the interlock alarm sounds.",
    "collision": "At step {step} the {name} hits something and makes a protective stop.",
    "offline": "At step {step} the {name} stops answering; the last command has had no "
    "reply for 30 s.",
    "labware": "At step {step} the {name} reads labware that is not the one this workflow names.",
}


def catalog_scenario(instrument, family):
    found = _instrument(instrument)
    if family not in found["families"]:
        raise HTTPException(422, "That fault does not apply to this instrument")
    spec = found["spec"]
    rule = FAMILIES[family]
    step = fault_step(spec, family)
    contract = contract_refusal(spec, family)
    return {
        "source": "catalog",
        "instrument": instrument,
        "instrument_name": spec["name"],
        "family": family,
        "title": rule["title"],
        "steps": lines(spec),
        "fault_step": step,
        "symptom": SYMPTOMS[family].format(name=spec["name"].lower(), step=step),
        "contract": contract,
        "layer": (contract or {}).get("layer") or LAYERS.get(family),
        "recovery": deepcopy(rule["recovery"]),
        "unsafe": deepcopy(rule["unsafe"]),
        "ending": "resume" if rule["resumable"] else "operator",
        "why": rule["why"],
    }


def lab_scenario(incident, lab):
    instrument = instruments().get(incident["instrument"])
    spec = instrument["spec"] if instrument else None
    steps = lines(spec) if spec else [f"Step {i + 1}" for i in range(incident["step"])]
    return {
        "source": "lab",
        "lab": lab,
        "incident_id": incident["id"],
        "instrument": incident["instrument"],
        "instrument_name": spec["name"] if spec else incident["instrument"],
        "family": incident["family"],
        "title": incident["title"],
        "steps": steps,
        "fault_step": min(incident["step"], len(steps)),
        "symptom": incident["symptom"],
        "contract": None,
        "layer": None,
        "recovery": [_step(f"r{i + 1}", text) for i, text in enumerate(incident["recovery"])],
        "unsafe": [_step(f"u{i + 1}", text) for i, text in enumerate(incident["unsafe"])],
        "ending": incident["ending"],
        "why": incident["why"],
    }


def pool(scenario, seed):
    """Every action offered, recovery and unsafe mixed in an order fixed per drill."""
    taken = {a["id"] for a in scenario["recovery"] + scenario["unsafe"]}
    shared = [_step(k, t) for k, t in SHARED_UNSAFE if k not in taken]
    actions = scenario["recovery"] + scenario["unsafe"] + shared[:1]
    return sorted(actions, key=lambda a: hashlib.sha256(f"{seed}{a['id']}".encode()).hexdigest())


def unsafe_ids(drill):
    safe = {a["id"] for a in drill["scenario"]["recovery"]}
    return {a["id"] for a in drill["pool"]} - safe


def score(drill):
    actions = drill["actions"]
    steps = [a["id"] for a in actions if a["id"] not in ENDINGS]
    ending = next((a["id"] for a in actions if a["id"] in ENDINGS), None)
    bad = unsafe_ids(drill)
    unsafe = [a for a in steps if a in bad]
    recovery = [a["id"] for a in drill["scenario"]["recovery"]]
    in_order = [a for a in steps if a not in bad] == recovery
    correct = in_order and ending == drill["scenario"]["ending"]
    timed_out = drill["status"] == "timed_out"
    return {
        "response_s": actions[0]["t"] if actions else None,
        "total_s": actions[-1]["t"] if actions else None,
        "unsafe_actions": len(unsafe),
        "recovery_correct": correct,
        "ending": ending,
        "timed_out": timed_out,
        "passed": correct and not unsafe and not timed_out,
    }


class Revision(StrictModel):
    expected_version: int = Field(ge=0, strict=True)


class StartDrill(Revision):
    instrument: str | None = Field(default=None, max_length=80)
    family: str | None = Field(default=None, max_length=40)
    lab: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{1,39}$")
    incident_id: UUID | None = None

    @model_validator(mode="after")
    def one_source(self):
        catalog = self.instrument is not None and self.family is not None
        lab = self.lab is not None and self.incident_id is not None
        if catalog == lab:
            raise ValueError("Choose an instrument and fault, or one of your lab's drills")
        return self


class Act(Revision):
    action: str = Field(min_length=1, max_length=40)


class Incident(Revision):
    title: str = Field(min_length=4, max_length=80)
    instrument: str = Field(min_length=1, max_length=80)
    family: Literal[tuple(FAMILIES) + ("other",)] = "other"
    step: int = Field(ge=1, le=12)
    symptom: str = Field(min_length=10, max_length=300)
    recovery: list[str] = Field(min_length=1, max_length=5)
    unsafe: list[str] = Field(min_length=1, max_length=3)
    ending: Literal["resume", "operator"]
    why: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def tidy(self):
        self.recovery = [r.strip() for r in self.recovery]
        self.unsafe = [u.strip() for u in self.unsafe]
        lines_given = self.recovery + self.unsafe
        if any(not 3 <= len(text) <= 120 for text in lines_given):
            raise ValueError("Write each response in 3 to 120 characters")
        if len({t.lower() for t in lines_given}) != len(lines_given):
            raise ValueError("Each response must differ from the others")
        if self.instrument not in instruments():
            raise ValueError("Choose one of the instruments offered")
        return self


def author(owner):
    """A stable pseudonym, so a lab's drills never carry an account id."""
    return hashlib.sha256(f"academy-drill-author:{owner}".encode()).hexdigest()[:12]


def _seconds(start, moment):
    return round((moment - datetime.fromisoformat(start)).total_seconds(), 2)


def settle(found, moment):
    """Close an open drill whose time ran out, and a checkride whose drills are all done."""
    for drill in found["drills"]:
        if drill["status"] == "open" and _seconds(drill["fires_at"], moment) > LIMIT_SECONDS:
            drill["status"] = "timed_out"
            drill["finished_at"] = stamp(moment)
            drill["result"] = score(drill)
    for ride in found["checkrides"]:
        if ride["status"] != "open":
            continue
        drills = [d for d in found["drills"] if d["id"] in ride["drill_ids"]]
        if len(drills) == len(ride["picks"]) and all(d["status"] != "open" for d in drills):
            ride["status"] = "done"
            ride["finished_at"] = max(d["finished_at"] for d in drills)
            ride["passed"] = all(d["result"]["passed"] for d in drills)
    return found


def drill_view(drill, found, moment):
    scenario = drill["scenario"]
    ride = next((c for c in found["checkrides"] if drill["id"] in c["drill_ids"]), None)
    revealed = drill["status"] != "open" and (ride is None or ride["status"] != "open")
    fires_in = -_seconds(drill["fires_at"], moment)
    return {
        "id": drill["id"],
        "status": drill["status"],
        "checkride_id": ride and ride["id"],
        "started_at": drill["started_at"],
        "title": scenario["title"] if revealed else None,
        "source": scenario["source"],
        "instrument": scenario["instrument"],
        "instrument_name": scenario["instrument_name"],
        "steps": scenario["steps"],
        "fault_step": scenario["fault_step"] if fires_in <= 0 or revealed else None,
        "symptom": scenario["symptom"] if fires_in <= 0 or revealed else None,
        "running_s": _seconds(drill["started_at"], moment) if drill["status"] == "open" else 0.0,
        "fires_in_s": max(0.0, fires_in) if drill["status"] == "open" else 0.0,
        "time_left_s": max(0.0, LIMIT_SECONDS - max(0.0, -fires_in))
        if drill["status"] == "open"
        else 0.0,
        "pool": drill["pool"],
        "endings": [{"id": k, "text": t} for k, t in ENDINGS.items()],
        "actions": drill["actions"],
        **(
            {
                "result": drill["result"],
                "answer": {
                    "recovery": scenario["recovery"],
                    "unsafe": sorted(unsafe_ids(drill)),
                    "ending": scenario["ending"],
                    "why": scenario["why"],
                    "contract": scenario["contract"],
                    "layer": scenario["layer"],
                },
            }
            if revealed
            else {}
        ),
    }


def ride_view(ride, found):
    drills = [d for d in found["drills"] if d["id"] in ride["drill_ids"]]
    return {
        "id": ride["id"],
        "status": ride["status"],
        "started_at": ride["started_at"],
        "finished_at": ride.get("finished_at"),
        "size": len(ride["picks"]),
        "done": sum(d["status"] != "open" for d in drills),
        "passed": ride.get("passed"),
        **(
            {
                "drills": [
                    {
                        "title": d["scenario"]["title"],
                        "instrument_name": d["scenario"]["instrument_name"],
                        **d["result"],
                    }
                    for d in drills
                ]
            }
            if ride["status"] == "done"
            else {}
        ),
    }


def summary(found):
    done = [d for d in found["drills"] if d["status"] != "open"]
    times = [d["result"]["response_s"] for d in done if d["result"]["response_s"] is not None]
    return {
        "drills": len(done),
        "passed": sum(d["result"]["passed"] for d in done),
        "unsafe_actions": sum(d["result"]["unsafe_actions"] for d in done),
        "median_response_s": sorted(times)[len(times) // 2] if times else None,
        "checkrides_passed": sum(bool(c.get("passed")) for c in found["checkrides"]),
    }


def record_entry(found):
    """The latest passed checkride, as the signed training record includes it."""
    if not found:
        return None
    found = settle(deepcopy(found), now())
    passed = [c for c in found["checkrides"] if c.get("passed")]
    if not passed:
        return None
    ride = max(passed, key=lambda c: c["finished_at"])
    drills = [d for d in found["drills"] if d["id"] in ride["drill_ids"]]
    return {
        "rules_version": RULES,
        # (source, ref) name this pass; each drill gives (instrument_kind, criterion).
        "source": "fault-drills/checkride",
        "ref": ride["id"],
        "passed_at": ride["finished_at"],
        "attempts": len(found["checkrides"]),
        "drills": [
            {
                "instrument": d["scenario"]["instrument_name"],
                "instrument_kind": d["scenario"]["instrument"],
                "fault": d["scenario"]["family"],
                # Recovering and resuming, or knowing to stop and escalate.
                "criterion": "recover" if d["scenario"]["ending"] == "resume" else "escalate",
                "response_s": d["result"]["response_s"],
                "unsafe_actions": d["result"]["unsafe_actions"],
                "recovery_correct": d["result"]["recovery_correct"],
            }
            for d in drills
        ],
        "evidence": "synthetic",
    }


def picks(rng=None):
    """CHECKRIDE_SIZE catalog drills, each of a different fault family."""
    rng = rng or random.SystemRandom()
    pairs = [(key, f) for key, i in instruments().items() for f in i["families"]]
    rng.shuffle(pairs)
    chosen, families = [], set()
    for key, family in pairs:
        if family not in families:
            chosen.append({"instrument": key, "family": family})
            families.add(family)
        if len(chosen) == CHECKRIDE_SIZE:
            break
    return chosen


def install(app, *, store):
    def record(owner):
        return store.get(owner, KEY) or {"version": 0, "drills": [], "checkrides": []}

    def current(owner, expected, moment):
        found = record(owner)
        if found["version"] != expected:
            raise Conflict
        return settle(found, moment)

    def save(owner, found, expected):
        found["version"] = expected + 1
        # Drills a kept checkride counts are kept with it; of the rest, the newest.
        counted = {i for c in found["checkrides"] for i in c["drill_ids"]}
        newest = sorted(found["drills"], key=lambda d: d["started_at"], reverse=True)
        loose = [d for d in newest if d["id"] not in counted][:KEEP_DRILLS]
        found["drills"] = [d for d in newest if d["id"] in counted or d in loose]
        store.put(owner, KEY, found, expected or None)
        return found

    def listing(found, moment, request):
        open_drill = next((d for d in found["drills"] if d["status"] == "open"), None)
        open_ride = next((c for c in found["checkrides"] if c["status"] == "open"), None)
        return {
            "version": found["version"],
            "rules_version": RULES,
            "evidence": "synthetic",
            "limit_s": LIMIT_SECONDS,
            "step_s": STEP_SECONDS,
            "checkride_size": CHECKRIDE_SIZE,
            "can_author": operator_claims(request),
            "instruments": [
                {
                    "key": i["key"],
                    "name": i["spec"]["name"],
                    "steps": lines(i["spec"]),
                    "families": [{"key": f, "title": FAMILIES[f]["title"]} for f in i["families"]],
                }
                for i in instruments().values()
            ],
            "open": open_drill and drill_view(open_drill, found, moment),
            "checkride": open_ride and ride_view(open_ride, found),
            "drills": [drill_view(d, found, moment) for d in found["drills"]],
            "checkrides": [ride_view(c, found) for c in found["checkrides"]],
            "summary": summary(found),
        }

    def begin(found, scenario, moment):
        if any(d["status"] == "open" for d in found["drills"]):
            raise HTTPException(409, "Finish the drill you have open first")
        drill_id = str(uuid4())
        # The fault fires halfway through its step.
        lead = (scenario["fault_step"] - 0.5) * STEP_SECONDS
        drill = {
            "id": drill_id,
            "status": "open",
            "started_at": stamp(moment),
            "fires_at": stamp(moment + timedelta(seconds=lead)),
            "finished_at": None,
            "scenario": scenario,
            "pool": pool(scenario, drill_id),
            "actions": [],
            "result": None,
        }
        found["drills"].insert(0, drill)
        return drill

    def lab_record(lab):
        return store.get(f"lab#{lab}", LAB_KEY) or {"version": 0, "incidents": []}

    def respond(owner, found, expected, moment, request, drill=None):
        saved = save(owner, found, expected)
        body = listing(saved, moment, request)
        if drill is not None:
            body["drill"] = drill_view(drill, saved, moment)
        return body

    @app.get("/api/fault-drills")
    def drills(request: Request, owner: str = Depends(identify)):
        moment = now()
        return listing(settle(record(owner), moment), moment, request)

    @app.post("/api/fault-drills/drills", status_code=201)
    def start_drill(data: StartDrill, request: Request, owner: str = Depends(identify)):
        moment = now()
        found = current(owner, data.expected_version, moment)
        if any(c["status"] == "open" for c in found["checkrides"]):
            raise HTTPException(409, "Finish the checkride you have open first")
        if data.lab is not None:
            incident = next(
                (i for i in lab_record(data.lab)["incidents"] if i["id"] == str(data.incident_id)),
                None,
            )
            if incident is None:
                raise HTTPException(404, "Drill not found in this lab")
            scenario = lab_scenario(incident, data.lab)
        else:
            scenario = catalog_scenario(data.instrument, data.family)
        drill = begin(found, scenario, moment)
        return respond(owner, found, data.expected_version, moment, request, drill)

    @app.post("/api/fault-drills/drills/{drill_id}/actions")
    def act(drill_id: UUID, data: Act, request: Request, owner: str = Depends(identify)):
        moment = now()
        found = record(owner)
        if found["version"] != data.expected_version:
            raise Conflict
        drill = next((d for d in found["drills"] if d["id"] == str(drill_id)), None)
        if drill is None:
            raise HTTPException(404, "Drill not found")
        settle(found, moment)
        if drill["status"] == "timed_out":
            raise HTTPException(409, "Time ran out for this drill")
        if drill["status"] != "open":
            raise HTTPException(409, "This drill has ended")
        elapsed = _seconds(drill["fires_at"], moment)
        if elapsed < 0:
            raise HTTPException(409, "The fault has not happened yet")
        offered = {a["id"] for a in drill["pool"]} | set(ENDINGS)
        if data.action not in offered:
            raise HTTPException(422, "Choose one of the actions offered")
        if any(a["id"] == data.action for a in drill["actions"]):
            raise HTTPException(422, "You have already done that")
        drill["actions"].append({"id": data.action, "t": round(elapsed, 2)})
        if data.action in ENDINGS:
            drill.update(status="done", finished_at=stamp(moment))
            drill["result"] = score(drill)
            settle(found, moment)
        return respond(owner, found, data.expected_version, moment, request, drill)

    @app.post("/api/fault-drills/checkrides", status_code=201)
    def start_checkride(data: Revision, request: Request, owner: str = Depends(identify)):
        moment = now()
        found = current(owner, data.expected_version, moment)
        if any(c["status"] == "open" for c in found["checkrides"]):
            raise HTTPException(409, "Finish the checkride you have open first")
        chosen = picks()
        if len(chosen) < CHECKRIDE_SIZE:
            raise HTTPException(409, "Not enough different faults for a checkride")
        drill = begin(found, catalog_scenario(**chosen[0]), moment)
        ride = {
            "id": str(uuid4()),
            "status": "open",
            "started_at": stamp(moment),
            "finished_at": None,
            "picks": chosen,
            "drill_ids": [drill["id"]],
            "passed": None,
        }
        found["checkrides"] = [ride, *found["checkrides"][: KEEP_CHECKRIDES - 1]]
        return respond(owner, found, data.expected_version, moment, request, drill)

    @app.post("/api/fault-drills/checkrides/{ride_id}/next")
    def next_drill(ride_id: UUID, data: Revision, request: Request, owner: str = Depends(identify)):
        moment = now()
        found = current(owner, data.expected_version, moment)
        ride = next((c for c in found["checkrides"] if c["id"] == str(ride_id)), None)
        if ride is None:
            raise HTTPException(404, "Checkride not found")
        if ride["status"] != "open" or len(ride["drill_ids"]) >= len(ride["picks"]):
            raise HTTPException(409, "This checkride has no drills left")
        drill = begin(found, catalog_scenario(**ride["picks"][len(ride["drill_ids"])]), moment)
        ride["drill_ids"].append(drill["id"])
        return respond(owner, found, data.expected_version, moment, request, drill)

    def incident_view(incident, full):
        keys = ("id", "title", "instrument", "family", "step", "symptom", "created_at")
        shown = {k: incident[k] for k in keys}
        if full:
            shown.update({k: incident[k] for k in ("recovery", "unsafe", "ending", "why")})
        return shown

    @app.get("/api/fault-drills/labs/{lab}/incidents")
    def lab_drills(lab: str, request: Request, _owner: str = Depends(identify)):
        lab = _lab(lab)
        found = lab_record(lab)
        full = operator_claims(request)
        return {
            "lab": lab,
            "version": found["version"],
            "can_author": full,
            "incidents": [incident_view(i, full) for i in found["incidents"]],
        }

    @app.post("/api/fault-drills/labs/{lab}/incidents", status_code=201)
    def add_incident(lab: str, data: Incident, operator: str = Depends(identify_operator)):
        lab = _lab(lab)
        found = lab_record(lab)
        if found["version"] != data.expected_version:
            raise Conflict
        if len(found["incidents"]) >= LAB_LIMIT:
            raise HTTPException(422, f"A lab keeps at most {LAB_LIMIT} drills")
        instrument = instruments()[data.instrument]
        if data.step > len(workflow(instrument["spec"])):
            raise HTTPException(422, "Choose a step of this instrument's run")
        incident = {
            "id": str(uuid4()),
            "created_at": stamp(now()),
            "author": author(operator),
            **data.model_dump(exclude={"expected_version"}),
        }
        found["incidents"].insert(0, incident)
        found["version"] = data.expected_version + 1
        store.put(f"lab#{lab}", LAB_KEY, found, data.expected_version or None)
        return {
            "lab": lab,
            "version": found["version"],
            "can_author": True,
            "incidents": [incident_view(i, True) for i in found["incidents"]],
        }


def _lab(lab):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,39}", lab):
        raise HTTPException(422, "A lab code is 2 to 40 lowercase letters, digits or dashes")
    return lab
