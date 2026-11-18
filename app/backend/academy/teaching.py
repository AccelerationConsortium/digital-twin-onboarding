"""A deliberately limited teaching model. Never used as Matterix evidence."""

from copy import deepcopy
from datetime import UTC, datetime
from math import isclose, isfinite
from uuid import uuid4

from .models import Experiment, LearningProgress


class InvalidTransition(ValueError):
    pass


# Module limits as the Opentrons simulator enforces or documents them.
HEAT_RANGE = {"heater_shaker": (37, 95), "temperature": (4, 95)}
SHAKE_RANGE = (200, 3000)
NAMES = {
    "deck": "the deck",
    "heater_shaker": "the Heater-Shaker",
    "temperature": "the Temperature Module",
    "reader": "the plate reader",
    "stacker": "the stacker",
}


def uses_modules(experiment: dict) -> bool:
    return bool(experiment.get("modules")) or any(
        a["kind"] in {"move", "heat", "shake", "read"} for a in experiment["actions"]
    )


def capacities(experiment: dict) -> tuple[float, float]:
    """(pipette, well) capacity in µL.

    Lessons use one 300 µL teaching pipette and 1,500 µL containers. A Studio design uses
    the pipette of its instrument, and the flat plate that fits the modules once it has any.
    """
    if experiment["course_id"] != "workflow-sandbox":
        return 300, 1500
    pipette = 300 if experiment.get("instrument") == "ot2" else 1000
    return pipette, 360 if uses_modules(experiment) else 1500


def initial_state(experiment: dict) -> dict:
    return {
        "wells": {
            "stock": {
                "volume": experiment["source_volume"],
                "solute": experiment["source_volume"] * 100,
            },
            **{
                well: {"volume": experiment["diluent_volume"], "solute": 0}
                for well in ["A1", "A2", "A3"]
            },
        },
        "pipette": {"volume": 0.0, "solute": 0.0, "tip": False, "used": False},
        "tips_used": 0,
        "tips_discarded": 0,
        "waste_volume": 0.0,
        "waste_solute": 0.0,
        **(
            {"plate": {"at": "deck", "temperature": None, "shaken": False}, "readings": []}
            if uses_modules(experiment)
            else {}
        ),
    }


def new_session(experiment: Experiment) -> dict:
    definition = experiment.model_dump()
    return {
        "id": str(uuid4()),
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "experiment": definition,
        "engine": "teaching",
        "evidence": "synthetic",
        "status": "draft",
        "cursor": 0,
        "state": initial_state(definition),
        "events": [],
        "assessment": None,
        "attempts": [],
        "learning": LearningProgress().model_dump(),
    }


def model_checks(state: dict, experiment: dict, completed_steps: int) -> list[dict]:
    """Check bookkeeping without assigning a scientific goal to a learner's design."""
    initial = initial_state(experiment)

    def total(snapshot, field):
        return (
            sum(well[field] for well in snapshot["wells"].values())
            + snapshot["pipette"][field]
            + snapshot[f"waste_{field}"]
        )

    pipette_ul, well_ul = capacities(experiment)
    containers = [
        (state["wells"]["stock"], 1500),
        *((well, well_ul) for name, well in state["wells"].items() if name != "stock"),
        (state["pipette"], pipette_ul),
        ({"volume": state["waste_volume"], "solute": state["waste_solute"]}, None),
    ]
    return [
        {
            "label": "Every workflow step completed in the teaching model",
            "passed": completed_steps == len(experiment["actions"]) and completed_steps > 0,
        },
        *[
            {
                "label": f"Total {label} is conserved, including the pipette and waste",
                "passed": isclose(
                    total(state, field), total(initial, field), rel_tol=1e-9, abs_tol=1e-6
                ),
            }
            for field, label in [("volume", "liquid volume"), ("solute", "stock tracer")]
        ],
        {
            "label": "Liquid amounts stay finite, nonnegative and within teaching capacities",
            "passed": all(
                isfinite(container["volume"])
                and isfinite(container["solute"])
                and container["volume"] >= -1e-8
                and container["solute"] >= -1e-8
                and (capacity is None or container["volume"] <= capacity + 1e-8)
                for container, capacity in containers
            ),
        },
        {
            "label": "The pipette finishes empty with its tip discarded",
            "passed": not state["pipette"]["tip"]
            and abs(state["pipette"]["volume"]) < 1e-8
            and abs(state["pipette"]["solute"]) < 1e-8,
        },
    ]


def assessment(state: dict, experiment: dict, completed_steps: int) -> dict:
    measured = {
        name: round(well["solute"] / well["volume"], 4) if well["volume"] else 0
        for name, well in state["wells"].items()
        if name != "stock"
    }
    if experiment["course_id"] == "workflow-sandbox":
        checks = model_checks(state, experiment, completed_steps)
        return {
            "scope": "model-checks",
            "passed": all(check["passed"] for check in checks),
            "checks": checks,
            "concentrations": measured,
        }
    targets = {"A1": 50, "A2": 25, "A3": 12.5}
    checks = [
        {
            "label": f"{name} reaches {target}% stock concentration",
            "passed": abs(measured[name] - target) < 0.05,
        }
        for name, target in targets.items()
    ]
    if experiment["course_id"] == "flex-first-transfer":
        volume = experiment["transfer_volume"]
        checks = [
            {
                "label": f"Target well A1 received {volume:g} µL",
                "passed": abs(state["wells"]["A1"]["volume"] - volume) < 1e-6,
            },
            {
                "label": "The source volume decreased by the transferred amount",
                "passed": abs(
                    state["wells"]["stock"]["volume"] - (experiment["source_volume"] - volume)
                )
                < 1e-6,
            },
            {
                "label": "No liquid was transferred to other wells",
                "passed": all(state["wells"][w]["volume"] == 0 for w in ["A2", "A3"]),
            },
        ]
    checks.append(
        {
            "label": "All liquid is dispensed and the final tip is discarded",
            "passed": not state["pipette"]["tip"] and state["pipette"]["volume"] == 0,
        }
    )
    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "concentrations": measured,
    }


def execute_step(session: dict) -> dict:
    if session["status"] != "running":
        raise InvalidTransition("Start or resume the experiment before advancing")
    result = deepcopy(session)
    index = result["cursor"]
    action = result["experiment"]["actions"][index]
    state = result["state"]
    pipette = state["pipette"]
    well = state["wells"][action["well"]]
    volume = action["volume"]
    kind = action["kind"]
    problem = None
    detail = ""
    pipette_ul, well_ul = capacities(result["experiment"])
    studio = result["experiment"]["course_id"] == "workflow-sandbox"
    modules = result["experiment"].get("modules", [])
    # A lesson has no modules: its plate never leaves the deck and its state stays as it was.
    plate = state.get("plate") or {"at": "deck", "temperature": None, "shaken": False}
    if kind == "move":
        to = action.get("to", "deck")
        if result["experiment"].get("instrument") != "ot2" and "gripper" not in modules:
            problem = (
                "no_gripper",
                "This Flex has no gripper to move the plate.",
                "Add the gripper to the deck setup, or leave the plate where it is.",
            )
        elif to != "deck" and to not in modules:
            problem = (
                "module_missing",
                f"{NAMES[to].capitalize()} is not on this deck.",
                "Add the module to the deck setup before moving a plate to it.",
            )
        elif to == plate["at"]:
            problem = (
                "already_there",
                f"The plate is already on {NAMES[to]}.",
                "Remove this step or choose where the plate should go next.",
            )
        else:
            plate["at"] = to
            # Off a module the plate drifts back to room temperature in this model.
            if to not in HEAT_RANGE:
                plate["temperature"] = None
            detail = f"Plate moved to {NAMES[to]}"
    elif kind == "heat":
        low, high = HEAT_RANGE.get(plate["at"], (0, 0))
        if plate["at"] not in HEAT_RANGE:
            problem = (
                "not_on_module",
                f"The plate is on {NAMES[plate['at']]}, which cannot set a temperature.",
                "Move the plate to the Heater-Shaker or the Temperature Module first.",
            )
        elif not low <= action["value"] <= high:
            problem = (
                "temperature_range",
                f"{NAMES[plate['at']].capitalize()} holds {low}–{high} °C, "
                f"not {action['value']:g} °C.",
                "Choose a temperature inside the module's range."
                if plate["at"] == "temperature"
                else "The Heater-Shaker only heats; use the Temperature Module to cool.",
            )
        else:
            plate["temperature"] = action["value"]
            detail = f"Plate at {action['value']:g} °C on {NAMES[plate['at']]}"
    elif kind == "shake":
        if plate["at"] != "heater_shaker":
            problem = (
                "not_on_module",
                f"The plate is on {NAMES[plate['at']]}; only the Heater-Shaker shakes.",
                "Move the plate to the Heater-Shaker first.",
            )
        elif not SHAKE_RANGE[0] <= action["value"] <= SHAKE_RANGE[1]:
            problem = (
                "shake_range",
                f"The Heater-Shaker shakes at 200–3000 rpm, not {action['value']:g} rpm.",
                "Choose a speed inside that range.",
            )
        else:
            plate["shaken"] = True
            detail = f"Shaken at {action['value']:g} rpm for {action['seconds']:g} s"
    elif kind == "read":
        if plate["at"] != "reader":
            problem = (
                "not_in_reader",
                f"The plate is on {NAMES[plate['at']]}, not in the plate reader.",
                "Move the plate into the reader before reading it.",
            )
        else:
            # A teaching number, proportional to the stock tracer in each well.
            reading = {
                name: round(w["solute"] / w["volume"], 2) if w["volume"] else 0.0
                for name, w in state["wells"].items()
                if name != "stock"
            }
            state.setdefault("readings", []).append({"step": index + 1, "wells": reading})
            detail = "Plate read: " + ", ".join(f"{k} {v:g}%" for k, v in reading.items())
    elif (
        kind in {"aspirate", "dispense"}
        and action["well"] != "stock"
        and plate["at"]
        in {
            "reader",
            "stacker",
        }
    ):
        problem = (
            "plate_away",
            f"The plate is in {NAMES[plate['at']]}, where the pipette cannot reach it.",
            "Move the plate back to the deck or onto a module before pipetting into it.",
        )
    elif kind == "pickup":
        if pipette["tip"]:
            problem = (
                "tip_attached",
                "There is already a tip attached.",
                "Discard it before picking up a fresh tip.",
            )
        elif state["tips_used"] >= 96:
            problem = (
                "tips_empty",
                "The tip rack is empty.",
                "Reset the experiment to replenish the rack.",
            )
        else:
            pipette.update(tip=True, used=False)
            state["tips_used"] += 1
    elif not pipette["tip"]:
        problem = (
            "no_tip",
            "The pipette has no tip.",
            "Add a pick-up step before transferring liquid.",
        )
    elif kind == "aspirate":
        if pipette["used"]:
            problem = (
                "used_tip",
                "This tip has already dispensed into a destination.",
                "This lesson requires a fresh tip for each transfer to reduce carryover risk.",
            )
        elif pipette["volume"] >= pipette_ul or volume + pipette["volume"] > pipette_ul + 1e-8:
            problem = (
                "capacity",
                f"The requested volume exceeds the {pipette_ul:,} µL "
                f"{'' if studio else 'teaching '}pipette capacity.",
                "Reduce the transfer volume or split it into smaller transfers.",
            )
        elif well["volume"] <= 0 or volume > well["volume"] + 1e-8:
            problem = (
                "source_empty",
                f"{action['well']} contains only {well['volume']:g} µL.",
                "Check the starting liquid amount and earlier transfers.",
            )
        else:
            # Tolerate floating-point roundoff without moving more liquid than exists.
            volume = min(volume, well["volume"], pipette_ul - pipette["volume"])
            solute = well["solute"] * volume / well["volume"]
            well["volume"] -= volume
            well["solute"] -= solute
            pipette["volume"] += volume
            pipette["solute"] += solute
    elif kind == "dispense":
        if pipette["volume"] <= 0 or volume > pipette["volume"] + 1e-8:
            problem = (
                "insufficient_liquid",
                f"The tip holds only {pipette['volume']:g} µL.",
                "Aspirate enough liquid before dispensing.",
            )
        elif volume + well["volume"] > (1500 if action["well"] == "stock" else well_ul):
            problem = (
                "overflow",
                "The destination would exceed its "
                f"{1500 if action['well'] == 'stock' else well_ul:,} µL "
                f"{'' if studio else 'teaching '}capacity.",
                "Use less liquid or a different destination.",
            )
        else:
            volume = min(volume, pipette["volume"])
            solute = pipette["solute"] * volume / pipette["volume"]
            pipette["volume"] -= volume
            pipette["solute"] -= solute
            well["volume"] += volume
            well["solute"] += solute
            pipette["used"] = True
    elif kind == "drop":
        state["waste_volume"] += pipette["volume"]
        state["waste_solute"] += pipette["solute"]
        pipette.update(volume=0, solute=0, tip=False, used=False)
        state["tips_discarded"] += 1

    if problem:
        code, message, hint = problem
        result["status"] = "faulted"
        result["events"].append(
            {
                "step": index + 1,
                "level": "error",
                "code": code,
                "message": message,
                "hint": hint,
                # A refused step changes nothing; replay shows the state it met.
                "state": deepcopy(state),
            }
        )
    else:
        result["cursor"] += 1
        detail = detail or (
            f"{volume:g} µL · {action['well']}"
            if kind in {"aspirate", "dispense"}
            else "Fresh tip attached"
            if kind == "pickup"
            else "Tip discarded"
        )
        result["events"].append(
            {
                "step": index + 1,
                "level": "success",
                "code": kind,
                "message": detail,
                "hint": "",
                "state": deepcopy(state),
            }
        )
        if result["cursor"] == len(result["experiment"]["actions"]):
            result["status"] = "completed"
            result["assessment"] = assessment(state, result["experiment"], result["cursor"])
    return result


def control(session: dict, command: str) -> dict:
    result = deepcopy(session)
    status = result["status"]
    if command in {"start", "resume"} and not result["experiment"]["actions"]:
        raise InvalidTransition("Add a step before running your workflow")
    if command == "start" and status == "draft":
        result["status"] = "running"
    elif command == "pause" and status == "running":
        result["status"] = "paused"
    elif command == "resume" and status == "paused":
        result["status"] = "running"
    elif command == "reset":
        if status != "draft":
            result["attempts"] = (
                result["attempts"]
                + [
                    {
                        "status": status,
                        "steps": result["cursor"],
                        "assessment": result["assessment"],
                        "last_event": result["events"][-1] if result["events"] else None,
                        "learning": deepcopy(result.get("learning")),
                    }
                ]
            )[-10:]
        result.update(
            status="draft",
            cursor=0,
            state=initial_state(result["experiment"]),
            events=[],
            assessment=None,
        )
        if result["experiment"]["course_id"] == "flex-first-transfer":
            result["learning"].update(phase="prepare", checks=[], prediction=None, reflection="")
    else:
        raise InvalidTransition(f"Cannot {command} an experiment that is {status}")
    return result
