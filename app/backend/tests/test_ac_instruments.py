"""Acceleration Consortium instruments: listed like cloud lab ones, never their own spec."""

import pytest
from academy import ac_equipment, chemlab
from academy.cloudlab import CLOUDLAB, CONTRACTS, SKETCHES
from academy.cloudlab_anatomy import anatomy
from academy.cloudlab_teaching import instruments
from academy.simple_twins import Part

AC = {key: CLOUDLAB[key] for key in ac_equipment.INSTRUMENTS}


def test_every_ac_instrument_is_listed_apart_from_the_cloud_lab():
    found = instruments()
    labs = {lab["id"]: lab for lab in found["labs"]}
    assert labs["ac"]["provider"] == "Acceleration Consortium"
    assert labs["ac"]["source"] == ac_equipment.SOURCE
    ac = [i for i in found["instruments"] if i["lab"] == "ac"]
    assert [i["id"] for i in ac] == list(ac_equipment.INSTRUMENTS)
    assert labs["ac"]["sections"] == list(dict.fromkeys(i["section"] for i in ac))
    # The cloud lab's own list and sections are unchanged.
    assert sum(i["lab"] == "ecl" for i in found["instruments"]) == 24
    assert "Plate handling" not in found["sections"]


@pytest.mark.parametrize("key", list(ac_equipment.INSTRUMENTS))
def test_an_ac_twin_names_only_what_the_reference_lists(key):
    asset = AC[key]
    name, ids, section, (listed, url), _, geometry = ac_equipment.INSTRUMENTS[key]
    assert asset["lab"] == "ac" and asset["provider"] == "Acceleration Consortium"
    assert asset["experiment"] == ids and asset["published"] == listed
    assert asset["url"] == url and (not url or url.startswith("https://"))
    assert asset["domain"] == f"Acceleration Consortium · {section}"
    # Everything the reference does not list is an Academy default, said so on the twin.
    assumptions = asset["spec"]["assumptions"]
    assert f"equipment reference lists {listed} ({ids})" in assumptions
    assert "Other values are Academy teaching defaults" in assumptions
    # Every one holds a sample, so it can be practised step by step.
    assert "load" in asset["spec"]["operations"]
    if isinstance(geometry, str):
        # A ChemLab model no other instrument is drawn with stands in for it.
        assert geometry in chemlab.MODELS["models"]
        assert asset["slug"] == geometry and asset["mesh"]
        assert "MBZUAI" in asset["attribution"]
    else:
        # Otherwise it is a box, never another instrument's model under this name.
        assert asset["slug"] is None and anatomy(key) is None
        assert asset["geometry_basis"]["size"].startswith(("datasheet:", "estimate"))


SKETCHED = [key for key, asset in AC.items() if asset["sketch"]]


def test_five_ac_boxes_are_drawn_from_a_product_photo():
    assert SKETCHED == [
        "ac-tecan",
        "ac-bead-separator",
        "ac-plate-stacker",
        "ac-qpcr",
        "ac-medchem-lcms",
    ]


@pytest.mark.parametrize("key", SKETCHED)
def test_a_photo_sketch_fills_the_twins_box_and_says_where_it_is_from(key):
    asset, pinned = AC[key], SKETCHES["sketches"][key]
    mesh, (width, height, depth) = asset["mesh"], asset["spec"]["parts"][0]["size"]
    assert mesh["kind"] == "sketch" and mesh["asset"] == key and asset["stand_in"] is None
    assert 12 <= len(mesh["parts"]) <= 80
    for part in mesh["parts"]:
        assert part.get("shape", "cylinder") == "cylinder"
        assert 0 < part.get("opacity", 1) <= 1 and 0 < part.get("round", 0.1) <= 0.5
    parts = [
        Part.model_validate({k: p[k] for k in ("size", "position", "color")}) for p in mesh["parts"]
    ]
    assert all(p["label"] for p in mesh["parts"])
    # The boxes span exactly the twin's own box: standing on the bench, centred on it.
    for axis, (low, high) in enumerate(
        ((-width / 2, width / 2), (0, height), (-depth / 2, depth / 2))
    ):
        assert min(p.position[axis] - p.size[axis] / 2 for p in parts) == pytest.approx(
            low, abs=1e-3
        )
        assert max(p.position[axis] + p.size[axis] / 2 for p in parts) == pytest.approx(
            high, abs=1e-3
        )
    # The twin itself is still its one sized box; the sketch only changes what is drawn.
    assert len(asset["spec"]["parts"]) == 1
    assert asset["sketch"] == {
        "instrument": pinned["instrument"],
        "page": pinned["page"],
        "read": pinned["read"],
        "model": "claude-fable-5-2",
    }
    assert pinned["page"].startswith("https://") and pinned["photos"] and pinned["unseen"]
    assert f"sketched by Claude Fable 5.2 from a {pinned['instrument']}" in asset["attribution"]


DRAWN = [key for key, asset in AC.items() if asset["slug"]]


def test_no_model_is_drawn_for_two_ac_instruments():
    assert len({AC[key]["slug"] for key in DRAWN}) == len(DRAWN) == 26


@pytest.mark.parametrize("key", DRAWN)
def test_every_drawn_ac_instrument_comes_apart(key):
    found = anatomy(key)
    assert found and 5 <= len(found["parts"]) <= 8
    nodes = CONTRACTS["stand_ins"][AC[key]["slug"]].get("nodes")
    for part in found["parts"]:
        assert part["components"]
        # A model that names nodes its own way sends those names with every part.
        assert bool(part.get("nodes")) == bool(nodes)


def test_new_stand_ins_carry_layout_from_their_pinned_contracts():
    for slug in ("genevac_mivac2", "ika_ks4000", "hepatochem_photoredoxbox"):
        assert CONTRACTS["stand_ins"][slug]["size"]["evidence"] == "manufacturer"
    lid = CONTRACTS["stand_ins"]["genevac_mivac2"]["joints"]["lid"]
    assert lid["type"] == "revolute" and lid["limits"] == [0.0, 1.45]
    cuvette = CONTRACTS["stand_ins"]["antonpaar_litesizerdls"]["joints"]["cuvette"]
    assert cuvette["type"] == "prismatic" and cuvette["limits"] == [0.0, 0.12]
    # A freely turning rotor has no range, so it is not posed.
    assert "rotor" not in CONTRACTS["stand_ins"]["antonpaar_mcr503"]["joints"]
    assert set(CONTRACTS["stand_ins"]["eppendorf_5910ri"]["nodes"]["chassis"]) >= {
        "eppendorf_5910ri__housing"
    }


def test_an_ac_instrument_is_practised_through_the_api(client):
    found = client.get("/api/cloudlab/instruments").json()
    item = next(i for i in found["instruments"] if i["id"] == "ac-evaporator")
    assert item["lab"] == "ac" and item["motion"] and item["anatomy"]
    ran = client.post(
        "/api/cloudlab/instruments/ac-evaporator/check", json={"steps": item["starter"]}
    ).json()
    assert ran["ok"] and len(ran["trace"]) == len(item["starter"])
    hot = [
        {**item["starter"][0]},
        {"operation": "heat", "sample": "plate", "value": 110, "slot": ""},
    ]
    refused = client.post("/api/cloudlab/instruments/ac-evaporator/check", json={"steps": hot})
    assert refused.json()["error"]["layer"] == "constraint"
