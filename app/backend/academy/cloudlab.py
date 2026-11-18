"""Cloud lab instruments usable as starting points for teaching twins.

Each entry is an instrument class that Emerald Cloud Lab lists on its public
instrumentation page, the facility the CMU Cloud Lab is built on. The page publishes
capabilities but names no makes, models or dimensions. So operations and the limits the
page states (temperatures, positions, volumes) come from it, and everything else is an
Academy teaching default.

Geometry is never this instrument's own. Where ChemLab-Assets has a comparable
instrument, its footprint stands in and the 3D view draws its model (CC-BY-NC-4.0,
attribution travels with the twin). Otherwise the box is an Academy estimate. Either way
the size counts as estimated until the learner checks it against the real instrument.
"""

from . import chemlab
from .simready import footprint_spec

SOURCE = "https://www.emeraldcloudlab.com/instrumentation/"
RETRIEVED = "2026-11-18"
PROVIDER = "Emerald Cloud Lab"
ROWS = {row["slug"]: row for row in chemlab.SNAPSHOT["instruments"]}
TIPS = [{"name": "Pipette tips", "used_by": "mix", "per_use": 1, "stock": 96}]

# id: (name, ECL experiment, ECL section, published figures used, twin defaults,
#      ChemLab stand-in slug or estimated (width, depth, height) in metres)
INSTRUMENTS = {
    "robotic-sample-preparation": (
        "Robotic sample preparation workcell",
        "ExperimentRoboticSamplePreparation",
        "Transfers",
        "12 SBS plate positions; 8 single-channel pipettes and a 96-channel head, "
        "1 µL to 1 mL; heater/shakers to 105 °C, heater/coolers 0–110 °C",
        {
            "operations": ["load", "mix", "heat", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 12,
            "temps": (4, 110),
            "note": "Academy twins hold 4–120 °C, so the 0 °C cooling floor is modelled as 4 °C.",
            "consumables": TIPS,
        },
        (1.7, 1.0, 0.9),
    ),
    "robotic-cell-preparation": (
        "Robotic cell preparation workcell",
        "ExperimentRoboticCellPreparation",
        "Cell Culture",
        "8 SBS plate positions; 1 µL to 1 mL pipetting; integrated incubator for 20 "
        "plates at 33–50 °C; heater/coolers 0–110 °C",
        {
            "operations": ["load", "mix", "heat", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 8,
            "temps": (4, 110),
            "note": "Academy twins hold 4–120 °C, so the 0 °C cooling floor is modelled as 4 °C.",
            "consumables": TIPS,
        },
        (2.0, 1.0, 0.9),
    ),
    "acoustic-liquid-handler": (
        # Tipless, so a search for pipetting should not rank it with pipetting robots.
        "Acoustic droplet dispenser",
        "ExperimentAcousticLiquidHandling",
        "Transfers",
        "tipless transfer of 2.5 nL to 5 µL from 384-well source plates into 96- or "
        "384-well plates",
        {"operations": ["load", "mix", "wait"], "vessel": "plate", "volume": 5, "slots": 2},
        (0.6, 0.7, 0.5),
    ),
    "plate-reader": (
        "Multimode plate reader",
        "ExperimentAbsorbanceIntensity",
        "Spectroscopy",
        "absorbance, fluorescence and luminescence; one 6- to 96-well plate per batch; "
        "25–45 °C chamber; shakes before reading",
        {
            "operations": ["load", "read", "mix", "wait"],
            "vessel": "plate",
            "volume": 300,
            "slots": 1,
            "temps": (25, 45),
        },
        "bmg_clariostarplus",
    ),
    "plate-centrifuge": (
        "Workcell plate centrifuge",
        "ExperimentCentrifuge",
        "Transfers",
        "2 SBS plate buckets; 3,000 RPM (1,000 × g); 48.3 mm maximum plate height",
        {"operations": ["load", "wait"], "vessel": "plate", "volume": 2000, "slots": 2},
        (0.35, 0.55, 0.3),
    ),
    "positive-pressure-filter": (
        "Positive pressure filter",
        "ExperimentFilter",
        "Transfers",
        "0–40 PSI per well through SBS filter plates into SBS plates",
        {
            "operations": ["load", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 1,
            "consumables": [
                {"name": "Filter plates", "used_by": "load", "per_use": 1, "stock": 10}
            ],
        },
        (0.4, 0.5, 0.45),
    ),
    "plate-washer": (
        "Plate washer",
        "ExperimentRoboticSamplePreparation",
        "Transfers",
        "96-tube manifold for 96-well SBS plates; up to 4 buffers",
        {"operations": ["load", "mix", "wait"], "vessel": "plate", "volume": 300, "slots": 1},
        "biotek_405ts",
    ),
    "thermocycler": (
        "Automated thermocycler",
        "ExperimentPCR",
        "Organic Synthesis",
        "96-well PCR plates; 10–100 µL samples; 4–105 °C; integrated with the "
        "Hamilton STAR liquid handler",
        {
            "operations": ["load", "heat", "wait"],
            "vessel": "plate",
            "volume": 100,
            "slots": 1,
            "temps": (4, 105),
        },
        "biorad_cfxopus",
    ),
    "qpcr": (
        "Real-time qPCR instrument",
        "ExperimentqPCR",
        "Bioassays",
        "384-well plates or array cards; 4–100 °C; up to 100 cycles; six excitation "
        "and emission filters",
        {
            "operations": ["load", "heat", "read", "wait"],
            "vessel": "plate",
            "volume": 20,
            "slots": 1,
            "temps": (4, 100),
        },
        "biorad_cfxopus",
    ),
    "analytical-hplc": (
        "Analytical HPLC",
        "ExperimentHPLC",
        "Separations",
        "up to 48 HPLC vials or 2 deep-well plates per batch; 75 µL sample loop; "
        "20–90 °C column oven; PDA, fluorescence or ELS detection",
        {
            "operations": ["load", "heat", "read", "wait"],
            "vessel": "vial",
            "volume": 1500,
            "slots": 48,
            "temps": (20, 90),
        },
        "agilent_hplc1260",
    ),
    "preparative-hplc": (
        "Preparative HPLC with fraction collection",
        "ExperimentHPLC",
        "Separations",
        "up to 16 mL injections from 60 × 50 mL or 216 × 15 mL tubes; up to 200 mL/min; "
        "fractions of 2 to 45 mL",
        {"operations": ["load", "read", "wait"], "vessel": "tube", "volume": 50000, "slots": 60},
        (0.9, 0.6, 0.9),
    ),
    "lcms": (
        "Liquid chromatography mass spectrometer",
        "ExperimentLCMS",
        "Mass Spectrometry",
        "up to 48 HPLC vials or 2 deep-well plates per batch; 5–90 °C column; QTOF or "
        "triple quadrupole detection",
        {
            "operations": ["load", "heat", "read", "wait"],
            "vessel": "vial",
            "volume": 1500,
            "slots": 48,
            "temps": (5, 90),
        },
        "thermo_orbitrapexploris",
    ),
    "gcms": (
        "Gas chromatograph mass spectrometer",
        "ExperimentGCMS",
        "Mass Spectrometry",
        "autosampler vortexes to 2,000 RPM and incubates samples at 30–200 °C; oven "
        "30–450 °C; single quadrupole or FID detection",
        {
            "operations": ["load", "heat", "mix", "read", "wait"],
            "vessel": "vial",
            "volume": 2000,
            "slots": 12,
            "temps": (30, 120),
            "note": "Academy twins hold 4–120 °C, so the oven above 120 °C is not modelled.",
        },
        "agilent_gc8890b",
    ),
    "sfc-ms": (
        "Supercritical fluid chromatograph with MS",
        "ExperimentSupercriticalFluidChromatography",
        "Separations",
        "up to 48 HPLC vials or 2 deep-well plates per batch; 20–90 °C column selector "
        "for 8 columns; single quadrupole MS",
        {
            "operations": ["load", "heat", "read", "wait"],
            "vessel": "vial",
            "volume": 1500,
            "slots": 48,
            "temps": (20, 90),
        },
        "agilent_1260infinity",
    ),
    "ion-chromatography": (
        "Ion chromatography system",
        "ExperimentIonChromatography",
        "Separations",
        "up to 40 vials or 2 deep-well plates per batch; 10–70 °C column oven; "
        "anion and cation channels",
        {
            "operations": ["load", "heat", "read", "wait"],
            "vessel": "vial",
            "volume": 1500,
            "slots": 40,
            "temps": (10, 70),
        },
        "thermo_dionexintegrion",
    ),
    "flash-chromatography": (
        "Flash chromatography system",
        "ExperimentFlashChromatography",
        "Separations",
        "0.1–25 mL samples; 5–200 mL/min; UV 200–360 nm; 15 mL fraction tubes",
        {"operations": ["load", "read", "wait"], "vessel": "tube", "volume": 25000, "slots": 1},
        "biotage_selekt",
    ),
    "capillary-electrophoresis": (
        "Protein capillary electrophoresis system",
        "ExperimentCapillaryGelElectrophoresisSDS",
        "Separations",
        "CE-SDS and capillary isoelectric focusing on a single capillary",
        {"operations": ["load", "read", "wait"], "vessel": "plate", "volume": 200, "slots": 1},
        "sciex_pa800",
    ),
    "nmr": (
        "500 MHz NMR spectrometer",
        "ExperimentNMR",
        "Spectroscopy",
        "autosampler holds 480 tubes at 6–51 °C; standard tubes hold 600 µL to 1.5 mL",
        {
            "operations": ["load", "read", "wait"],
            "vessel": "tube",
            "volume": 1500,
            "slots": 96,
            "temps": (6, 51),
            "note": "Academy twins hold at most 96 slots, so the twin models 96 of the 480 tubes.",
        },
        (1.5, 1.5, 2.5),
    ),
    "dls-plate-reader": (
        "Dynamic light scattering plate reader",
        "ExperimentDynamicLightScattering",
        "Spectroscopy",
        "96- or 384-well plates, at least 25 µL per well; 4–85 °C",
        {
            "operations": ["load", "heat", "read", "wait"],
            "vessel": "plate",
            "volume": 300,
            "slots": 1,
            "temps": (4, 85),
        },
        (0.45, 0.55, 0.4),
    ),
    "icp-ms": (
        "ICP mass spectrometer",
        "ExperimentICPMS",
        "Mass Spectrometry",
        "nebulizer spray chamber; microwave digestion available",
        {"operations": ["load", "read", "wait"], "vessel": "tube", "volume": 15000, "slots": 24},
        "shimadzu_icpms2030",
    ),
    "peptide-synthesizer": (
        "Robotic peptide synthesizer",
        "ExperimentPeptideSynthesis",
        "Organic Synthesis",
        "24 reaction vessels of 10 or 45 mL; Fmoc chemistry; 5–100 µmol scale",
        {"operations": ["load", "mix", "wait"], "vessel": "vial", "volume": 45000, "slots": 24},
        "cem_libertyblue",
    ),
    "dna-synthesizer": (
        "Robotic DNA synthesizer",
        "ExperimentDNASynthesis",
        "Organic Synthesis",
        "48 synthesis columns per batch at 40 nmol to 1 µmol; 8 standard and 6 custom "
        "reagent positions; listed as discontinued with legacy support",
        {"operations": ["load", "mix", "wait"], "vessel": "tube", "volume": 1000, "slots": 48},
        "cytiva_ktaoligosynt",
    ),
    "elisa": (
        "Robotic ELISA device",
        "ExperimentELISA",
        "Bioassays",
        "incubates, washes and reads absorbance, fluorescence or luminescence",
        {
            "operations": ["load", "mix", "heat", "read", "wait"],
            "vessel": "plate",
            "volume": 300,
            "slots": 4,
            "temps": (20, 45),
        },
        (1.2, 0.8, 0.9),
    ),
    "cell-incubator": (
        "Workcell cell incubator",
        "ExperimentRoboticCellPreparation",
        "Cell Culture",
        "20 shallow or deep well plates; 33–50 °C; 0–10 % CO2; shaking 25–600 RPM",
        {
            "operations": ["load", "heat", "mix", "wait"],
            "vessel": "plate",
            "volume": 2000,
            "slots": 20,
            "temps": (33, 50),
        },
        "eppendorf_cellxpertc170i",
    ),
}
FEATURED = {"robotic-sample-preparation", "acoustic-liquid-handler", "thermocycler"}
COLORS = ["#d9dcde", "#c9ced1", "#466e7d", "#365445", "#5a6470"]


def entry(asset_id, name, experiment, section, published, spec, geometry):
    color = COLORS[sum(map(ord, asset_id)) % len(COLORS)]
    capabilities = f"{PROVIDER} lists this instrument for {experiment}: {published}."
    # Where a published figure lies outside what an Academy twin can hold, say how it is cut.
    spec = dict(spec)
    if note := spec.pop("note", None):
        capabilities += f" {note}"
    if isinstance(geometry, str):
        row = ROWS[geometry]
        stand_in = f"{row['maker']} {row['model']}"
        size = row["size_m"]
        shape = (
            f"Geometry is the ChemLab-Assets footprint of a comparable instrument, the "
            f"{stand_in} ({chemlab.LICENSE}), not this instrument's size."
        )
        source = {
            "license": chemlab.LICENSE,
            "attribution": f"{stand_in} model © MBZUAI, {chemlab.LICENSE}, via ChemLab-Assets",
            "repo": chemlab.REPO,
            "revision": chemlab.REVISION,
            "path": row["path"],
            "mesh": chemlab.mesh(geometry),
            "stand_in": stand_in,
        }
    else:
        size = geometry
        shape = "Geometry is one box with an Academy estimate of the size."
        source = {
            "license": "Academy estimate",
            "attribution": f"Capabilities from {PROVIDER}'s instrumentation page",
            "repo": "",
            "revision": RETRIEVED,
            "path": "",
            "mesh": None,
            "stand_in": None,
        }
    twin = footprint_spec(
        size,
        color,
        {**spec, "name": name},
        f"{capabilities} {shape} Other values are Academy teaching defaults. Correct them "
        "for your instrument before confirming.",
    )
    return {
        "label": f"{PROVIDER} {name}",
        "provider": PROVIDER,
        "domain": f"Cloud lab · {section}",
        "experiment": experiment,
        "featured": asset_id in FEATURED,
        "url": SOURCE,
        "retrieved": RETRIEVED,
        **source,
        "spec": twin,
    }


CLOUDLAB = {key: entry(key, *row) for key, row in INSTRUMENTS.items()}


def provenance(asset_id):
    """Attribution and the drawn stand-in model stored on a twin; exports never resolve them."""
    asset = CLOUDLAB[asset_id]
    return {"id": asset_id, **{k: v for k, v in asset.items() if k not in {"spec", "featured"}}}
