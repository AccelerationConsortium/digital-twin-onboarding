"""The Academy as a headless simulation and readiness node: version 1 of its service API.

Other platforms (a cloud lab portal, a university lab's scheduler, an agent harness) call
these routes without adopting the Academy's own workspace. Simulate, validate and replay
are stateless: the caller sends the devices, steps and optional bench layout, and nothing
is stored. Devices are either inline twin specs or entries of the instrument library.
Assess checks a signed training record. Every answer is synthetic teaching evidence, never
Isaac/GPU, robot or chemical validation, and never permission to run anything.
"""

from copy import deepcopy
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, model_validator

from . import cloudlab_training, opentrons_check, sll_adapter
from .auth import identify
from .library import COLLECTIONS
from .mock_contract import PlanError, execute_mock
from .models import Action, StrictModel
from .simple_twins import OPERATIONS, LayoutDraft, Step, TwinSpec
from .workcell_layout import plan_workflow, validate_layout

VERSION = "node/1"
LAYERS = ["volume", "resource", "geometry", "container", "consumable", "state", "constraint"]
# What an observation is compared on, and the twin layer a mismatch belongs to.
OBSERVABLE = {"volume_ul": "volume", "temperature_c": "constraint", "location": "state"}
EVIDENCE = "synthetic"


class LibraryRef(StrictModel):
    collection: str = Field(min_length=1, max_length=20)
    id: str = Field(min_length=1, max_length=80)


class Device(StrictModel):
    id: UUID
    spec: TwinSpec | None = None
    library: LibraryRef | None = None

    @model_validator(mode="after")
    def one_source(self):
        if (self.spec is None) == (self.library is None):
            raise ValueError("Give each device either a spec or a library entry")
        return self


class Workflow(StrictModel):
    devices: list[Device] = Field(min_length=1, max_length=12)
    steps: list[Step] = Field(min_length=1, max_length=48)
    layout: LayoutDraft | None = None


class Observation(StrictModel):
    step: int = Field(ge=1, le=48)
    volume_ul: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    temperature_c: float | None = Field(default=None, ge=-80, le=400, allow_inf_nan=False)
    location: UUID | None = None


class Replay(Workflow):
    observed: list[Observation] = Field(min_length=1, max_length=48)
    volume_tolerance_ul: float = Field(default=1, ge=0, le=1000)
    temperature_tolerance_c: float = Field(default=1, ge=0, le=50)


class Assess(StrictModel):
    record: dict


class SllProgram(StrictModel):
    program: str = Field(min_length=1, max_length=sll_adapter.MAX_LENGTH)
    instrument: Literal["flex", "ot2"] = "flex"
    source_volume: float = Field(ge=0, le=15000)


class OpentronsPlan(StrictModel):
    instrument: Literal["flex", "ot2"] = "flex"
    source_volume: float = Field(ge=0, le=15000)
    diluent_volume: float = Field(default=0, ge=0, le=2000)
    actions: list[Action] = Field(min_length=1, max_length=64)


def twins(devices):
    """The devices as confirmed mock twins, the only kind the command contract runs."""
    found = {}
    for device in devices:
        if device.library:
            entry = COLLECTIONS.get(device.library.collection, {}).get(device.library.id)
            if entry is None:
                raise HTTPException(
                    422, f"Unknown library entry {device.library.collection}:{device.library.id}"
                )
            spec = deepcopy(entry["spec"])
        else:
            spec = device.spec.model_dump(mode="json")
        key = str(device.id)
        if key in found:
            raise HTTPException(422, "Each device needs its own id")
        found[key] = {"id": key, "spec": spec, "confirmed": True, "mode": "mock"}
    return found


def plan(data):
    """The trace of a workflow, or the first failure and the twin layer it belongs to."""
    devices = twins(data.devices)
    steps = [s.model_dump(mode="json") for s in data.steps]
    try:
        trace = execute_mock(devices, steps)
        if data.layout:
            layout = data.layout.model_dump(mode="json")
            unknown = {p["twin_id"] for p in layout["placements"]} - set(devices)
            if unknown:
                raise HTTPException(422, "Place only devices listed in this request")
            validate_layout(devices, layout)
            for motion in plan_workflow(devices, layout, steps):
                trace[motion["step"] - 1]["motion"] = motion
    except PlanError as exc:
        return None, {"message": str(exc), "layer": exc.layer}
    return trace, None


def residuals(trace, data):
    """Where observations differ from the simulated trace, shaped like twin residuals."""
    found = []
    for seen in data.observed:
        if seen.step > len(trace):
            raise HTTPException(422, f"Step {seen.step} is not in the workflow")
        predicted = trace[seen.step - 1]
        for field, layer in OBSERVABLE.items():
            value = getattr(seen, field)
            if value is None:
                continue
            expected = predicted["location" if field == "location" else field]
            if field == "location":
                differs = str(value) != expected
            else:
                tolerance = (
                    data.volume_tolerance_ul
                    if field == "volume_ul"
                    else data.temperature_tolerance_c
                )
                differs = expected is None or abs(value - expected) > tolerance
            if differs:
                found.append(
                    {
                        "step": seen.step,
                        "layer": layer,
                        "field": field,
                        "predicted": expected,
                        "observed": str(value) if field == "location" else value,
                    }
                )
    return found


def install(app):
    settings = app.state.settings
    router = APIRouter(prefix="/api/node/v1")

    @router.get("/capabilities")
    def capabilities(_owner: str = Depends(identify)):
        return {
            "version": VERSION,
            "operations": OPERATIONS,
            "layers": LAYERS,
            "library": {name: len(entries) for name, entries in COLLECTIONS.items()},
            "services": ["simulate", "validate", "replay", "assess"],
            "adapters": ["opentrons", "sll-pipetting-subset"],
            "rules": {
                "training": cloudlab_training.RULES,
                "opentrons_api": opentrons_check.API_LEVEL,
            },
            "limits": {"devices": 12, "steps": 48},
            "evidence": EVIDENCE,
        }

    @router.post("/validate")
    def validate(data: Workflow, _owner: str = Depends(identify)):
        trace, error = plan(data)
        return {
            "version": VERSION,
            "valid": error is None,
            "error": error,
            "steps": len(trace or []),
            "evidence": EVIDENCE,
        }

    @router.post("/simulate")
    def simulate(data: Workflow, _owner: str = Depends(identify)):
        trace, error = plan(data)
        return {
            "version": VERSION,
            "valid": error is None,
            "error": error,
            "trace": trace or [],
            "evidence": EVIDENCE,
        }

    @router.post("/replay")
    def replay(data: Replay, _owner: str = Depends(identify)):
        """Compare what a run reported with what the twins predicted for the same workflow."""
        trace, error = plan(data)
        if error:
            return {
                "version": VERSION,
                "valid": False,
                "error": error,
                "residuals": [],
                "evidence": EVIDENCE,
            }
        found = residuals(trace, data)
        return {
            "version": VERSION,
            "valid": True,
            "error": None,
            "matches": not found,
            "residuals": found,
            "evidence": EVIDENCE,
        }

    @router.post("/assess")
    def assess(data: Assess, _owner: str = Depends(identify)):
        return {"version": VERSION, **cloudlab_training.verify(data.record, settings)}

    @router.post("/adapters/opentrons/validate")
    def opentrons(data: OpentronsPlan, _owner: str = Depends(identify)):
        """An Opentrons Flex or OT-2 transfer plan, under the rules `opentrons_simulate` applies."""
        result = opentrons_check.check(
            {
                "instrument": data.instrument,
                "source_volume": data.source_volume,
                "diluent_volume": data.diluent_volume,
                "actions": [a.model_dump() for a in data.actions],
            }
        )
        return {"version": VERSION, "valid": not result["stops"], **result}

    @router.post("/adapters/sll/validate")
    def sll(data: SllProgram, _owner: str = Depends(identify)):
        """SLL pipetting unit operations, read without evaluation and checked as a plan."""
        try:
            units, actions, unsupported = sll_adapter.translate(data.program)
        except sll_adapter.SllError as exc:
            return {
                "version": VERSION,
                "valid": False,
                "error": {"message": str(exc), "position": exc.position},
                "units": [],
                "unsupported": [],
                "evidence": EVIDENCE,
            }
        if not actions:
            result = {"stops": [], "unnoticed": []}
        else:
            result = opentrons_check.check(
                {
                    "instrument": data.instrument,
                    "source_volume": data.source_volume,
                    "diluent_volume": 0,
                    "actions": actions,
                }
            )
        return {
            "version": VERSION,
            "valid": bool(actions) and not result["stops"] and not unsupported,
            "error": None,
            "units": units,
            "unsupported": unsupported,
            "actions": actions,
            "stops": result["stops"],
            "unnoticed": result["unnoticed"],
            "evidence": EVIDENCE,
        }

    app.include_router(router)
