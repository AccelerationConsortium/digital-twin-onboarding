"""Check a run report against the plan it claims to have run, before it is kept."""

from . import bindings, compiler

REPORT = "simreal.report/1"
OUTCOMES = ("passed", "failed", "diverged", "refused")
MAX_STEPS = 4000


class ReportError(ValueError):
    """A report that does not belong to the plan, or was not made by pinned connectors."""


def check(plan, report):
    """A compact, verified record of one simulated run; raises ReportError otherwise."""
    if plan.get("schema") != compiler.PLAN or compiler.digest(plan) != plan.get("digest"):
        raise ReportError("The plan was changed after it was compiled")
    if not plan.get("valid"):
        raise ReportError("Only a plan that compiled without problems can have a run")
    if report.get("schema") != REPORT or report.get("evidence") != compiler.EVIDENCE:
        raise ReportError("Not a Sim–Real run report")
    if report.get("plan_digest") != plan["digest"]:
        raise ReportError("The report is for another plan")
    if report.get("outcome") not in OUTCOMES:
        raise ReportError("Unknown outcome")
    steps = report.get("steps")
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        raise ReportError("The report's steps are missing")
    planned = [s["id"] for s in plan["steps"]]
    ran = [s.get("id") for s in steps]
    if ran != planned[: len(ran)]:
        raise ReportError("The report's steps are not the plan's steps in order")
    done = sum(s.get("status") == "done" for s in steps)
    if report["outcome"] == "passed" and (done != len(planned) or len(ran) != len(planned)):
        raise ReportError("A passed run completes every step of the plan")
    if report["outcome"] != "passed" and done == len(planned):
        raise ReportError("A run that completed every step passed")
    bound = {d["id"]: d["connector"] for d in plan["devices"] if d["connector"]}
    served = report.get("connectors") or {}
    if set(served) != set(bound):
        raise ReportError("The report does not name the plan's connectors")
    for device, key in bound.items():
        pinned = plan["connectors"][key]["features"]
        features = served[device].get("features") or {}
        if served[device].get("connector") != key or any(
            pinned.get(identifier) != digest for identifier, digest in features.items()
        ):
            raise ReportError(
                f"{bindings.profile(key)['name']} served features the plan was not compiled against"
            )

    def number(value):
        return round(float(value), 3) if isinstance(value, (int, float)) else None

    return {
        "schema": REPORT,
        "evidence": compiler.EVIDENCE,
        "name": plan["name"],
        "plan_digest": plan["digest"],
        "outcome": report["outcome"],
        "stopped_at": report.get("stopped_at"),
        "reason": (report.get("reason") or None) and str(report["reason"])[:600],
        "started_at": number(report.get("started_at")),
        "wall_s": number(report.get("wall_s")),
        "device_s": number(sum(c.get("device_s", 0) for c in report.get("cycles", []))),
        "cycles": [
            {
                "cycle": int(c["cycle"]),
                "steps": int(c["steps"]),
                "wall_s": number(c.get("wall_s")),
                "device_s": number(c.get("device_s")),
            }
            for c in report.get("cycles", [])[:50]
        ],
        "connectors": {
            device: {
                "connector": bound[device],
                "package_version": str(served[device].get("package_version"))[:40],
                "commit": served[device].get("commit"),
                "dirty": served[device].get("dirty"),
                "features": len(served[device].get("features") or {}),
            }
            for device in bound
        },
        "steps": [
            {
                "id": s["id"],
                "cycle": int(s.get("cycle", 1)),
                "device": s.get("device"),
                "command": s.get("command"),
                "status": s.get("status"),
                "wall_s": number(s.get("wall_s")),
                "device_s": number(s.get("device_s")),
                "error_type": s.get("error_type"),
                "error": (s.get("error") or None) and str(s["error"])[:400],
                "differences": s.get("differences"),
            }
            for s in steps
        ],
        "world": report.get("world"),
    }
