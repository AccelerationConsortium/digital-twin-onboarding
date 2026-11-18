"""What the Opentrons simulator would say about a Studio plan, and the protocol to try it.

The rules mirror what `opentrons_simulate` did with the same mistakes (opentrons 9.0.0;
API 2.20, or 2.25 for a design with deck modules). It stops a run for tip and pipette
volume errors, for a Heater-Shaker asked for a temperature or speed it cannot reach, and
for pipetting into a plate the stacker holds; it runs low volumes, overfilled wells, dry
sources and empty modules without complaint, so those are reported separately. Latches
and lids are worked by the emitted protocol, not by the learner. Nothing here is a run
on a robot.
"""

import json

from .models import MODULE_KINDS, MODULE_SLOTS
from .teaching import HEAT_RANGE, NAMES, SHAKE_RANGE, uses_modules

API_LEVEL = "2.20"
MODULE_API_LEVEL = "2.25"
PLATE = {"load_name": "nest_96_wellplate_2ml_deep", "capacity_ul": 2000}
# The plate reader takes labware up to 16 mm tall, so designs with modules use a flat plate.
FLAT_PLATE = {"load_name": "corning_96_wellplate_360ul_flat", "capacity_ul": 360}
STOCK = {"load_name": "nest_12_reservoir_15ml", "capacity_ul": 15000}
PROFILES = {
    "flex": {
        "robot": "Flex",
        "pipette": "flex_1channel_1000",
        "pipette_name": "Flex 1-Channel 1000 µL",
        "tips": "opentrons_flex_96_tiprack_1000ul",
        "min_ul": 5,
        "max_ul": 1000,
        "waste": "ctx.load_waste_chute()",
    },
    "ot2": {
        "robot": "OT-2",
        "pipette": "p300_single_gen2",
        "pipette_name": "P300 Single-Channel GEN2",
        "tips": "opentrons_96_tiprack_300ul",
        "min_ul": 20,
        "max_ul": 300,
        "waste": "ctx.fixed_trash",
    },
}


def _ul(value):
    return f"{value:g} µL"


def _plate(experiment):
    return FLAT_PLATE if uses_modules(experiment) else PLATE


def check(experiment: dict) -> dict:
    instrument = experiment.get("instrument", "flex")
    profile = PROFILES[instrument]
    plate = _plate(experiment)
    modules = experiment.get("modules", [])
    at = "deck"
    wells = {
        "stock": experiment["source_volume"],
        **dict.fromkeys(("A1", "A2", "A3"), experiment["diluent_volume"]),
    }
    capacity = {
        "stock": STOCK["capacity_ul"],
        **dict.fromkeys(("A1", "A2", "A3"), plate["capacity_ul"]),
    }
    stops, unnoticed = [], []
    tip, held = False, 0.0

    def stop(step, message):
        stops.append({"step": step, "message": message})

    def note(step, message):
        unnoticed.append({"step": step, "message": message})

    for name, amount in wells.items():
        if amount > capacity[name]:
            note(None, f"{name} starts with {_ul(amount)}, more than its labware holds")
    for step, action in enumerate(experiment["actions"], 1):
        kind, well, volume = action["kind"], action["well"], action["volume"]
        if kind == "move":
            to = action.get("to", "deck")
            if instrument != "ot2" and "gripper" not in modules:
                # The simulator assumes a gripper is installed.
                note(step, "Moves the plate with a gripper this Flex does not have")
            if to != "deck" and to not in modules:
                stop(step, f"Moves the plate to {NAMES[to]}, which is not on the deck")
            elif to == at:
                stop(step, f"Moves the plate to {NAMES[to]}, where it already is")
            else:
                at = to
            continue
        if kind == "heat":
            low, high = HEAT_RANGE.get(at, (0, 0))
            value = action["value"]
            if at not in HEAT_RANGE:
                # No module is addressed, so no command is sent.
                note(step, f"Sets a temperature while the plate is on {NAMES[at]}")
            elif not low <= value <= high:
                message = f"Asks {NAMES[at]} for {value:g} °C; it holds {low}–{high} °C"
                # The simulator refuses what is above the Heater-Shaker's range or outside
                # -9 to 99 °C on the Temperature Module, and lets the rest through.
                refused = value > high if at == "heater_shaker" else not -9 <= value <= 99
                (stop if refused else note)(step, message)
            continue
        if kind == "shake":
            if "heater_shaker" not in modules:
                note(step, "Shakes with no Heater-Shaker on the deck")
            elif at != "heater_shaker":
                # Its latch is closed only around a plate, and it will not shake unlatched.
                stop(step, f"Shakes while the plate is on {NAMES[at]}")
            elif not SHAKE_RANGE[0] <= action["value"] <= SHAKE_RANGE[1]:
                stop(
                    step,
                    f"Asks the Heater-Shaker for {action['value']:g} rpm; "
                    "it shakes at 200–3000 rpm",
                )
            continue
        if kind == "read":
            if at != "reader":
                note(step, f"Reads while the plate is on {NAMES[at]}")
            continue
        if kind in {"aspirate", "dispense"} and well != "stock" and at == "stacker" and tip:
            stop(step, "Pipettes into a plate the stacker is holding")
            continue
        if kind in {"aspirate", "dispense"} and well != "stock" and at == "reader" and tip:
            note(step, "Pipettes into a plate inside the plate reader")
        if kind == "pickup":
            if tip:
                stop(step, "Picks up a tip while one is still attached")
            tip = True
            continue
        if not tip:
            verb = "Drops a tip" if kind == "drop" else f"{kind.capitalize()}s"
            stop(step, f"{verb} with no tip attached")
            continue
        if kind == "drop":
            if held > 1e-6:
                note(step, f"Drops the tip with {_ul(held)} still in it")
            tip, held = False, 0.0
            continue
        if volume < profile["min_ul"]:
            low = _ul(profile["min_ul"])
            note(
                step, f"{_ul(volume)} is below the {low} the {profile['pipette_name']} can measure"
            )
        if kind == "aspirate":
            room = profile["max_ul"] - held
            if volume > room + 1e-6:
                stop(step, f"Aspirates {_ul(volume)} when the tip has room for {_ul(room)}")
                continue
            if wells[well] < volume - 1e-6:
                note(step, f"Aspirates {_ul(volume)} from {well}, which holds {_ul(wells[well])}")
            wells[well] = max(0.0, wells[well] - volume)
            held += volume
        else:
            if volume > held + 1e-6:
                stop(step, f"Dispenses {_ul(volume)} when the tip holds {_ul(held)}")
                continue
            held -= volume
            wells[well] += volume
            if wells[well] > capacity[well] + 1e-6:
                note(step, f"Fills {well} to {_ul(wells[well])}, past its {_ul(capacity[well])}")
    if tip:
        note(None, "Ends with a tip still on the pipette")
    return {
        "robot": profile["robot"],
        "pipette": profile["pipette_name"],
        "tips": profile["tips"],
        "plate": plate["load_name"],
        "stock": STOCK["load_name"],
        "api_level": MODULE_API_LEVEL if uses_modules(experiment) else API_LEVEL,
        "evidence": "synthetic",
        "stops": stops,
        "unnoticed": unnoticed,
    }


ADAPTERS = {
    "heater_shaker": ("heaterShakerModuleV1", "opentrons_universal_flat_adapter"),
    "temperature": ("temperature module gen2", "opentrons_aluminum_flat_bottom_plate"),
}


def protocol_steps(experiment: dict) -> tuple[str, dict[int, int]]:
    """The Protocol API file for the plan, and which workflow step each of its lines is."""
    instrument = experiment.get("instrument", "flex")
    profile = PROFILES[instrument]
    layout = experiment["layout"]
    modules = experiment.get("modules", [])
    slots = MODULE_SLOTS[instrument]
    with_modules = uses_modules(experiment)
    level = MODULE_API_LEVEL if with_modules else API_LEVEL
    gripper = "True" if instrument == "flex" else "False"
    lines = [
        f"requirements = {json.dumps({'robotType': profile['robot'], 'apiLevel': level})}",
        f"metadata = {json.dumps({'protocolName': experiment['title']}, ensure_ascii=True)}",
        "",
        "",
        "def run(ctx):",
        f'    tips = ctx.load_labware("{profile["tips"]}", "{layout["tips"]}")',
        f'    plate = ctx.load_labware("{_plate(experiment)["load_name"]}", "{layout["plate"]}")',
        f'    stock = ctx.load_labware("{STOCK["load_name"]}", "{layout["stock"]}")',
        f'    pipette = ctx.load_instrument("{profile["pipette"]}", "left", tip_racks=[tips])',
        f"    waste = {profile['waste']}",
    ]
    for module in ("heater_shaker", "temperature"):
        if module in modules:
            model, adapter = ADAPTERS[module]
            lines += [
                f'    {module} = ctx.load_module("{model}", "{slots[module]}")',
                f'    {module}_seat = {module}.load_adapter("{adapter}")',
            ]
    if "reader" in modules:
        lines += [
            f'    reader = ctx.load_module("absorbanceReaderV1", "{slots["reader"]}")',
            "    reader.close_lid()",
            '    reader.initialize("single", [450])',
        ]
    if "stacker" in modules:
        # The stacker stands in column 4 and takes the slot beside it.
        lines += [
            f'    stacker = ctx.load_module("flexStackerModuleV1", "{slots["stacker"][0]}4")',
            f'    stacker.set_stored_labware("{FLAT_PLATE["load_name"]}", count=0)',
        ]
    seats = {
        "deck": f'"{layout["plate"]}"',
        "heater_shaker": "heater_shaker_seat",
        "temperature": "temperature_seat",
        "reader": "reader",
        "stacker": "stacker",
    }
    owner, at = {}, "deck"

    def emit(step, *code):
        for line in code:
            lines.append(f"    {line}")
            owner[len(lines)] = step

    for step, action in enumerate(experiment["actions"], 1):
        kind = action["kind"]
        if kind in MODULE_KINDS:
            to, value = action.get("to", "deck"), action.get("value", 0)
            if kind == "move":
                # Latches, lids and the stacker's hopper are worked for the learner.
                if at == "heater_shaker":
                    emit(step, "heater_shaker.open_labware_latch()")
                if at == "reader" or to == "reader":
                    emit(step, "reader.open_lid()")
                if at == "stacker":
                    emit(step, "plate = stacker.retrieve()")
                if to == "heater_shaker":
                    emit(step, "heater_shaker.open_labware_latch()")
                emit(step, f"ctx.move_labware(plate, {seats[to]}, use_gripper={gripper})")
                if to == "heater_shaker":
                    emit(step, "heater_shaker.close_labware_latch()")
                if to == "reader":
                    emit(step, "reader.close_lid()")
                if to == "stacker":
                    emit(step, "stacker.store()")
                at = to
            elif kind == "heat" and at == "heater_shaker":
                emit(step, f"heater_shaker.set_and_wait_for_temperature({value:g})")
            elif kind == "heat" and at == "temperature":
                emit(step, f"temperature.set_temperature({value:g})")
            elif kind == "shake" and "heater_shaker" in modules:
                emit(
                    step,
                    f"heater_shaker.set_and_wait_for_shake_speed({value:g})",
                    f"ctx.delay(seconds={action.get('seconds', 0):g})",
                    "heater_shaker.deactivate_shaker()",
                )
            elif kind == "read" and at == "reader":
                emit(step, "reader.read()")
            else:
                # Nothing on the deck to command: the step is kept as a comment.
                emit(step, f"ctx.comment({json.dumps(kind + ' with no plate on a module for it')})")
            continue
        target = 'stock["A1"]' if action["well"] == "stock" else f'plate["{action["well"]}"]'
        emit(
            step,
            {
                "pickup": "pipette.pick_up_tip()",
                "drop": "pipette.drop_tip(waste)",
                "aspirate": f"pipette.aspirate({action['volume']:g}, {target})",
                "dispense": f"pipette.dispense({action['volume']:g}, {target})",
            }[kind],
        )
    source = "\n".join(lines) + "\n"
    compile(source, "academy_protocol.py", "exec")
    return source, owner


def protocol(experiment: dict) -> str:
    """A readable Protocol API file for the plan; the caller checks nothing stops it first."""
    return protocol_steps(experiment)[0]
