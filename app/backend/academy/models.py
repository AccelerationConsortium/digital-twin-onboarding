from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

SLOTS = {f"{row}{col}" for row in "ABCD" for col in range(1, 4)}
OT2_SLOTS = {str(slot) for slot in range(1, 13)}
DEFAULT_LAYOUT = {"stock": "D1", "plate": "D2", "tips": "B1", "waste": "D3"}
WELLS = {"stock", "A1", "A2", "A3"}
# Deck modules a Workflow Studio design can add, and the slot each one takes.
MODULE_SLOTS = {
    "flex": {"heater_shaker": "C1", "temperature": "A1", "reader": "B3", "stacker": "C3"},
    "ot2": {"heater_shaker": "7", "temperature": "6"},
}
MODULE_KINDS = {"move", "heat", "shake", "read"}
Module = Literal["gripper", "heater_shaker", "temperature", "reader", "stacker"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Action(StrictModel):
    kind: Literal["pickup", "aspirate", "dispense", "drop", "move", "heat", "shake", "read"]
    well: Literal["stock", "A1", "A2", "A3"] = "stock"
    volume: float = Field(default=100, gt=0, le=1000)
    # Where a move takes the sample plate.
    to: Literal["deck", "heater_shaker", "temperature", "reader", "stacker"] = "deck"
    # °C for heat, rpm for shake.
    value: float = Field(default=0, ge=0, le=5000)
    seconds: float = Field(default=0, ge=0, le=3600)

    @model_serializer(mode="wrap")
    def keep_pipetting_wire_format(self, handler):
        definition = handler(self)
        # Pipetting steps keep the three fields saved plans and native hashes were made with.
        if self.kind not in MODULE_KINDS:
            for field in ("to", "value", "seconds"):
                definition.pop(field, None)
        return definition


def default_actions() -> list[Action]:
    result = []
    for source, target in [("stock", "A1"), ("A1", "A2"), ("A2", "A3")]:
        result.extend(
            [
                Action(kind="pickup"),
                Action(kind="aspirate", well=source),
                Action(kind="dispense", well=target),
                Action(kind="drop"),
            ]
        )
    return result


class Experiment(StrictModel):
    title: str = Field(default="My serial dilution", min_length=1, max_length=80)
    course_id: Literal["flex-foundations", "flex-first-transfer", "workflow-sandbox"] = (
        "flex-foundations"
    )
    instrument: Literal["flex", "ot2"] = "flex"
    transfer_volume: float = Field(default=100, ge=1, le=300)
    layout: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_LAYOUT))
    source_volume: float = Field(default=1000, ge=0, le=1500)
    diluent_volume: float = Field(default=100, ge=0, le=1500)
    actions: list[Action] = Field(default_factory=default_actions, max_length=64)
    modules: list[Module] = Field(default_factory=list, max_length=5)

    @model_serializer(mode="wrap")
    def keep_fixed_flex_wire_format(self, handler):
        definition = handler(self)
        if not self.modules:
            definition.pop("modules", None)
        # Existing courses have always implied Flex. Preserve their native hashes and
        # gateway schema while making the new instrument choice explicit in studio plans.
        if self.course_id != "workflow-sandbox":
            definition.pop("instrument", None)
        return definition

    @model_validator(mode="after")
    def layout_is_valid(self):
        if self.course_id != "workflow-sandbox":
            if self.instrument != "flex":
                raise ValueError("This lesson uses the Opentrons Flex")
            if not self.actions:
                raise ValueError("This lesson needs at least one workflow step")
        if self.course_id != "workflow-sandbox" and (
            self.modules or any(a.kind in MODULE_KINDS for a in self.actions)
        ):
            raise ValueError("Deck modules belong to Workflow Studio designs")
        if len(set(self.modules)) != len(self.modules):
            raise ValueError("Add each module once")
        taken = MODULE_SLOTS[self.instrument]
        for module in self.modules:
            if module != "gripper" and module not in taken:
                raise ValueError("The OT-2 has no plate reader or stacker; use a Flex for those")
        if self.instrument == "ot2" and "gripper" in self.modules:
            raise ValueError("The OT-2 has no gripper; labware is moved by hand")
        if (
            self.modules or any(a.kind in MODULE_KINDS for a in self.actions)
        ) and self.diluent_volume > 360:
            raise ValueError("With modules the plate is a flat one whose wells hold 360 µL")
        if set(self.layout) != set(DEFAULT_LAYOUT):
            raise ValueError("Use the stock vial, destination plate, tip rack and waste")
        for module in self.modules:
            if taken.get(module) in self.layout.values():
                raise ValueError(
                    f"Slot {taken[module]} is where the {module.replace('_', ' ')} goes; "
                    "move the labware there to another slot"
                )
        slots = SLOTS if self.instrument == "flex" else OT2_SLOTS
        if not set(self.layout.values()) <= slots:
            raise ValueError(
                "Labware must occupy a Flex deck slot A1–D3"
                if self.instrument == "flex"
                else "Use OT-2 deck positions 1–11 and fixed trash position 12"
            )
        if len(set(self.layout.values())) != len(self.layout):
            raise ValueError("Two pieces of labware cannot occupy the same slot")
        if self.instrument == "flex" and self.layout["waste"] != "D3":
            raise ValueError("The Flex waste chute is fixed at D3. It is not a movable trash bin.")
        if self.instrument == "ot2" and self.layout["waste"] != "12":
            raise ValueError("The OT-2 fixed trash occupies position 12")
        if self.course_id == "flex-first-transfer":
            expected = [
                ("pickup", "stock"),
                ("aspirate", "stock"),
                ("dispense", "A1"),
                ("drop", "stock"),
            ]
            if [(a.kind, a.well) for a in self.actions] != expected:
                raise ValueError(
                    "The first-transfer lesson uses pick up, aspirate stock, dispense A1, discard"
                )
            if any(
                a.volume != self.transfer_volume
                for a in self.actions
                if a.kind in {"aspirate", "dispense"}
            ):
                raise ValueError("Transfer actions must match the lesson volume")
            if self.diluent_volume != 0 or self.source_volume < self.transfer_volume:
                raise ValueError("Start with empty destination wells and enough source liquid")
        return self


class Prediction(StrictModel):
    source: float = Field(ge=0, le=1500)
    tip: float = Field(ge=0, le=300)
    target: float = Field(ge=0, le=1500)


class LearningProgress(StrictModel):
    phase: Literal["orient", "prepare", "predict", "run", "reflect"] = "orient"
    visited: list[Literal["pipette", "tips", "stock", "plate", "waste"]] = Field(
        default_factory=list, max_length=5
    )
    checks: list[Literal["instrument", "labware", "liquids", "simulation"]] = Field(
        default_factory=list, max_length=4
    )
    location_answer: Literal["", "slot", "well"] = ""
    prediction: Prediction | None = None
    reflection: Literal["", "source_to_tip", "source_to_target", "target_to_tip"] = ""


class UpdateLearning(StrictModel):
    version: int = Field(ge=1)
    learning: LearningProgress


class Revision(StrictModel):
    version: int = Field(ge=1)


class UpdateExperiment(Revision):
    experiment: Experiment


class Guest(StrictModel):
    name: str = Field(min_length=1, max_length=60)


class Profile(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    experience: Literal["new", "some", "experienced"] = "new"
    onboarded: bool = False


COURSES = [
    {
        "id": "workflow-sandbox",
        "number": "04",
        "title": "Workflow Studio",
        "subtitle": "Build your own liquid-handling workflow for the Flex or OT-2.",
        "duration": "Explore at your own pace",
        "level": "Create and experiment",
        "objectives": [
            "Arrange an instrument-specific teaching deck",
            "Compose steps and explore liquid amounts",
            "Explain observations and revise your design",
        ],
        "model_note": "Synthetic teaching model: the instrument's own pipette (1,000 µL on the Flex, 300 µL on the OT-2), four liquid locations, optional deck modules, ideal mixing and fresh-tip rules. No hardware, Isaac/GPU or chemical validation.",
    },
    {
        "id": "workflow-readiness",
        "number": "03",
        "title": "Can this workflow run?",
        "subtitle": "Find capability gaps, repair a synthetic plan and reconcile an unknown outcome.",
        "duration": "15–20 min",
        "level": "Workflow judgment",
        "objectives": [
            "Distinguish declarations from evidence",
            "Repair and test a teaching workflow",
            "Reconcile before retrying",
        ],
        "model_note": "Synthetic teaching and scripted incidents only. No hardware authorization.",
    },
    {
        "id": "flex-first-transfer",
        "number": "01",
        "title": "From manual pipetting to your first automated transfer",
        "subtitle": "Meet the Flex, predict liquid volumes and complete a 100 µL transfer step by step.",
        "duration": "20–30 min",
        "level": "First steps",
        "objectives": [
            "Identify equipment and wells",
            "Check the deck and liquids",
            "Explain a liquid transfer",
        ],
        "model_note": "Practice uses a teaching model. Live 3D and remote execution require a qualified Ubuntu gateway.",
    },
    {
        "id": "flex-foundations",
        "number": "01",
        "title": "A little less, each time.",
        "subtitle": "Learn the Flex through a three-step serial dilution.",
        "duration": "15–20 min",
        "level": "Getting started",
        "objectives": [
            "Arrange a Flex deck",
            "Build a transfer sequence",
            "Diagnose and recover from mistakes",
        ],
        "target_concentrations": {"A1": 50, "A2": 25, "A3": 12.5},
        "model_note": "Teaching model: ideal mixing, volume bookkeeping and fresh-tip rules. No collision physics, fluid dynamics or chemical predictions.",
    },
]
