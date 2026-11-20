"""Layout geometry of the cloud lab stand-ins, read from the pinned ChemLab-Assets contracts.

  uv run python scripts/library-models/chemlab_layout.py [CACHE]

Downloads geometry_manifest.json and asset.contract.json of every ChemLab stand-in that
cloudlab.py and ac_equipment.py name, at the revision chemlab.py pins (into CACHE, default a temporary
folder), and writes app/backend/academy/chemlab_layout.json. For each stand-in:

  size      outside (width, depth, height) in metres
  access    the face a sample goes in through: front or top
  opening   the part of the front it uses, as fractions from left to right
  level_m   the height above the bench a sample is set down at
  site      where on the footprint that is, in the twin's frame (x right, z toward the front)
  extends_m how far a drawer moves out of the front, to keep clear
  parts     the components a learner can point at in the 3D view
  joints    of those, the ones that move: type, axis, limits and pivot in the asset frame
  components every component the model names, which the anatomy view may group
  nodes     each component's node names in model.glb, for the stand-ins in OWN_NODES

Every field carries the dataset's evidence for it: `manufacturer` where the asset records a
manufacturer document, otherwise `engineering_assumption`, with the dataset's own label as
`detail`. Which port and which joint say how a sample goes in is chosen here, per stand-in,
and named in the output. A stand-in whose contract has no sample nest (samples arrive by
tubing) or whose nest the contract does not place gets no access, opening or height.

Only numbers, identifiers and evidence labels are written, never dataset text. The data is
CC-BY-NC-4.0 (MBZUAI ChemLab-Assets); attribution travels with every twin started from it.
"""

import json
import math
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app/backend/academy"
OUT = BACKEND / "chemlab_layout.json"
REPO = "MBZUAI/ChemLab-Assets"
FILES = ("geometry_manifest.json", "asset.contract.json")

# slug: (where manufacturer_dimensions_m gives W, D, H, or None for the model's own
#        bounding box; the component a sample is set into; the joint that opens it and
#        the face that joint opens, or None where the contract does not say)
STAND_INS = {
    "bmg_clariostarplus": (("W_D_H", (0, 1, 2)), "plate_carrier", ("plate_carrier", "front")),
    "biorad_cfxopus": (("external_W_D_H", (0, 1, 2)), "sample_block", ("lid", "top")),
    "biotek_405ts": (("workbook", (0, 1, 2)), "plate_carrier", ("plate_carrier", "top")),
    "eppendorf_cellxpertc170i": (
        ("external_W_D_H", (0, 1, 2)),
        "shelf_1",
        ("outer_door", "front"),
    ),
    "agilent_1260infinity": (None, "vial_tray_1", ("drawer_1", "front")),
    "biotage_selekt": (("W_D_H", (0, 1, 2)), "tray", ("tray", "front")),
    "sciex_pa800": (("W_D_H", (0, 1, 2)), "sample_tray_inlet", ("sample_cover", "front")),
    "cem_libertyblue": (None, "reactor", ("reactor_cover", "top")),
    # The rest take samples through tubing or from a nest the contract does not place.
    "agilent_hplc1260": (None, None, None),
    "agilent_gc8890b": (None, None, None),
    "thermo_dionexintegrion": (None, None, None),
    "thermo_orbitrapexploris": (("", (0, 1, 2)), None, None),
    "shimadzu_icpms2030": (("main_unit_W_D_H_excluding_protrusions", (0, 1, 2)), None, None),
    "cytiva_ktaoligosynt": (("full_W_H_D", (0, 2, 1)), None, None),
    # Acceleration Consortium stand-ins. None of these contracts places a sample nest this
    # script reads, so each gives its size only (or nothing, and the catalog size stands).
    "antonpaar_hit300": (None, None, None),
    "antonpaar_mcr503": (("", (0, 1, 2)), None, None),
    "azenta_automated_roll_heat_sealer_a4s": (None, None, None),
    "azenta_intellixcap_s1_46_0001": (None, None, None),
    "biotage_extrahera_classic": (None, None, None),
    "eppendorf_5910ri": (None, None, None),
    "gamry_reference620": (None, None, None),
    "genevac_mivac2": (("Duo_W_D_H", (0, 1, 2)), None, None),
    "hepatochem_photoredoxbox": (("W_D_H", (0, 1, 2)), None, None),
    "ika_ks4000": (("W_D_H", (0, 1, 2)), None, None),
    "ika_t25": (None, None, None),
    "mt_xpr204e": (None, None, None),
    "opentrons_flex_single_5_1000ul": (None, None, None),
    "syrris_asiadiscovery": (None, None, None),
    "ta_dsc2500": (None, None, None),
}
# The components a learner can point at on each stand-in's model: the doors, lids and
# drawers a sample goes through and what they uncover. Their joints are the motions the
# 3D view plays, so the view never moves a part further than its contract allows.
PARTS = {
    "bmg_clariostarplus": ("plate_carrier", "top_lid", "injector_a"),
    "biorad_cfxopus": ("lid", "sample_block"),
    "biotek_405ts": ("plate_carrier", "manifold"),
    "eppendorf_cellxpertc170i": ("outer_door", "inner_door", "shelf_rack"),
    "agilent_1260infinity": ("drawer_1", "sampler_door", "mct_door"),
    "biotage_selekt": ("tray", "collector_y", "collector_x"),
    "sciex_pa800": ("sample_cover", "cartridge_cover", "sample_tray_inlet"),
    "cem_libertyblue": ("reactor_cover", "reactor_clamp", "reactor", "aa_rack"),
    "thermo_dionexintegrion": ("main_door", "column_compartment"),
    "thermo_orbitrapexploris": ("source_housing",),
    "shimadzu_icpms2030": ("plasma_cover", "torch", "spray_chamber"),
    "cytiva_ktaoligosynt": ("column_clamp", "column_valve", "column"),
    # No joints in these contracts: the model is shown as it stands.
    "agilent_hplc1260": (),
    "agilent_gc8890b": (),
    "antonpaar_hit300": ("load_head", "stage_x", "specimen"),
    "antonpaar_mcr503": ("head_lift", "rotor", "temperature_stage"),
    "azenta_automated_roll_heat_sealer_a4s": ("plate_carriage", "press_head", "film_roll"),
    "azenta_intellixcap_s1_46_0001": ("gripper", "sample_interface"),
    "biotage_extrahera_classic": ("safety_shield", "pipette_head", "pressure_manifold"),
    "eppendorf_5910ri": ("sample_lid", "rotor", "chamber"),
    "gamry_reference620": ("cell_connector", "front_panel"),
    "genevac_mivac2": ("lid", "rotor", "basket_left", "basket_right"),
    "hepatochem_photoredoxbox": ("lid", "sample_rack"),
    "ika_ks4000": ("hood", "platform"),
    "ika_t25": ("drive", "rotor", "vessel"),
    "mt_xpr204e": ("door_left", "door_right", "pan"),
    "opentrons_flex_single_5_1000ul": ("gantry_y", "carriage_x", "pipette", "deck"),
    "syrris_asiadiscovery": ("chip_clamp", "collector_x", "chip"),
    "ta_dsc2500": ("lid", "sampler_x", "furnace"),
}
# Stand-ins whose model.glb names nodes after neither the slug nor the component, so the
# anatomy view needs each component's own node names from the contract.
OWN_NODES = {"azenta_automated_roll_heat_sealer_a4s", "eppendorf_5910ri", "mt_xpr204e"}
# Which part of each drawer's front is open: the drawer's own front panel.
DRAWER_FRONT = {"agilent_1260infinity": "drawer_1", "biotage_selekt": "tray_handle"}


def revision():
    for line in (BACKEND / "chemlab.py").read_text().splitlines():
        if line.startswith("REVISION = "):
            return line.split('"')[1]
    raise SystemExit("REVISION not found in chemlab.py")


def stand_ins():
    """The ChemLab slugs cloudlab.py and ac_equipment.py use as stand-ins."""
    text = "".join((BACKEND / name).read_text() for name in ("cloudlab.py", "ac_equipment.py"))
    return sorted(set(re.findall(r'^        "([a-z0-9_]+)",\n    \),', text, re.M)))


def fetch(cache, rev):
    rows = {
        r["slug"]: r
        for r in json.loads((BACKEND / "chemlab_catalog.json").read_text())["instruments"]
    }
    for slug in stand_ins():
        for name in FILES:
            path = cache / f"{rev}__{slug}__{name}"
            if path.exists():
                continue
            url = (
                f"https://huggingface.co/datasets/{REPO}/resolve/{rev}/{rows[slug]['path']}/{name}"
            )
            with urllib.request.urlopen(url, timeout=120) as response:
                # Renamed into place, so an interrupted download is never reused.
                part = path.with_name(path.name + ".part")
                part.write_bytes(response.read())
                part.replace(path)


def evidence(label):
    label = label or "unknown"
    kind = "manufacturer" if label.startswith("manufacturer") else "engineering_assumption"
    return {"evidence": kind, "detail": label}


def field(value, label):
    return {"value": value, **evidence(label)}


def components(manifest):
    found = manifest["components"]
    # A few newer manifests key their components by id instead of listing them.
    return dict(found) if isinstance(found, dict) else {c["id"]: c for c in found}


def origin(manifest, parts, cid):
    """A component's origin in the asset frame: its world origin, else its parents' sum."""
    world = (manifest.get("world_origins_m") or {}).get(cid)
    if world is not None:
        return world
    part = parts[cid]
    above = origin(manifest, parts, part["parent"]) if part["parent"] in parts else (0, 0, 0)
    return [a + b for a, b in zip(above, part["origin_m"], strict=True)]


def box(manifest, parts, cid):
    """(centre, size) of a component's largest collision box in the asset frame."""
    found = [c for c in parts[cid]["collisions"] if c["shape"] == "box"]
    if not found:
        return None
    big = max(found, key=lambda c: c["size_m"][0] * c["size_m"][1])
    base = origin(manifest, parts, cid)
    return [b + o for b, o in zip(base, big["origin_m"], strict=True)], big["size_m"]


def size(manifest, spec):
    if spec is None:
        overall = manifest.get("overall_dimensions_m")
        if not overall:
            return None
        return field([round(v, 4) for v in overall], "model_bounding_box")
    key, order = spec
    dims = manifest["manufacturer_dimensions_m"]
    dims = dims if isinstance(dims, list) else dims[key]
    width, depth, height = (dims[i] for i in order)
    return field([width, depth, height], "manufacturer_dimensions_m")


def derive(manifest, slug):
    dims, port, joint = STAND_INS[slug]
    found = size(manifest, dims)
    out = {"size": found} if found else {}
    if not port or not found:
        return out
    parts = components(manifest)
    (cx, cy, cz), (sx, sy, sz) = box(manifest, parts, port)
    width, depth, _ = out["size"]["value"]
    # Asset frame: +X right, +Y back, +Z up from the bench. Twin frame: z toward the front.
    x, z = round(cx, 4), round(-cy, 4)
    if abs(x) > width / 2 or abs(z) > depth / 2:
        return out  # the contract's nest lies off this footprint; leave it unset
    label = parts[port]["geometry_evidence"]
    name, face = joint
    moves = manifest["joint_definitions"][name]
    # The face is this script's reading of the joint that opens the nest, not a dataset value.
    out["access"] = {
        "value": face,
        "evidence": "engineering_assumption",
        "detail": f"joint {name} ({moves['type']})",
    }
    out["level_m"] = field(round(cz + sz / 2, 4), label)
    out["site"] = field([x, z], label)
    out["port"] = port
    if face == "front" and moves["type"] == "prismatic":
        out["extends_m"] = field(max(map(abs, moves["limits_m"])), moves["range_evidence"])
        panel = DRAWER_FRONT.get(slug, port)
        (px, _, _), (pw, _, _) = box(manifest, parts, panel)
        start, end = (px - pw / 2 + width / 2) / width, (px + pw / 2 + width / 2) / width
        # The schema keeps at least a fifth of a face open; widen a narrower drawer evenly.
        grow = max(0.0, 0.2 - (end - start)) / 2
        start, end = max(0.0, start - grow), min(1.0, end + grow)
        out["opening"] = field(
            # Rounded outward, so a widened drawer keeps its fifth.
            {
                "face": "front",
                "start": math.floor(start * 1000) / 1000,
                "end": math.ceil(end * 1000) / 1000,
            },
            parts[panel]["geometry_evidence"],
        )
    return out


def nodes(manifest):
    """Each component's node names in the model, as the contract lists them."""
    out = {}
    for cid, part in components(manifest).items():
        names = part.get("objects") or ([part["object"]] if part.get("object") else [])
        if names:
            out[cid] = names
    return out


def motion(manifest, slug):
    """The parts a learner can point at and the joints among them, in the asset frame."""
    parts = components(manifest)
    named = PARTS[slug]
    missing = [cid for cid in named if cid not in parts]
    if missing:
        raise SystemExit(f"{slug}: no component {missing} in the contract")
    joints = {}
    for cid in named:
        moves = manifest.get("joint_definitions", {}).get(cid)
        if not moves:
            continue
        limits = moves.get("limits_m", moves.get("limits_rad"))
        if limits is None or moves["type"] == "continuous":
            continue  # a rotor that turns freely has no range for the view to pose
        joints[cid] = {
            "type": moves["type"],
            "axis": [round(v, 6) for v in moves["axis"]],
            "limits": [round(v, 6) for v in limits],
            "pivot": [round(v, 5) for v in origin(manifest, parts, cid)],
            **evidence(moves["range_evidence"]),
        }
    return {"parts": list(named), "joints": joints} if named else {}


def main():
    rev = revision()
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
    cache.mkdir(parents=True, exist_ok=True)
    fetch(cache, rev)
    missing = (set(stand_ins()) ^ set(STAND_INS)) | (set(STAND_INS) ^ set(PARTS))
    if missing:
        raise SystemExit(f"Stand-ins without a row in STAND_INS (or not in cloudlab.py): {missing}")
    result = {}
    for slug in sorted(STAND_INS):
        manifest = json.loads((cache / f"{rev}__{slug}__geometry_manifest.json").read_text())
        result[slug] = {
            **derive(manifest, slug),
            **motion(manifest, slug),
            "components": sorted(components(manifest)),
        }
        if slug in OWN_NODES:
            result[slug]["nodes"] = nodes(manifest)
        print(slug, sorted(result[slug]), flush=True)
    OUT.write_text(
        json.dumps(
            {"repo": REPO, "revision": rev, "license": "CC-BY-NC-4.0", "stand_ins": result},
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
