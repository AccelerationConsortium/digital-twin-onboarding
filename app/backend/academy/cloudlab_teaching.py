"""What each cloud lab teaching twin teaches: what it is for, its parts and how it moves.

Every instrument gets a one-line purpose and the steps a learner takes with it, written
from its twin's operations and values. Instruments drawn with a ChemLab-Assets stand-in
also name the parts a learner can point at and a few states that move them. A state poses
the stand-in's own joints (chemlab_layout.json) as a fraction of the way to the limit its
contract gives, so the 3D view never moves a part further than the contract allows.

This is teaching copy about a comparable instrument, not the cloud lab's instrument or
its specification.
"""

import re
from typing import Literal

from pydantic import Field, model_validator

from .cloudlab import CLOUDLAB, CONTRACTS, overview
from .cloudlab_anatomy import anatomy
from .cloudlab_workflow import INSTRUMENTS as WORKFLOW
from .mock_contract import PlanError, execute_mock, site_keys
from .models import StrictModel

MAX_STEPS = 24
STATEMENT = (
    "Synthetic teaching run on one Academy twin. It checks the steps against the twin's "
    "rules only; it is not the cloud lab's instrument specification or a chemical result."
)
STEP_AT = re.compile(r"^Step (\d+):")

# id: one line on what the instrument is for.
DOES = {
    "robotic-sample-preparation": "Pipettes liquids between plates on a deck, so plates "
    "arrive at the next instrument ready.",
    "robotic-cell-preparation": "Pipettes cell cultures between plates and keeps them warm "
    "in its own incubator.",
    "acoustic-liquid-handler": "Moves nanolitre droplets with sound, without touching the "
    "liquid or using tips.",
    "plate-reader": "Shines light through each well and measures what comes back.",
    "plate-centrifuge": "Spins plates so solids settle and liquids collect at the bottom of "
    "each well.",
    "positive-pressure-filter": "Pushes liquid through a filter plate into the plate "
    "underneath with air pressure.",
    "plate-washer": "Empties wells and refills them with buffer, again and again, to rinse "
    "a plate.",
    "thermocycler": "Heats and cools a PCR plate in cycles to copy DNA.",
    "qpcr": "Cycles a PCR plate like a thermocycler and reads how much DNA there is after "
    "each cycle.",
    "analytical-hplc": "Pushes a sample through a column and detects each compound as it "
    "comes out.",
    "preparative-hplc": "Separates larger samples on a column and collects each compound "
    "into its own tube.",
    "lcms": "Separates a sample on a column, then weighs the molecules that come out.",
    "gcms": "Vaporises a sample, separates it in a heated column and weighs what comes out.",
    "sfc-ms": "Separates a sample with supercritical CO2 instead of a liquid, then weighs "
    "what comes out.",
    "ion-chromatography": "Separates charged ions on a column and measures each by conductivity.",
    "flash-chromatography": "Runs a sample through a cartridge and collects what comes out "
    "in fractions.",
    "capillary-electrophoresis": "Pulls proteins through a thin capillary with a voltage "
    "and separates them by size or charge.",
    "nmr": "Places a tube in a strong magnetic field and reads the signal of the atoms in "
    "the sample.",
    "dls-plate-reader": "Shines a laser into each well and reads how particles scatter it, "
    "to size them.",
    "icp-ms": "Turns a sample into ions in a plasma and counts the elements in it.",
    "peptide-synthesizer": "Builds a peptide one amino acid at a time in a heated reaction vessel.",
    "dna-synthesizer": "Builds DNA strands one base at a time on a column.",
    "elisa": "Incubates, washes and reads plates to detect a protein with antibodies.",
    "cell-incubator": "Keeps plates of cells warm, humid and at the right CO2 while they grow.",
}

# id: (ChemLab slug, {part: (label, what it is)},
#      [(state, label, {joint: 0–1}, what happens, the operation it shows or None)])
# The first state is the instrument at rest, every joint closed.
MOTION = {
    "plate-reader": (
        "bmg_clariostarplus",
        {
            "plate_carrier": ("Plate carrier", "Slides out of the front to take a plate."),
            "top_lid": ("Lid", "Opens the chamber for service; plates go in on the carrier."),
            "injector_a": ("Injectors", "Add a reagent to a well just before it is read."),
        },
        [
            (
                "reading",
                "Reading",
                {},
                "The plate sits in the dark chamber while each well is read.",
                "read",
            ),
            (
                "carrier-out",
                "Carrier out",
                {"plate_carrier": 1},
                "The carrier slides out of the lower left of the front for an arm to set a plate "
                "on it.",
                "load",
            ),
            (
                "lid-open",
                "Lid open",
                {"top_lid": 1},
                "With the lid up you can see into the chamber; plates still go in on the carrier.",
                None,
            ),
        ],
    ),
    "thermocycler": (
        "biorad_cfxopus",
        {
            "lid": ("Heated lid", "Presses on the plate so samples do not condense."),
            "sample_block": ("Block", "Holds the 96-well plate and heats and cools it."),
        },
        [
            (
                "cycling",
                "Cycling",
                {},
                "The lid is shut and the block heats and cools the plate in cycles.",
                "heat",
            ),
            (
                "lid-open",
                "Lid open",
                {"lid": 1},
                "The lid slides back to show the block; a plate drops into it from above.",
                "load",
            ),
        ],
    ),
    "qpcr": (
        "biorad_cfxopus",
        {
            "lid": ("Heated lid", "Presses on the plate and lets the optics see each well."),
            "sample_block": ("Block", "Holds the plate and heats and cools it."),
        },
        [
            (
                "cycling",
                "Cycling",
                {},
                "The block cycles and the optics read the glow of each well after every cycle.",
                "read",
            ),
            (
                "lid-open",
                "Lid open",
                {"lid": 1},
                "The lid slides back to show the block; a plate drops into it from above.",
                "load",
            ),
        ],
    ),
    "plate-washer": (
        "biotek_405ts",
        {
            "plate_carrier": ("Carrier", "Holds the plate and moves it under the manifold."),
            "manifold": ("Manifold", "96 tubes that empty and fill every well at once."),
        },
        [
            (
                "plate-in",
                "Plate in",
                {},
                "The plate sits on the carrier, clear of the manifold.",
                "load",
            ),
            (
                "under",
                "Under the manifold",
                {"plate_carrier": 1},
                "The carrier moves the plate under the manifold.",
                None,
            ),
            (
                "washing",
                "Washing",
                {"plate_carrier": 1, "manifold": 1},
                "The manifold dips into the wells to take out liquid and add fresh buffer.",
                "mix",
            ),
        ],
    ),
    "cell-incubator": (
        "eppendorf_cellxpertc170i",
        {
            "outer_door": ("Door", "Keeps the chamber warm; it opens from the left hinge."),
            "inner_door": (
                "Glass door",
                "Seals the chamber, so you can look in without losing the air.",
            ),
            "shelf_rack": ("Shelves", "Plates rest here while the cells grow."),
        },
        [
            (
                "closed",
                "Closed",
                {},
                "Both doors are shut; the chamber holds its temperature and CO2.",
                "heat",
            ),
            (
                "door-open",
                "Door open",
                {"outer_door": 1},
                "The outer door swings open; the glass door still seals the chamber.",
                None,
            ),
            (
                "plate-in",
                "Glass door open",
                {"outer_door": 1, "inner_door": 1},
                "Both doors open, so a plate can go onto the lowest shelf.",
                "load",
            ),
        ],
    ),
    "sfc-ms": (
        "agilent_1260infinity",
        {
            "drawer_1": ("Vial drawer", "Holds the vials waiting to be injected."),
            "sampler_door": ("Sampler door", "Covers the needle that draws each sample."),
            "mct_door": ("Column door", "Covers the columns the selector switches between."),
        },
        [
            (
                "running",
                "Running",
                {},
                "The sampler draws from one vial at a time and sends it through a column.",
                "read",
            ),
            (
                "drawer-out",
                "Drawer out",
                {"drawer_1": 1},
                "The top drawer slides out with its tray of vials.",
                "load",
            ),
            (
                "columns",
                "Columns",
                {"mct_door": 1},
                "Behind this door the columns sit in an oven, ready to be switched.",
                "heat",
            ),
        ],
    ),
    "flash-chromatography": (
        "biotage_selekt",
        {
            "tray": ("Tube tray", "Racks of tubes that catch each fraction."),
            "collector_y": ("Collector arm", "Moves the outlet over the next empty tube."),
        },
        [
            (
                "ready",
                "Ready",
                {},
                "The tray is in and the collector waits over the first tube.",
                None,
            ),
            (
                "tray-out",
                "Tray out",
                {"tray": 1},
                "The tray slides out of the front to swap the racks of tubes.",
                "load",
            ),
            (
                "collecting",
                "Collecting",
                {"collector_y": 1, "collector_x": 0.5},
                "The arm moves over the tubes, dropping each fraction into the next one.",
                "read",
            ),
        ],
    ),
    "capillary-electrophoresis": (
        "sciex_pa800",
        {
            "sample_cover": ("Sample cover", "Covers the trays the capillary dips into."),
            "cartridge_cover": ("Cartridge cover", "Covers the capillary cartridge."),
            "sample_tray_inlet": ("Sample tray", "Where the sample plate sits."),
        },
        [
            (
                "running",
                "Running",
                {},
                "The capillary dips into a sample and a voltage pulls the proteins through it.",
                "read",
            ),
            (
                "cover-open",
                "Cover open",
                {"sample_cover": 1},
                "The cover lifts to show the trays where the sample plate goes.",
                "load",
            ),
            (
                "cartridge",
                "Cartridge",
                {"cartridge_cover": 1},
                "Under this cover sits the cartridge with the capillary that separates proteins.",
                None,
            ),
        ],
    ),
    "peptide-synthesizer": (
        "cem_libertyblue",
        {
            "reactor_cover": ("Microwave cover", "Closes over the reaction vessel to heat it."),
            "reactor": ("Reaction vessel", "Where the peptide grows on resin beads."),
            "aa_rack": ("Amino acids", "Bottles the synthesiser draws from, one per step."),
        },
        [
            (
                "coupling",
                "Coupling",
                {},
                "The cover is down and microwaves heat each coupling step.",
                "mix",
            ),
            (
                "open",
                "Cover up",
                {"reactor_cover": 1, "reactor_clamp": 1},
                "The cover and clamp lift so the reaction vessel can be changed.",
                "load",
            ),
        ],
    ),
    "ion-chromatography": (
        "thermo_dionexintegrion",
        {
            "main_door": ("Door", "Covers the flow path."),
            "column_compartment": (
                "Columns",
                "The column, suppressor and detector the sample flows through.",
            ),
        },
        [
            (
                "closed",
                "Closed",
                {},
                "Samples arrive by tubing from an autosampler and flow through the column.",
                "read",
            ),
            (
                "door-open",
                "Door open",
                {"main_door": 1},
                "Behind the door: the column and the detector each sample passes.",
                None,
            ),
        ],
    ),
    "lcms": (
        "thermo_orbitrapexploris",
        {
            "source_housing": ("Ion source", "Turns the liquid from the column into ions."),
        },
        [
            (
                "running",
                "Running",
                {},
                "The column's outflow is sprayed into the source and the ions fly into the "
                "analyser.",
                "read",
            ),
            (
                "source-out",
                "Source out",
                {"source_housing": 1},
                "The ion source slides out on its rails for cleaning.",
                None,
            ),
        ],
    ),
    "icp-ms": (
        "shimadzu_icpms2030",
        {
            "plasma_cover": ("Plasma cover", "Covers the torch while the plasma burns."),
            "torch": ("Torch", "Where argon plasma turns the sample into ions."),
            "spray_chamber": ("Spray chamber", "Turns the liquid sample into a fine mist."),
        },
        [
            (
                "running",
                "Running",
                {},
                "The sample is sprayed into the plasma and its elements are counted.",
                "read",
            ),
            (
                "cover-up",
                "Cover up",
                {"plasma_cover": 1},
                "Under the cover: the torch, with the spray chamber feeding it.",
                None,
            ),
        ],
    ),
    "dna-synthesizer": (
        "cytiva_ktaoligosynt",
        {
            "column": ("Column", "Where the DNA strand grows, one base per cycle."),
            "column_clamp": ("Clamp", "Holds the column in the flow path."),
            "column_valve": ("Column valve", "Sends reagents through the column or past it."),
        },
        [
            ("ready", "Ready", {}, "Reagents flow through the column one after another.", "mix"),
            (
                "clamp-up",
                "Clamp up",
                {"column_clamp": 1},
                "The clamp lifts so the column can be swapped.",
                "load",
            ),
            (
                "bypass",
                "Valve turned",
                {"column_valve": 1},
                "The valve turns to send reagents past the column.",
                None,
            ),
        ],
    ),
}

# Acceleration Consortium instruments: what each is for, and how its stand-in moves.
DOES |= {
    "ac-biomek-i5": "Pipettes liquids between plates on its deck, column by column or one well "
    "at a time.",
    "ac-starlet": "Pipettes liquids between plates and tubes on a deck of carriers.",
    "ac-tecan": "Pipettes liquids between labware on its deck and hands plates to the next "
    "instrument.",
    "ac-balance": "Weighs a sample behind glass, so air currents do not move the reading.",
    "ac-capper": "Takes the caps off a rack of tubes, or screws them back on, all at once.",
    "ac-homogenizer": "Spins a rotor inside a stator to break a sample up and mix it evenly.",
    "ac-shaker": "Shakes plates in small circles while keeping them warm.",
    "ac-evaporator": "Spins plates under vacuum and gentle heat until the solvent is gone.",
    "ac-filtration": "Pushes samples through a filter plate with air pressure and collects "
    "what passes.",
    "ac-bead-separator": "Pulls magnetic beads out of each well so the liquid around them can "
    "be changed.",
    "ac-centrifuge": "Spins plates so solids settle and liquids collect at the bottom of each "
    "well.",
    "ac-plate-sealer": "Presses a heated film onto a plate to seal every well.",
    "ac-plate-stacker": "Holds a column of plates and hands them to the next instrument one by "
    "one.",
    "ac-cytomat": "Stores plates at a set temperature and CO2 and hands one out when asked.",
    "ac-scila": "Keeps a few plates warm in their own drawers between steps.",
    "ac-cytation-5": "Reads each well's light and takes microscope images of the cells in it.",
    "ac-cytation-c10": "Images each well through a confocal microscope and reads its light.",
    "ac-synergy-neo2": "Shines light through each well and measures what comes back, fast.",
    "ac-dls-reader": "Shines a laser into each well and reads how particles scatter it, to "
    "size them.",
    "ac-qpcr": "Cycles a PCR plate and reads how much DNA there is after each cycle.",
    "ac-hplc": "Pushes a sample through a column and detects each compound as it comes out.",
    "ac-uplc-ms": "Separates a sample on a column at high pressure, then weighs the molecules.",
    "ac-orbitrap-lcms": "Separates a sample on a column, then weighs its molecules very precisely.",
    "ac-medchem-lcms": "Separates a sample on a column and weighs what comes out, to check a "
    "compound.",
    "ac-purification": "Collects each compound from a separation into its own tube by its mass.",
    "ac-photoreactor": "Lights a set of stirred vials evenly to drive a reaction with light.",
    "ac-flow-reactor": "Pumps reagents through a heated channel and collects the product in "
    "fractions.",
    "ac-potentiostat": "Sets a voltage on an electrochemical cell and measures the current.",
    "ac-viscometer": "Turns a sample between plates and measures how hard it resists flowing.",
    "ac-dsc": "Heats a sample and an empty pan side by side and measures the heat difference.",
    "ac-indenter": "Presses a fine tip into a material and measures how far it goes in.",
}
# Where an AC instrument shares its stand-in with a cloud lab one, it moves the same way.
MOTION |= {
    ac: MOTION[same]
    for ac, same in {
        "ac-cytation-5": "plate-reader",
        "ac-cytation-c10": "plate-reader",
        "ac-synergy-neo2": "plate-reader",
        "ac-qpcr": "qpcr",
        "ac-uplc-ms": "lcms",
        "ac-orbitrap-lcms": "lcms",
        "ac-medchem-lcms": "lcms",
        "ac-cytomat": "cell-incubator",
        "ac-scila": "cell-incubator",
        "ac-bead-separator": "plate-washer",
        "ac-purification": "flash-chromatography",
    }.items()
}
MOTION |= {
    "ac-plate-stacker": (
        "eppendorf_cellxpertc170i",
        {
            "outer_door": ("Door", "Closes the stack off from the room."),
            "shelf_rack": ("Shelves", "Hold the plates one above another."),
        },
        [
            ("closed", "Closed", {}, "The door is shut; the plates wait in the stack.", "wait"),
            (
                "door-open",
                "Door open",
                {"outer_door": 1},
                "The door swings open so a plate can go onto a shelf.",
                "load",
            ),
        ],
    ),
    "ac-dls-reader": (
        "antonpaar_litesizerdls",
        {
            "sample_lid": ("Sample lid", "Shuts out room light over the cell."),
            "cuvette": ("Cuvette", "Holds the sample in the laser beam."),
        },
        [
            ("closed", "Closed", {}, "The lid is down; the cell sits in the beam.", "read"),
            (
                "lid-open",
                "Lid open",
                {"sample_lid": 1},
                "The lid swings up so the cell can be reached.",
                "load",
            ),
            (
                "cell-out",
                "Cell lifted out",
                {"sample_lid": 1, "cuvette": 1},
                "The cuvette comes up out of the temperature block.",
                "load",
            ),
        ],
    ),
    "ac-shaker": (
        "ika_ks4000",
        {
            "hood": ("Hood", "Closes the warm chamber over the plates."),
            "platform": ("Platform", "Carries the plates round in small circles."),
        },
        [
            ("closed", "Closed", {}, "The hood is down; the plates are kept warm.", "heat"),
            (
                "hood-open",
                "Hood open",
                {"hood": 1},
                "The hood swings up so plates can go onto the platform.",
                "load",
            ),
            (
                "shaking",
                "Shaking",
                {"hood": 0, "platform": 1},
                "The platform orbits to mix the wells.",
                "mix",
            ),
        ],
    ),
    "ac-evaporator": (
        "genevac_mivac2",
        {
            "lid": ("Lid", "Seals the chamber so it can be pumped down."),
            "rotor": ("Rotor", "Spins the plates while the solvent boils off."),
            "basket_left": ("Baskets", "Swing out with the plates as the rotor turns."),
        },
        [
            ("closed", "Closed", {}, "The lid is shut and the chamber is under vacuum.", "heat"),
            (
                "lid-open",
                "Lid open",
                {"lid": 1},
                "The lid opens so plates can go into the baskets.",
                "load",
            ),
            (
                "spinning",
                "Spinning",
                {"rotor": 0.5, "basket_left": 1, "basket_right": 1},
                "The rotor turns and the baskets swing out level.",
                "wait",
            ),
        ],
    ),
    "ac-homogenizer": (
        "ika_t25",
        {
            "drive": ("Drive", "Carries the dispersing tool down into the vessel."),
            "rotor": ("Rotor", "Spins inside the stator to shear the sample."),
            "vessel": ("Vessel", "Holds the sample under the tool."),
        },
        [
            ("down", "Tool in", {}, "The tool sits in the sample and the rotor shears it.", "mix"),
            (
                "raised",
                "Tool raised",
                {"drive": 1},
                "The drive rises so the vessel can be changed.",
                "load",
            ),
        ],
    ),
    "ac-photoreactor": (
        "hepatochem_photoredoxbox",
        {
            "lid": ("Lid", "Keeps the light inside the box."),
            "sample_rack": ("Vial rack", "Holds each vial the same distance from the lamps."),
        },
        [
            ("closed", "Closed", {}, "The lid is on and the lamps light the stirred vials.", "mix"),
            (
                "lid-open",
                "Lid open",
                {"lid": 1},
                "The lid lifts so vials can go into the rack.",
                "load",
            ),
        ],
    ),
    "ac-flow-reactor": (
        "syrris_asiadiscovery",
        {
            "chip_clamp": ("Chip clamp", "Holds the reactor chip against its heater."),
            "collector_x": ("Fraction collector", "Moves the nozzle along the rack of vials."),
        },
        [
            ("running", "Running", {}, "Reagents flow through the heated chip.", "heat"),
            (
                "collecting",
                "Collecting",
                {"collector_x": 1},
                "The nozzle moves along to fill the next vial.",
                "wait",
            ),
            (
                "chip-out",
                "Clamp open",
                {"chip_clamp": 1},
                "The clamp opens to change the chip.",
                None,
            ),
        ],
    ),
    "ac-viscometer": (
        "antonpaar_mcr503",
        {"head_lift": ("Measuring head", "Lowers onto the sample to measure it.")},
        [
            ("measuring", "Measuring", {}, "The head sits on the sample and turns it.", "read"),
            (
                "head-up",
                "Head up",
                {"head_lift": 1},
                "The head rises so a sample can go onto the stage.",
                "load",
            ),
        ],
    ),
    "ac-dsc": (
        "ta_dsc2500",
        {
            "lid": ("Cell lid", "Closes over the furnace during a run."),
            "sampler_x": ("Autosampler", "Carries pans between the trays and the cell."),
        },
        [
            ("closed", "Running", {}, "The lid is shut and the furnace heats both pans.", "heat"),
            (
                "loading",
                "Loading a pan",
                {"lid": 1, "sampler_x": 1},
                "The lid lifts and the autosampler sets a pan in the cell.",
                "load",
            ),
        ],
    ),
    "ac-indenter": (
        "antonpaar_hit300",
        {
            "load_head": ("Indentation head", "Lowers the tip into the specimen."),
            "stage_x": ("Stage", "Moves the specimen under the tip."),
        },
        [
            ("raised", "Head up", {}, "The tip is clear of the specimen.", "load"),
            (
                "indenting",
                "Indenting",
                {"load_head": 1},
                "The head comes down and the tip presses in.",
                "read",
            ),
            (
                "next-spot",
                "Next spot",
                {"stage_x": 1},
                "The stage moves the specimen to the next spot.",
                None,
            ),
        ],
    ),
}

VERB = {
    "load": "Load",
    "transfer": "Move in",
    "mix": "Mix",
    "heat": "Heat",
    "read": "Read",
    "wait": "Wait",
}


def volume(ul):
    return f"{ul / 1000:g} mL" if ul >= 1000 else f"{ul:g} µL"


def steps(spec):
    """How a learner uses the twin, one line per operation, from its own values."""
    vessel = spec["container"]["vessel"]
    slots = spec["resource"]["slots"]
    limits = spec["limits"]
    most = volume(spec["container"]["max_volume_ul"])
    lines = {
        "load": (
            f"Put a {vessel} in, up to {most}."
            if slots == 1
            else f"Put up to {slots} {vessel}s in, each up to {most}."
        ),
        "transfer": "Bring a sample from the instrument before.",
        "mix": "Mix the sample, by shaking or pipetting.",
        "heat": f"Set a temperature between {limits['min_temp_c']:g} and "
        f"{limits['max_temp_c']:g} °C.",
        "read": "Read the result.",
        "wait": f"Wait while it works, up to {limits['max_duration_s'] // 60:g} min a step.",
    }
    for item in spec["consumables"]:
        lines[item["used_by"]] += f" Each one uses {item['per_use']} of the {item['name'].lower()}."
    return [{"operation": op, "verb": VERB[op], "says": lines[op]} for op in spec["operations"]]


def motion(asset_id):
    """The parts and states of a drawn stand-in, with its joints, or None."""
    if asset_id not in MOTION:
        return None
    slug, parts, states = MOTION[asset_id]
    joints = CONTRACTS["stand_ins"][slug].get("joints", {})
    return {
        "node_prefix": f"{slug}__",
        "joints": joints,
        "parts": [
            {"id": part, "label": label, "about": about, "moves": part in joints}
            for part, (label, about) in parts.items()
        ],
        "states": [
            {"id": key, "label": label, "pose": pose, "says": says, "shows": shows}
            for key, label, pose, says, shows in states
        ],
    }


def instruments():
    """Meet the instruments' cloud lab overview, with what each twin teaches."""
    found = overview()
    for item in found["instruments"]:
        key = item["id"]
        item["does"] = DOES[key]
        item["motion"] = motion(key)
        item["anatomy"] = anatomy(key)
        shown = {x["shows"]: x["id"] for x in (item["motion"] or {"states": []})["states"]}
        # A step the 3D view can show names the state that shows it.
        item["steps"] = [
            {**step, "state": shown.get(step["operation"])} for step in steps(CLOUDLAB[key]["spec"])
        ]
        # The instruments the cloud lab workflow page can chain.
        item["in_workflow"] = key in WORKFLOW
        spec = CLOUDLAB[key]["spec"]
        item["sites"] = site_keys(spec)
        item["starter"] = starter(spec)
    return found


class Step(StrictModel):
    """One action on the instrument a learner is practising with."""

    operation: Literal["load", "mix", "heat", "read", "wait"]
    sample: str = Field(default="plate", pattern=r"^[a-z][a-z0-9-]{0,23}$")
    value: float = Field(default=1, ge=0.001, le=1_000_000, allow_inf_nan=False)
    slot: str = Field(default="", pattern=r"^[A-Za-z0-9-]{0,8}$")

    @model_validator(mode="after")
    def bounded(self):
        if self.slot and self.operation != "load":
            raise ValueError("Only a load chooses a slot")
        if self.operation == "heat" and not 4 <= self.value <= 120:
            raise ValueError("Teaching temperature must be 4–120 °C")
        return self


class Practice(StrictModel):
    steps: list[Step] = Field(max_length=MAX_STEPS)


def default(spec, operation):
    """A value the twin accepts for an action, to start a step from."""
    if operation == "load":
        return min(100, spec["container"]["max_volume_ul"])
    if operation == "heat":
        return round((spec["limits"]["min_temp_c"] + spec["limits"]["max_temp_c"]) / 2)
    if operation in {"mix", "wait"}:
        return min(60, spec["limits"]["max_duration_s"])
    return 1


def starter(spec):
    """Every action the instrument has, once, in its own order: the way to meet it."""
    return [
        {"operation": op, "sample": "plate", "value": default(spec, op), "slot": ""}
        for op in spec["operations"]
        if op != "transfer"
    ]


def practise(asset_id, steps):
    """The synthetic trace of steps on one twin, or the first step that breaks its rules."""
    twin = {"id": asset_id, "confirmed": True, "mode": "mock", "spec": CLOUDLAB[asset_id]["spec"]}
    try:
        trace = execute_mock(
            {asset_id: twin},
            [
                {
                    "device_id": asset_id,
                    "operation": step["operation"],
                    "sample": step["sample"],
                    "value": step["value"],
                    "site": step["slot"],
                }
                for step in steps
            ],
        )
    except PlanError as exc:
        found = STEP_AT.match(str(exc))
        # With one instrument there is nowhere to move a sample from: it is loaded here.
        message = re.sub(r"transfer (\S+) to .+ first$", r"load \1 first", str(exc))
        return {
            "ok": False,
            "trace": [],
            "error": {
                "step": int(found[1]) if found else None,
                "message": message,
                "layer": exc.layer,
            },
            "statement": STATEMENT,
        }
    return {"ok": True, "trace": trace, "error": None, "statement": STATEMENT}
