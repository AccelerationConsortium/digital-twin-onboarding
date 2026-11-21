"""Marketplace papers as cloud lab workflow templates: synthetic, never paper conditions."""

import pytest
from academy import cloudlab_workflow as cw
from academy import paper_workflows as pw
from academy.discovery import WorkflowId


def test_every_marketplace_paper_has_steps():
    assert set(pw.PAPERS) == set(WorkflowId.__args__)


@pytest.mark.parametrize("paper", list(pw.PAPERS))
def test_default_picks_make_a_workflow_that_fits_every_twin(paper):
    result = pw.template(paper, {})
    assert result["evidence"] == "synthetic"
    assert result["check"]["ok"], result["check"]["error"]
    assert all(row["chosen"] and not row["gap"] for row in result["rows"])
    # The workflow is one the cloud lab designer accepts as written.
    cw.Draft(steps=result["steps"])
    shown = {i["id"] for i in result["instruments"]}
    assert {s["instrument"] for s in result["steps"]} <= shown
    assert result["steps"][-1]["operation"] == "read"


@pytest.mark.parametrize("paper", list(pw.PAPERS))
def test_candidates_can_do_the_step_they_are_offered_for(paper):
    for row, step in zip(pw.template(paper, {})["rows"], pw.PAPERS[paper], strict=True):
        assert row["candidates"]
        for candidate in row["candidates"]:
            assert step["operation"] in cw.spec_of(candidate["id"])["operations"]
        for refused in row["rejected"]:
            assert step["operation"] not in cw.spec_of(refused["id"])["operations"]


def test_instruments_beyond_opentrons_are_recommended():
    chosen = {row["chosen"] for p in pw.PAPERS for row in pw.template(p, {})["rows"]}
    assert "chemlab:retsch_pm100" in chosen  # ball mill for A-Lab
    assert "chemlab:rigaku_miniflex600_external_cooling" in chosen  # XRD
    assert "chemlab:metrohm_914" in chosen  # conductivity for Clio
    assert "plate-reader" in chosen  # a cloud lab instrument for Rainbow


def test_a_paper_condition_beyond_the_twins_is_clamped_and_said():
    [fire] = [r for r in pw.template("alab", {})["rows"] if r["operation"] == "heat"]
    assert all("so the template uses" in c["notes"][0] for c in fire["candidates"])
    heat = next(s for s in pw.template("alab", {})["steps"] if s["operation"] == "heat")
    assert heat["value"] == 120


def test_a_new_vessel_starts_a_new_sample():
    result = pw.template("clio", {})
    meter = result["rows"][2]
    assert "new vial" in meter["candidates"][0]["notes"][0]
    assert [s["sample"] for s in result["steps"]] == ["plate", "plate", "vial", "vial"]


def test_picks_swap_or_leave_out_a_step():
    swapped = pw.template("rainbow", {3: "chemlab:bmg_clariostarplus"})
    assert swapped["rows"][3]["chosen"] == "chemlab:bmg_clariostarplus"
    assert swapped["steps"][-1]["instrument"] == "chemlab:bmg_clariostarplus"
    assert swapped["check"]["ok"]
    # The load takes what every instrument on the plate's way can hold.
    assert swapped["steps"][0]["value"] == 200

    left = pw.template("rainbow", {2: ""})
    assert left["rows"][2]["chosen"] == ""
    assert "cell-incubator" not in {s["instrument"] for s in left["steps"]}
    # A pick that is not a candidate falls back to the best one.
    assert pw.template("rainbow", {3: "qpcr"})["rows"][3]["chosen"] == "plate-reader"


def test_the_template_route_saves_nothing(client):
    result = client.post("/api/marketplace/ada/template", json={"picks": {"4": ""}})
    assert result.status_code == 200
    body = result.json()
    assert body["rows"][4]["chosen"] == ""
    assert client.get("/api/cloudlab/workflow").json()["version"] == 0
    assert client.post("/api/marketplace/nope/template", json={}).status_code == 422


def test_a_chemlab_twin_saves_and_runs_in_the_cloud_lab_designer(client):
    steps = pw.template("alab", {})["steps"]
    saved = client.get("/api/cloudlab/workflow").json()
    put = client.put(
        "/api/cloudlab/workflow",
        json={"expected_version": saved["version"], "title": "A-Lab", "steps": steps},
    ).json()
    assert put["check"]["ok"]
    furnace = next(i for i in put["instruments"] if i["id"] == "chemlab:nabertherm_l9")
    assert furnace["section"] == "ChemLab-Assets" and "CC-BY-NC-4.0" in furnace["published"]
    ran = client.post("/api/cloudlab/workflow/run", json={"expected_version": put["version"]})
    assert ran.json()["runs"][0]["evidence"] == "synthetic"
    bad = [cw.step("chemlab:not-a-twin", "load", 100)]
    assert client.post("/api/cloudlab/workflow/check", json={"steps": bad}).status_code == 422


@pytest.mark.parametrize("paper", list(pw.PAPERS))
def test_every_step_is_one_part_of_the_experiment(paper):
    rows = pw.template(paper, {})["rows"]
    for row in rows:
        # Only a reading characterizes or tests; everything before it prepares.
        assert (row["stage"] == "prepare") == (row["operation"] != "read")
    assert rows[0]["stage"] == "prepare"
    assert rows[-1]["stage"] in {"characterize", "test"}


@pytest.mark.parametrize("paper", list(pw.PAPERS))
def test_a_paper_is_a_workcell_of_drawn_twins_in_step_order(paper):
    cell = pw.cell(paper)
    assert cell["evidence"] == "synthetic" and "not the lab's own" in cell["statement"]
    told = [step["index"] for station in cell["stations"] for step in station["steps"]]
    assert told == list(range(len(pw.PAPERS[paper])))
    for station in cell["stations"]:
        # Every station is a twin that can do its steps, drawn with its model and credit.
        for step in station["steps"]:
            wanted = pw.PAPERS[paper][step["index"]]
            assert wanted["operation"] in cw.spec_of(station["id"])["operations"]
        assert station["mesh"]["kind"] == "glb" and station["credit"]
        assert len(station["size_m"]) == 3


def test_the_cell_route_names_each_station(client):
    cell = client.get("/api/marketplace/alab/cell").json()
    assert [len(s["steps"]) for s in cell["stations"]] == [1, 1, 1, 1]
    assert client.get("/api/marketplace/nope/cell").status_code == 422
