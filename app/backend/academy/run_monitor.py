"""Run a saved workcell workflow with its state twin alongside and ahead of execution.

Three layers guard every step:

1. Lookahead: after each step the executor's observation is synced into the state
   twin, which simulates the next steps from there and blocks the run before the first
   step it predicts will fail (out of tips, a sample missing, a door open, ...).
2. Motion pre-validation: before an arm transfer the planner checks the path against
   the layout as last observed (`workcell_layout.plan_transfer`; no geometry here).
3. Divergence: each observation is compared with what the twin expected; a difference
   beyond tolerance pauses the run and names the fields.

Execution goes through the `Executor` protocol. Only the in-process mock is wired here,
so every run is synthetic and never physical. A real connector would implement the same
protocol behind an operator-approved gateway.
"""

from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from typing import Annotated, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from labtwin import Evidence, Fact, Observation, Outcome, Status, compare
from pydantic import Field

from . import state_twin
from .auth import identify
from .mock_contract import PlanError
from .models import StrictModel
from .store import Write
from .workcell_layout import MotionError, plan_transfer, validate_layout

PREFIX = "twin-run#"
WORKSPACE = "simple-lab"
router = APIRouter(prefix="/api/twin-runs")

# Field kind -> (unit, frame, tolerance). Counts and categories must match exactly.
TOLERANCES = {
    "volume_ul": ("uL", "", 0.5),
    "temperature_c": ("degC", "", 0.5),
    "stock": ("count", "", 0.0),
    "busy": ("s", "", 0.5),
    "x": ("m", "bench", 0.01),
    "z": ("m", "bench", 0.01),
    "yaw": ("deg", "bench", 1.0),
}


# --- executor interface ---------------------------------------------------------------


class Executor(Protocol):
    """What the monitor needs from whatever carries out the steps.

    `observe` and the `observed` of `execute` return a full twin state (see
    `state_twin`), as the executor itself sees the cell. `snapshot` is what to persist
    between requests; the monitor never reads inside it.
    """

    kind: str
    transport: str
    evidence: str  # "synthetic" for the mock; a real connector reports its own
    physical: bool

    def observe(self) -> dict: ...

    def execute(self, number: int, step: dict) -> dict: ...

    def snapshot(self) -> dict: ...


class TipShortfall(StrictModel):
    """The rack holds fewer than declared. It is not counted until first used."""

    kind: Literal["tip_shortfall"]
    device_id: UUID
    consumable: str = Field(min_length=1, max_length=80)
    actual: int = Field(ge=0, le=100_000)


class VolumeLoss(StrictModel):
    kind: Literal["volume_loss"]
    step: int = Field(ge=1, le=48)
    sample: str = Field(default="sample", max_length=24)
    loss_ul: float = Field(gt=0, le=100_000, allow_inf_nan=False)


class DoorOpen(StrictModel):
    kind: Literal["door_open"]
    step: int = Field(ge=0, le=48)
    device_id: UUID


class GripperStuck(StrictModel):
    """The arm finishes a transfer still holding the sample."""

    kind: Literal["gripper_stuck"]
    step: int = Field(ge=1, le=48)


class LayoutShift(StrictModel):
    kind: Literal["layout_shift"]
    step: int = Field(ge=0, le=48)
    twin_id: UUID
    dx: float = Field(ge=-0.5, le=0.5, allow_inf_nan=False)
    dz: float = Field(ge=-0.5, le=0.5, allow_inf_nan=False)


Fault = Annotated[
    TipShortfall | VolumeLoss | DoorOpen | GripperStuck | LayoutShift,
    Field(discriminator="kind"),
]


class MockExecutor:
    """The in-process mock connector: the same contract, plus injected faults.

    Its world is a twin state that the faults make differ from the declared one. With
    no faults it reports exactly what the twin expects.
    """

    kind = "mock"
    transport = "in-process-mock"
    evidence = "synthetic"
    physical = False

    def __init__(self, twins, snapshot):
        self.twins = twins
        self.world = deepcopy(snapshot["world"])
        self.faults = snapshot["faults"]
        self.hidden = deepcopy(snapshot["hidden"])

    @classmethod
    def start(cls, twins, layout, faults):
        world = state_twin.initial(twins, layout)
        hidden = {}
        for fault in faults:
            if fault["kind"] == "tip_shortfall":
                items = world["stock"][fault["device_id"]]
                hidden.setdefault(fault["device_id"], {})[fault["consumable"]] = (
                    items[fault["consumable"]] - fault["actual"]
                )
                items[fault["consumable"]] = fault["actual"]
        executor = cls(twins, {"world": world, "faults": faults, "hidden": hidden})
        executor.disturb(0, None)
        return executor

    def snapshot(self):
        return {"world": deepcopy(self.world), "faults": self.faults, "hidden": self.hidden}

    def observe(self):
        seen = deepcopy(self.world)
        for device, items in self.hidden.items():
            for name, missing in items.items():
                seen["stock"][device][name] += missing
        return seen

    def execute(self, number, step):
        try:
            self.world, _ = state_twin.advance(self.twins, self.world, step, number)
        except state_twin.TwinFault as fault:
            return {"status": "failed", "error": str(fault), "observed": self.observe()}
        spec = self.twins[step["device_id"]]["spec"]
        for item in spec["consumables"]:
            if item["used_by"] == step["operation"]:
                # Using the rack is what counts it.
                self.hidden.get(step["device_id"], {}).pop(item["name"], None)
        self.disturb(number, step)
        return {"status": "succeeded", "error": "", "observed": self.observe()}

    def disturb(self, number, step):
        world = self.world
        for fault in self.faults:
            if fault.get("step") != number:
                continue
            key = fault.get("sample", "sample")
            if fault["kind"] == "volume_loss" and key in world["samples"]:
                sample = world["samples"][key]
                sample["volume_ul"] = max(0.0, sample["volume_ul"] - fault["loss_ul"])
            elif fault["kind"] == "door_open":
                world["doors"][fault["device_id"]] = "open"
            elif fault["kind"] == "gripper_stuck" and step and step["operation"] == "transfer":
                key = step.get("sample") or "sample"
                world["samples"][key].update(location=step["device_id"], site=None)
                world["gripper"][step["device_id"]] = key
            elif fault["kind"] == "layout_shift" and fault["twin_id"] in world["placements"]:
                at = world["placements"][fault["twin_id"]]
                at["x"] = round(at["x"] + fault["dx"], 6)
                at["z"] = round(at["z"] + fault["dz"], 6)


class ReplayExecutor:
    """Replays a recorded run: the twin's model plus the differences it observed.

    Each recorded divergence is reapplied after its step: numeric fields by the amount
    they differed, the others as observed. An edited quantity replaces what was recorded
    for it. Steps the original run never reached go as the model predicts.
    """

    kind = "replay"
    transport = "recorded-trace"
    evidence = "synthetic"
    physical = False

    def __init__(self, twins, world, disturbances):
        self.twins = twins
        self.world = deepcopy(world)
        self.disturbances = disturbances

    def snapshot(self):
        return {"world": deepcopy(self.world)}

    def observe(self):
        return deepcopy(self.world)

    def execute(self, number, step):
        try:
            self.world, _ = state_twin.advance(self.twins, self.world, step, number)
        except state_twin.TwinFault as fault:
            return {"status": "failed", "error": str(fault), "observed": self.observe()}
        for change in self.disturbances.get(number, []):
            _assign(self.world, change)
        return {"status": "succeeded", "error": "", "observed": self.observe()}


def _assign(state, change):
    path = change["field"].split(".")
    group = path[0]
    if group in {"gripper", "doors", "busy"}:
        target, key = state[group], path[1]
    elif group == "stock":
        target, key = state["stock"].setdefault(path[1], {}), ".".join(path[2:])
    elif group == "placements":
        target, key = state["placements"].setdefault(path[1], {}), path[2]
    elif group == "samples" and path[1] in state["samples"]:
        target, key = state["samples"][path[1]], path[2]
    else:
        return
    if "delta" in change and isinstance(target.get(key), (int, float)):
        target[key] = round(target[key] + change["delta"], 6)
    else:
        target[key] = change["observed"]


# --- divergence -----------------------------------------------------------------------


def _kind(field):
    group = field.split(".", 1)[0]
    return group if group in {"stock", "busy"} else field.rsplit(".", 1)[-1]


def _fact(field, value, evidence):
    unit, frame, _ = TOLERANCES.get(_kind(field), ("", "", 0.0))
    return Fact("" if value is None else value, evidence, unit, frame)


def divergence(expected, observed, evidence="synthetic"):
    """Fields where an observation differs from the twin's expectation beyond tolerance.

    Uses the shared operation-boundary comparison, so units and frames must agree.
    """
    want, seen = state_twin.flatten(expected), state_twin.flatten(observed)
    want.pop("elapsed_s"), seen.pop("elapsed_s")
    source = Evidence.HARDWARE if evidence == "hardware" else Evidence.SIMULATED
    sim = Outcome(
        Status.SUCCEEDED,
        Observation("state-twin", {k: _fact(k, v, Evidence.SIMULATED) for k, v in want.items()}),
    )
    real = Outcome(
        Status.SUCCEEDED,
        Observation("executor", {k: _fact(k, v, source) for k, v in seen.items()}),
    )
    tolerances = {k: TOLERANCES.get(_kind(k), ("", "", 0.0))[2] for k in want.keys() & seen.keys()}
    out = []
    for result in compare(real, sim, tolerances):
        if result.status == "different":
            out.append(_difference(result.field, want[result.field], seen[result.field]))
    for key in sorted(want.keys() ^ seen.keys()):
        out.append(_difference(key, want.get(key), seen.get(key)))
    return sorted(out, key=lambda d: d["field"])


def _difference(field, expected, observed):
    entry = {"field": field, "expected": expected, "observed": observed}
    numeric = all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in (expected, observed)
    )
    if numeric:
        entry["delta"] = round(observed - expected, 6)
    return entry


def _describe(twins, differences):
    names = {i: t["spec"]["name"] for i, t in twins.items()}

    def label(field):
        parts = field.split(".")
        if parts[0] == "stock":
            return f"{names.get(parts[1], 'instrument')} {'.'.join(parts[2:])}"
        if parts[0] == "samples":
            return f"{parts[1]} {parts[2].replace('_', ' ')}"
        return f"{names.get(parts[1], parts[1])} {parts[0].rstrip('s')}" + (
            f" {parts[2]}" if len(parts) > 2 else ""
        )

    def shown(value):
        return names.get(value, value) if isinstance(value, str) else value

    return "; ".join(
        f"{label(d['field'])}: expected {shown(d['expected'])}, observed {shown(d['observed'])}"
        for d in differences[:3]
    ) + (f"; {len(differences) - 3} more" if len(differences) > 3 else "")


# --- monitor --------------------------------------------------------------------------


def _layout_key(layout):
    return hashlib.sha256(json.dumps(layout, sort_keys=True).encode()).hexdigest()[:16]


def _motion(twins, run, number, step, sites):
    """Layer 2: the next transfer's path, planned on the layout as last observed."""
    layout = state_twin.layout_of(run["twin"], run["layout"])
    key = _layout_key(layout)
    cached = run.get("next") or {}
    if cached.get("step") == number and (cached.get("motion") or {}).get("layout_key") == key:
        return cached["motion"], None
    try:
        validate_layout(twins, layout)
        planned = plan_transfer(twins, layout, number, step, sites)
    except (MotionError, PlanError) as exc:
        attempt = getattr(exc, "attempt", None) or {}
        return None, {"message": str(exc), "blocked_by": attempt.get("blocked_by")}
    precomputed = next((m for m in run["motions"] if m["step"] == number), None)
    return {
        "layout_key": key,
        "replanned": key != run["layout_key"],
        "planner": planned["planner"],
        "length_m": planned["length_m"],
        "clearance_m": planned["clearance_m"],
        "seconds": planned["seconds"],
        "precomputed_length_m": precomputed and precomputed["length_m"],
        "joints": planned["joints"],
        "path": [frame[-1] for frame in planned["frames"]],
    }, None


def prepare(run, twins):
    """Look ahead from the synced state; block before a step predicted to fail."""
    cursor, steps = run["cursor"], run["steps"]
    if cursor >= len(steps):
        run.update(status="completed", next=None, prediction=None)
        return run
    look = state_twin.lookahead(twins, run["twin"], steps, cursor, run["horizon"])
    run["prediction"] = look
    number, step = cursor + 1, steps[cursor]
    failure = look["failure"]
    ghost = {
        "step": number,
        "operation": step["operation"],
        "device_id": step["device_id"],
        "source_id": step["source_id"],
        "target_id": step["target_id"],
        "sample": step.get("sample") or "sample",
        "motion": None,
        "changes": [],
    }
    if failure and failure["step"] == number:
        run.update(
            status="blocked",
            next=ghost,
            pause={"kind": "predicted", "layer": "lookahead", **failure, "fields": []},
        )
        return run
    expected, entry = state_twin.advance(twins, run["twin"], step, number)
    ghost["changes"] = state_twin.change(run["twin"], expected)
    if step["operation"] == "transfer" and run["layout"]:
        motion, error = _motion(twins, run, number, step, (entry["source_site"], entry["site"]))
        ghost["motion"] = motion
        if error:
            run.update(
                status="blocked",
                next=ghost,
                pause={
                    "kind": "motion",
                    "layer": "motion",
                    "step": number,
                    "code": "path_blocked",
                    "message": error["message"],
                    "blocked_by": error["blocked_by"],
                    "fields": [],
                },
            )
            return run
    run.update(status="ready", next=ghost, pause=None)
    return run


def tick(run, twins, executor):
    """Execute the next step, compare, sync and look ahead again."""
    number, step = run["cursor"] + 1, run["steps"][run["cursor"]]
    expected, _ = state_twin.advance(twins, run["twin"], step, number)
    result = executor.execute(number, step)
    observed = result["observed"]
    differences = divergence(expected, observed, executor.evidence)
    motion = (run.get("next") or {}).get("motion")
    entry = {
        "step": number,
        "operation": step["operation"],
        "device_id": step["device_id"],
        "status": result["status"],
        "expected": state_twin.change(run["twin"], expected),
        "observed": state_twin.change(run["twin"], observed),
        "divergence": differences,
        "motion": motion and {k: v for k, v in motion.items() if k not in {"joints", "path"}},
    }
    run["trace"].append(entry)
    run["twin"] = state_twin.sync(observed)
    if result["status"] != "succeeded":
        run.update(
            status="failed",
            next=None,
            pause={
                "kind": "failed",
                "layer": "executor",
                "step": number,
                "code": "step_failed",
                "message": result["error"],
                "fields": differences,
            },
        )
        return _remember(run)
    run["cursor"] = number
    # Look ahead even when pausing, so the ghost shows what comes next.
    prepare(run, twins)
    if differences:
        pause = {
            "kind": "diverged",
            "layer": "divergence",
            "step": number,
            "code": "diverged",
            "message": f"Step {number}: {_describe(twins, differences)}",
            "fields": differences,
        }
        # A divergence on the last step is still reported on the completed run.
        run.update(status=run["status"] if run["status"] == "completed" else "paused", pause=pause)
    return _remember(run)


def _remember(run):
    """Keep every distinct pause, so a replay can say which one it would avoid."""
    pause = run.get("pause")
    if pause and (not run["pauses"] or run["pauses"][-1] != pause):
        run["pauses"].append(pause)
    return run


def command(run, twins, executor, name):
    status = run["status"]
    if name in {"step", "run"}:
        if status != "ready":
            raise HTTPException(
                409,
                "Resume the run before the next step"
                if status in {"paused", "blocked"}
                else f"This run is {status}",
            )
        for _ in range(1 if name == "step" else len(run["steps"])):
            tick(run, twins, executor)
            if run["status"] != "ready":
                break
    elif name == "resume":
        if status not in {"paused", "blocked"}:
            raise HTTPException(409, f"Only a paused or blocked run resumes; this one is {status}")
        run["twin"] = state_twin.sync(executor.observe())
        _remember(prepare(run, twins))
    elif name == "stop":
        if status not in {"ready", "paused", "blocked"}:
            raise HTTPException(409, f"This run is already {status}")
        run.update(status="stopped", next=None)
    return run


# --- persistence and routes -----------------------------------------------------------


class CreateRun(StrictModel):
    run_id: UUID
    expected_version: int = Field(ge=1, strict=True)
    horizon: int = Field(default=3, ge=1, le=12)
    faults: list[Fault] = Field(default_factory=list, max_length=6)


class RunCommand(StrictModel):
    expected_version: int = Field(ge=1, strict=True)
    command: Literal["step", "run", "resume", "stop"]


class Placement(StrictModel):
    x: float = Field(ge=-2, le=2, allow_inf_nan=False)
    z: float = Field(ge=-1.5, le=1.5, allow_inf_nan=False)
    yaw: float = Field(default=0, ge=-180, le=180, allow_inf_nan=False)


class Counterfactual(StrictModel):
    """What to change in a replay: counts in racks, step values, instrument positions."""

    stock: dict[UUID, dict[str, int]] = Field(default_factory=dict, max_length=12)
    step_values: dict[int, float] = Field(default_factory=dict, max_length=48)
    placements: dict[UUID, Placement] = Field(default_factory=dict, max_length=12)


def _twins(run):
    return {t["id"]: t for t in run["twins"]}


def _check_faults(faults, twins, steps, layout):
    for fault in faults:
        device = fault.get("device_id")
        if device and device not in twins:
            raise ValueError("A fault names an instrument that is not in this workcell")
        if fault.get("step", 0) > len(steps):
            raise ValueError(f"The workflow has only {len(steps)} steps")
        if fault["kind"] == "tip_shortfall":
            stock = {c["name"]: c["stock"] for c in twins[device]["spec"]["consumables"]}
            if fault["consumable"] not in stock:
                raise ValueError(f"{twins[device]['spec']['name']} has no {fault['consumable']}")
            if fault["actual"] >= stock[fault["consumable"]]:
                raise ValueError("A shortfall leaves fewer than the declared stock")
        if fault["kind"] == "door_open" and twins[device]["spec"].get("access") != "front":
            raise ValueError(f"{twins[device]['spec']['name']} has no door")
        if fault["kind"] == "gripper_stuck" and steps[fault["step"] - 1]["operation"] != "transfer":
            raise ValueError(f"Step {fault['step']} is not an arm transfer")
        if fault["kind"] == "layout_shift":
            placed = {p["twin_id"] for p in (layout or {}).get("placements", [])}
            if fault["twin_id"] not in placed:
                raise ValueError("Only an instrument placed on the bench can shift")


def _summary(run):
    return {
        k: run[k]
        for k in ("run_id", "version", "status", "cursor", "created_at", "workspace_version")
    } | {"steps": len(run["steps"]), "faults": len(run["faults"])}


def _get(store, owner, run_id):
    run = store.get(owner, PREFIX + str(run_id))
    if not run:
        raise HTTPException(404, "Monitored run not found")
    return run


@router.get("")
def list_runs(request: Request, owner: str = Depends(identify)):
    runs = request.app.state.store.partition(owner, PREFIX, limit=20)
    return sorted((_summary(r) for r in runs), key=lambda r: -r["created_at"])


@router.post("")
def create(data: CreateRun, request: Request, owner: str = Depends(identify)):
    store = request.app.state.store
    existing = store.get(owner, PREFIX + str(data.run_id))
    if existing:
        if existing["workspace_version"] != data.expected_version:
            raise HTTPException(409, "This run ID belongs to another saved revision")
        return existing
    raw = store.get(owner, WORKSPACE)
    if not raw or not raw.get("steps"):
        raise HTTPException(422, "Save a workflow before running")
    if raw["version"] != data.expected_version:
        raise HTTPException(409, "Reload the workcell before starting a monitored run")
    service = request.app.state.twins
    record = service.get(owner)
    trace = service.check_plan(record, record["steps"])
    layout = deepcopy(record.get("layout"))
    steps = deepcopy(record["steps"])
    used = {s[k] for s in steps for k in ("device_id", "source_id", "target_id") if s[k]}
    placed = {p["twin_id"] for p in (layout or {}).get("placements", [])}
    twins = {
        t["id"]: {k: deepcopy(t[k]) for k in ("id", "confirmed", "mode", "spec", "revision")}
        for t in record["twins"]
        if t["id"] in used | placed and t["spec"]
    }
    faults = [f.model_dump(mode="json") for f in data.faults]
    try:
        _check_faults(faults, twins, steps, layout)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    executor = MockExecutor.start(twins, layout, faults)
    run = start(
        twins,
        steps,
        layout,
        [entry["motion"] for entry in trace if entry.get("motion")],
        executor,
        data.horizon,
    )
    now = time.time()
    run.update(
        run_id=str(data.run_id),
        version=1,
        workspace_version=data.expected_version,
        faults=faults,
        created_at=now,
        updated_at=now,
    )
    # Binds the run to the saved revision without changing the workspace.
    store.transact(
        [
            Write(owner, WORKSPACE, raw, data.expected_version),
            Write(owner, PREFIX + str(data.run_id), run, None),
        ]
    )
    return run


def start(twins, steps, layout, motions, executor, horizon, declared=None):
    """A new monitored run, synced to the executor's first observation."""
    declared = declared or state_twin.initial(twins, layout)
    observed = executor.observe()
    differences = divergence(declared, observed, executor.evidence)
    run = {
        "engine": "state-twin-monitor",
        "evidence": "synthetic",
        "simulation_mode": True,
        "physical_execution": False,
        "executor": {
            "kind": executor.kind,
            "transport": executor.transport,
            "snapshot": executor.snapshot(),
        },
        "twins": list(twins.values()),
        "steps": steps,
        "layout": layout,
        "layout_key": _layout_key(layout),
        "motions": [
            {k: m[k] for k in ("step", "planner", "length_m", "clearance_m", "seconds")}
            for m in motions
        ],
        "horizon": horizon,
        "cursor": 0,
        "initial": {"declared": declared, "observed": observed, "divergence": differences},
        "twin": state_twin.sync(observed),
        "trace": [],
        "status": "ready",
        "pause": None,
        "pauses": [],
        "next": None,
        "prediction": None,
    }
    prepare(run, twins)
    if differences and run["status"] == "ready":
        run.update(
            status="paused",
            pause={
                "kind": "diverged",
                "layer": "divergence",
                "step": 0,
                "code": "diverged",
                "message": f"Before step 1: {_describe(twins, differences)}",
                "fields": differences,
            },
        )
    return _remember(run)


@router.get("/{run_id}")
def get(run_id: UUID, request: Request, owner: str = Depends(identify)):
    return _get(request.app.state.store, owner, run_id)


@router.post("/{run_id}/commands")
def run_command(run_id: UUID, data: RunCommand, request: Request, owner: str = Depends(identify)):
    store = request.app.state.store
    old = _get(store, owner, run_id)
    if old["version"] != data.expected_version:
        raise HTTPException(409, "Reload the monitored run before issuing another command")
    run = deepcopy(old)
    twins = _twins(run)
    executor = MockExecutor(twins, run["executor"]["snapshot"])
    command(run, twins, executor, data.command)
    run["executor"]["snapshot"] = executor.snapshot()
    run.update(version=old["version"] + 1, updated_at=time.time())
    store.put(owner, PREFIX + str(run_id), run, old["version"])
    return run


def outcome(run):
    pause = run.get("pause") or {}
    stopped = run["status"] != "completed"
    return {
        "status": run["status"],
        "step": pause.get("step") if stopped else len(run["steps"]),
        "code": pause.get("code") if stopped else None,
        "message": pause.get("message", "") if stopped else "",
        "steps_run": run["cursor"],
    }


def counterfactual(run, edits):
    """Replay a recorded run in the twin with edited parameters. Pure and deterministic.

    Edits apply to the plan and the cell alike: a rack edited to 50 tips is declared and
    holds 50. The replay resumes through divergences, as an operator would, and stops
    where the live run would block or fail.
    """
    twins = _twins(run)
    steps = deepcopy(run["steps"])
    for number, value in edits.get("step_values", {}).items():
        if not 1 <= number <= len(steps):
            raise ValueError(f"The workflow has only {len(steps)} steps")
        if steps[number - 1]["operation"] == "transfer":
            raise ValueError(f"Step {number} is a transfer and has no value")
        steps[number - 1]["value"] = value
    world = deepcopy(run["initial"]["observed"])
    declared = deepcopy(run["initial"]["declared"])
    edited = set()
    for device, items in edits.get("stock", {}).items():
        if device not in world["stock"]:
            raise ValueError("Edited stock names an instrument with no consumables")
        for name, count in items.items():
            if name not in world["stock"][device]:
                raise ValueError(f"No consumable {name} to edit")
            world["stock"][device][name] = declared["stock"][device][name] = count
            edited.add(f"stock.{device}.{name}")
    for twin, at in edits.get("placements", {}).items():
        if twin not in world["placements"]:
            raise ValueError("Only an instrument placed on the bench can move")
        world["placements"][twin] = dict(at)
        declared["placements"][twin] = dict(at)
        edited |= {f"placements.{twin}.{axis}" for axis in ("x", "z", "yaw")}
    disturbances = {
        entry["step"]: [d for d in entry["divergence"] if d["field"] not in edited]
        for entry in run["trace"]
    }
    executor = ReplayExecutor(twins, world, disturbances)
    replay = start(twins, steps, run["layout"], [], executor, run["horizon"], declared)
    replay["motions"] = run["motions"]
    for _ in range(2 * len(steps) + 2):
        if replay["status"] == "paused":
            replay["twin"] = state_twin.sync(executor.observe())
            _remember(prepare(replay, twins))
        elif replay["status"] == "ready":
            tick(replay, twins, executor)
        else:
            break
    stops = {(p["step"], p["code"]) for p in replay["pauses"]}
    target = (run.get("pauses") or [None])[-1]
    reached = max((e["step"] for e in run["trace"]), default=0)
    return {
        "evidence": "synthetic",
        "physical_execution": False,
        "edits": {
            "stock": {d: dict(i) for d, i in edits.get("stock", {}).items()},
            "step_values": {str(k): v for k, v in edits.get("step_values", {}).items()},
            "placements": {t: dict(a) for t, a in edits.get("placements", {}).items()},
        },
        "original": outcome(run),
        "replay": outcome(replay),
        # Whether the last stop of the recorded run would not happen with these edits.
        "avoided": None if target is None else (target["step"], target["code"]) not in stops,
        "stops": [
            {k: p.get(k) for k in ("step", "kind", "code", "message")} for p in replay["pauses"]
        ],
        "assumption": f"Steps after step {reached} never ran; the replay assumes they go "
        "as the twin predicts."
        if reached < len(steps)
        else "",
        "trace": [
            {k: e[k] for k in ("step", "operation", "status", "divergence")}
            for e in replay["trace"]
        ],
    }


@router.post("/{run_id}/counterfactual")
def replay(run_id: UUID, data: Counterfactual, request: Request, owner: str = Depends(identify)):
    run = _get(request.app.state.store, owner, run_id)
    edits = data.model_dump(mode="json")
    edits["step_values"] = {int(k): v for k, v in edits["step_values"].items()}
    try:
        return counterfactual(run, edits)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


__all__ = [
    "Executor",
    "MockExecutor",
    "ReplayExecutor",
    "command",
    "counterfactual",
    "divergence",
    "prepare",
    "router",
    "start",
    "tick",
]
