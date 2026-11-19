"""What is inside each drawn cloud lab stand-in: numbered parts a learner can pull apart.

The anatomy view on an instrument's own page fades the housing and moves these parts out
of it. A part is one or more of the stand-in's contract components (chemlab_layout.json
lists them); a name ending in `*` takes every component that starts with it. Components a
part does not name stay with the housing. A part moves away from the middle of the model,
or along `toward` (in the model's frame: x right, y back, z up) where that reads better.

This is teaching copy about a comparable instrument, not the cloud lab's instrument.
"""

from .cloudlab import CLOUDLAB, CONTRACTS

UP, FRONT, BACK = (0, 0, 1), (0, -1, 0), (0, 1, 0)
LEFT, RIGHT = (-1, 0, 0), (1, 0, 0)

# Stand-ins whose model names its nodes with a prefix other than `<slug>__`.
PREFIX = {"agilent_hplc1260": "hplc1260__", "agilent_gc8890b": "GC7890B__"}

# slug: [(label, what it does, components, toward or None)], in the order they are numbered.
ANATOMY = {
    "bmg_clariostarplus": [
        ("Top lid", "Closes the reading chamber off from room light.", ("top_lid",), UP),
        (
            "Optical head",
            "Light source, filters and detector; it reads each well from above or below.",
            ("optical_head",),
            UP,
        ),
        (
            "Incubation chamber",
            "Keeps the plate at a set temperature and atmosphere while it is read.",
            ("incubation_chamber",),
            None,
        ),
        (
            "Plate carrier",
            "Slides out to take the microplate, then carries it under the optics.",
            ("plate_carrier", "carrier_label"),
            FRONT,
        ),
        ("Microplate", "The samples, one per well.", ("microplate*",), (0, -1, 0.8)),
        (
            "Injectors",
            "Syringe pumps that add reagent to a well during the read.",
            ("injector_a*", "injector_b*", "injector_lines"),
            None,
        ),
        ("Reagent bottles", "Feed the injectors.", ("reagent_bottle_*",), None),
    ],
    "biorad_cfxopus": [
        ("Lid", "Presses the plate down so every well touches the block.", ("lid",), UP),
        (
            "Heated lid plate",
            "Stays hotter than the samples so no water condenses under the seal.",
            ("lid_heater_plate",),
            UP,
        ),
        (
            "Sample block",
            "Heats and cools the plate between the cycle temperatures.",
            ("sample_block", "block_wells"),
            None,
        ),
        ("Touch screen", "Where a run is set and followed.", ("touch_screen", "screen_ui"), FRONT),
        (
            "Fans and vents",
            "Carry the block's heat out of the case when it cools.",
            ("fan_grilles", "intake_vent_*", "lid_vents"),
            None,
        ),
        ("Power module", "Supplies the block and the electronics.", ("rear_power_module",), BACK),
    ],
    "biotek_405ts": [
        (
            "Manifold",
            "Rows of tubes that dispense buffer into the wells and aspirate it again.",
            ("manifold", "manifold_tubes", "manifold_screws"),
            UP,
        ),
        (
            "Manifold carriage",
            "Lowers the manifold into the wells and lifts it out.",
            ("manifold_carriage", "manifold_hood"),
            UP,
        ),
        (
            "Plate carrier",
            "Holds the plate and moves it under the manifold, row by row.",
            ("plate_carrier", "carrier_a1_label", "carrier_rails"),
            FRONT,
        ),
        ("Prime trough", "Catches buffer when the lines are primed.", ("prime_trough",), None),
        ("Buffer inlets", "Where the wash and rinse buffers come in.", ("buffer_inlets",), BACK),
        ("Touch screen", "Where a wash programme is chosen.", ("touch_screen", "screen_*"), None),
    ],
    "eppendorf_cellxpertc170i": [
        ("Outer door", "Insulated door that keeps the chamber warm.", ("outer_door*",), FRONT),
        (
            "Glass inner door",
            "Lets you look at the cultures without letting the warm, moist air out.",
            ("inner_door*",),
            FRONT,
        ),
        (
            "Shelves",
            "Hold the flasks and plates; holes let the air move round them.",
            ("shelf_*",),
            FRONT,
        ),
        ("Water tray", "Evaporates to keep the air humid.", ("water_tray", "water_surface"), None),
        (
            "Sensors",
            "Measure the temperature, CO2 and humidity the controller holds.",
            ("chamber_sensors", "rh_sensor"),
            None,
        ),
        ("Chamber", "The sealed space the cultures grow in.", ("chamber", "chamber_gasket"), None),
        ("Control panel", "Sets temperature and CO2.", ("control_panel", "touch_screen"), UP),
    ],
    "agilent_1260infinity": [
        (
            "Solvent cabinet",
            "Holds the co-solvent bottles above the pump.",
            ("solvent_cabinet*", "bottle_*"),
            UP,
        ),
        ("Degasser", "Removes dissolved gas so the pump does not stall.", ("degasser",), None),
        ("Pump heads", "Push CO2 and co-solvent at high pressure.", ("pump_head_*",), None),
        (
            "Sample drawers",
            "Hold the vials the injector draws from.",
            ("drawer_*", "vial_tray_1"),
            FRONT,
        ),
        (
            "Injection valve",
            "Switches a measured sample into the flowing stream.",
            ("injection_valve", "needle_assembly", "metering_device"),
            None,
        ),
        (
            "Columns",
            "Separate the sample's compounds; the valve picks one of four.",
            ("column_1", "column_2", "column_3", "column_4", "column_valve"),
            None,
        ),
        (
            "Flow cell",
            "Where the detector shines light through the separated stream.",
            ("flow_cell",),
            None,
        ),
        (
            "Back-pressure regulator",
            "Keeps the CO2 dense enough to act as a solvent.",
            ("bpr_unit",),
            None,
        ),
    ],
    "biotage_selekt": [
        ("Top cover", "Covers the fraction bay.", ("top_cover",), UP),
        (
            "Columns",
            "Cartridges of silica that separate the mixture as solvent flows through.",
            ("column_0*", "column_1*", "column_cap_*", "column_clamp_*", "column_wrap_*"),
            None,
        ),
        ("Pump", "Drives solvent through the column.", ("pump", "pump_tower"), None),
        ("UV cell", "Sees each compound come off the column.", ("uv_cell",), None),
        (
            "Fraction collector",
            "Moves the needle over the tubes and drops each compound into its own.",
            ("collector_x", "collector_y", "needle", "x_rail", "y_rail"),
            UP,
        ),
        ("Tube racks", "Hold the collection tubes.", ("tray", "rack_*", "tube_*"), FRONT),
        ("Solvent lines", "Bring in the solvents the gradient mixes.", ("solvent_*",), BACK),
    ],
    "sciex_pa800": [
        (
            "Sample cover",
            "Closes over the trays so the capillary can dip into the vials.",
            ("sample_cover",),
            UP,
        ),
        (
            "Capillary cartridge",
            "The thin, coolant-wrapped capillary the sample separates in.",
            ("capillary_cartridge",),
            UP,
        ),
        (
            "Electrodes",
            "Put the high voltage across the capillary that pulls the ions along.",
            ("electrode_inlet", "electrode_outlet"),
            None,
        ),
        (
            "Sample and buffer trays",
            "Hold the vials the capillary ends dip into.",
            ("sample_tray_*", "buffer_tray_*"),
            FRONT,
        ),
        (
            "UV detector",
            "Sees each band as it passes the window.",
            ("uv_detector", "detector_face"),
            None,
        ),
        ("Fibre optic", "Brings the light to the detector window.", ("fiber_optic_cable",), None),
    ],
    "cem_libertyblue": [
        (
            "Reactor cover",
            "Seals the reaction vessel inside the cavity.",
            ("reactor_cover", "cover_grip"),
            UP,
        ),
        (
            "Reaction vessel",
            "Where the resin and each amino acid react.",
            ("reactor", "reactor_basin", "reactor_clamp", "clamp_grip"),
            UP,
        ),
        (
            "Microwave cavity",
            "Heats the vessel quickly so each coupling takes minutes.",
            ("heater", "microwave_vents", "fiber_probe"),
            None,
        ),
        ("Amino acid rack", "One bottle per amino acid.", ("aa_*",), FRONT),
        ("Reagent bottles", "Activator, base and deprotection reagents.", ("reagent_*",), None),
        (
            "Valve block",
            "Routes each reagent to the vessel.",
            ("valve_block", "valve_fittings"),
            None,
        ),
        ("Resin tubes", "Hold the resin for each peptide in a batch.", ("resin_*", "ht12_*"), None),
    ],
    "thermo_dionexintegrion": [
        (
            "Front door",
            "Closes the column and detector compartments.",
            ("main_door", "door_*"),
            FRONT,
        ),
        (
            "Pump heads",
            "Push the eluent at a steady flow.",
            ("pump_head_*", "pump_cap_*", "pump_drive"),
            None,
        ),
        (
            "Eluent generator",
            "Makes the eluent electrically from water, at the set strength.",
            ("eluent_generator",),
            None,
        ),
        ("Injection valve", "Switches the sample into the eluent.", ("injection_valve",), None),
        (
            "Columns",
            "Separate the ions by how strongly they cling to the resin.",
            ("column_guard", "column_separator", "column_fitting_*", "trap_column"),
            None,
        ),
        (
            "Suppressor",
            "Takes the eluent's own conductivity away so the ions stand out.",
            ("suppressor", "suppressor_label"),
            None,
        ),
        ("Conductivity cell", "Measures each ion as it comes off.", ("conductivity_cell",), None),
    ],
    "thermo_orbitrapexploris": [
        (
            "Ion source",
            "Sprays the liquid into charged droplets that become gas-phase ions.",
            ("source_*", "spray_emitter", "sweep_cone", "probe_upper_cap"),
            FRONT,
        ),
        (
            "Ion transfer tube",
            "Carries the ions from air into the vacuum.",
            ("ion_transfer_tube", "transfer_*"),
            None,
        ),
        ("S-lens", "Focuses the ion stream.", ("s_lens*",), UP),
        ("Quadrupole", "Lets through only the masses chosen.", ("quadrupole*",), UP),
        ("C-trap", "Gathers a packet of ions and fires it into the analyser.", ("c_trap",), UP),
        (
            "Orbitrap analyser",
            "Ions orbit a central electrode; their frequency gives their mass.",
            ("orbitrap_*",),
            UP,
        ),
        (
            "Turbo pump",
            "Holds the high vacuum the ions need.",
            ("turbomolecular_pump", "turbo_*"),
            None,
        ),
    ],
    "shimadzu_icpms2030": [
        ("Plasma cover", "Shields the plasma.", ("plasma_cover",), UP),
        (
            "Nebuliser and spray chamber",
            "Turn the liquid sample into a fine mist and drop the larger drops.",
            ("nebulizer", "spray_chamber*"),
            None,
        ),
        (
            "Torch and RF coil",
            "Argon plasma at thousands of degrees that breaks the sample into ions.",
            ("torch", "torch_inner_tube", "torch_holder*", "rf_coil*"),
            None,
        ),
        (
            "Cones",
            "Two small holes that let the ions from the plasma into the vacuum.",
            ("sampling_cone", "skimmer_cone", "interface_flange"),
            None,
        ),
        (
            "Collision cell",
            "Helium knocks out ions that would be mistaken for the element.",
            ("collision_cell", "octopole_*"),
            UP,
        ),
        ("Quadrupole", "Lets through one mass at a time.", ("quadrupole*",), UP),
        ("Detector", "Counts the ions of each mass.", ("detector", "detector_entrance"), UP),
        ("Peristaltic pump", "Pulls the sample in at a steady rate.", ("pump_*",), None),
    ],
    "cytiva_ktaoligosynt": [
        (
            "Column",
            "Holds the support the DNA strand is built on.",
            ("column", "column_end_fittings"),
            FRONT,
        ),
        (
            "Column clamp",
            "Holds the column between its fittings.",
            ("column_clamp", "clamp_grip"),
            FRONT,
        ),
        ("Amidite bottles", "One building block per base.", ("monomer_*",), UP),
        (
            "Reagent bottles",
            "Activator, oxidiser, capping and deblock reagents.",
            ("reagent_*", "bottle_*"),
            None,
        ),
        ("Pumps", "Push each reagent through the column in turn.", ("pump_a*", "pump_b*"), None),
        (
            "Valves",
            "Pick which bottle feeds the column.",
            ("amidite_valve_*", "solvent_valve_*", "column_valve*"),
            None,
        ),
        ("UV monitor", "Follows each coupling by the colour released.", ("uv_monitor*",), None),
    ],
    "agilent_hplc1260": [
        ("Solvent tray", "Holds the mobile-phase bottles.", ("solvent_tray",), UP),
        ("Pump", "Pushes solvent at high pressure.", ("pump_module", "pump_controls"), None),
        (
            "Autosampler",
            "Draws each vial and injects it into the stream.",
            ("injector_module", "injector_door", "sample_slot", "sample_vial"),
            FRONT,
        ),
        (
            "Column oven",
            "Keeps the column at a set temperature.",
            ("column_oven_module", "column_holder"),
            None,
        ),
        ("Detector", "Sees each compound as it leaves the column.", ("detector_module",), None),
    ],
    "agilent_gc8890b": [
        (
            "Inlet",
            "Takes the injected sample through the septum, vaporises it and splits off part of it.",
            ("inlet_*", "liner*", "septum*", "split_valve", "split_vent"),
            UP,
        ),
        ("Oven door", "Closes the column oven.", ("oven_door*",), FRONT),
        (
            "Column",
            "A long coiled capillary; compounds leave it at different times.",
            ("column", "column_cage", "column_inlet_fitting", "column_outlet_fitting"),
            FRONT,
        ),
        (
            "Oven fan and heater",
            "Ramp the column temperature evenly.",
            ("oven_fan", "oven_heater"),
            None,
        ),
        (
            "Flame ionisation detector",
            "Burns what leaves the column and measures the ions.",
            ("fid_*",),
            UP,
        ),
        (
            "Gas controllers",
            "Hold the carrier, hydrogen and air flows steady.",
            ("carrier_epc", "hydrogen_epc", "air_epc", "makeup_epc"),
            BACK,
        ),
    ],
}


def members(slug, names):
    """The components `names` takes from a stand-in, in its own order."""
    every = CONTRACTS["stand_ins"][slug]["components"]
    found = []
    for name in names:
        hits = (
            [c for c in every if c.startswith(name[:-1])]
            if name.endswith("*")
            else [c for c in every if c == name]
        )
        if not hits:
            raise ValueError(f"{slug}: no component {name}")
        found += [c for c in hits if c not in found]
    return found


def anatomy(asset_id):
    """The numbered parts of an instrument's drawn stand-in, or None."""
    slug = CLOUDLAB[asset_id].get("slug")
    if slug not in ANATOMY:
        return None
    return {
        "node_prefix": PREFIX.get(slug, f"{slug}__"),
        "parts": [
            {
                "n": n,
                "label": label,
                "about": about,
                "components": members(slug, names),
                "toward": list(toward) if toward else None,
            }
            for n, (label, about, names, toward) in enumerate(ANATOMY[slug], 1)
        ],
    }
