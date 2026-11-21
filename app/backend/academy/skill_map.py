"""A learner's skill tree: instruments met, published workflows reproduced, and changed.

The tree has three tiers. A function, such as spin-coating or X-ray diffraction, is met
when the learner has a twin do it. A published workflow is reproduced when one run takes
every step the paper is read into, in order. From there a learner makes it their own:
another instrument for a step, a measurement the paper did not take, or one paper's
preparation measured the way another paper measures.

Everything is read from what a run did on the twins, never from a claim: a workflow
edited until it no longer covers a paper earns nothing for that paper. Runs are
synthetic, so the tree records practice on teaching twins and nothing about a robot,
Isaac/GPU or chemistry.
"""

import re
from functools import cache
from typing import Literal

from fastapi import HTTPException
from pydantic import Field

from . import cloudlab_workflow as cw
from . import paper_workflows as pw
from .models import StrictModel
from .stages import STAGES
from .store import Write

KEY = "skills"
STATEMENT = (
    "Practice on synthetic teaching twins. It does not show that a method works or "
    "authorize use of any instrument."
)


class Meet(StrictModel):
    expected_version: int = Field(ge=0, strict=True)
    function: Literal[tuple(pw.FUNCTIONS)]
    instrument: str = Field(max_length=80)


def initial():
    return {"version": 0, "functions": {}, "papers": {}, "extended": [], "recombined": []}


@cache
def functions_of(instrument):
    """The functions a twin's name says it does."""
    text = pw.POOL[instrument][0] if instrument in pw.POOL else ""
    return frozenset(f for f, pattern in pw.FUNCTIONS.items() if re.search(pattern, text, re.I))


def trial(function):
    """A step that shows a function, at a teaching value."""
    operation = pw.LABELS[function][1]
    value = {"load": 200, "mix": 30, "wait": 60, "heat": 60, "read": 1}[operation]
    return pw.paper_step(pw.LABELS[function][0], [function], operation, value)


@cache
def twins(function):
    """The twins that can show a function, best first."""
    return tuple(pw.rank(trial(function), None)[0][: pw.SHOWN])


@cache
def defaults(paper):
    return tuple(row["chosen"] for row in pw.template(paper, {})["rows"])


def takes(use, step):
    """Whether one run step does one paper step."""
    return use[1] == step["operation"] and bool(functions_of(use[0]) & set(step["functions"]))


def cover(uses, steps, start=0):
    """Where a run finishes taking `steps` in order from `start`, and on which twins."""
    at, picked = start, []
    for step in steps:
        while at < len(uses) and not takes(uses[at], step):
            at += 1
        if at == len(uses):
            return None
        picked.append(uses[at][0])
        at += 1
    return at, picked


def only(uses, steps):
    """Whether a run does nothing to the sample but `steps`; loading and reading aside."""
    return all(
        use[1] in {"load", "read"} or any(takes(use, step) for step in steps) for use in uses
    )


def within(steps, others):
    """Whether `others` already contains `steps`, in order."""
    at = 0
    for step in steps:
        while at < len(others) and not (
            others[at]["operation"] == step["operation"]
            and set(others[at]["functions"]) & set(step["functions"])
        ):
            at += 1
        if at == len(others):
            return False
        at += 1
    return True


def read_run(steps):
    """What a run shows: functions done, papers reproduced, and how they were changed."""
    uses = [(s["instrument"], s["operation"]) for s in steps if s["operation"] != "transfer"]
    found = {"functions": {}, "papers": {}, "extended": [], "recombined": []}
    for instrument, operation in uses:
        for function in functions_of(instrument):
            if pw.LABELS[function][1] == operation:
                found["functions"].setdefault(function, instrument)
    prepared = {}
    for paper in pw.PAPERS:
        made = cover(uses, pw.prepares(paper))
        if not made:
            continue
        prepared[paper] = made[0]
        whole = cover(uses, pw.PAPERS[paper])
        if not whole:
            continue
        found["papers"][paper] = {"swapped": tuple(whole[1]) != defaults(paper)}
        own = {f for step in pw.PAPERS[paper] for f in step["functions"]}
        for instrument, operation in uses[made[0] :]:
            extra = sorted(functions_of(instrument) & set(pw.MEASURES))
            if operation == "read" and extra and not own & set(extra):
                if [paper, extra[0]] not in found["extended"]:
                    found["extended"].append([paper, extra[0]])
    for paper, end in prepared.items():
        # A paper's own measurements after its preparation reproduce it; a longer
        # preparation that was also made is the one this run recombines.
        if paper in found["papers"] or any(
            other != paper and within(pw.prepares(paper), pw.prepares(other)) for other in prepared
        ):
            continue
        for other in pw.PAPERS:
            if (
                other != paper
                and cover(uses, pw.measures(other), end)
                and not within(pw.prepares(paper), pw.prepares(other))
                and not within(pw.measures(other), pw.measures(paper))
                and only(uses, pw.prepares(paper) + pw.measures(other))
            ):
                found["recombined"].append([paper, other])
    return found


def merged(record, found):
    """The record with what a run found added, and what of it is new."""
    new = {"functions": [], "papers": [], "swapped": [], "extended": [], "recombined": []}
    for function, instrument in found["functions"].items():
        if function not in record["functions"]:
            record["functions"][function] = instrument
            new["functions"].append(function)
    for paper, how in found["papers"].items():
        known = record["papers"].get(paper)
        if not known:
            new["papers"].append(paper)
        if how["swapped"] and not (known or {}).get("swapped"):
            new["swapped"].append(paper)
        record["papers"][paper] = {"swapped": how["swapped"] or bool((known or {}).get("swapped"))}
    for kind in ("extended", "recombined"):
        for pair in found[kind]:
            if pair not in record[kind]:
                record[kind].append(pair)
                new[kind].append(pair)
    return new if any(new.values()) else None


def tree(record):
    met = record["functions"]
    return {
        "version": record["version"],
        "stages": list(STAGES),
        "functions": [
            {
                "id": function,
                "label": label,
                "operation": operation,
                "group": "measure" if operation == "read" else "prepare",
                "twins": list(twins(function)),
                "met": met.get(function),
            }
            for function, (label, operation) in pw.LABELS.items()
        ],
        "papers": [
            {
                "id": paper,
                "steps": [
                    {
                        "text": step["text"],
                        "stage": step["stage"],
                        "functions": step["functions"],
                        "met": any(f in met for f in step["functions"]),
                    }
                    for step in steps
                ],
                "reproduced": paper in record["papers"],
                "swapped": record["papers"].get(paper, {}).get("swapped", False),
                "extended": [f for p, f in record["extended"] if p == paper],
            }
            for paper, steps in pw.PAPERS.items()
        ],
        "recombined": [{"prepare": a, "measure": b} for a, b in record["recombined"]],
        "statement": STATEMENT,
        "evidence": "synthetic",
    }


class Skills:
    def __init__(self, store):
        self.store = store

    def record(self, owner):
        return self.store.get(owner, KEY) or initial()

    def get(self, owner):
        return tree(self.record(owner))

    def learn(self, owner, steps):
        """The write that adds a run to the tree, and what is new; neither if nothing is."""
        record = self.record(owner)
        expected = record["version"]
        new = merged(record, read_run(steps))
        if not new:
            return None, None
        record["version"] = expected + 1
        return Write(owner, KEY, record, expected or None), new

    def meet(self, owner, data):
        """Have one twin do one function, and record that the learner has seen it."""
        record = self.record(owner)
        if record["version"] != data.expected_version:
            raise cw.Conflict
        if data.instrument not in {t["id"] for t in twins(data.function)}:
            raise HTTPException(422, "That twin cannot show this function")
        spec = cw.spec_of(data.instrument)
        step = trial(data.function)
        sample = spec["container"]["vessel"]
        steps = [
            cw.step(data.instrument, "load", min(200, spec["container"]["max_volume_ul"]), sample)
        ]
        if step["operation"] != "load":
            steps.append(cw.step(data.instrument, step["operation"], pw.value(spec, step), sample))
        result = cw.check(steps)
        if not result["ok"]:
            raise HTTPException(422, result["error"])
        merged(record, read_run(steps))
        record["version"] = data.expected_version + 1
        self.store.put(owner, KEY, record, data.expected_version or None)
        return {**tree(record), "trace": result["trace"]}
