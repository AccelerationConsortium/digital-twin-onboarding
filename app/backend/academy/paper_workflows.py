"""Marketplace papers as adjustable cloud lab workflow templates.

Each curated paper is read into steps: what the step does (Academy's reading of the
paper, not its protocol), the function an instrument needs for it, and one of the twins'
operations. A step's candidates are the twins whose name says they do that function:
the cloud lab instruments of workflow design and the ChemLab-Assets twins. They are
ranked by the twins' own rules: whether they can do the operation within their limits,
and whether they take the vessel the sample is already in. A learner's picks become a
cloud lab workflow draft.

Values are teaching values within the twins' limits, never the paper's conditions, and
every run is synthetic: no robot, Isaac/GPU or chemistry.
"""

import re
from typing import Literal

from pydantic import Field

from . import cloudlab_workflow as cw
from .chemlab import CHEMLAB
from .cloudlab import CLOUDLAB
from .models import StrictModel

# Instrument functions a paper step can ask for, matched against twin names.
FUNCTIONS = {
    "dispense": r"liquid-handl|sample preparation workcell",
    "stir": r"stirrer|orbital shaker",
    "incubate": r"incubat",
    "sonicate": r"ultrasonic|sonicat",
    "dose-powder": r"powder dosing",
    "grind": r"ball mill",
    "spin-coat": r"spin coater",
    "anneal": r"hotplate|drying oven",
    "fire": r"furnace",
    "illuminate": r"photochemical|photoredox",
    "conductivity": r"conductivity meter",
    "absorbance": r"UV-Vis spectrophotometer|plate reader",
    "fluorescence": r"spectrofluorometer|plate reader",
    "sheet-resistance": r"four-point",
    "gas-analysis": r"gas chromatograph",
    "diffraction": r"powder X-ray diffract",
}
DOING = {
    "load": "hold a sample",
    "mix": "mix",
    "heat": "hold a temperature",
    "read": "take a reading",
    "wait": "hold a sample",
}
SHOWN = 4


def paper_step(text, functions, operation, value=1):
    return {"text": text, "functions": functions, "operation": operation, "value": value}


# The load step's value is the volume the template would like; the chain's smallest
# vessel decides what it gets.
PAPERS = {
    "clio": [
        paper_step(
            "Dispense salt and solvent stocks into a composition library", ["dispense"], "load", 200
        ),
        paper_step("Mix each formulation", ["dispense", "stir"], "mix", 60),
        paper_step("Measure ionic conductivity", ["conductivity"], "read"),
    ],
    "ada": [
        paper_step("Combine precursor formulations", ["dispense"], "load", 200),
        paper_step("Mix each formulation", ["dispense", "stir"], "mix", 30),
        paper_step("Spin-coat the formulation into a film", ["spin-coat"], "wait", 60),
        paper_step("Anneal the film", ["anneal"], "heat", 100),
        paper_step("Measure the film's optical response", ["absorbance"], "read"),
        paper_step("Measure the film's electrical response", ["sheet-resistance"], "read"),
    ],
    "sonication": [
        paper_step("Prepare precursor solutions", ["dispense"], "load", 200),
        paper_step("Apply ultrasound to form nanocrystals", ["sonicate"], "mix", 120),
        paper_step("Record optical spectra", ["absorbance", "fluorescence"], "read"),
    ],
    "rainbow": [
        paper_step("Prepare nanocrystal formulations in a plate", ["dispense"], "load", 200),
        paper_step("Mix each formulation", ["dispense", "stir"], "mix", 30),
        paper_step("Let the reaction proceed", ["incubate", "stir"], "wait", 300),
        paper_step("Measure emission across the plate", ["fluorescence"], "read"),
    ],
    "mobile": [
        paper_step("Dispense solid photocatalyst into a vial", ["dose-powder"], "load", 1000),
        paper_step("Disperse the mixture", ["sonicate", "stir"], "mix", 60),
        paper_step("Illuminate the sample", ["illuminate"], "wait", 600),
        paper_step("Measure the hydrogen produced", ["gas-analysis"], "read"),
    ],
    "alab": [
        paper_step("Dose precursor powders", ["dose-powder"], "load", 1000),
        paper_step("Mix and grind the precursors", ["grind"], "mix", 120),
        # Firing is far hotter than any teaching twin holds, so every furnace says so.
        paper_step("Fire the mixture in a furnace", ["fire"], "heat", 1000),
        paper_step("Identify phases by X-ray diffraction", ["diffraction"], "read"),
    ],
}
PaperId = Literal[tuple(PAPERS)]


class Picks(StrictModel):
    # Step index -> chosen instrument; "" leaves the step out of the template.
    picks: dict[int, str] = Field(default_factory=dict, max_length=16)


def pool():
    """Every twin a step could use: its id, the text naming its function, its spec."""
    out = {k: (CLOUDLAB[k]["spec"]["name"], CLOUDLAB[k]["spec"]) for k in cw.INSTRUMENTS}
    for slug, asset in CHEMLAB.items():
        if "load" in asset["spec"]["operations"]:
            out[cw.CHEMLAB_PREFIX + slug] = (
                f"{asset['label']} {asset['spec']['name']}",
                asset["spec"],
            )
    return out


POOL = pool()


def fit(spec, step, sample):
    """Notes on how a twin would take a step, and how much each costs the ranking."""
    notes, cost = [], 0
    if step["operation"] == "heat":
        limits = spec["limits"]
        low, high = max(4, limits["min_temp_c"]), min(120, limits["max_temp_c"])
        if not low <= step["value"] <= high:
            notes.append(
                f"Holds {low:g}–{high:g} °C, so the template uses {clamp(step['value'], low, high):g} °C"
            )
            cost += 2
    vessel = spec["container"]["vessel"]
    if sample and sample["vessel"] != vessel:
        notes.append(f"Takes a {vessel}, so the sample starts again in a new {vessel}")
        cost += 1
    return notes, cost


def clamp(value, low, high):
    return min(max(value, low), high)


def value(spec, step):
    limits = spec["limits"]
    if step["operation"] == "heat":
        return clamp(step["value"], max(4, limits["min_temp_c"]), min(120, limits["max_temp_c"]))
    if step["operation"] in {"mix", "wait"}:
        return min(step["value"], limits["max_duration_s"])
    return 1


def rank(step, sample):
    """Twins that can take a step, best first, and those whose name fits but cannot."""
    pattern = "|".join(FUNCTIONS[f] for f in step["functions"])
    eligible, rejected = [], []
    for key, (text, spec) in POOL.items():
        if not re.search(pattern, text, re.I):
            continue
        source = "Cloud lab" if key in CLOUDLAB else "ChemLab-Assets"
        if step["operation"] not in spec["operations"]:
            rejected.append(
                {
                    "id": key,
                    "name": spec["name"],
                    "reason": f"Cannot {DOING[step['operation']]} in its teaching twin",
                }
            )
            continue
        notes, cost = fit(spec, step, sample)
        featured = key in CLOUDLAB or CHEMLAB[key.removeprefix(cw.CHEMLAB_PREFIX)]["featured"]
        eligible.append(
            (
                (cost, key not in CLOUDLAB, not featured, spec["name"]),
                {"id": key, "name": spec["name"], "source": source, "notes": notes},
            )
        )
    return [c for _, c in sorted(eligible, key=lambda pair: pair[0])], rejected


def template(paper, picks):
    """The paper's steps with ranked candidates, and the workflow the picks make."""
    rows, steps, chain = [], [], {}
    sample, count = None, {}
    for index, step in enumerate(PAPERS[paper]):
        candidates, rejected = rank(step, sample)
        ids = [c["id"] for c in candidates]
        wanted = picks.get(index)
        # An unknown pick falls back to the best candidate, as no pick does.
        chosen = wanted if wanted in ids or wanted == "" else (ids[0] if ids else "")
        row = {
            "index": index,
            "text": step["text"],
            "operation": step["operation"],
            "chosen": chosen,
            "candidates": candidates[:SHOWN] + [c for c in candidates[SHOWN:] if c["id"] == chosen],
            "rejected": rejected,
            "gap": None if candidates else "No twin can take this step yet",
        }
        rows.append(row)
        if not chosen:
            continue
        spec = POOL[chosen][1]
        vessel = spec["container"]["vessel"]
        if sample is None or sample["vessel"] != vessel:
            count[vessel] = count.get(vessel, 0) + 1
            name = vessel if count[vessel] == 1 else f"{vessel}-{count[vessel]}"
            sample = {"name": name, "vessel": vessel, "at": chosen}
            chain[name] = {"want": step["value"] if step["operation"] == "load" else 200, "at": []}
            steps.append(cw.step(chosen, "load", 0, name))
        elif sample["at"] != chosen:
            sample["at"] = chosen
            steps.append(cw.step(chosen, "transfer", 1, sample["name"]))
        chain[sample["name"]]["at"].append(chosen)
        if step["operation"] != "load":
            steps.append(cw.step(chosen, step["operation"], value(spec, step), sample["name"]))
    # Each sample starts with what every instrument on its way can hold.
    for item in steps:
        if item["operation"] == "load":
            route = chain[item["sample"]]
            item["value"] = min(
                route["want"], *(POOL[k][1]["container"]["max_volume_ul"] for k in route["at"])
            )
    used = [s["instrument"] for s in steps]
    return {
        "paper": paper,
        "rows": rows,
        "steps": steps,
        "check": cw.check(steps) if steps else None,
        "instruments": cw.catalog(used),
        "statement": cw.STATEMENT,
        "evidence": "synthetic",
    }
