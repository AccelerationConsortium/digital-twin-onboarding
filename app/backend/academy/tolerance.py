"""How far each instrument and the arm may sit off their planned spots before a transfer fails.

Every check replans the saved workflows with `plan_workflow` on a misplaced copy of the
layout, as if the arm were taught the positions the instruments actually have. Three
parts, run as one fixed list of tasks:

1. Bands. For every instrument on the bench, every axis (bench x and z, yaw about its
   placement origin, height for the ones the arm serves) and both directions, the largest
   error the workflow still plans at: coarse steps outward, then bisection between the
   last pass and the first failure. The first failure says which transfer stops and why
   (unreachable, collision with what, joint limit, footprint overlap).
2. Combined errors. At a ladder of ± tolerances every instrument is misplaced at once,
   half the samples at the corners of the band and half inside it, giving the share of
   layouts that still plan at each tolerance. The same for the arm base pose.
3. Arm calibration. The arm base is a subject like any instrument. With the gripper
   pointing down, a tool longer than modelled is the same as the base sitting lower, and
   a sideways tool offset is taken as the base moved that way along the bench.

The work is chunked like the layout search: a request plans until its time cap, at
least once, and returns `next` with the trail of the task in progress. The client sends
back `done` and `next`; the summary is rebuilt from them on every request. The same
inputs, seed and `done` always give the same answer. Synthetic teaching geometry only:
not calibrated, Isaac/GPU or physical robot validation.
"""

import hashlib
import json
import math
import random
import re
import time
from collections import OrderedDict
from copy import deepcopy

from . import arm_simulation
from .mock_contract import PlanError
from .workcell_layout import GRASP_TOLERANCE, corners, plan_workflow

CHUNK_SECONDS = 6.0
# Axis: (furthest error checked, resolution of the band edge). Metres, yaw in degrees.
AXES = {
    "x": (0.12, 0.002),
    "z": (0.12, 0.002),
    "yaw": (15.0, 0.25),
    "height": (0.06, 0.002),
}
RELATIVE = 0.1  # a band edge is found to a tenth of the band, or the axis resolution
COARSE = (1 / 16, 1 / 8, 1 / 4, 1 / 2, 1)  # shares of the limit tried before bisecting
# Combined tolerances: (± metres, ± degrees), the same ladder for every instrument.
LEVELS = ((0.002, 0.5), (0.005, 1.0), (0.01, 2.0), (0.02, 4.0), (0.04, 8.0), (0.08, 15.0))
SAMPLES = 12
FAIL_STOP = 3  # failures after which a level stops drawing samples
Z95 = 1.645  # one-sided 95% normal quantile for the Wilson lower bound
GROUPS = ("instruments", "arm")
VERDICTS = 4096
_verdicts = OrderedDict()


def workflows_of(named):
    """[(name, steps)] with at least one transfer each, identical workflows once."""
    out, seen = [], set()
    for name, steps in named:
        key = json.dumps(steps, sort_keys=True)
        if key in seen or not any(s["operation"] == "transfer" for s in steps):
            continue
        seen.add(key)
        out.append((name, steps))
    if not out:
        raise PlanError("state", "Save a workflow with a transfer step first")
    return out


def subjects(twins, layout, workflows):
    """(twin_id, role, axes) for every placed instrument: served, others, then the arms."""
    arms, served = set(), set()
    for _, steps in workflows:
        for s in steps:
            if s["operation"] == "transfer":
                arms.add(s["device_id"])
                served.update((s["source_id"], s["target_id"]))
    rows = {"station": [], "spare": [], "arm": []}
    for p in layout["placements"]:
        twin_id = p["twin_id"]
        role = "arm" if twin_id in arms else "station" if twin_id in served else "spare"
        rows[role].append((twin_id, role, tuple(AXES) if role != "spare" else ("x", "z", "yaw")))
    return rows["station"] + rows["spare"] + rows["arm"]


def tasks(twins, layout, workflows, samples):
    out = []
    for twin_id, _role, axes in subjects(twins, layout, workflows):
        for axis in axes:
            for sign in (-1, 1):
                for w in range(len(workflows)):
                    out.append(("band", twin_id, axis, sign, w))
    for group in GROUPS:
        for level in range(len(LEVELS)):
            for index in range(samples):
                out.append(("sample", group, level, index))
    return out


def raised(twin, dh):
    """The twin standing dh higher: its parts, deck level and so its top all move up."""
    spec = deepcopy(twin["spec"])
    for part in spec["parts"]:
        part["position"] = [part["position"][0], part["position"][1] + dh, part["position"][2]]
    if spec.get("level_m") is not None:
        spec["level_m"] = spec["level_m"] + dh
    return {**twin, "spec": spec}


def shifted(twins, layout, moves):
    """(twins, layout) with each twin in `moves` off by {x, z, yaw, height} (metres, °)."""
    placements, twins = [], dict(twins)
    for p in layout["placements"]:
        move = moves.get(p["twin_id"])
        if not move:
            placements.append(p)
            continue
        placements.append(
            {
                **p,
                "x": round(p["x"] + move.get("x", 0.0), 5),
                "z": round(p["z"] + move.get("z", 0.0), 5),
                "yaw": round(p["yaw"] + move.get("yaw", 0.0), 4),
            }
        )
        if move.get("height"):
            twins[p["twin_id"]] = raised(twins[p["twin_id"]], move["height"])
    return twins, {**layout, "placements": placements}


def _name(twins, twin_id):
    twin = twins.get(twin_id)
    return twin["spec"]["name"] if twin else "an instrument"


def classify(exc, twins, steps):
    """What stopped the plan: cause, step, transfer, blocker and link."""
    message = str(exc)
    attempt = getattr(exc, "attempt", None) or {}
    found = re.match(r"Step (\d+)", message)
    step = attempt.get("step") or (int(found.group(1)) if found else None)
    transfer = None
    if step and 0 < step <= len(steps) and steps[step - 1]["operation"] == "transfer":
        s = steps[step - 1]
        transfer = f"{_name(twins, s['source_id'])} → {_name(twins, s['target_id'])}"
    blocker, link = attempt.get("blocked_by"), attempt.get("link")
    low = message.lower()
    if "overlaps" in low:
        cause = "overlap"
        blocker = message.split(" overlaps ", 1)[1]
    elif "past the bench edge" in low:
        cause, blocker = "bench edge", None
    elif blocker or " hit" in low:
        cause = "collision"
        if not blocker:
            hit = re.search(
                r"the (.+?) (?:would hit|hits) (.+?)(?: on the way in| \(|;|$)", message
            )
            if hit:
                link, blocker = hit.group(1), hit.group(2)
    elif "joint torque" in low:
        cause = "torque"
    elif "strays" in low or "too long to simulate" in low:
        cause = "tracking"
    elif "reaches about" in low or "cannot hold the gripper" in low:
        cause = "unreachable"
    elif "elbow" in low or "joint limits" in low or "wrist flip" in low:
        cause = "joint limit"
    else:
        cause = "other"
    return {
        "ok": False,
        "cause": cause,
        "step": step,
        "transfer": transfer,
        "blocker": blocker,
        "link": link,
        "message": message[:400],
    }


OK = {"ok": True, "cause": None, "step": None, "transfer": None, "blocker": None, "link": None}


def verdict(twins, layout, steps):
    """Whether the workflow plans on this layout; the reason when it does not. Memoised."""
    used = sorted({p["twin_id"] for p in layout["placements"]})
    key = hashlib.sha256(
        json.dumps(
            [
                arm_simulation.available(),
                layout,
                steps,
                [
                    [t, twins[t]["spec"], twins[t].get("source"), twins[t].get("asset")]
                    for t in used
                ],
            ],
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    if key not in _verdicts:
        try:
            plan_workflow(twins, layout, steps)
            _verdicts[key] = dict(OK, message=None)
        except PlanError as exc:
            _verdicts[key] = classify(exc, twins, steps)
        if len(_verdicts) > VERDICTS:
            _verdicts.popitem(last=False)
    _verdicts.move_to_end(key)
    return dict(_verdicts[key])


def bisect(axis, trail):
    """('probe', distance) for the next check of a band, or ('done', band, saturated, limit).

    Coarse steps outward stop at the first failure, then the bracket is halved until it
    is narrower than the axis resolution or a tenth of the band, whichever is wider. The
    band is the largest distance that passed; `limit` is the check that failed just beyond.
    """
    furthest, resolution = AXES[axis]
    i, lo, hi, limit = 0, 0.0, None, None
    for share in COARSE:
        step = round(furthest * share, 6)
        if i == len(trail):
            return ("probe", step)
        result, i = trail[i], i + 1
        if result["ok"]:
            lo = step
        else:
            hi, limit = step, result
            break
    else:
        return ("done", furthest, True, None)
    while hi - lo > max(resolution, lo * RELATIVE) + 1e-9:
        mid = round((lo + hi) / 2, 6)
        if i == len(trail):
            return ("probe", mid)
        result, i = trail[i], i + 1
        if result["ok"]:
            lo = mid
        else:
            hi, limit = mid, result
    return ("done", lo, False, limit)


def offsets(group, level, index, seed, members):
    """Errors for one combined sample: even samples at the band corners, odd ones inside."""
    rng = random.Random(f"{seed}:{group}:{level}:{index}")
    metres, degrees = LEVELS[level]

    def draw(size):
        return size * rng.choice((-1, 1)) if index % 2 == 0 else rng.uniform(-size, size)

    moves = {}
    for twin_id in members:
        move = {"x": draw(metres), "z": draw(metres), "yaw": draw(degrees)}
        if group == "arm":
            move["height"] = draw(metres)
        moves[twin_id] = move
    return moves


def members(group, twins, layout, workflows):
    rows = subjects(twins, layout, workflows)
    return [t for t, role, _ in rows if (role == "arm") == (group == "arm")]


def _skipped(task, done, samples):
    """A level stops after FAIL_STOP failures; higher levels once a lower one is below half."""
    _, group, level, _ = task
    by_level = {}
    for result in done:
        key = result.get("group"), result.get("level")
        if result.get("kind") == "sample" and key[0] == group and not result["skipped"]:
            by_level.setdefault(key[1], []).append(all(r["ok"] for r in result["results"]))
    here = by_level.get(level, [])
    if sum(not ok for ok in here) >= FAIL_STOP:
        return True
    for lower in range(level):
        runs = by_level.get(lower, [])
        if runs and sum(runs) / len(runs) < 0.5:
            return True
    return False


def matches(task, result, index):
    """Whether a result handed back by the client is the one this task would produce."""
    if result.get("task") != index or result.get("kind") != task[0]:
        return False
    if task[0] == "band":
        keys = ("twin_id", "axis", "sign", "workflow")
    else:
        keys = ("group", "level", "index")
    return all(result.get(k) == v for k, v in zip(keys, task[1:], strict=True))


def analyse(
    twins,
    layout,
    named,
    done=(),
    start=0,
    trail=(),
    seed=0,
    samples=SAMPLES,
    target=0.99,
    seconds=None,
):
    """One chunk of the tolerance analysis, and the summary of everything done so far."""
    workflows = workflows_of(named)
    plan = tasks(twins, layout, workflows, samples)
    done = [dict(d) for d in done]
    if (
        start != len(done)
        or start > len(plan)
        or (trail and start >= len(plan))
        or not all(matches(plan[i], r, i) for i, r in enumerate(done))
    ):
        raise PlanError("state", "This analysis does not match the layout; start it again")
    if not done and not trail:
        # The layout itself has to carry every workflow first.
        for name, steps in workflows:
            nominal = verdict(twins, layout, steps)
            if not nominal["ok"]:
                raise PlanError(
                    "geometry", f"{name} cannot run on this layout: {nominal['message']}"
                )
    deadline = time.monotonic() + (CHUNK_SECONDS if seconds is None else seconds)
    trail, index, checked = [dict(t) for t in trail], start, 0
    while index < len(plan) and (not checked or time.monotonic() < deadline):
        task = plan[index]
        if task[0] == "band":
            _, twin_id, axis, sign, w = task
            state = bisect(axis, trail)
            if state[0] == "probe":
                moved = shifted(twins, layout, {twin_id: {axis: sign * state[1]}})
                check = verdict(*moved, workflows[w][1])
                if check["cause"] == "overlap" and check["blocker"] == _name(twins, twin_id):
                    # Name the instrument it runs into, not the one that moved.
                    check["blocker"] = check["message"].split(" overlaps ", 1)[0]
                trail.append(check)
                checked += 1
                continue
            _, band, saturated, limit = state
            done.append(
                {
                    "task": index,
                    "kind": "band",
                    "twin_id": twin_id,
                    "axis": axis,
                    "sign": sign,
                    "workflow": w,
                    "band": round(band, 6),
                    "saturated": saturated,
                    "limit": limit,
                    "checks": len(trail),
                }
            )
        else:
            _, group, level, sample = task
            result = {
                "task": index,
                "kind": "sample",
                "group": group,
                "level": level,
                "index": sample,
                "skipped": False,
                "results": [],
            }
            if _skipped(task, done, samples):
                result["skipped"] = True
            else:
                moves = offsets(
                    group, level, sample, seed, members(group, twins, layout, workflows)
                )
                moved = shifted(twins, layout, moves)
                while len(trail) < len(workflows):
                    trail.append(verdict(*moved, workflows[len(trail)][1]))
                    checked += 1
                    if time.monotonic() > deadline and len(trail) < len(workflows):
                        break
                if len(trail) < len(workflows):
                    continue
                result["results"] = trail
            done.append(result)
        trail, index = [], index + 1
    return {
        "total": len(plan),
        "next": index if index < len(plan) else None,
        "trail": trail,
        "done": done,
        "checked": checked,
        "summary": summary(twins, layout, workflows, done, samples, target),
    }


def wilson(passed, runs):
    """One-sided 95% lower bound on the success rate."""
    if not runs:
        return None
    p, z = passed / runs, Z95
    centre = p + z * z / (2 * runs)
    spread = z * math.sqrt(p * (1 - p) / runs + z * z / (4 * runs * runs))
    return round(max(0.0, (centre - spread) / (1 + z * z / runs)), 4)


def needed(target):
    """Samples that must all pass for the lower bound to reach `target`."""
    return math.ceil(target * Z95 * Z95 / (1 - target))


def _side(results):
    """The tighter of a band's results over workflows: (band, saturated, limit, workflow)."""
    if not results:
        return None
    best = min(results, key=lambda r: (r["band"], r["workflow"]))
    return {
        "band": best["band"],
        "saturated": all(r["saturated"] for r in results),
        "limit": best["limit"],
        "workflow": best["workflow"],
    }


def _binding(rows, axes):
    """The tightest side over `axes`, metres before degrees."""
    sides = [
        (rows[a][k], a, k)
        for a in axes
        if a in rows
        for k in ("minus", "plus")
        if rows[a].get(k) and rows[a][k]["limit"]
    ]
    if not sides:
        return None
    side, axis, k = min(sides, key=lambda s: s[0]["band"] / AXES[s[1]][0])
    return {"axis": axis, "sign": -1 if k == "minus" else 1, **side["limit"], "band": side["band"]}


def summary(twins, layout, workflows, done, samples, target=0.99):
    rows = subjects(twins, layout, workflows)
    names = [n for n, _ in workflows]
    bands = {}
    for r in done:
        if r["kind"] == "band":
            bands.setdefault(r["twin_id"], {}).setdefault(r["axis"], {}).setdefault(
                "minus" if r["sign"] < 0 else "plus", []
            ).append(r)
    overlay, requirements, arms, per_workflow = {}, [], [], []
    for twin_id, role, axes in rows:
        found = bands.get(twin_id, {})
        sides = {
            axis: {k: _side(found.get(axis, {}).get(k, [])) for k in ("minus", "plus")}
            for axis in axes
        }
        complete = all(
            len(found.get(a, {}).get(k, [])) == len(workflows)
            for a in axes
            for k in ("minus", "plus")
        )
        overlay[twin_id] = {
            axis: [s["band"] if s else None for s in (v["minus"], v["plus"])]
            for axis, v in sides.items()
        }

        def within(axis_list, sides=sides):
            values = [
                sides[a][k]["band"]
                for a in axis_list
                if a in sides
                for k in ("minus", "plus")
                if sides[a][k]
            ]
            return min(values) if values else None

        row = {
            "twin_id": twin_id,
            "name": _name(twins, twin_id),
            "role": role,
            "xz_m": within(("x", "z")),
            "yaw_deg": within(("yaw",)),
            "height_m": within(("height",)),
            "sides": sides,
            "binding": _binding(sides, ("x", "z")) or _binding(sides, axes),
            "complete": complete,
        }
        if role == "arm":
            height = sides.get("height", {})
            # A longer tool needs the flange higher: the same as the base standing lower.
            row["tool"] = {
                "longer_m": height["minus"]["band"] if height.get("minus") else None,
                "shorter_m": height["plus"]["band"] if height.get("plus") else None,
                "lateral_m": row["xz_m"],
            }
            arms.append(row)
        else:
            requirements.append(row)
    requirements.sort(
        key=lambda r: (
            r["xz_m"] if r["xz_m"] is not None else math.inf,
            r["yaw_deg"] if r["yaw_deg"] is not None else math.inf,
            r["name"],
        )
    )
    for w, name in enumerate(names):
        own = [
            r
            for r in done
            if r["kind"] == "band" and r["workflow"] == w and r["axis"] in ("x", "z")
        ]
        own = [r for r in own if r["twin_id"] in {t for t, role, _ in rows if role != "arm"}]
        tight = min(own, key=lambda r: r["band"], default=None)
        per_workflow.append(
            {
                "name": name,
                "xz_m": tight["band"] if tight else None,
                "binding": tight
                and {
                    "twin_id": tight["twin_id"],
                    "name": _name(twins, tight["twin_id"]),
                    "axis": tight["axis"],
                    "sign": tight["sign"],
                    **(tight["limit"] or {}),
                },
            }
        )
    curves = {}
    for group in GROUPS:
        points = []
        for level, (metres, degrees) in enumerate(LEVELS):
            runs = [
                r
                for r in done
                if r["kind"] == "sample" and r["group"] == group and r["level"] == level
            ]
            ran = [r for r in runs if not r["skipped"]]
            passed = sum(all(x["ok"] for x in r["results"]) for r in ran)
            causes = {}
            for r in ran:
                for x in r["results"]:
                    if not x["ok"]:
                        causes[x["cause"]] = causes.get(x["cause"], 0) + 1
            points.append(
                {
                    "level_m": metres,
                    "level_deg": degrees,
                    "runs": len(ran),
                    "passed": passed,
                    "skipped": len(runs) - len(ran),
                    "drawn": len(runs),
                    "rate": round(passed / len(ran), 4) if ran else None,
                    "lower": wilson(passed, len(ran)),
                    "by_workflow": [
                        sum(r["results"][w]["ok"] for r in ran) if ran else None
                        for w in range(len(names))
                    ],
                    "causes": causes,
                }
            )
        curves[group] = {"points": points, "advice": advice(points, target, samples)}
    return {
        "evidence": "synthetic",
        "workflows": names,
        "target": target,
        "samples": samples,
        "requirements": requirements,
        "arms": arms,
        "per_workflow": per_workflow,
        "curves": curves,
        "overlay": overlay,
        "capture_m": GRASP_TOLERANCE,
        "axes": {a: {"limit": v[0], "resolution": v[1]} for a, v in AXES.items()},
    }


def advice(points, target, samples):
    """The widest ladder tolerance up to which every level met the target, as observed."""
    best = None
    for point in points:
        if point["rate"] is None or point["drawn"] < samples:
            break
        if point["rate"] < target:
            break
        best = point
    if not best:
        return None
    return {
        "level_m": best["level_m"],
        "level_deg": best["level_deg"],
        "rate": best["rate"],
        "lower": best["lower"],
        "runs": best["runs"],
        "needed": needed(target),
    }


# ---- Printable 1:1 placement template -------------------------------------------------

MM = 1000
A4 = (190, 265)  # drawn area of an A4 sheet in millimetres, portrait, under 10 mm margins
OVERLAP = 10


def _hull(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def allowed_outline(spec, placement, band):
    """Footprint swept over its x/z band: the region the instrument may cover."""
    xs, zs = band.get("x") or [0, 0], band.get("z") or [0, 0]
    shape = corners(spec, placement)
    sweep = [
        (x + dx, z + dz)
        for x, z in shape
        for dx in (-(xs[0] or 0), xs[1] or 0)
        for dz in (-(zs[0] or 0), zs[1] or 0)
    ]
    return _hull(sweep)


def _esc(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _pts(points):
    return " ".join(f"{x * MM:.1f},{z * MM:.1f}" for x, z in points)


def _band_text(row):
    parts = []
    if row.get("xz_m") is not None:
        parts.append(f"±{row['xz_m'] * MM:.0f} mm")
    if row.get("yaw_deg") is not None:
        parts.append(f"±{row['yaw_deg']:g}°")
    return " · ".join(parts)


def template_body(twins, layout, result):
    """SVG content of the bench in millimetres, bench centre at the origin, z toward you."""
    bench = layout["bench"]
    w, d = bench["width"] * MM, bench["depth"] * MM
    overlay = (result or {}).get("overlay", {})
    rows = {
        r["twin_id"]: r
        for r in (result or {}).get("requirements", []) + (result or {}).get("arms", [])
    }
    out = [
        f'<rect x="{-w / 2:.1f}" y="{-d / 2:.1f}" width="{w:.1f}" height="{d:.1f}" '
        'fill="none" stroke="#000" stroke-width="0.6"/>',
    ]
    # Datum: the bench centre, and corner marks to square the sheet to the bench edge.
    out.append(
        '<g stroke="#000" stroke-width="0.4"><line x1="-20" y1="0" x2="20" y2="0"/>'
        '<line x1="0" y1="-20" x2="0" y2="20"/><circle r="5" fill="none"/></g>'
        '<text x="8" y="-8" font-size="6">Datum 0,0 · bench centre</text>'
    )
    for sx in (-1, 1):
        for sz in (-1, 1):
            x, z = sx * w / 2, sz * d / 2
            out.append(
                f'<path d="M{x - sx * 30:.1f},{z:.1f} L{x:.1f},{z:.1f} L{x:.1f},{z - sz * 30:.1f}" '
                'fill="none" stroke="#000" stroke-width="1"/>'
            )
    for p in layout["placements"]:
        twin = twins.get(p["twin_id"])
        if not twin:
            continue
        spec = twin["spec"]
        shape = corners(spec, p)
        band = overlay.get(p["twin_id"])
        if band and (band.get("x") or band.get("z")):
            out.append(
                f'<polygon points="{_pts(allowed_outline(spec, p, band))}" fill="#000" '
                'fill-opacity="0.06" stroke="#000" stroke-width="0.4" stroke-dasharray="4 3"/>'
            )
        out.append(
            f'<polygon points="{_pts(shape)}" fill="none" stroke="#000" stroke-width="0.8"/>'
        )
        # Datum corner of each footprint: the first corner, with a tick along both edges.
        (x0, z0), (x1, z1), _, (x3, z3) = shape
        out.append(
            f'<circle cx="{x0 * MM:.1f}" cy="{z0 * MM:.1f}" r="3" fill="#000"/>'
            f'<text x="{x0 * MM + 5:.1f}" y="{z0 * MM + 10:.1f}" font-size="5">'
            f"{x0 * MM:.0f}, {z0 * MM:.0f}</text>"
        )
        cx, cz = sum(x for x, _ in shape) / 4 * MM, sum(z for _, z in shape) / 4 * MM
        row = rows.get(p["twin_id"])
        out.append(
            f'<text x="{cx:.1f}" y="{cz:.1f}" font-size="9" text-anchor="middle">'
            f"{_esc(spec['name'])}</text>"
        )
        label = f"x {p['x'] * MM:.0f} · z {p['z'] * MM:.0f} mm · {p['yaw']:g}°"
        if row and _band_text(row):
            label += f" · within {_band_text(row)}"
        out.append(
            f'<text x="{cx:.1f}" y="{cz + 11:.1f}" font-size="6" text-anchor="middle">'
            f"{_esc(label)}</text>"
        )
    # A 100 mm bar to check the print scale.
    out.append(
        f'<g transform="translate({-w / 2 + 20:.1f},{d / 2 - 20:.1f})">'
        '<line x1="0" y1="0" x2="100" y2="0" stroke="#000" stroke-width="1"/>'
        '<line x1="0" y1="-4" x2="0" y2="4" stroke="#000"/>'
        '<line x1="100" y1="-4" x2="100" y2="4" stroke="#000"/>'
        '<text x="0" y="-6" font-size="6">100 mm at 1:1</text></g>'
        f'<text x="{-w / 2 + 20:.1f}" y="{-d / 2 + 14:.1f}" font-size="6">'
        "Synthetic teaching layout: not a calibrated or validated placement. "
        "Dashed: the region each instrument may cover.</text>"
    )
    return "\n".join(out), (w, d)


def template_svg(twins, layout, result):
    body, (w, d) = template_body(twins, layout, result)
    m = 20
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w + 2 * m:.0f}mm" '
        f'height="{d + 2 * m:.0f}mm" viewBox="{-w / 2 - m:.1f} {-d / 2 - m:.1f} '
        f'{w + 2 * m:.1f} {d + 2 * m:.1f}" font-family="sans-serif">\n{body}\n</svg>\n'
    )


def template_pages(twins, layout, result):
    """The template on A4 sheets at 1:1, overlapping 10 mm, for printing to paper or PDF."""
    body, (w, d) = template_body(twins, layout, result)
    pw, ph = A4
    cols = max(1, math.ceil((w - OVERLAP) / (pw - OVERLAP)))
    rows = max(1, math.ceil((d - OVERLAP) / (ph - OVERLAP)))
    pages = []
    for r in range(rows):
        for c in range(cols):
            x = -w / 2 + c * (pw - OVERLAP)
            z = -d / 2 + r * (ph - OVERLAP)
            pages.append(
                f'<section><svg xmlns="http://www.w3.org/2000/svg" width="{pw}mm" height="{ph}mm" '
                f'viewBox="{x:.1f} {z:.1f} {pw} {ph}" font-family="sans-serif">{body}'
                f'<rect x="{x:.1f}" y="{z:.1f}" width="{pw}" height="{ph}" fill="none" '
                'stroke="#999" stroke-width="0.3" stroke-dasharray="2 2"/></svg>'
                f"<p>Sheet {r + 1}-{c + 1} of {rows}×{cols} · overlap {OVERLAP} mm · "
                "print at 100%</p></section>"
            )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Placement template</title>"
        "<style>@page{size:A4 portrait;margin:10mm}body{margin:0;font:9pt sans-serif}"
        "section{page-break-after:always;break-after:page}section:last-child{break-after:auto}"
        "p{margin:1mm 0 0}</style></head><body>" + "".join(pages) + "</body></html>"
    )
