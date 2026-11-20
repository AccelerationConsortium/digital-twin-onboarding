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
PREFIX = {
    "agilent_hplc1260": "hplc1260__",
    "agilent_gc8890b": "GC7890B__",
    "azenta_intellixcap_s1_46_0001": "intellixcap_s1__",
    "biotage_extrahera_classic": "extrahera__",
    "gamry_reference620": "gamry_ref620__",
    "opentrons_flex_single_5_1000ul": "flex__",
}

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
    # Acceleration Consortium stand-ins.
    "opentrons_flex_single_5_1000ul": [
        (
            "Deck",
            "Holds plates, tip racks and reservoirs in a grid of slots.",
            ("deck", "slot_*"),
            None,
        ),
        (
            "Gantry",
            "Carries the pipette left and right, front and back.",
            ("gantry_y", "y_rails", "carriage_x"),
            UP,
        ),
        (
            "Pipette",
            "Rides down on its own axis to draw and release liquid.",
            ("carriage_z", "pipette"),
            FRONT,
        ),
        ("Touchscreen", "Starts runs and shows where a protocol is.", ("touchscreen",), RIGHT),
        (
            "Status light",
            "Shows whether the robot is idle, running or needs attention.",
            ("status_light",),
            UP,
        ),
    ],
    "mt_xpr204e": [
        (
            "Draft shield",
            "Glass doors that keep air currents off the pan.",
            ("door_left", "door_right", "door_top", "front_glass", "draftshield_frame"),
            UP,
        ),
        ("Weighing pan", "Where the vial sits while it is weighed.", ("pan", "pan_support"), FRONT),
        (
            "Weighing cell",
            "Measures the force on the pan under the chamber floor.",
            ("chamber_floor", "weigh_below"),
            None,
        ),
        (
            "Terminal",
            "Display and keys to tare, zero and read the mass.",
            ("terminal_*", "touch_key_*", "status_light"),
            FRONT,
        ),
        (
            "Rear ports",
            "Power and the data link to the computer that reads it.",
            ("rear_ports", "security_switch", "security_anchor"),
            BACK,
        ),
    ],
    "azenta_intellixcap_s1_46_0001": [
        (
            "Gripper",
            "Grips the caps of a rack of tubes at once.",
            ("gripper", "jaw_left", "jaw_right"),
            UP,
        ),
        ("Spindle", "Turns the gripper to unscrew or screw the caps.", ("spindle",), UP),
        (
            "Sample interface",
            "Where the tube rack is set and held down.",
            ("sample_interface",),
            FRONT,
        ),
        ("Controller", "Chooses capping or decapping.", ("controller", "trigger_disc"), RIGHT),
        (
            "Power entry",
            "Mains input and the switch that selects the supply.",
            ("power_inlet", "power_selection_button"),
            BACK,
        ),
    ],
    "ika_t25": [
        (
            "Drive",
            "The motor that spins the dispersing tool.",
            ("drive", "drive_*", "tool_lock"),
            UP,
        ),
        (
            "Dispersing tool",
            "A rotor turning inside a stator shears the sample apart.",
            ("shaft_tube", "stator", "rotor", "rotor_marker"),
            FRONT,
        ),
        (
            "Vessel",
            "Holds the sample under the tool.",
            ("vessel", "vessel_*", "sample_surface"),
            FRONT,
        ),
        (
            "Stand",
            "Holds the drive at the height of the vessel.",
            ("stand_base", "stand_column", "extension_arm", "cross_sleeve", "clamp_*"),
            LEFT,
        ),
        (
            "Speed control",
            "Sets how fast the rotor turns.",
            ("panel", "knob_speed", "switch_run", "display_digits", "speed_reference_mark"),
            RIGHT,
        ),
    ],
    "ika_ks4000": [
        ("Hood", "Closes the chamber so the plates stay warm.", ("hood", "hood_*"), UP),
        (
            "Shaking platform",
            "Carries the plates round in small circles.",
            ("platform", "fixture_frame", "fixture_rollers"),
            UP,
        ),
        (
            "Drive",
            "Motor and eccentric that make the platform orbit.",
            ("motor", "eccentric_drive", "orbit_x"),
            None,
        ),
        (
            "Heater and fan",
            "Warm the air in the chamber and move it over the plates.",
            ("heater", "air_fan"),
            BACK,
        ),
        (
            "Control panel",
            "Sets speed, temperature and time.",
            ("front_console", "control_panel", "button_*", "display_digits"),
            FRONT,
        ),
    ],
    "genevac_mivac2": [
        ("Lid", "Seals the chamber so it can be pumped down.", ("lid", "lid_*"), UP),
        (
            "Rotor",
            "Spins the plates so the liquid stays in the wells as it boils off.",
            ("rotor", "rotor_arm", "rotor_mark", "spindle"),
            UP,
        ),
        (
            "Plate baskets",
            "Swing out as the rotor turns, holding the plates.",
            ("basket_*", "stacker_*", "plate_*", "wells_*"),
            UP,
        ),
        (
            "Chamber",
            "Heated bowl under vacuum where the solvent evaporates.",
            ("chamber_wall", "chamber_floor", "top_rim"),
            None,
        ),
        (
            "Panel",
            "Starts, stops and preheats a run.",
            ("panel", "display_*", "button_*", "encoder"),
            FRONT,
        ),
    ],
    "biotage_extrahera_classic": [
        (
            "Safety shield",
            "Closes the deck while pressure is applied.",
            ("safety_shield", "shield_handle"),
            FRONT,
        ),
        (
            "Pipetting head",
            "Moves on a gantry to add sample and solvent to the plate.",
            ("gantry_frame", "gantry_x", "gantry_y", "pipette_z", "pipette_head"),
            UP,
        ),
        (
            "Pressure manifold",
            "Pushes air through the filter plate, well by well.",
            ("pressure_manifold",),
            UP,
        ),
        (
            "Work deck",
            "Racks, plates and tips the run uses.",
            ("work_deck", "deck_slots", "rack_*", "plate_*", "tip_rack"),
            None,
        ),
        (
            "Collection",
            "Catches what comes through the filter.",
            ("collection_carousel", "collection_plate", "waste_tray"),
            FRONT,
        ),
    ],
    "eppendorf_5910ri": [
        ("Lid", "Locks shut while the rotor turns.", ("sample_lid", "lid_lock", "lid_hinges"), UP),
        (
            "Rotor",
            "Carries the plates round at speed.",
            ("rotor", "rotor_slots", "sample_carriers"),
            UP,
        ),
        ("Chamber", "The bowl the rotor turns in.", ("chamber",), None),
        (
            "Drive and cooling",
            "Motor under the rotor and the refrigeration that keeps samples cool.",
            ("drive", "refrigeration"),
            BACK,
        ),
        ("Control panel", "Sets speed, time and temperature.", ("control_panel", "display"), FRONT),
    ],
    "azenta_automated_roll_heat_sealer_a4s": [
        (
            "Plate carriage",
            "Draws the plate in under the press and back out.",
            ("plate_carriage", "plate_adapter", "external_plate", "guide_rails"),
            FRONT,
        ),
        ("Press head", "Heated plate that presses the film onto the wells.", ("press_head",), UP),
        (
            "Film roll",
            "Feeds sealing film over the plate.",
            ("film_roll", "roll_support", "feed_rollers", "film_path"),
            BACK,
        ),
        ("Cutter", "Cuts the seal from the roll.", ("cutter",), UP),
        (
            "Front panel",
            "Status display and the buttons that start a seal.",
            ("front_fascia", "status_display"),
            FRONT,
        ),
    ],
    "hepatochem_photoredoxbox": [
        ("Lid", "Keeps the light inside the box.", ("lid", "lid_*", "handle_recess"), UP),
        (
            "Sample rack",
            "Holds the vials at the same distance from the lamps.",
            ("sample_rack", "vial_interface_*", "sample_vial_*", "vial_cap_*"),
            UP,
        ),
        ("Lamps", "Light the vials from below.", ("led_*",), None),
        (
            "Stirring and cooling",
            "Stir each vial and carry the lamps' heat away.",
            ("stir_motor", "cooling_fan"),
            BACK,
        ),
        (
            "Front panel",
            "Sets and shows the run.",
            ("front_panel", "display_*", "knob_*", "button_power"),
            FRONT,
        ),
    ],
    "syrris_asiadiscovery": [
        (
            "Pumps",
            "Push the reagents through the reactor at a set flow.",
            ("pump", "pump_*", "syringe_*"),
            FRONT,
        ),
        (
            "Injector",
            "Switches sample loops into the flow.",
            ("injector", "injector_*", "injection_valve_*", "sample_loop_*"),
            UP,
        ),
        ("Reactor chip", "The heated channel where the reaction happens.", ("chip", "chip_*"), UP),
        ("Climate", "Heats or cools the reactor.", ("climate", "climate_*"), None),
        (
            "Fraction collector",
            "Moves a nozzle over the vials to collect each fraction.",
            ("collector", "collector_*", "fraction_*"),
            RIGHT,
        ),
    ],
    "gamry_reference620": [
        (
            "Cell connector",
            "Where the cell cable plugs in.",
            ("cell_connector", "cable_guide"),
            FRONT,
        ),
        (
            "Electrode leads",
            "Working, reference and counter electrode connections.",
            (
                "working_electrode_slot",
                "reference_electrode_slot",
                "counter_electrode_slot",
            ),
            FRONT,
        ),
        ("Front panel", "Shows whether the cell is on.", ("front_panel", "status_indicators"), UP),
        (
            "Rear ports",
            "Power and the computer link that runs it.",
            ("power_inlet", "data_port"),
            BACK,
        ),
        (
            "Cell slot",
            "Where the cell cable is parked when no cell is connected.",
            ("cell_slot",),
            FRONT,
        ),
    ],
    "antonpaar_mcr503": [
        (
            "Measuring head",
            "Lowers onto the sample and turns it to measure how it flows.",
            (
                "head_lift",
                "head_carriage",
                "motor_*",
                "air_bearing_hub",
                "rotor",
                "rotor_index_mark",
                "quickconnect_collar",
                "upper_plate",
            ),
            UP,
        ),
        (
            "Temperature stage",
            "Holds the sample at a set temperature.",
            ("temperature_stage", "stage_*", "sample_plate"),
            FRONT,
        ),
        (
            "Column",
            "Guides the head up and down.",
            ("column", "column_*", "guide_left", "guide_right"),
            BACK,
        ),
        ("Display", "Shows the measurement.", ("controller", "display_*"), RIGHT),
        (
            "Rear connections",
            "Air, coolant, power and the computer link.",
            (
                "rear_panel",
                "air_inlet",
                "coolant_inlet",
                "coolant_outlet",
                "host_port",
                "power_inlet",
                "power_switch",
            ),
            BACK,
        ),
    ],
    "antonpaar_hit300": [
        (
            "Indentation head",
            "Lowers the diamond tip into the specimen.",
            ("load_head", "head_*", "stylus", "stylus_holder", "diamond_tip", "depth_sensor"),
            UP,
        ),
        (
            "Sample stage",
            "Moves the specimen under the tip.",
            ("stage_x", "stage_y", "x_*", "y_*"),
            FRONT,
        ),
        (
            "Specimen holder",
            "Clamps the specimen flat.",
            ("sample_holder", "specimen", "clamp_*", "holder_bolt_*"),
            FRONT,
        ),
        (
            "Column",
            "Holds the head and carries it down.",
            ("column", "column_foot", "z_*", "handwheel", "handwheel_*"),
            BACK,
        ),
        (
            "Controller",
            "Runs the measurement and records depth against load.",
            ("controller", "controller_standoff_*"),
            BACK,
        ),
    ],
    "ta_dsc2500": [
        ("Cell lid", "Closes over the furnace during a run.", ("lid", "lid_*", "inner_lid"), UP),
        (
            "Furnace",
            "Heats the sample pan and an empty reference pan side by side.",
            (
                "furnace",
                "furnace_*",
                "sample_pan",
                "sample_pan_rim",
                "reference_pan",
                "reference_pan_rim",
                "sample_sensor",
                "reference_sensor",
            ),
            UP,
        ),
        (
            "Autosampler",
            "Picks pans from the trays and sets them in the cell.",
            (
                "sampler_x",
                "sampler_y",
                "sampler_z",
                "sampler_gripper",
                "gripper_finger_*",
                "beam",
                "beam_*",
            ),
            FRONT,
        ),
        ("Pan trays", "Hold the pans waiting to be measured.", ("tray_*",), FRONT),
        (
            "Cooling",
            "Draws heat out of the cell to cool it fast.",
            ("cooling_ring", "cooling_rod_*", "facs_*"),
            None,
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
    # Where the model names nodes after neither slug nor component, the contract says.
    own = CONTRACTS["stand_ins"][slug].get("nodes")
    parts = []
    for n, (label, about, names, toward) in enumerate(ANATOMY[slug], 1):
        found = members(slug, names)
        part = {
            "n": n,
            "label": label,
            "about": about,
            "components": found,
            "toward": list(toward) if toward else None,
        }
        if own:
            part["nodes"] = [node for c in found for node in own.get(c, [])]
        parts.append(part)
    return {"node_prefix": PREFIX.get(slug, f"{slug}__"), "parts": parts}
