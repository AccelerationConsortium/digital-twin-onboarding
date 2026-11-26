"""Check a run report against the plan it claims to have run, before it is kept.

Both arrive from a browser, so neither is trusted to have the shape a compiler or a
runner writes: anything else is refused by name, and what is kept is bounded.
"""

import json
import math

from . import bindings, compiler

REPORT = "simreal.report/1"
OUTCOMES = ("passed", "failed", "diverged", "refused")
MAX_STEPS = compiler.MAX_COMMANDS
MAX_CYCLES = 50
MAX_DEVICES = 12
# A kept run is one stored item, and DynamoDB holds 400 KB in one.
MAX_RECORD_BYTES = 380_000
MAX_WORLD_BYTES = 20_000
# Each connector reports at most two differences after a command.
MAX_DIFFERENCES = 2 * MAX_DEVICES
MAX_DIFFERENCES_BYTES = 8_000
# What a plan's digest is taken over; a step without them is not a compiled step.
STEP_KEYS = ("id", "device", "feature", "command", "arguments", "effects")


class ReportError(ValueError):
    """A report that does not belong to the plan, or was not made by pinned connectors."""


def _rows(value, what, limit):
    """A list of objects no longer than `limit`."""
    if (
        not isinstance(value, list)
        or len(value) > limit
        or not all(isinstance(row, dict) for row in value)
    ):
        raise ReportError(f"{what} are missing")
    return value


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return round(float(value), 3)


def _whole(value, what):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_STEPS:
        raise ReportError(f"{what} is not a count")
    return value


def _text(value, limit):
    return None if value is None or value == "" else str(value)[:limit]


def _size(value):
    return len(json.dumps(value, allow_nan=False))


def _bounded(value, kind, limit, what):
    """`value` when it is absent or a small `kind`; reports hold nothing larger."""
    if value is None:
        return None
    try:
        fits = isinstance(value, kind) and _size(value) <= limit
    except ValueError:  # a number JSON cannot hold
        fits = False
    if not fits:
        raise ReportError(f"{what} is not what a run writes")
    return value


def _differences(value):
    if value is not None:
        _rows(value, "A step's differences", MAX_DIFFERENCES)
    return _bounded(value, list, MAX_DIFFERENCES_BYTES, "A step's differences")


def _compiled(plan):
    """The plan's steps and its devices with connectors, once it has a compiled plan's shape."""
    if plan.get("schema") != compiler.PLAN:
        raise ReportError("The plan was changed after it was compiled")
    steps = _rows(plan.get("steps"), "The plan's steps", MAX_STEPS)
    devices = _rows(plan.get("devices"), "The plan's devices", MAX_DEVICES)
    pinned = plan.get("connectors")
    bound = {}
    for device in devices:
        key = device.get("connector")
        if key is None:
            continue
        if (
            not isinstance(device.get("id"), str)
            or not isinstance(key, str)
            or key not in bindings.PROFILES
            or not isinstance(pinned, dict)
            or not isinstance(pinned.get(key), dict)
            or not isinstance(pinned[key].get("features"), dict)
        ):
            raise ReportError("Not a compiled Sim–Real plan")
        bound[device["id"]] = key
    if not all(isinstance(s.get("id"), str) and all(k in s for k in STEP_KEYS) for s in steps):
        raise ReportError("Not a compiled Sim–Real plan")
    if compiler.digest(plan) != plan.get("digest"):
        raise ReportError("The plan was changed after it was compiled")
    if not plan.get("valid"):
        raise ReportError("Only a plan that compiled without problems can have a run")
    return steps, bound


def check(plan, report):
    """A compact, verified record of one simulated run; raises ReportError otherwise."""
    plan_steps, bound = _compiled(plan)
    if report.get("schema") != REPORT:
        raise ReportError("Not a Sim–Real run report")
    if report.get("evidence") != compiler.EVIDENCE:
        # A run that reached an instrument is not a teaching result and is not stored as one.
        raise ReportError("Only simulated runs are kept here; this report is not one")
    if report.get("plan_digest") != plan["digest"]:
        raise ReportError("The report is for another plan")
    if report.get("outcome") not in OUTCOMES:
        raise ReportError("Unknown outcome")
    steps = _rows(report.get("steps"), "The report's steps", MAX_STEPS)
    cycles = _rows(report.get("cycles") or [], "The report's cycles", MAX_CYCLES)
    planned = [s["id"] for s in plan_steps]
    ran = [s.get("id") for s in steps]
    if ran != planned[: len(ran)]:
        raise ReportError("The report's steps are not the plan's steps in order")
    done = sum(s.get("status") == "done" for s in steps)
    if report["outcome"] == "passed" and (done != len(planned) or len(ran) != len(planned)):
        raise ReportError("A passed run completes every step of the plan")
    if report["outcome"] != "passed" and done == len(planned):
        raise ReportError("A run that completed every step passed")
    served = report.get("connectors")
    if (
        not isinstance(served, dict)
        or set(served) != set(bound)
        or not all(isinstance(entry, dict) for entry in served.values())
    ):
        raise ReportError("The report does not name the plan's connectors")
    for device, key in bound.items():
        pinned = plan["connectors"][key]["features"]
        features = served[device].get("features") or {}
        if (
            not isinstance(features, dict)
            or served[device].get("connector") != key
            or any(pinned.get(identifier) != digest for identifier, digest in features.items())
        ):
            raise ReportError(
                f"{bindings.profile(key)['name']} served features the plan was not compiled against"
            )
    record = {
        "schema": REPORT,
        "evidence": compiler.EVIDENCE,
        "name": _text(plan.get("name"), 80),
        "plan_digest": plan["digest"],
        "outcome": report["outcome"],
        "stopped_at": _text(report.get("stopped_at"), 80),
        "reason": _text(report.get("reason"), 600),
        "started_at": _number(report.get("started_at")),
        "wall_s": _number(report.get("wall_s")),
        "device_s": _number(sum(_number(c.get("device_s")) or 0 for c in cycles)),
        "cycles": [
            {
                "cycle": _whole(c.get("cycle"), "A cycle's number"),
                "steps": _whole(c.get("steps"), "A cycle's step count"),
                "wall_s": _number(c.get("wall_s")),
                "device_s": _number(c.get("device_s")),
            }
            for c in cycles
        ],
        "connectors": {
            device: {
                "connector": bound[device],
                "package_version": _text(served[device].get("package_version"), 40),
                "commit": _text(served[device].get("commit"), 40),
                "dirty": served[device].get("dirty")
                if isinstance(served[device].get("dirty"), bool)
                else None,
                "features": len(served[device].get("features") or {}),
            }
            for device in bound
        },
        "steps": [
            {
                "id": s["id"],
                "cycle": _whole(s.get("cycle", 1), "A step's cycle"),
                "device": _text(s.get("device"), 40),
                "command": _text(s.get("command"), 100),
                "status": _text(s.get("status"), 20),
                "wall_s": _number(s.get("wall_s")),
                "device_s": _number(s.get("device_s")),
                "error_type": _text(s.get("error_type"), 80),
                "error": _text(s.get("error"), 400),
                "differences": _differences(s.get("differences")),
            }
            for s in steps
        ],
        "world": _bounded(report.get("world"), dict, MAX_WORLD_BYTES, "The report's final world"),
    }
    if _size(record) > MAX_RECORD_BYTES:
        raise ReportError("The run is too long to keep")
    return record
