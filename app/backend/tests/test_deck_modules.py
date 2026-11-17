"""Deck modules in a Workflow Studio design: the plate moves, and each module has limits."""

import pytest
from academy.models import Experiment
from academy.opentrons_check import check, protocol
from academy.teaching import control, execute_step, new_session
from pydantic import ValidationError

FLEX = {"stock": "D1", "plate": "D2", "tips": "B1", "waste": "D3"}
OT2 = {"stock": "1", "plate": "2", "tips": "4", "waste": "12"}
ALL = ["gripper", "heater_shaker", "temperature", "reader", "stacker"]
TRANSFER = [
    {"kind": "pickup"},
    {"kind": "aspirate", "volume": 100},
    {"kind": "dispense", "well": "A1", "volume": 100},
    {"kind": "drop"},
]


def move(to):
    return {"kind": "move", "to": to}


def design(actions, modules=ALL, instrument="flex", **fields):
    return Experiment(
        course_id="workflow-sandbox",
        instrument=instrument,
        layout=FLEX if instrument == "flex" else OT2,
        source_volume=1000,
        diluent_volume=0,
        actions=actions,
        modules=modules,
        **fields,
    )


def run(experiment):
    session = control(new_session(experiment), "start")
    while session["status"] == "running":
        session = execute_step(session)
    return session


def test_a_plate_is_heated_shaken_read_and_stored():
    session = run(
        design(
            [
                *TRANSFER,
                move("heater_shaker"),
                {"kind": "heat", "value": 60},
                {"kind": "shake", "value": 1000, "seconds": 30},
                move("reader"),
                {"kind": "read"},
                move("stacker"),
                move("deck"),
            ]
        )
    )
    assert session["status"] == "completed" and session["assessment"]["passed"]
    assert session["state"]["plate"] == {"at": "deck", "temperature": None, "shaken": True}
    # The reading is the stock tracer in each well: A1 holds undiluted stock.
    assert session["state"]["readings"] == [{"step": 9, "wells": {"A1": 100, "A2": 0, "A3": 0}}]
    assert [e["message"] for e in session["events"]][4:7] == [
        "Plate moved to the Heater-Shaker",
        "Plate at 60 °C on the Heater-Shaker",
        "Shaken at 1000 rpm for 30 s",
    ]


@pytest.mark.parametrize(
    ("actions", "modules", "instrument", "step", "code"),
    [
        ([move("heater_shaker")], ["heater_shaker"], "flex", 1, "no_gripper"),
        ([move("reader")], ["gripper"], "flex", 1, "module_missing"),
        ([move("deck")], ALL, "flex", 1, "already_there"),
        ([{"kind": "heat", "value": 60}], ALL, "flex", 1, "not_on_module"),
        (
            [move("heater_shaker"), {"kind": "heat", "value": 20}],
            ALL,
            "flex",
            2,
            "temperature_range",
        ),
        ([move("temperature"), {"kind": "heat", "value": 0}], ALL, "flex", 2, "temperature_range"),
        ([move("temperature"), {"kind": "shake", "value": 500}], ALL, "flex", 2, "not_on_module"),
        ([move("heater_shaker"), {"kind": "shake", "value": 100}], ALL, "flex", 2, "shake_range"),
        ([{"kind": "read"}], ALL, "flex", 1, "not_in_reader"),
        ([move("reader"), *TRANSFER], ALL, "flex", 4, "plate_away"),
        ([move("stacker"), *TRANSFER], ALL, "flex", 4, "plate_away"),
        # The OT-2 has no gripper: its plate is moved by hand, so the move is allowed.
        (
            [move("heater_shaker"), {"kind": "heat", "value": 120}],
            ["heater_shaker"],
            "ot2",
            2,
            "temperature_range",
        ),
    ],
)
def test_a_module_mistake_stops_the_run_where_it_is_made(actions, modules, instrument, step, code):
    session = run(design(actions, modules, instrument))
    fault = session["events"][-1]
    assert (session["status"], fault["step"], fault["code"]) == ("faulted", step, code)
    assert fault["hint"]
    # A refused step leaves the plate where it was.
    before = session["events"][-2]["state"]["plate"] if len(session["events"]) > 1 else None
    assert before is None or fault["state"]["plate"] == before


def test_pipetting_reaches_a_plate_on_a_module():
    session = run(design([move("temperature"), {"kind": "heat", "value": 4}, *TRANSFER]))
    assert session["status"] == "completed"
    assert session["state"]["plate"]["temperature"] == 4


def test_a_design_with_modules_uses_the_flat_plate():
    overfilled = [
        {"kind": "pickup"},
        {"kind": "aspirate", "volume": 400},
        {"kind": "dispense", "well": "A1", "volume": 400},
    ]
    assert run(design(overfilled))["events"][-1]["code"] == "overflow"
    # Without modules the deep-well plate takes it.
    assert run(design(overfilled, modules=[]))["status"] == "completed"
    assert check(design(overfilled).model_dump())["plate"] == "corning_96_wellplate_360ul_flat"


def test_the_pipette_is_the_instruments_own():
    twice = [{"kind": "pickup"}, {"kind": "aspirate", "volume": 400}]
    assert run(design(twice, modules=[]))["status"] == "completed"
    assert run(design(twice, modules=[], instrument="ot2"))["events"][-1]["code"] == "capacity"


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"modules": ["reader"], "instrument": "ot2"}, "no plate reader or stacker"),
        ({"modules": ["gripper"], "instrument": "ot2"}, "no gripper"),
        ({"modules": ["reader", "reader"]}, "once"),
        ({"modules": ["heater_shaker"], "layout": {**FLEX, "tips": "C1"}}, "Slot C1"),
    ],
)
def test_impossible_decks_are_refused(fields, message):
    values = {"instrument": "flex", "layout": FLEX, **fields}
    if values["instrument"] == "ot2" and "layout" not in fields:
        values["layout"] = OT2
    with pytest.raises(ValidationError, match=message):
        Experiment(course_id="workflow-sandbox", actions=[], **values)
    with pytest.raises(ValidationError, match="Workflow Studio"):
        Experiment(course_id="flex-foundations", modules=["gripper"])


def test_saved_plans_without_modules_keep_their_shape():
    plain = Experiment(course_id="workflow-sandbox", actions=TRANSFER).model_dump()
    assert "modules" not in plain
    assert all(set(a) == {"kind", "well", "volume"} for a in plain["actions"])
    assert (
        "plate"
        not in new_session(Experiment(course_id="workflow-sandbox", actions=TRANSFER))["state"]
    )


def test_the_exported_protocol_works_latches_and_lids():
    plan = design(
        [
            *TRANSFER,
            move("heater_shaker"),
            {"kind": "shake", "value": 500, "seconds": 5},
            move("reader"),
            {"kind": "read"},
            move("stacker"),
            move("deck"),
        ]
    ).model_dump()
    assert check(plan)["stops"] == []
    source = protocol(plan)
    order = [
        "heater_shaker.open_labware_latch()",
        "ctx.move_labware(plate, heater_shaker_seat, use_gripper=True)",
        "heater_shaker.close_labware_latch()",
        "heater_shaker.set_and_wait_for_shake_speed(500)",
        "heater_shaker.deactivate_shaker()",
        "reader.open_lid()",
        "ctx.move_labware(plate, reader, use_gripper=True)",
        "reader.close_lid()",
        "reader.read()",
        "stacker.store()",
        "plate = stacker.retrieve()",
    ]
    # Each line follows the one before it, from the first workflow step on.
    at = source.index("pipette.pick_up_tip()")
    for line in order:
        at = source.index(line, at + 1)
    assert '"apiLevel": "2.25"' in source


def test_the_check_says_what_the_simulator_stops_and_what_it_lets_through():
    stops = check(design([move("heater_shaker"), {"kind": "heat", "value": 120}]).model_dump())
    assert [s["step"] for s in stops["stops"]] == [2]
    # The simulator accepts a Heater-Shaker below 37 °C and a command to an empty module.
    quiet = check(design([move("heater_shaker"), {"kind": "heat", "value": 20}]).model_dump())
    assert quiet["stops"] == [] and [n["step"] for n in quiet["unnoticed"]] == [2]
    empty = check(design([{"kind": "read"}]).model_dump())
    assert empty["stops"] == [] and "Reads while the plate is on the deck" in str(empty)
