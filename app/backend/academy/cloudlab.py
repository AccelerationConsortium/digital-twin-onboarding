"""Cloud lab instruments usable as starting points for teaching twins.

Each entry is an instrument class that Emerald Cloud Lab lists on its public
instrumentation page, the facility the CMU Cloud Lab is built on. The page publishes
capabilities but names no makes, models or dimensions. So operations and the limits the
page states (temperatures, positions, volumes) come from it, and everything else is an
Academy teaching default.

Geometry is never this instrument's own. Where ChemLab-Assets has a comparable
instrument, the 3D view draws its model (CC-BY-NC-4.0, attribution travels with the twin)
and the twin takes what that model's pinned contract gives for layout (chemlab_layout.json):
outside size, the face a sample goes in through and the part of it, the loading height, a
drawn slot and how far a drawer comes out. Otherwise LAYOUT gives a named comparable model's
datasheet figures, or an Academy estimate with the reason.

Every value carries its basis, and a value no source gives stays unset. These are a
comparable model's figures, never the cloud lab's own, so a twin is only as good as its
weakest value until the learner checks it against the real instrument.

The Acceleration Consortium's self-driving lab equipment (`ac_equipment`) is built the same
way and kept in the same registry, so its twins are met, practised and taken apart on the
same pages; `lab` says which facility an instrument belongs to.
"""

import json
from pathlib import Path

from . import ac_equipment, chemlab
from .simple_twins import TwinSpec
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


def datasheet(document, url):
    return f"datasheet: {document}, {url}, read {RETRIEVED}"


ESTIMATE = "estimate"
UNSET = "unset"

STAR_SITE = "https://robotics.hamiltoncompany.com/microlab-star-site-requirements"
STAR_FRONT = (
    "front",
    "estimate: carriers go onto the deck through the hinged front window "
    "(Hamilton Operator's Manual 610766/08, read from a third-party copy)",
)

# Instruments without a ChemLab stand-in. id: (the comparable model the figures are for,
# {value: (figure, basis)}); size is the outside (width, depth, height) in metres, access
# the face a sample goes in through. None of these documents states a loading height.
LAYOUT = {
    "dls-plate-reader": (
        "Wyatt DynaPro Plate Reader III",
        {
            "size": (
                (0.36, 0.60, 0.25),
                datasheet(
                    "Wyatt DynaPro Plate Reader III brochure W3400C, 60 (l) × 36 (w) × 25 (h) "
                    "cm with length taken as depth, distributor-hosted",
                    "https://somatco.com/wp-content/uploads/2025/02/"
                    "dynapro-microplate-reader-iii-somatco-saudi.pdf",
                ),
            ),
            "access": ("front", "estimate: the brochure does not say how a plate goes in"),
        },
    ),
    "elisa": (
        "Dynex DSX",
        {
            "size": (
                (0.991, 0.787, 0.819),
                datasheet(
                    "Dynex System Comparison Brochure POR-E10-V2-2025, DSX 39 × 31 × 32.25 in",
                    "https://www.dynextechnologies.com/pdf/"
                    "DYN.Dynex_System_Comparison_Brochure_updated_2026_.pdf",
                ),
            ),
            "access": (
                "top",
                "estimate: plates are set on a deck under a hinged cover; no loading face "
                "for an outside arm is stated",
            ),
        },
    ),
    "positive-pressure-filter": (
        "Hamilton MPE²",
        {
            "size": (
                (0.159, 0.445, 0.181),
                datasheet(
                    "Hamilton [MPE]² brochure BR0028 v1.0, logistics module 44.5 (l) × 15.9 "
                    "(w) × 18.1 (h) cm with length taken as depth, one 7-track carrier wide",
                    "https://cdn2.hubspot.net/hubfs/523047/MPE2%20brochure%20(BR0028%202017-06).pdf",
                ),
            ),
            "access": ("top", "estimate: the brochure does not say how a plate goes in"),
        },
    ),
    "robotic-sample-preparation": (
        "Hamilton Microlab STAR",
        {
            "size": (
                (1.664, 0.7925, 0.902),
                datasheet(
                    "Hamilton Microlab STAR site requirements, 166.37 × 79.25 × 90.2 cm "
                    "without the multiprobe head or autoload",
                    STAR_SITE,
                ),
            ),
            "access": STAR_FRONT,
        },
    ),
    "robotic-cell-preparation": (
        "Hamilton Microlab STARplus",
        {
            "size": (
                (2.16, 0.795, 0.903),
                datasheet(
                    "Hamilton Microlab STAR brochure BR0010 v3.1, STARplus 2160 × 903 × 795 mm "
                    "(W × H × D), distributor-hosted",
                    "https://www.analitykgenetyka.pl/sites/default/files/"
                    "2_microlab_star_brochure_0.pdf",
                ),
            ),
            "access": STAR_FRONT,
        },
    ),
    "acoustic-liquid-handler": (
        "Beckman Coulter Echo 525",
        {
            "size": (
                (0.539, 0.683, 0.925),
                datasheet(
                    "Beckman Coulter Echo 525 specifications, 53.9 × 68.3 × 92.5 cm",
                    "https://www.beckman.com/liquid-handlers/echo-525",
                ),
            ),
            "access": (
                "front",
                "estimate: plates go onto gripper stages behind a door, from the user guide's "
                "contents only; no manufacturer text says through which face",
            ),
        },
    ),
    "preparative-hplc": (
        "Agilent 1290 Infinity II Preparative Open-Bed Sampler/Collector",
        {
            "size": (
                (0.9, 0.6, 0.9),
                "estimate: the G7158B manual gives only the sampler/collector module "
                "(39.3 × 62.2 × 78.1 cm), not the whole system",
            ),
            "access": (
                "front",
                "estimate: the G7158B manual has tubes in drawers that protrude when open, "
                "without naming the face",
            ),
        },
    ),
    "nmr": (
        "Bruker Ascend 500 with SampleXpress",
        {
            "size": (
                (1.5, 1.5, 2.5),
                "estimate: Bruker's AVANCE site planning tables could only be read without "
                "their column alignment, so their figures are not used",
            ),
            "access": (
                "top",
                "estimate: SampleXpress sits on top of the magnet and takes cassettes loaded "
                "on the bench (Bruker press release, 2010)",
            ),
        },
    ),
    "plate-centrifuge": (
        "Agilent VSpin",
        {
            "size": (
                (0.35, 0.55, 0.3),
                "estimate: Agilent's VSpin documents refuse automated reading, so its "
                "figures are not used",
            ),
        },
    ),
}

# Stand-ins: what the pinned ChemLab-Assets contract of each gives, from
# scripts/library-models/chemlab_layout.py. Numbers and evidence labels only.
CONTRACTS = json.loads((Path(__file__).parent / "chemlab_layout.json").read_text())
assert CONTRACTS["revision"] == chemlab.REVISION, "chemlab_layout.json is pinned elsewhere"
EVIDENCE = {
    "manufacturer": "manufacturer figure",
    "engineering_assumption": "asset author's estimate",
}


def contract(slug, stand_in, slots):
    """The stand-in's layout values as (twin fields, {field: basis}) for an entry."""
    found = CONTRACTS["stand_ins"][slug]
    fields, basis = {}, {}

    def take(key, value=None):
        item = found[key]
        fields[key] = item["value"] if value is None else value
        basis[key] = (
            f"{item['evidence']}: {EVIDENCE[item['evidence']]} in the ChemLab-Assets "
            f"{stand_in} contract ({item['detail']})"
        )

    if "size" in found:
        take("size")
    if "access" in found:
        take("access")
        if found["access"]["value"] == "front":
            take("level_m")
            if "opening" in found:
                take("opening")
            if "extends_m" in found:
                take("extends_m")
        elif slots == 1:
            # One sample set into the block from above, where the contract places it.
            take("level_m")
            x, z = found["site"]["value"]
            take("site", [{"key": "1", "x": x, "z": z}])
    return fields, basis


FEATURED = {"robotic-sample-preparation", "acoustic-liquid-handler", "thermocycler"}
COLORS = ["#d9dcde", "#c9ced1", "#466e7d", "#365445", "#5a6470"]


ECL = {
    "id": "ecl",
    "name": "Cloud lab",
    "provider": PROVIDER,
    "source": SOURCE,
    "retrieved": RETRIEVED,
}
AC = {
    "id": "ac",
    "name": "Acceleration Consortium",
    "provider": ac_equipment.PROVIDER,
    "source": ac_equipment.SOURCE,
    "retrieved": ac_equipment.RETRIEVED,
}


def entry(asset_id, name, experiment, section, published, spec, geometry, lab=ECL):
    color = COLORS[sum(map(ord, asset_id)) % len(COLORS)]
    url = lab["source"]
    if lab is ECL:
        capabilities = f"{PROVIDER} lists this instrument for {experiment}: {published}."
    else:
        # The AC reference names the instrument only; `experiment` is its equipment IDs.
        published, url = published
        capabilities = (
            f"The {lab['provider']} equipment reference lists {published} ({experiment})."
        )
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
            "slug": geometry,
        }
    else:
        size = geometry
        shape = "Geometry is one box with an Academy estimate of the size."
        source = {
            "license": "Academy estimate",
            "attribution": f"Capabilities from {PROVIDER}'s instrumentation page"
            if lab is ECL
            else f"Listed in the {lab['provider']} equipment reference",
            "repo": "",
            "revision": RETRIEVED,
            "path": "",
            "mesh": None,
            "stand_in": None,
            "slug": None,
        }
    stand_in, extra, mass = source["stand_in"], {}, None
    basis = {"size": f"footprint: ChemLab-Assets {stand_in}" if stand_in else ESTIMATE}
    if stand_in:
        model = stand_in
        fields, found = contract(geometry, stand_in, spec.get("slots", 0))
        size = fields.pop("size", size)
        # Weight is not geometry, so it stays out of the basis that grades a twin's size.
        if weighed := CONTRACTS["stand_ins"][geometry].get("mass_kg"):
            mass = {
                "value": weighed["value"],
                "range": weighed.get("range"),
                "basis": (
                    f"{weighed['evidence']}: {EVIDENCE[weighed['evidence']]} in the "
                    f"ChemLab-Assets {stand_in} contract ({weighed['detail']})"
                ),
            }
        for key, twin_key in (("access", "access"), ("level_m", "level_m")):
            if key in fields:
                spec[twin_key] = fields[key]
        for key, twin_key in (("opening", "opening"), ("extends_m", "drawer_m"), ("site", "sites")):
            if key in fields:
                extra[twin_key] = fields[key]
        basis.update(
            {{"extends_m": "drawer_m", "site": "sites"}.get(k, k): v for k, v in found.items()}
        )
        if found:
            shape = (
                f"Geometry is one box with what the ChemLab-Assets contract of a comparable "
                f"instrument, the {stand_in} ({chemlab.LICENSE}), gives for outside size and "
                "loading, not this instrument's size."
            )
    else:
        model, sourced = LAYOUT.get(asset_id, (None, {}))
        if "size" in sourced:
            size, basis["size"] = sourced["size"]
        if "access" in sourced:
            spec["access"], basis["access"] = sourced["access"]
        if model and any(b.startswith("datasheet:") for b in basis.values()):
            shape = (
                f"Geometry is one box with what the {model} datasheet gives for outside size "
                "and loading where it gives them, a comparable instrument's figures, not this "
                "instrument's size."
            )
        elif model:
            shape = (
                "Geometry is one box with an Academy estimate, not this instrument's size; "
                f"the {model} documents read gave no figures it could use."
            )
    if "access" not in basis:
        basis["access"] = (
            "estimate: an Academy default from what the instrument is; no source read gives "
            "its loading face"
        )
    if spec.get("access") == "front" and "level_m" not in basis:
        basis["level_m"] = UNSET  # the planner then presents the plate a third of the way up
    twin = footprint_spec(
        size,
        color,
        {**spec, "name": name},
        f"{capabilities} {shape} Other values are Academy teaching defaults. Correct them "
        "for your instrument before confirming.",
    )
    twin = TwinSpec.model_validate({**twin, **extra}).model_dump(mode="json")
    return {
        "label": f"{lab['provider']} {name}",
        "provider": lab["provider"],
        "lab": lab["id"],
        "domain": f"{lab['name']} · {section}",
        "section": section,
        "experiment": experiment,
        "published": published,
        "narrowed": note,
        "featured": asset_id in FEATURED,
        "url": url,
        "retrieved": lab["retrieved"],
        **source,
        "layout_model": model,
        "geometry_basis": basis,
        # The drawn stand-in's documented mass, with the range its documents give.
        "mass_kg": mass,
        "spec": twin,
    }


CLOUDLAB = {
    **{key: entry(key, *row) for key, row in INSTRUMENTS.items()},
    **{key: entry(key, *row, lab=AC) for key, row in ac_equipment.INSTRUMENTS.items()},
}
LABS = {lab["id"]: lab for lab in (ECL, AC)}


def overview():
    """Every cloud lab instrument as Meet the instruments shows it, by ECL section."""
    found = []
    for key, asset in CLOUDLAB.items():
        spec = asset["spec"]
        width, height, depth = spec["parts"][0]["size"]  # Y-up twin box
        found.append(
            {
                "id": key,
                "lab": asset["lab"],
                "url": asset["url"],
                "name": spec["name"],
                "section": asset["section"],
                "experiment": asset["experiment"],
                "published": asset["published"],
                "narrowed": asset["narrowed"],
                "operations": spec["operations"],
                "holds": spec["container"],
                "slots": spec["resource"]["slots"],
                "limits": spec["limits"],
                "consumables": spec["consumables"],
                "size_m": [width, depth, height],
                "access": spec["access"],
                "level_m": spec["level_m"],
                "opening": spec.get("opening"),
                "drawer_m": spec.get("drawer_m"),
                # The drawn stand-in model's own bounding box, when it differs from the twin.
                "model_size_m": ROWS[asset["slug"]]["size_m"] if asset["slug"] else None,
                "mass_kg": asset["mass_kg"],
                "layout_model": asset["layout_model"],
                "geometry_basis": asset["geometry_basis"],
                "stand_in": asset["stand_in"],
                "mesh": asset["mesh"],
                "attribution": asset["attribution"],
                "license": asset["license"],
            }
        )
    return {
        "provider": PROVIDER,
        "source": SOURCE,
        "retrieved": RETRIEVED,
        "sections": list(dict.fromkeys(i["section"] for i in found if i["lab"] == "ecl")),
        "labs": [
            {
                **lab,
                "sections": list(dict.fromkeys(i["section"] for i in found if i["lab"] == key)),
            }
            for key, lab in LABS.items()
        ],
        "instruments": found,
        "evidence": "synthetic",
    }


def provenance(asset_id):
    """Attribution and the drawn stand-in model stored on a twin; exports never resolve them."""
    asset = CLOUDLAB[asset_id]
    return {"id": asset_id, **{k: v for k, v in asset.items() if k not in {"spec", "featured"}}}
