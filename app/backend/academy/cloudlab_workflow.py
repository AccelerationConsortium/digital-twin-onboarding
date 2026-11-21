"""Cloud lab workflows: chain cloud lab instruments by what each one does.

A learner composes steps on a handful of the cloud lab twins in `cloudlab`. Each step
acts on one named sample at one instrument: load it there, heat, mix, read or wait, or
move it there from wherever it is. The workflow runs through the same teaching contract
as every other twin (`mock_contract.execute_mock`), so vessel, volume, slot, limit and
consumable rules are the twins' own. Moves between instruments go through one synthetic
sample-handling station; the page is about functions, so there is no bench layout.

A step may also name a ChemLab-Assets twin as `chemlab:<slug>`, as a marketplace paper
template does when the cloud lab has no instrument for a step. Those twins keep their
Academy teaching defaults.

The limits are the teaching twins' (published figures narrowed to what a twin holds,
plus Academy defaults), never the cloud lab's instrument specification, and every run
is synthetic: no robot, Isaac/GPU or chemistry.
"""

import re
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field, model_validator

from .chemlab import CHEMLAB
from .cloudlab import CLOUDLAB, overview
from .mock_contract import PlanError, execute_mock, site_keys
from .models import StrictModel
from .store import Conflict, Write

KEY = "cloudlab-workflow"
MAX_STEPS = 32
KEPT_RUNS = 5
# Instruments that join workflow design: the liquid handler that prepares plates, and
# instruments with a ChemLab-Assets stand-in.
INSTRUMENTS = [
    "robotic-sample-preparation",
    "cell-incubator",
    "plate-washer",
    "plate-reader",
    "thermocycler",
    "qpcr",
    "capillary-electrophoresis",
    "flash-chromatography",
]
HANDLER = "sample-handling"
HANDLING = {
    "id": HANDLER,
    "confirmed": True,
    "mode": "mock",
    "spec": {
        "name": "Sample handling",
        "operations": ["transfer"],
        "container": {"vessel": "none", "max_volume_ul": 0},
        "resource": {"slots": 0},
        "consumables": [],
        "limits": {"min_temp_c": 4, "max_temp_c": 120, "max_duration_s": 600},
        "sites": [],
    },
}
CHEMLAB_PREFIX = "chemlab:"
STATEMENT = (
    "Synthetic teaching run on Academy twins. It checks the workflow against the twins' "
    "rules only; it is not the cloud lab's instrument specification or a chemical result."
)
STEP_AT = re.compile(r"^Step (\d+):")


def known(key):
    return key in INSTRUMENTS or (
        key.startswith(CHEMLAB_PREFIX) and key.removeprefix(CHEMLAB_PREFIX) in CHEMLAB
    )


def spec_of(key):
    if key in CLOUDLAB:
        return CLOUDLAB[key]["spec"]
    return CHEMLAB[key.removeprefix(CHEMLAB_PREFIX)]["spec"]


def twins(keys):
    return {
        HANDLER: HANDLING,
        **{k: {"id": k, "confirmed": True, "mode": "mock", "spec": spec_of(k)} for k in keys},
    }


class Step(StrictModel):
    instrument: str = Field(max_length=96)
    # "transfer" moves the sample to this instrument from wherever it is.
    operation: Literal["load", "transfer", "mix", "heat", "read", "wait"]
    sample: str = Field(default="plate", pattern=r"^[a-z][a-z0-9-]{0,23}$")
    value: float = Field(default=1, ge=0.001, le=1_000_000, allow_inf_nan=False)
    # The slot a load or move takes; empty takes the first free one.
    slot: str = Field(default="", pattern=r"^[A-Za-z0-9-]{0,8}$")

    @model_validator(mode="after")
    def bounded(self):
        if not known(self.instrument):
            raise ValueError("Choose a cloud lab instrument or a ChemLab-Assets twin")
        if self.slot and self.operation not in {"load", "transfer"}:
            raise ValueError("Only a load or a move chooses a slot")
        if self.operation == "heat" and not 4 <= self.value <= 120:
            raise ValueError("Teaching temperature must be 4–120 °C")
        return self


class Draft(StrictModel):
    steps: list[Step] = Field(max_length=MAX_STEPS)


class SaveWorkflow(Draft):
    expected_version: int = Field(ge=0, strict=True)
    title: str = Field(min_length=1, max_length=80)


class RunWorkflow(StrictModel):
    expected_version: int = Field(ge=0, strict=True)


def contract_steps(steps):
    """The workflow as `execute_mock` steps; a move starts wherever its sample is."""
    where = {}
    out = []
    for index, step in enumerate(steps):
        key, at = step["sample"], step["instrument"]
        if step["operation"] == "transfer":
            source = where.get(key)
            name = spec_of(at)["name"]
            if source is None:
                raise PlanError("state", f"Step {index + 1}: load {key} before moving it")
            if source == at:
                raise PlanError("state", f"Step {index + 1}: {key} is already at {name}")
            out.append(
                {
                    "device_id": HANDLER,
                    "operation": "transfer",
                    "source_id": source,
                    "target_id": at,
                    "sample": key,
                    "value": 1,
                    "target_site": step["slot"],
                }
            )
            where[key] = at
        else:
            if step["operation"] == "load":
                where.setdefault(key, at)
            out.append(
                {
                    "device_id": at,
                    "operation": step["operation"],
                    "sample": key,
                    "value": step["value"],
                    "site": step["slot"],
                }
            )
    return out


def check(steps):
    """The synthetic trace of a workflow, or the first step that breaks a twin's rules."""
    try:
        trace = execute_mock(twins({s["instrument"] for s in steps}), contract_steps(steps))
    except PlanError as exc:
        found = STEP_AT.match(str(exc))
        return {
            "ok": False,
            "trace": [],
            "error": {
                "step": int(found[1]) if found else None,
                "message": str(exc),
                "layer": exc.layer,
            },
        }
    for entry, step in zip(trace, steps, strict=True):
        # The station that acted, as the learner wrote it: a move is the instrument it
        # moved to.
        entry["device_id"] = step["instrument"]
    return {"ok": True, "trace": trace, "error": None}


def chemlab_entry(key):
    """A ChemLab-Assets twin in the shape of the cloud lab instruments."""
    asset = CHEMLAB[key.removeprefix(CHEMLAB_PREFIX)]
    spec = asset["spec"]
    return {
        "id": key,
        "name": spec["name"],
        "section": "ChemLab-Assets",
        "experiment": asset["domain"],
        "published": asset["attribution"],
        "narrowed": "Operations, vessel, volume and limits are Academy teaching defaults, "
        "not the manufacturer's specification.",
        "operations": spec["operations"],
        "holds": spec["container"],
        "limits": spec["limits"],
        "consumables": spec["consumables"],
        "stand_in": None,
        "slots": site_keys(spec),
    }


def catalog(extra=()):
    """The designer's instruments, then any ChemLab-Assets twins in `extra`."""
    shown = {i["id"]: i for i in overview()["instruments"]}
    chemlab = [chemlab_entry(k) for k in dict.fromkeys(extra) if k not in INSTRUMENTS]
    return [
        {
            **{
                k: shown[key][k]
                for k in (
                    "id",
                    "name",
                    "section",
                    "experiment",
                    "published",
                    "narrowed",
                    "operations",
                    "holds",
                    "limits",
                    "consumables",
                    "stand_in",
                )
            },
            "slots": site_keys(CLOUDLAB[key]["spec"]),
        }
        for key in INSTRUMENTS
    ] + chemlab


def step(instrument, operation, value=1, sample="plate", slot=""):
    return {
        "instrument": instrument,
        "operation": operation,
        "sample": sample,
        "value": value,
        "slot": slot,
    }


STARTERS = {
    "cell-assay": {
        "title": "Cell assay readout",
        "steps": [
            step("robotic-sample-preparation", "load", 200),
            step("robotic-sample-preparation", "mix", 30),
            step("cell-incubator", "transfer"),
            step("cell-incubator", "heat", 37),
            step("cell-incubator", "wait", 600),
            step("plate-washer", "transfer"),
            step("plate-washer", "mix", 60),
            step("plate-reader", "transfer"),
            step("plate-reader", "read"),
        ],
    },
    "pcr-sizing": {
        "title": "PCR then fragment sizing",
        "steps": [
            step("thermocycler", "load", 50),
            step("thermocycler", "heat", 95),
            step("thermocycler", "wait", 30),
            step("thermocycler", "heat", 60),
            step("thermocycler", "wait", 60),
            step("capillary-electrophoresis", "transfer"),
            step("capillary-electrophoresis", "read"),
        ],
    },
}


def initial():
    return {"version": 0, "title": "Cloud lab workflow", "steps": [], "runs": []}


class CloudLabWorkflows:
    def __init__(self, store, learn=None):
        self.store = store
        # What a run adds to the learner's skill tree: a write, and what is new.
        self.learn = learn

    def record(self, owner):
        return self.store.get(owner, KEY) or initial()

    def view(self, record):
        return {
            **record,
            "check": check(record["steps"]),
            "instruments": catalog(s["instrument"] for s in record["steps"]),
            "starters": STARTERS,
            "statement": STATEMENT,
            "evidence": "synthetic",
        }

    def get(self, owner):
        return self.view(self.record(owner))

    def current(self, owner, expected):
        record = self.record(owner)
        if record["version"] != expected:
            raise Conflict
        return record

    def put(self, owner, record, expected):
        record["version"] = expected + 1
        self.store.put(owner, KEY, record, expected or None)
        return self.view(record)

    def save(self, owner, data):
        """Save a draft as written; a draft may still break a rule, and its check says so."""
        record = self.current(owner, data.expected_version)
        record["title"] = data.title.strip() or initial()["title"]
        record["steps"] = [s.model_dump() for s in data.steps]
        return self.put(owner, record, data.expected_version)

    def run(self, owner, data):
        record = self.current(owner, data.expected_version)
        if not record["steps"]:
            raise HTTPException(422, "Add a step before running the workflow")
        result = check(record["steps"])
        if not result["ok"]:
            raise HTTPException(422, result["error"])
        run = {
            "id": str(uuid4()),
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "title": record["title"],
            "steps": record["steps"],
            "trace": result["trace"],
            "statement": STATEMENT,
            "evidence": "synthetic",
        }
        record["runs"] = [run, *record["runs"]][:KEPT_RUNS]
        record["version"] = data.expected_version + 1
        writes = [Write(owner, KEY, record, data.expected_version or None)]
        earned = None
        if self.learn:
            write, earned = self.learn(owner, record["steps"])
            if write:
                writes.append(write)
        # The run and what it earned are saved together or not at all.
        self.store.transact(writes)
        return {**self.view(record), "earned": earned}
