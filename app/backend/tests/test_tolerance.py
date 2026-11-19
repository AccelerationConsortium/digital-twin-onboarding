"""How far instruments and the arm may sit off their planned spots before a transfer fails."""

import pytest
from academy import arm_simulation, layout_search, tolerance
from academy.simple_twins import TEMPLATES, new_twin
from fastapi.testclient import TestClient
from test_layout import BENCH, placed_cell, placements

READER, HEATER, ARM = (f"00000000-0000-0000-0000-00000000000{c}" for c in "abc")
TWINS = {
    twin_id: {**new_twin(twin_id, "template", TEMPLATES[key], None), "confirmed": True}
    for twin_id, key in ((READER, "reader"), (HEATER, "heater"), (ARM, "transfer-arm"))
}


def step(device, operation, source=None, target=None, value=1):
    return {
        "device_id": device,
        "operation": operation,
        "source_id": source,
        "target_id": target,
        "value": value,
    }


STEPS = [
    step(HEATER, "load", value=150),
    step(ARM, "transfer", HEATER, READER),
    step(READER, "read"),
]
# A second workflow on the same bench brings the plate back to the heater.
BACK = [
    step(HEATER, "load", value=150),
    step(ARM, "transfer", HEATER, READER),
    step(ARM, "transfer", READER, HEATER),
]


def layout(heater_x=-0.5):
    """The test cell; at x = -0.8 the heater sits just inside the arm's reach."""
    return {
        "bench": BENCH,
        "placements": [
            {"twin_id": ARM, "x": 0, "z": 0, "yaw": 0, "access": "top"},
            {"twin_id": HEATER, "x": heater_x, "z": 0.1, "yaw": 0, "access": "top"},
            {"twin_id": READER, "x": 0.8, "z": 0.1, "yaw": -90, "access": "front"},
        ],
    }


@pytest.fixture(scope="module")
def geometry():
    """Geometry-only planning, so whole analyses fit in a test; the bisection is the same."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(arm_simulation, "available", lambda: False)
        tolerance._verdicts.clear()
        yield
    tolerance._verdicts.clear()


@pytest.fixture
def quick(geometry):
    """Plans already made in this module are remembered, as on a warm Lambda."""


@pytest.fixture(scope="module")
def tight(geometry):
    """The whole analysis of the cell with the heater at the edge of the arm's reach."""
    return run([("Current workflow", STEPS)], layout(-0.8))[0]


def run(named, cell, seconds=60.0, samples=4, seed=0):
    done, start, trail, chunks = [], 0, [], 0
    while start is not None:
        chunk = tolerance.analyse(
            TWINS, cell, named, done, start, trail, seed=seed, samples=samples, seconds=seconds
        )
        done, start, trail = chunk["done"], chunk["next"], chunk["trail"]
        chunks += 1
    return chunk, chunks


def band(cell, twin_id, axis, sign, steps=STEPS):
    """Bisect one band the way `analyse` does, with the same probes."""
    trail = []
    while True:
        state = tolerance.bisect(axis, trail)
        if state[0] == "done":
            return state, trail
        moved = tolerance.shifted(TWINS, cell, {twin_id: {axis: sign * state[1]}})
        trail.append(tolerance.verdict(*moved, steps))


def test_bisection_finds_the_edge_a_brute_force_scan_finds(quick):
    cell = layout(-0.8)
    (_, found, saturated, limit), trail = band(cell, HEATER, "x", -1)
    assert not saturated and limit["cause"] == "unreachable"
    # Every 2 mm from the planned spot outward, until the first failure.
    scan, first = [], None
    for mm in range(0, 122, 2):
        moved = tolerance.shifted(TWINS, cell, {HEATER: {"x": -mm / 1000}})
        ok = tolerance.verdict(*moved, STEPS)["ok"]
        scan.append((mm / 1000, ok))
        if not ok:
            first = mm / 1000
            break
    assert first is not None
    # The band ends between the last pass and the first failure the scan sees.
    assert found < first <= found + max(0.002, 0.1 * found) + 1e-9
    assert all(ok for d, ok in scan if d <= found)
    # Far fewer plans than the scan.
    assert len(trail) < len(scan)


def test_a_tight_layout_names_the_instrument_and_transfer_that_limit_it(tight):
    summary = tight["summary"]
    assert summary["evidence"] == "synthetic"
    tightest = summary["requirements"][0]
    assert tightest["twin_id"] == HEATER and tightest["complete"]
    binding = tightest["binding"]
    assert binding["axis"] == "x" and binding["sign"] == -1
    assert binding["cause"] == "unreachable"
    assert binding["transfer"] == "Heating station → Plate reader"
    assert tightest["xz_m"] < 0.06
    assert tightest["sides"]["x"]["plus"]["band"] > tightest["xz_m"]
    # The overlay draws the asymmetric band.
    x_minus, x_plus = summary["overlay"][HEATER]["x"]
    assert x_minus == tightest["xz_m"] and x_plus > x_minus
    # Arm calibration: the base, and the tool offsets that equal moving it.
    (arm,) = summary["arms"]
    assert arm["twin_id"] == ARM
    assert arm["tool"]["longer_m"] == arm["sides"]["height"]["minus"]["band"]
    assert arm["tool"]["lateral_m"] == arm["xz_m"]
    # The combined curve is read from the smallest tolerances up.
    points = summary["curves"]["instruments"]["points"]
    assert [p["level_m"] for p in points] == [lv[0] for lv in tolerance.LEVELS]
    assert points[0]["runs"] == 4 and points[0]["rate"] == 1.0
    advice = summary["curves"]["instruments"]["advice"]
    assert advice and advice["level_m"] < points[-1]["level_m"]
    assert advice["needed"] == tolerance.needed(0.99)

    # Moved well inside the reach the heater can move much further that way.
    (_, roomy, _, _), _ = band(layout(-0.5), HEATER, "x", -1)
    assert roomy > tightest["xz_m"] + 0.05


def test_the_analysis_is_deterministic_and_resumes_from_any_chunk(tight, monkeypatch):
    named = [("Current workflow", STEPS)]
    # A cap that lets each request plan once still ends with the same answer.
    pieces, many = run(named, layout(-0.8), seconds=0.0)
    assert many > 100
    assert pieces["done"] == tight["done"] and pieces["summary"] == tight["summary"]
    # Planned afresh, without remembered verdicts, a smaller analysis comes out the same.
    monkeypatch.setattr(tolerance, "LEVELS", tolerance.LEVELS[:1])
    monkeypatch.setattr(tolerance, "AXES", {"x": tolerance.AXES["x"]})
    monkeypatch.setattr(tolerance, "_verdicts", type(tolerance._verdicts)())
    whole, _ = run(named, layout(-0.8))
    monkeypatch.setattr(tolerance, "_verdicts", type(tolerance._verdicts)())
    again, _ = run(named, layout(-0.8), seconds=0.0)
    assert again["done"] == whole["done"]
    # Another seed draws other combined errors; the same seed the same ones.
    a = tolerance.offsets("instruments", 0, 1, 0, [HEATER, READER])
    assert a == tolerance.offsets("instruments", 0, 1, 0, [HEATER, READER])
    assert a != tolerance.offsets("instruments", 0, 1, 7, [HEATER, READER])
    # Results that do not belong to this layout's task list are refused.
    forged = [dict(whole["done"][0], axis="yaw")]
    with pytest.raises(tolerance.PlanError):
        tolerance.analyse(TWINS, layout(-0.8), named, forged, 1)


def test_every_workflow_on_the_bench_gets_its_own_tolerance(quick, monkeypatch):
    monkeypatch.setattr(tolerance, "LEVELS", tolerance.LEVELS[:1])
    monkeypatch.setattr(tolerance, "AXES", {"x": tolerance.AXES["x"]})
    named = [("Current workflow", STEPS), ("Back again", BACK), ("Same", STEPS)]
    result, _ = run(named, layout(-0.8))
    summary = result["summary"]
    # The duplicate workflow is checked once.
    assert summary["workflows"] == ["Current workflow", "Back again"]
    assert [w["name"] for w in summary["per_workflow"]] == summary["workflows"]
    assert all(w["xz_m"] is not None for w in summary["per_workflow"])
    # The requirement holds for both: the tighter of the two.
    heater = next(r for r in summary["requirements"] if r["twin_id"] == HEATER)
    assert heater["xz_m"] == min(w["xz_m"] for w in summary["per_workflow"])
    point = summary["curves"]["instruments"]["points"][0]
    assert len(point["by_workflow"]) == 2


def test_a_layout_search_can_widen_the_smallest_margin_over_every_workflow(quick):
    cell = layout(-0.8)
    search = layout_search.Search(TWINS, BENCH, STEPS, [], shared=[BACK])
    start = search.check(cell)
    assert start and start["workflows"] == 2
    assert start["margin_m"] <= min(start["clearance_m"], start["reach_margin_m"])
    improved = layout_search.improve_layout(
        TWINS, cell, STEPS, ["margin_m"], seconds=120, shared=[BACK]
    )
    assert improved["kept"] >= 1 and improved["margin_m"] > start["margin_m"]
    # Both workflows still plan on the improved layout.
    for steps in (STEPS, BACK):
        assert tolerance.verdict(TWINS, improved["layout"], steps)["ok"]


def test_the_placement_template_is_drawn_at_full_scale(tight):
    result = tight
    svg = tolerance.template_svg(TWINS, layout(-0.8), result["summary"])
    assert 'width="3040mm" height="1640mm"' in svg
    assert "Datum 0,0" in svg and "100 mm at 1:1" in svg and "Synthetic" in svg
    assert svg.count('stroke-dasharray="4 3"') == 3  # one allowed region per instrument
    assert "Heating station" in svg and "within ±" in svg
    pages = tolerance.template_pages(TWINS, layout(-0.8), result["summary"])
    # 3.04 m by 1.64 m of drawing on A4 sheets overlapping 10 mm.
    assert pages.count("<section>") == 17 * 7
    assert "print at 100%" in pages


def test_the_tolerance_api_runs_on_the_owners_layout_only(client, app, monkeypatch):
    monkeypatch.setattr(arm_simulation, "available", lambda: False)
    monkeypatch.setattr(tolerance, "LEVELS", tolerance.LEVELS[:1])
    reader, heater, arm, _, catalog = placed_cell(client)
    rows = placements(reader, heater, arm)
    body = {"bench": BENCH, "placements": rows, "samples": 4}
    first = client.post("/api/twins/layout/tolerance", json=body)
    assert first.status_code == 200, first.text
    chunk = first.json()
    assert chunk["total"] > len(chunk["done"]) and chunk["next"] is not None
    resumed = client.post(
        "/api/twins/layout/tolerance",
        json={**body, "start": chunk["next"], "trail": chunk["trail"], "done": chunk["done"]},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["summary"]["evidence"] == "synthetic"
    template = client.post("/api/twins/layout/template", json={**body, "done": chunk["done"]})
    assert template.status_code == 200
    assert template.headers["content-type"].startswith("image/svg+xml")
    assert "mm" in template.text and "Synthetic" in template.text
    pages = client.post("/api/twins/layout/template?pages=true", json=body)
    assert pages.status_code == 200 and "<section>" in pages.text

    # Keeping a workflow for the bench is a versioned write.
    version = client.get("/api/twins").json()["version"]
    stale = client.post(
        "/api/twins/layout/workflows", json={"expected_version": version - 1, "name": "Old"}
    )
    assert stale.status_code == 409
    kept = client.post(
        "/api/twins/layout/workflows", json={"expected_version": version, "name": "Read"}
    )
    assert kept.status_code == 200, kept.text
    saved = kept.json()
    assert [w["name"] for w in saved["bench_workflows"]] == ["Read"]
    again = client.post(
        "/api/twins/layout/workflows",
        json={"expected_version": saved["version"], "name": "Twice"},
    )
    assert again.status_code == 409
    both = client.post("/api/twins/layout/tolerance", json={**body, "workflows": "bench"})
    assert both.status_code == 200
    # The kept copy is the same workflow, so it is analysed once.
    assert both.json()["summary"]["workflows"] == ["Current workflow"]
    dropped = client.request(
        "DELETE",
        f"/api/twins/layout/workflows/{saved['bench_workflows'][0]['id']}",
        json={"expected_version": saved["version"]},
    )
    assert dropped.status_code == 200 and dropped.json()["bench_workflows"] == []

    # Another learner has no layout or workflow of this owner to analyse.
    with TestClient(app) as other:
        assert other.post("/api/auth/guest", json={"name": "Grace"}).status_code == 200
        assert other.post("/api/twins/layout/tolerance", json=body).status_code == 404
