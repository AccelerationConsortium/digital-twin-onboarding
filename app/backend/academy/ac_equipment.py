"""Acceleration Consortium self-driving lab equipment, as teaching twin starting points.

Each entry is an instrument in the AC's global equipment reference (SDL Data Survey,
Equipment sheet): its equipment IDs, the SDLs that run it, and the vendor, model and
documentation link the reference lists. The reference lists nothing else, so the
operations, vessel, volume, slots and limits below are Academy teaching defaults.

Geometry follows `cloudlab`: where ChemLab-Assets has no model of the instrument itself, the
unused model closest in what it does stands in, and the twin takes what that model's pinned
contract gives. No model is drawn for two instruments. Where nothing close is left the twin
is a box: `cloudlab.LAYOUT` sizes it from the documents of the make and model the reference
names, or leaves an Academy estimate where it names none.

Left out: the Opentrons Flex and OT-2 (they have their own studios), robot arms (UR3, UR5,
UR7, xArm5, PF3400; arms belong to the workcell planner), and cameras, sensors, PLCs,
relays, power strips, actuators and custom devices, which hold no sample.
"""

SOURCE = "Acceleration Consortium SDL Data Survey, Equipment sheet (normalized integrations)"
RETRIEVED = "2026-11-20"
PROVIDER = "Acceleration Consortium"
TIPS = [{"name": "Pipette tips", "used_by": "mix", "per_use": 1, "stock": 96}]
WARM = "Academy twins hold 4–120 °C, so a higher working temperature is not modelled."

# id: (name, equipment IDs, section, what the reference lists, twin defaults,
#      ChemLab stand-in slug or estimated (width, depth, height) in metres)
INSTRUMENTS = {
    "ac-biomek-i5": (
        "Liquid handler (Biomek i5)",
        "SDL6-EQ02",
        "Liquid handling",
        (
            "Beckman Coulter Biomek i5",
            "https://www.mybeckman.ca/liquid-handlers/biomek-i-series-automated-workstations/biomek-i5",
        ),
        {
            "operations": ["load", "mix", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 12,
            "consumables": TIPS,
        },
        "opentrons_flex_single_5_1000ul",
    ),
    "ac-starlet": (
        "Liquid handler (Hamilton STARlet)",
        "SDL6-EQ06",
        "Liquid handling",
        ("Hamilton Microlab STARlet 950", ""),
        {
            "operations": ["load", "mix", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 8,
            "consumables": TIPS,
        },
        "teledyne_atomxxyz",
    ),
    "ac-tecan": (
        "Liquid handler (Tecan)",
        "SDL3-EQ06",
        "Liquid handling",
        ("Tecan, run from FluentControl", ""),
        {
            "operations": ["load", "mix", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 12,
            "consumables": TIPS,
        },
        (1.5, 0.8, 0.9),
    ),
    "ac-balance": (
        "Analytical balance",
        "SDL2-EQ16, SDL3-EQ11, SDL4-EQ04, SDL5-EQ09",
        "Sample preparation",
        ("Mettler Toledo balance (SDL2); unnamed balances at SDL3, SDL4 and SDL5", ""),
        {"operations": ["load", "read", "wait"], "vessel": "vial", "volume": 20000, "slots": 1},
        "mt_xpr204e",
    ),
    "ac-capper": (
        "Capper/decapper",
        "SDL3-EQ12",
        "Sample preparation",
        ("capper/decapper, no make given", ""),
        {"operations": ["load", "wait"], "vessel": "tube", "volume": 1500, "slots": 24},
        "azenta_intellixcap_s1_46_0001",
    ),
    "ac-homogenizer": (
        "Homogenizer",
        "SDL5-EQ08",
        "Sample preparation",
        ("homogenizer, no make given", ""),
        {"operations": ["load", "mix", "wait"], "vessel": "tube", "volume": 50000, "slots": 1},
        "ika_t25",
    ),
    "ac-shaker": (
        "Heated plate shaker (Torrey Pines)",
        "SDL2-EQ08",
        "Sample preparation",
        ("Torrey Pines shaker", ""),
        {
            "operations": ["load", "heat", "mix", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 4,
            "temps": (20, 80),
        },
        "ika_ks4000",
    ),
    "ac-evaporator": (
        "Centrifugal evaporator (Hettich)",
        "SDL3-EQ13",
        "Sample preparation",
        ("Hettich evaporator", ""),
        {
            "operations": ["load", "heat", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 6,
            "temps": (20, 80),
        },
        "genevac_mivac2",
    ),
    "ac-filtration": (
        "Filtration station (Waters)",
        "SDL2-EQ09",
        "Sample preparation",
        ("Waters filtration", ""),
        {
            "operations": ["load", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 1,
            "consumables": [
                {"name": "Filter plates", "used_by": "load", "per_use": 1, "stock": 10}
            ],
        },
        "biotage_extrahera_classic",
    ),
    "ac-bead-separator": (
        "Magnetic bead separator",
        "SDL3-EQ16",
        "Sample preparation",
        ("magnetic bead separator: Thermo KingFisher Duo Prime and a Presto 2", ""),
        {"operations": ["load", "mix", "wait"], "vessel": "plate", "volume": 2000, "slots": 1},
        (0.4, 0.5, 0.4),
    ),
    "ac-centrifuge": (
        "Plate centrifuge (VSpin)",
        "SDL6-EQ08, SDL3-EQ19",
        "Plate handling",
        (
            "Agilent VSpin (SDL6); an unnamed centrifuge at SDL3",
            "https://www.agilent.com/Library/usermanuals/Public/G5405-90001C_CentrifugeUG_P_EN.pdf",
        ),
        {"operations": ["load", "wait"], "vessel": "plate", "volume": 2000, "slots": 2},
        "eppendorf_5910ri",
    ),
    "ac-plate-sealer": (
        "Thermal plate sealer (PlateLoc)",
        "SDL2-EQ10, SDL3-EQ20",
        "Plate handling",
        (
            "Agilent PlateLoc (SDL2); an unnamed plate sealer at SDL3",
            "https://www.agilent.com/en/product/automated-liquid-handling/"
            "automated-microplate-management/plateloc-thermal-microplate-sealer",
        ),
        {
            "operations": ["load", "heat", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 1,
            "temps": (20, 120),
            "note": WARM,
        },
        "azenta_automated_roll_heat_sealer_a4s",
    ),
    "ac-plate-stacker": (
        "Plate stacker (BioStack)",
        "SDL2-EQ12",
        "Plate handling",
        (
            "Agilent BioTek BioStack",
            "https://www.agilent.com/en/product/cell-analysis/microplate-automation-detection/"
            "microplate-stackers-incubators/biotek-biostack-microplate-stacker-1623222",
        ),
        {"operations": ["load", "wait"], "vessel": "plate", "volume": 2000, "slots": 30},
        (0.3, 0.4, 0.6),
    ),
    "ac-cytomat": (
        "Automated plate incubator (Cytomat 37)",
        "SDL6-EQ05",
        "Plate handling",
        ("Thermo Scientific Cytomat C2", ""),
        {
            "operations": ["load", "heat", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 21,
            "temps": (20, 50),
        },
        "binder_kbf115",
    ),
    "ac-scila": (
        "Plate incubator (Inheco SCILA)",
        "SDL6-EQ11",
        "Plate handling",
        ("Inheco SCILA", ""),
        {
            "operations": ["load", "heat", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 4,
            "temps": (20, 50),
        },
        "binder_fd056",
    ),
    "ac-cytation-5": (
        "Imaging plate reader (Cytation 5)",
        "SDL2-EQ01, SDL4-EQ01",
        "Plate readers and imaging",
        (
            "Agilent BioTek Cytation 5",
            "https://biomedcorefacilities.brown.edu/sites/default/files/"
            "biotekcytation5usermanual.pdf",
        ),
        {
            "operations": ["load", "read", "mix", "heat", "wait"],
            "vessel": "plate",
            "volume": 300,
            "slots": 1,
            "temps": (25, 45),
        },
        "thermo_ibrightfl1500",
    ),
    "ac-cytation-c10": (
        "Confocal imaging reader (Cytation C10)",
        "SDL6-EQ03, SDL6-EQ04",
        "Plate readers and imaging",
        ("Cytation C10, two units with Sony and Hamamatsu cameras", ""),
        {
            "operations": ["load", "read", "heat", "wait"],
            "vessel": "plate",
            "volume": 300,
            "slots": 1,
            "temps": (25, 45),
        },
        "keyence_vkx3000",
    ),
    "ac-synergy-neo2": (
        "Multimode plate reader (Synergy Neo2)",
        "SDL3-EQ18",
        "Plate readers and imaging",
        (
            "Agilent BioTek Synergy Neo2",
            "https://www.agilent.com/en/product/microplate-instrumentation/microplate-readers/"
            "multimode-microplate-readers/biotek-synergy-neo2-hybrid-multimode-reader-1623195",
        ),
        {
            "operations": ["load", "read", "mix", "wait"],
            "vessel": "plate",
            "volume": 300,
            "slots": 1,
        },
        "jasco_fp8350",
    ),
    "ac-dls-reader": (
        "DLS plate reader (Wyatt)",
        "SDL5-EQ01",
        "Plate readers and imaging",
        ("Wyatt plate reader, listed under Waters", ""),
        {"operations": ["load", "read", "wait"], "vessel": "plate", "volume": 300, "slots": 1},
        "antonpaar_litesizerdls",
    ),
    "ac-qpcr": (
        "Real-time PCR (QuantStudio 7 Pro)",
        "SDL3-EQ21",
        "Plate readers and imaging",
        ("Thermo Fisher QuantStudio 7 Pro", ""),
        {
            "operations": ["load", "heat", "read", "wait"],
            "vessel": "plate",
            "volume": 20,
            "slots": 1,
            "temps": (4, 100),
        },
        (0.3, 0.6, 0.5),
    ),
    "ac-hplc": (
        "HPLC",
        "SDL3-EQ15",
        "Separations and mass spectrometry",
        ("HPLC, no make given", ""),
        {
            "operations": ["load", "read", "wait"],
            "vessel": "vial",
            "volume": 1500,
            "slots": 48,
        },
        "agilent_1290infinity",
    ),
    "ac-uplc-ms": (
        "UPLC-MS (Agilent)",
        "SDL2-EQ02, SDL2-EQ11",
        "Separations and mass spectrometry",
        ("Agilent UPLC-MS, two units", ""),
        {"operations": ["load", "read", "wait"], "vessel": "vial", "volume": 1500, "slots": 48},
        "gas_flavourspec25gc",
    ),
    "ac-orbitrap-lcms": (
        "Orbitrap LC-MS",
        "SDL3-EQ05",
        "Separations and mass spectrometry",
        (
            "Thermo Fisher Orbitrap LC-MS, controlled from Chromeleon",
            "https://www.thermofisher.com/ca/en/home/industrial/mass-spectrometry/"
            "liquid-chromatography-mass-spectrometry-lc-ms/lc-ms-systems/orbitrap-lc-ms.html",
        ),
        {"operations": ["load", "read", "wait"], "vessel": "plate", "volume": 300, "slots": 2},
        "thermo_orbitrapexploris",
    ),
    "ac-medchem-lcms": (
        "MedChem LC-MS (Waters)",
        "SDL3-EQ01",
        "Separations and mass spectrometry",
        ("Waters MedChem LCMS", ""),
        {"operations": ["load", "read", "wait"], "vessel": "vial", "volume": 1500, "slots": 48},
        (1.2, 0.8, 1.0),
    ),
    "ac-purification": (
        "Purification sample manager (Waters 2767)",
        "SDL3-EQ09",
        "Separations and mass spectrometry",
        (
            "Waters 2767 Sample Manager, collecting compounds by molecular weight",
            "https://help.waters.com/content/dam/waters/en/support/usermanuals/2018/"
            "71500276704/71500276704rd.pdf",
        ),
        {"operations": ["load", "read", "wait"], "vessel": "tube", "volume": 15000, "slots": 48},
        "gilson_cpc250",
    ),
    "ac-photoreactor": (
        "Photoreactor",
        "SDL4-EQ02",
        "Reactors",
        ("photoreactor, no make given", ""),
        {"operations": ["load", "mix", "wait"], "vessel": "vial", "volume": 4000, "slots": 8},
        "hepatochem_photoredoxbox",
    ),
    "ac-flow-reactor": (
        "Flow reactor with fraction collector",
        "SDL4-EQ08",
        "Reactors",
        ("flow reactor with a fraction collector, no make given", ""),
        {
            "operations": ["load", "heat", "wait"],
            "vessel": "tube",
            "volume": 10000,
            "slots": 12,
            "temps": (20, 120),
        },
        "syrris_asiadiscovery",
    ),
    "ac-potentiostat": (
        "Potentiostat (Squidstat)",
        "SDL1-EQ01",
        "Characterisation",
        ("Admiral Instruments Squidstat", "https://www.admiralinstruments.com/potentiostats"),
        {"operations": ["load", "read", "wait"], "vessel": "vial", "volume": 20000, "slots": 1},
        "gamry_reference620",
    ),
    "ac-viscometer": (
        "Automated viscometer (Brookfield)",
        "SDL5-EQ07",
        "Characterisation",
        (
            "Brookfield automated viscometer",
            "https://www.brookfieldengineering.com/products/viscometers",
        ),
        {
            "operations": ["load", "heat", "mix", "read", "wait"],
            "vessel": "vial",
            "volume": 2000,
            "slots": 1,
            "temps": (20, 80),
        },
        "antonpaar_mcr503",
    ),
    "ac-dsc": (
        "Differential scanning calorimeter",
        "SDL5-EQ06",
        "Characterisation",
        ("differential scanning calorimeter, no make given", ""),
        {
            "operations": ["load", "heat", "read", "wait"],
            "vessel": "vial",
            "volume": 100,
            "slots": 1,
            "temps": (4, 120),
            "note": WARM,
        },
        "ta_dsc2500",
    ),
    "ac-indenter": (
        "Indenter",
        "SDL4-EQ07",
        "Characterisation",
        ("indenter, no make given", ""),
        {
            "operations": ["load", "read", "wait"],
            "vessel": "plate",
            "volume": 1000,
            "slots": 1,
            "note": "The specimen is modelled as one plate on the stage.",
        },
        "antonpaar_hit300",
    ),
}
