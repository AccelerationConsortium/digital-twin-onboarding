"""Find-the-fault practice: a working workflow with one mistake put in.

The learner says whether the workflow will finish and where it stops before running it,
names the cause, then repairs it. What they predicted, what they chose and how many
tries the repair took are kept, so the same items can show what a learner knows before
and after the lessons. The mistakes are the ones the comparison with the Opentrons
simulator uses. Everything runs in the teaching model: results are synthetic.
"""

from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field

from .models import Experiment, StrictModel
from .store import Conflict
from .teaching import control, execute_step, new_session

LIMIT = 60  # exercises one learner keeps
PREFIX = "practice#"
LAYOUTS = {
    "flex": {"stock": "D1", "plate": "D2", "tips": "B1", "waste": "D3"},
    "ot2": {"stock": "1", "plate": "2", "tips": "4", "waste": "12"},
}
MODULES = ["gripper", "heater_shaker", "temperature", "reader", "stacker"]


def _act(kind, **fields):
    return {"kind": kind, **fields}


def _transfer(source="stock", target="A1", volume=100):
    return [
        _act("pickup"),
        _act("aspirate", well=source, volume=volume),
        _act("dispense", well=target, volume=volume),
        _act("drop"),
    ]


def _move(to):
    return _act("move", to=to)


# name -> (title, modules, diluent µL, actions)
STARTERS = {
    "transfer": ("Transfer 100 µL into A1", [], 0, _transfer()),
    "dilution": (
        "Three-step serial dilution",
        [],
        100,
        [*_transfer("stock", "A1"), *_transfer("A1", "A2"), *_transfer("A2", "A3")],
    ),
    "shake": (
        "Transfer, then heat and shake",
        MODULES,
        0,
        [
            *_transfer(),
            _move("heater_shaker"),
            _act("heat", value=60),
            _act("shake", value=1000, seconds=30),
            _move("deck"),
        ],
    ),
    "read": (
        "Transfer, then read the plate",
        MODULES,
        0,
        [*_transfer(), _move("reader"), _act("read"), _move("deck")],
    ),
}


def _without(actions, index):
    return actions[:index] + actions[index + 1 :]


def _changed(actions, index, **fields):
    return actions[:index] + [{**actions[index], **fields}] + actions[index + 1 :]


def _find(actions, kind, nth=0, **fields):
    hits = [
        i
        for i, a in enumerate(actions)
        if a["kind"] == kind and all(a.get(k) == v for k, v in fields.items())
    ]
    return hits[nth]


# What a learner can name as the cause. One is right for each item.
CAUSES = {
    "no_tip": "A step uses the pipette before any tip is picked up.",
    "tip_attached": "A tip is picked up while another is still on the pipette.",
    "used_tip": "A tip that has already dispensed is used for the next transfer.",
    "source_short": "The source holds less liquid than a step draws from it.",
    "dispense_more": "A step dispenses more than the tip holds.",
    "overflow": "A well is filled past what it holds.",
    "tip_left": "The workflow ends with a tip still on the pipette.",
    "capacity": "More liquid is drawn into the tip than the pipette holds.",
    "not_on_module": "A module is given a command while the plate is somewhere else.",
    "temperature_range": "A module is asked for a temperature outside its range.",
    "shake_range": "The Heater-Shaker is asked for a speed outside its range.",
    "not_in_reader": "The plate is read while it is outside the plate reader.",
    "plate_away": "The pipette is sent to a plate it cannot reach where the plate is.",
    "already_there": "The plate is moved to where it already is.",
}
# (cause, instrument, starter, change to the plan)
ITEMS = [
    ("no_tip", "flex", "transfer", lambda a: {"actions": _without(a, 0)}),
    ("source_short", "ot2", "transfer", lambda a: {"source_volume": 50}),
    ("tip_attached", "flex", "dilution", lambda a: {"actions": _without(a, _find(a, "drop"))}),
    (
        "dispense_more",
        "ot2",
        "transfer",
        lambda a: {"actions": _changed(a, _find(a, "dispense"), volume=150)},
    ),
    (
        "used_tip",
        "flex",
        "dilution",
        lambda a: {
            "actions": _without(
                _without(a, _find(a, "drop")), _find(_without(a, _find(a, "drop")), "pickup", 1)
            )
        },
    ),
    ("tip_left", "ot2", "dilution", lambda a: {"actions": a[:-1]}),
    ("overflow", "flex", "transfer", lambda a: {"diluent_volume": 1450}),
    (
        "capacity",
        "ot2",
        "transfer",
        lambda a: {
            "actions": a[:2] + [_act("aspirate", well="stock", volume=250)] + a[2:],
        },
    ),
    (
        "not_on_module",
        "flex",
        "shake",
        lambda a: {"actions": _without(a, _find(a, "move", to="heater_shaker"))},
    ),
    (
        "temperature_range",
        "flex",
        "shake",
        lambda a: {"actions": _changed(a, _find(a, "heat"), value=20)},
    ),
    (
        "not_in_reader",
        "flex",
        "read",
        lambda a: {"actions": _without(a, _find(a, "move", to="reader"))},
    ),
    (
        "plate_away",
        "flex",
        "read",
        lambda a: {
            "actions": a[: _find(a, "read") + 1]
            + _transfer("stock", "A2", 50)
            + a[_find(a, "read") + 1 :]
        },
    ),
    (
        "shake_range",
        "flex",
        "shake",
        lambda a: {"actions": _changed(a, _find(a, "shake"), value=5000)},
    ),
    (
        "already_there",
        "flex",
        "read",
        lambda a: {
            "actions": a[: _find(a, "move", to="reader") + 1]
            + [_move("reader")]
            + a[_find(a, "move", to="reader") + 1 :]
        },
    ),
]


def _plan(index, faulty=True):
    cause, instrument, starter, change = ITEMS[index]
    title, modules, diluent, actions = STARTERS[starter]
    fields = {
        "title": f"Find the fault {index + 1} · {title}"[:80],
        "course_id": "workflow-sandbox",
        "instrument": instrument,
        "layout": LAYOUTS[instrument],
        "source_volume": 1000,
        "diluent_volume": diluent,
        "actions": deepcopy(actions),
        "modules": [
            m for m in modules if instrument == "flex" or m in ("heater_shaker", "temperature")
        ],
    }
    if faulty:
        fields.update(change(fields["actions"]))
    return Experiment(**fields)


def outcome(experiment: Experiment) -> dict:
    """What the teaching model does with a plan run from the start."""
    session = control(new_session(experiment), "start")
    while session["status"] == "running":
        session = execute_step(session)
    fault = session["events"][-1] if session["status"] == "faulted" else None
    state = session["state"]
    return {
        "stops": bool(fault),
        "step": fault["step"] if fault else None,
        "passed": bool(session["assessment"] and session["assessment"]["passed"]),
        "result": {
            # What each destination well gained, so a different starting fill still counts.
            "wells": {
                k: round(w["volume"] - experiment.diluent_volume, 3)
                for k, w in state["wells"].items()
                if k != "stock"
            },
            "plate": (state.get("plate") or {}).get("at", "deck"),
            "readings": len(state.get("readings", [])),
        },
    }


class Prediction(StrictModel):
    version: int = Field(ge=1)
    stops: bool
    step: int | None = Field(default=None, ge=1, le=64)


class Diagnosis(StrictModel):
    version: int = Field(ge=1)
    cause: Literal[tuple(CAUSES)]


class Repair(StrictModel):
    version: int = Field(ge=1)


def _choices(record):
    """The right cause among three others, in an order fixed for this exercise."""
    cause = ITEMS[record["item"]][0]
    order = sorted(CAUSES, key=lambda key: sha256(f"{record['id']}{key}".encode()).hexdigest())
    picked = [key for key in order if key != cause][:3] + [cause]
    return sorted(picked, key=order.index)


def public(record):
    """An exercise as its learner sees it: the answer appears only once they have answered."""
    cause = ITEMS[record["item"]][0]
    answered = record["diagnosis"] is not None
    return {
        "id": record["id"],
        "version": record["version"],
        "number": record["item"] + 1,
        "session_id": record["session_id"],
        "title": STARTERS[ITEMS[record["item"]][2]][0],
        "instrument": ITEMS[record["item"]][1],
        "created_at": record["created_at"],
        "phase": record["phase"],
        "prediction": record["prediction"],
        "choices": [{"cause": key, "text": CAUSES[key]} for key in _choices(record)],
        "diagnosis": record["diagnosis"],
        "attempts": record["attempts"],
        "repaired": record["repaired"],
        "last_check": record["last_check"],
        **(
            {
                "answer": {"cause": cause, "text": CAUSES[cause], **record["truth"]},
                "prediction_correct": record["prediction_correct"],
                "diagnosis_correct": record["diagnosis"] == cause,
            }
            if answered
            else {}
        ),
    }


class FaultPractice:
    def __init__(self, store):
        self.store = store

    def records(self, owner):
        return sorted(self.store.partition(owner, PREFIX, LIMIT + 1), key=lambda r: r["created_at"])

    def listing(self, owner):
        records = self.records(owner)
        done = [r for r in records if r["diagnosis"] is not None]
        return {
            "evidence": "synthetic",
            "total": len(ITEMS),
            "exercises": [public(r) for r in records],
            "summary": {
                "answered": len(done),
                "predicted": sum(bool(r["prediction_correct"]) for r in done),
                "diagnosed": sum(r["diagnosis"] == ITEMS[r["item"]][0] for r in done),
                "repaired": sum(r["repaired"] for r in records),
                "first_try": sum(r["repaired"] and r["attempts"] == 1 for r in records),
            },
        }

    def start(self, owner):
        records = self.records(owner)
        if len(records) >= LIMIT:
            raise HTTPException(422, f"You have reached the {LIMIT}-exercise limit")
        if any(r["phase"] != "done" for r in records):
            raise HTTPException(409, "Finish the exercise you have open first")
        # Items come in order and start again once every one has been met.
        item = len(records) % len(ITEMS)
        session = new_session(_plan(item))
        record = {
            "id": str(uuid4()),
            "version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "item": item,
            "session_id": session["id"],
            "truth": {k: outcome(_plan(item))[k] for k in ("stops", "step")},
            "phase": "predict",
            "prediction": None,
            "prediction_correct": None,
            "diagnosis": None,
            "attempts": 0,
            "repaired": False,
            "last_check": None,
        }
        self.store.put(owner, f"session#{session['id']}", session, None)
        self.store.put(owner, PREFIX + record["id"], record, None)
        return public(record)

    def _open(self, owner, practice_id, version):
        record = self.store.get(owner, f"{PREFIX}{practice_id}")
        if record is None:
            raise HTTPException(404, "Exercise not found")
        if record["version"] != version:
            raise Conflict
        return record

    def _save(self, owner, record):
        expected = record["version"]
        record["version"] += 1
        self.store.put(owner, PREFIX + record["id"], record, expected)
        return public(record)

    def predict(self, owner, practice_id, data: Prediction):
        record = self._open(owner, practice_id, data.version)
        if record["phase"] != "predict":
            raise HTTPException(409, "This exercise already has its prediction")
        session = self.store.get(owner, f"session#{record['session_id']}")
        if session is None:
            raise HTTPException(409, "The workflow of this exercise was deleted")
        if session["status"] != "draft" or session["attempts"]:
            # A prediction made after seeing the run is kept, and not counted.
            record["prediction_correct"] = False
            record["prediction"] = {"stops": data.stops, "step": data.step, "after_run": True}
        else:
            truth = record["truth"]
            record["prediction"] = {"stops": data.stops, "step": data.step, "after_run": False}
            record["prediction_correct"] = data.stops == truth["stops"] and (
                not truth["stops"] or data.step == truth["step"]
            )
        record["phase"] = "diagnose"
        return self._save(owner, record)

    def diagnose(self, owner, practice_id, data: Diagnosis):
        record = self._open(owner, practice_id, data.version)
        if record["phase"] != "diagnose":
            raise HTTPException(409, "Predict first, then name the cause once")
        if data.cause not in _choices(record):
            raise HTTPException(422, "Choose one of the causes offered")
        record.update(diagnosis=data.cause, phase="repair")
        return self._save(owner, record)

    def repair(self, owner, practice_id, data: Repair):
        record = self._open(owner, practice_id, data.version)
        if record["phase"] != "repair":
            raise HTTPException(409, "Name the cause before checking a repair")
        session = self.store.get(owner, f"session#{record['session_id']}")
        if session is None:
            raise HTTPException(409, "The workflow of this exercise was deleted")
        ran = outcome(Experiment(**session["experiment"]))
        goal = outcome(_plan(record["item"], faulty=False))["result"]
        record["attempts"] += 1
        if ran["stops"]:
            record["last_check"] = f"The workflow still stops at step {ran['step']}."
        elif not ran["passed"]:
            record["last_check"] = "The workflow runs, but the model's end checks do not all pass."
        elif ran["result"] != goal:
            record["last_check"] = (
                "The workflow runs, but it no longer does what it was meant to: "
                "compare the final volumes, where the plate ends and the readings."
            )
        else:
            record.update(repaired=True, phase="done", last_check="Repaired.")
        return self._save(owner, record)
