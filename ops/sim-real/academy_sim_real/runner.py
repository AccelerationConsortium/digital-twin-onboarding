"""Run a compiled Sim–Real plan: one SiLA command at a time, on simulated connectors,
and then, when asked, the same plan on the connectors of the instruments themselves.

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

from .launch import LaunchError, address, attached, running

REPORT = "simreal.report/1"
INSTRUMENT = "instrument"  # the evidence of a run that reached one; never kept as simulation
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


def _checked(plan):
    """The plan's devices that have a connector, once the plan is the one that was compiled."""
    if plan.get("schema") != compiler.PLAN or not plan.get("valid"):
        raise LaunchError("Give a valid compiled plan; compile the workflow first")
    if compiler.digest(plan) != plan.get("digest"):
        raise LaunchError("The plan was changed after it was compiled")
    bound = {d["id"]: d for d in plan["devices"] if d["connector"]}
    for device in bound.values():
        pinned = bindings.manifest(device["connector"])
        if {f["id"]: f["sha256"] for f in pinned["features"]} != plan["connectors"][
            device["connector"]
        ]["features"]:
            raise LaunchError(
                f"The plan was compiled against another {device['connector']} release"
            )
    return bound


def instruments(plan, pairs):
    """Where each of a plan's connectors runs on its instrument, from `device=host[:port]`.

    A real run is whole: every device with a connector is an instrument, or none is.
    """
    bound = _checked(plan)
    found = {}
    for pair in pairs:
        device, _, where = pair.partition("=")
        if device not in bound or not where:
            raise LaunchError(f"Give instruments as device=host[:port]; got {pair}")
        address(bound[device]["connector"], where)
        found[device] = where
    for device, record in bound.items():
        if device not in found:
            address(record["connector"], "unset")  # says so when it has no real run at all
            raise LaunchError(f"Give the address of {device}'s connector, or run in simulation")
    return found


async def run_plan(plan, installed, *, workdir=None):
    """Run every step of a valid plan on simulated connectors and return its report."""
    bound = _checked(plan)
    for device in bound.values():
        if device["connector"] not in installed:
            raise LaunchError(f"No installation given for the {device['connector']} connector")
    report = _report(plan, compiler.EVIDENCE)
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
        await _steps(plan, live, report)
    return _finished(report)


async def run_real(plan, where, rehearsal):
    """Run a plan on the connectors of its instruments, after it passed in simulation.

    `where` comes from `instruments`; `rehearsal` is the report of this plan's simulated
    run. Steps that only tell a simulator about its scene are left out.
    """
    bound = _checked(plan)
    if (
        not isinstance(rehearsal, dict)
        or rehearsal.get("schema") != REPORT
        or rehearsal.get("evidence") != compiler.EVIDENCE
        or rehearsal.get("plan_digest") != plan["digest"]
        or rehearsal.get("outcome") != "passed"
    ):
        raise LaunchError(
            "An instrument takes a plan only after that plan passed in simulation; nothing was sent"
        )
    if set(where) != set(bound):
        raise LaunchError("Give the address of every connector of the plan")
    report = _report(plan, INSTRUMENT)
    report["rehearsal"] = {
        k: rehearsal.get(k) for k in ("outcome", "started_at", "finished_at", "wall_s")
    }
    async with contextlib.AsyncExitStack() as stack:
        live = {}
        for key, device in bound.items():
            connector = await stack.enter_async_context(
                attached(device["connector"], where[key], device=key)
            )
            for feature, _ in world.READBACK[device["connector"]]:
                if feature not in connector.served:
                    raise LaunchError(
                        f"The {device['name']} connector there does not serve {feature}, so "
                        "its state cannot be read back; nothing was sent"
                    )
            live[key] = connector
            report["connectors"][key] = {
                "connector": device["connector"],
                "server": connector.server,
                "address": f"{connector.host}:{connector.port}",
                "features": {i: fdl.digest(x) for i, x in sorted(connector.served.items())},
            }
        await _steps(plan, live, report, simulated=False)
    return _finished(report)


def _report(plan, evidence):
    return {
        "schema": REPORT,
        "evidence": evidence,
        "plan_digest": plan["digest"],
        "name": plan["name"],
        "started_at": time.time(),
        "connectors": {},
        "steps": [],
        "outcome": "passed",
        "stopped_at": None,
        "reason": None,
    }


async def _steps(plan, live, report, *, simulated=True):
    """Send the plan's commands to the connectors in `live`, filling in the report."""
    devices = {d["id"]: d for d in plan["devices"]}
    names = {key: d["name"] for key, d in devices.items()}
    state = world.start(
        {
            key: {**d, "sites": None}  # slots were checked when the plan was compiled
            for key, d in devices.items()
        },
        plan["labware"],
    )
    responses = {}
    started = await _readback(live, state)
    if started:
        report.update(
            outcome="diverged",
            reason=(
                "A connector did not start in the state the plan assumes"
                if simulated
                else "An instrument is not in the state the plan starts from; nothing was sent"
            ),
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
        if step.get("simulation_only") and not simulated:
            entry["status"] = "skipped"
            state = trial
            continue
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
    report["world"] = world.snapshot(state)


def _finished(report):
    report["finished_at"] = time.time()
    report["wall_s"] = round(report["finished_at"] - report["started_at"], 2)
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
