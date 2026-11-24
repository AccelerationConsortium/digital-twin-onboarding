"""Run a compiled Sim–Real plan: one SiLA command at a time, on simulated connectors.

Before each command the world model must allow its effect; after it every connector is
read back and compared with the world. A refused effect, a connector error or a
difference stops the run there. Nothing is retried.
"""

import contextlib
import json
import tempfile
import time
import uuid
from copy import deepcopy
from pathlib import Path

from academy.simreal import bindings, compiler, fdl, world

from .launch import LaunchError, running

REPORT = "simreal.report/1"
KEEP = 2000  # characters of a response kept in the report


def _plain(value):
    """A SiLA response as JSON data: long text cut, embedded JSON reduced to its plain facts."""
    data = json.loads(json.dumps(value, default=str))
    if isinstance(data, dict):
        for key, item in data.items():
            # The arm connector answers with JSON text holding whole trajectories.
            if isinstance(item, str) and item.startswith("{"):
                with contextlib.suppress(ValueError):
                    data[key] = {
                        k: v
                        for k, v in json.loads(item).items()
                        if isinstance(v, (str, int, float, bool)) and len(str(v)) <= 200
                    }

    def cut(item):
        if isinstance(item, str) and len(item) > KEEP:
            return item[:KEEP] + "…"
        if isinstance(item, list):
            return [cut(v) for v in item]
        if isinstance(item, dict):
            return {k: cut(v) for k, v in item.items()}
        return item

    return cut(data)


def _lookup(value, path):
    """Follow a path into a response; text on the way is JSON the connector returned."""
    for key in path:
        if isinstance(value, str):
            value = json.loads(value)
        value = value[key]
    return value


def resolve(arguments, responses):
    """Arguments with their run-time values: earlier responses, fresh ids, expiry times."""

    def one(value):
        if isinstance(value, dict) and "$response" in value:
            return _lookup(responses[value["$response"]], value["path"])
        if isinstance(value, dict) and "$uuid" in value:
            return str(uuid.uuid4())
        if isinstance(value, dict) and "$expires_in" in value:
            return time.time() + value["$expires_in"]
        if isinstance(value, dict):
            return {k: one(v) for k, v in value.items()}
        if isinstance(value, list):
            return [one(v) for v in value]
        return value

    return {k: one(v) for k, v in arguments.items()}


async def _readback(live, state):
    """Differences between what every connector reports and what the world expects."""
    found = []
    for device, connector in live.items():
        readings = {key: await connector.read(*key) for key in world.READBACK[connector.key]}
        found += world.differences(
            device,
            world.expected(state, device, connector.key),
            world.observed(connector.key, readings),
        )
    return found


async def run_plan(plan, installed, *, workdir=None):
    """Run every step of a valid plan and return its report."""
    if plan.get("schema") != compiler.PLAN or not plan.get("valid"):
        raise LaunchError("Give a valid compiled plan; compile the workflow first")
    if compiler.digest(plan) != plan.get("digest"):
        raise LaunchError("The plan was changed after it was compiled")
    devices = {d["id"]: d for d in plan["devices"]}
    bound = {key: d for key, d in devices.items() if d["connector"]}
    for device in bound.values():
        if device["connector"] not in installed:
            raise LaunchError(f"No installation given for the {device['connector']} connector")
        pinned = bindings.manifest(device["connector"])
        if {f["id"]: f["sha256"] for f in pinned["features"]} != plan["connectors"][
            device["connector"]
        ]["features"]:
            raise LaunchError(
                f"The plan was compiled against another {device['connector']} release"
            )
    names = {key: d["name"] for key, d in devices.items()}
    state = world.start(
        {
            key: {**d, "sites": None}  # slots were checked when the plan was compiled
            for key, d in devices.items()
        },
        plan["labware"],
    )
    report = {
        "schema": REPORT,
        "evidence": compiler.EVIDENCE,
        "plan_digest": plan["digest"],
        "name": plan["name"],
        "started_at": time.time(),
        "connectors": {},
        "steps": [],
        "outcome": "passed",
        "stopped_at": None,
        "reason": None,
    }
    responses = {}
    async with contextlib.AsyncExitStack() as stack:
        root = Path(workdir or stack.enter_context(tempfile.TemporaryDirectory(prefix="simreal-")))
        live = {}
        for key, device in bound.items():
            connector = await stack.enter_async_context(
                running(
                    device["connector"],
                    installed[device["connector"]],
                    root / key,
                    device=key,
                    options=device["options"],
                )
            )
            live[key] = connector
            described = installed[device["connector"]].describe(
                bindings.profile(device["connector"])["package"]
            )
            report["connectors"][key] = {
                "connector": device["connector"],
                "server": connector.server,
                **described,
                "features": {i: fdl.digest(x) for i, x in sorted(connector.served.items())},
            }
        started = await _readback(live, state)
        if started:
            report.update(
                outcome="diverged",
                reason="A connector did not start in the state the plan assumes",
                differences=started,
            )
        for step in plan["steps"] if not started else []:
            entry = {
                "id": step["id"],
                "cycle": step.get("cycle", 1),
                "device": step["device"],
                "feature": step["feature"],
                "command": step["command"],
            }
            report["steps"].append(entry)
            try:
                trial = deepcopy(state)
                for effect in step["effects"]:
                    world.apply(trial, effect, names)
            except world.WorldError as exc:
                entry.update(status="refused", layer=exc.layer, error=str(exc))
                report.update(outcome="refused", stopped_at=step["id"], reason=str(exc))
                break
            connector = live[step["device"]]
            began = time.monotonic()
            try:
                answer = await connector.execute(
                    step["feature"], step["command"], resolve(step["arguments"], responses)
                )
            except Exception as exc:  # a SiLA error of any kind ends the run
                entry.update(
                    status="failed",
                    wall_s=round(time.monotonic() - began, 3),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                report.update(
                    outcome="failed",
                    stopped_at=step["id"],
                    reason=f"{names[step['device']]} refused {step['command']}: {exc}",
                )
                break
            entry["wall_s"] = round(time.monotonic() - began, 3)
            reported = world.device_seconds(step["feature"], step["command"], answer)
            if reported is not None:
                entry["device_s"] = round(reported, 3)
            responses[step["id"]] = answer
            entry["response"] = _plain(answer)
            state = trial
            differences = await _readback(live, state)
            if differences:
                entry.update(status="diverged", differences=differences)
                first = differences[0]
                report.update(
                    outcome="diverged",
                    stopped_at=step["id"],
                    reason=(
                        f"After {step['command']}, {names[first['device']]} reports "
                        f"{first['field']} {first['observed']}; the plan expects "
                        f"{first['expected']}"
                    ),
                )
                break
            entry["status"] = "done"
    report["finished_at"] = time.time()
    report["wall_s"] = round(report["finished_at"] - report["started_at"], 2)
    report["world"] = world.snapshot(state)
    cycles = {}
    for entry in report["steps"]:
        cycle = cycles.setdefault(
            entry["cycle"], {"cycle": entry["cycle"], "steps": 0, "wall_s": 0.0, "device_s": 0.0}
        )
        cycle["steps"] += 1
        cycle["wall_s"] = round(cycle["wall_s"] + entry.get("wall_s", 0.0), 3)
        # What the instruments say the cycle takes: their own durations where they report one.
        cycle["device_s"] = round(
            cycle["device_s"] + entry.get("device_s", entry.get("wall_s", 0.0)), 3
        )
    report["cycles"] = list(cycles.values())
    return report
