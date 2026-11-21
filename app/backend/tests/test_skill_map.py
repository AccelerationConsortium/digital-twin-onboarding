"""The skill tree: read from what a run did on teaching twins, never from a claim."""

import pytest
from academy import paper_workflows as pw
from academy import skill_map as sm
from academy.stages import STAGES


def run(client, steps):
    saved = client.get("/api/cloudlab/workflow").json()
    put = client.put(
        "/api/cloudlab/workflow",
        json={"expected_version": saved["version"], "title": "Run", "steps": steps},
    ).json()
    ran = client.post("/api/cloudlab/workflow/run", json={"expected_version": put["version"]})
    assert ran.status_code == 200, ran.text
    return ran.json()


def test_every_function_has_a_twin_that_shows_it():
    assert set(pw.LABELS) == set(pw.FUNCTIONS)
    for function in pw.FUNCTIONS:
        assert sm.twins(function), function


@pytest.mark.parametrize("paper", list(pw.PAPERS))
def test_a_paper_as_read_reproduces_only_itself(paper):
    found = sm.read_run(pw.template(paper, {})["steps"])
    assert found["papers"] == {paper: {"swapped": False}}
    assert not found["extended"] and not found["recombined"]
    needed = {tuple(step["functions"]) for step in pw.PAPERS[paper]}
    assert all(set(any_of) & set(found["functions"]) for any_of in needed)


def test_a_run_missing_a_step_reproduces_nothing():
    steps = pw.template("alab", {3: ""})["steps"]
    assert sm.read_run(steps)["papers"] == {}
    assert sm.read_run(list(reversed(pw.template("clio", {})["steps"])))["papers"] == {}


def test_changes_are_told_apart():
    swapped = pw.template("alab", {2: "chemlab:carbolite_tf1_12_60_300"})
    assert sm.read_run(swapped["steps"])["papers"] == {"alab": {"swapped": True}}

    more = sm.read_run(pw.template("clio", {}, None, ["diffraction"])["steps"])
    assert more["extended"] == [["clio", "diffraction"]] and not more["recombined"]

    mixed = pw.template("ada", {}, "clio")
    assert [row["paper"] for row in mixed["rows"]] == ["ada"] * 4 + ["clio"]
    assert [row["stage"] for row in mixed["rows"]][-1] == "test"
    assert mixed["check"]["ok"]
    found = sm.read_run(mixed["steps"])
    assert found["recombined"] == [["ada", "clio"]] and "ada" not in found["papers"]


def test_a_workflow_of_its_own_is_not_read_as_two_papers():
    from academy import cloudlab_workflow as cw

    for starter in cw.STARTERS.values():
        assert not sm.read_run(starter["steps"])["recombined"]


def test_a_new_tree_is_three_stages_with_nothing_met(client):
    tree = client.get("/api/skills").json()
    assert tree["version"] == 0 and tree["stages"] == list(STAGES)
    assert tree["evidence"] == "synthetic"
    assert not any(f["met"] for f in tree["functions"])
    assert not any(p["reproduced"] for p in tree["papers"])
    assert {f["group"] for f in tree["functions"]} == {"prepare", "measure"}
    for paper in tree["papers"]:
        assert paper["steps"][0]["stage"] == "prepare"


def test_meeting_a_function_runs_its_twin_and_needs_the_current_version(client):
    body = {"expected_version": 0, "function": "diffraction"}
    twin = sm.twins("diffraction")[0]["id"]
    assert client.post("/api/skills/meet", json={**body, "instrument": "nope"}).status_code == 422
    assert (
        client.post("/api/skills/meet", json={**body, "instrument": "plate-reader"}).status_code
        == 422
    )
    met = client.post("/api/skills/meet", json={**body, "instrument": twin}).json()
    assert met["version"] == 1
    assert [t["operation"] for t in met["trace"]] == ["load", "read"]
    assert {f["id"]: f["met"] for f in met["functions"]}["diffraction"] == twin
    assert client.post("/api/skills/meet", json={**body, "instrument": twin}).status_code == 409
    alab = next(p for p in client.get("/api/skills").json()["papers"] if p["id"] == "alab")
    assert [s["met"] for s in alab["steps"]] == [False, False, False, True]


def test_a_run_adds_what_it_did_to_the_tree_once(client):
    first = run(client, pw.template("clio", {})["steps"])
    assert first["earned"]["papers"] == ["clio"]
    assert set(first["earned"]["functions"]) == {"dispense", "conductivity"}
    assert run(client, pw.template("clio", {})["steps"])["earned"] is None
    again = run(client, pw.template("rainbow", {}, "clio")["steps"])
    assert again["earned"]["recombined"] == [["rainbow", "clio"]]
    tree = client.get("/api/skills").json()
    assert tree["version"] == 2
    assert tree["recombined"] == [{"prepare": "rainbow", "measure": "clio"}]
    assert next(p for p in tree["papers"] if p["id"] == "clio")["reproduced"]
