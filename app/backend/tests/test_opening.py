"""An enclosure entered through part of one face: a side window with half of it removed."""

from uuid import uuid4

import pytest
from academy import layout_search
from academy.collision import shapes
from academy.examples import EXAMPLES, build
from academy.simple_twins import TwinSpec
from academy.workcell_layout import _yaw, access
from pydantic import ValidationError

BENCH = {"width": 2.4, "depth": 1.6}
LEFT_FRONT = {"face": "left", "start": 0.5, "end": 1.0}


def cell(opening):
    twins, steps, _ = build({**EXAMPLES["flex-reader"], "placements": None}, lambda: str(uuid4()))
    flex = twins[0]
    if opening:
        flex["spec"]["opening"] = opening
    return {t["id"]: t for t in twins}, steps, flex


def search(twins, steps, seconds=60):
    found, start, chunk = [], 0, None
    while start is not None and not found:
        chunk = layout_search.search_layouts(twins, BENCH, steps, start=start, seconds=seconds)
        found, start = chunk["candidates"], chunk["next"]
    return found, chunk


def test_an_opening_shuts_the_other_sides_and_clears_its_own():
    _, _, plain = cell(None)
    _, _, flex = cell(LEFT_FRONT)
    before, after = shapes(plain), shapes(flex)
    level, height = flex["spec"]["level_m"], 0.84
    x0, x1, z0, z1 = -0.435, 0.435, -0.34545, 0.34545

    def covers(face_x=None, face_z=None, along=(0, 0)):
        """Some box spans the face at mid height over `along`."""
        for (cx, cy, cz), (hx, hy, hz) in after:
            if not cy - hy <= (level + height) / 2 <= cy + hy:
                continue
            if face_x is not None and abs(cx - face_x) <= 0.03 and cz - hz <= along[0] + 0.01:
                if cz + hz >= along[1] - 0.01:
                    return True
            if face_z is not None and abs(cz - face_z) <= 0.03 and cx - hx <= along[0] + 0.01:
                if cx + hx >= along[1] - 0.01:
                    return True
        return False

    assert covers(face_z=z1, along=(x0, x1))  # front shut
    assert covers(face_x=x1, along=(z0, z1))  # right shut
    assert covers(face_x=x0, along=(z0, 0.0))  # back half of the left shut
    # Nothing above the deck stands in the front half of the left side.
    for (cx, cy, cz), (hx, hy, hz) in after:
        above = cy + hy > level and cy - hy < height - 0.03
        # The front wall meets the left side at the corner and is not in the way.
        in_span = cz + hz > 0.0 and cz - hz < z1 - 0.04
        assert not (above and in_span and (cx - hx) - x0 < 0.08), ((cx, cy, cz), (hx, hy, hz))
    # A twin without an opening keeps the shape it had.
    assert before == shapes(cell(None)[2]) and len(after) != len(before)


def test_the_arm_reaches_the_deck_through_the_open_half():
    twins, steps, flex = cell(LEFT_FRONT)
    found, _ = search(twins, steps)
    assert found, "no layout through the left window"
    best = found[0]
    place = {p["twin_id"]: p for p in best["layout"]["placements"]}
    arm = next(p for t, p in place.items() if "transfer" in twins[t]["spec"]["operations"])
    p = place[flex["id"]]
    # The Flex's left side is the one turned toward the arm.
    left = _yaw(p["yaw"], -1, 0)
    to_arm = (arm["x"] - p["x"], arm["z"] - p["z"])
    assert left[0] * to_arm[0] + left[1] * to_arm[1] > 0
    # The plate leaves slot D1 sideways through that side, rising as it goes.
    _, direction, _, _ = access(flex["spec"], p, "D1")
    assert direction[0] * left[0] + direction[2] * left[1] > 0.8 and direction[1] > 0
    assert best["motions"][0]["source_site"] == "D1" and best["clearance_m"] >= 0.01


def test_the_shut_half_is_named_when_nothing_reaches_through_the_open_one():
    twins, steps, _ = cell({"face": "left", "start": 0.0, "end": 0.5})
    found, chunk = search(twins, steps, seconds=20)
    assert found == []
    first = chunk["diagnosis"][0]
    assert first["kind"] == "access" and "Opentrons Flex" in first["hint"]
    assert "through its left side" in chunk["failure"]


def test_an_opening_belongs_to_an_instrument_entered_from_a_side():
    _, _, flex = cell(None)
    spec = flex["spec"]
    assert "opening" not in TwinSpec(**spec).model_dump()
    kept = TwinSpec(**{**spec, "opening": LEFT_FRONT}).model_dump()
    assert kept["opening"] == LEFT_FRONT
    with pytest.raises(ValidationError, match="entered from a side"):
        TwinSpec(**{**spec, "access": "top", "opening": LEFT_FRONT})
    with pytest.raises(ValidationError, match="fifth"):
        TwinSpec(**{**spec, "opening": {"face": "left", "start": 0.5, "end": 0.6}})


def test_a_saved_instrument_takes_an_opening_unless_its_layout_needs_the_front(client):
    def with_opening(example):
        version = client.get("/api/twins").json()["version"]
        opened = client.put(
            f"/api/twins/examples/{example}",
            json={"expected_version": version, "replace": True},
        ).json()
        flex = next(t for t in opened["twins"] if "Flex" in t["spec"]["name"])
        version = client.get("/api/twins").json()["version"]
        return flex, client.put(
            f"/api/twins/{flex['id']}/confirm",
            json={"expected_version": version, "spec": {**flex["spec"], "opening": LEFT_FRONT}},
        )

    # The saved layout serves the Flex through its front, which the opening would shut.
    _, refused = with_opening("flex-reader")
    assert refused.status_code == 422 and "Opentrons Flex" in refused.text
    # Without a layout to break, the opening is saved with the twin.
    flex, saved = with_opening("flex-shaker-reader")
    assert saved.status_code == 200, saved.text
    twin = next(t for t in saved.json()["twins"] if t["id"] == flex["id"])
    assert twin["spec"]["opening"] == LEFT_FRONT


def test_only_slots_behind_the_open_part_are_served():
    from academy.workcell_layout import footprint, opening_sites

    _, _, flex = cell(LEFT_FRONT)
    spec = flex["spec"]
    x0, x1, z0, z1 = footprint(spec)
    keys = opening_sites(spec)
    assert keys and len(keys) < len(spec["sites"])
    middle = (z0 + z1) / 2
    for site in spec["sites"]:
        behind = site["key"] in keys
        assert behind == (site["z"] >= middle - 1e-9), site
    # Shallowest first: the left-most slots, nearest the left face.
    xs = [next(s["x"] for s in spec["sites"] if s["key"] == k) for k in keys]
    assert xs == sorted(xs)
    shut = {**spec, "opening": {"face": "left", "start": 0.0, "end": 0.2}}
    assert all(
        next(s for s in spec["sites"] if s["key"] == k)["z"] <= z0 + (z1 - z0) * 0.2 + 1e-9
        for k in opening_sites(shut)
    )


def test_an_opening_needs_drawn_slots_and_counts_as_geometry():
    from academy.simple_twins import detail_layers

    _, _, flex = cell(None)
    spec = {**flex["spec"], "access": "front"}
    with pytest.raises(ValidationError, match="slots drawn"):
        TwinSpec(**{**spec, "sites": [], "opening": LEFT_FRONT})
    opened = {**spec, "opening": LEFT_FRONT}
    assert "geometry" in detail_layers(spec, opened)[1]
