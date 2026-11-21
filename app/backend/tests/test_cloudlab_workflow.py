"""Cloud lab workflow design: synthetic teaching checks, never instrument evidence."""

import pytest
from academy import cloudlab_workflow as cw
from academy.cloudlab import CLOUDLAB
from academy.mock_contract import site_keys


def step(instrument, operation, value=1, sample="plate", slot=""):
    return cw.step(instrument, operation, value, sample, slot)


def save(client, steps, title="Assay"):
    saved = client.get("/api/cloudlab/workflow").json()
    return client.put(
        "/api/cloudlab/workflow",
        json={"expected_version": saved["version"], "title": title, "steps": steps},
    )


def test_instruments_take_part_through_what_their_twins_do():
    shown = {i["id"]: i for i in cw.catalog()}
    assert list(shown) == cw.INSTRUMENTS
    for key, item in shown.items():
        spec = CLOUDLAB[key]["spec"]
        assert item["operations"] == spec["operations"]
        assert item["holds"] == spec["container"]
        assert item["limits"] == spec["limits"]
        assert item["slots"] == site_keys(spec)
        assert len(item["slots"]) == spec["resource"]["slots"]
    # Every instrument besides the liquid handler draws a ChemLab-Assets stand-in.
    assert all(i["stand_in"] for k, i in shown.items() if k != "robotic-sample-preparation")
    assert shown["robotic-sample-preparation"]["consumables"][0]["name"] == "Pipette tips"


@pytest.mark.parametrize("starter", list(cw.STARTERS))
def test_starters_pass_every_twin_rule(starter):
    steps = cw.STARTERS[starter]["steps"]
    result = cw.check(steps)
    assert result["ok"] and result["error"] is None
    assert len(result["trace"]) == len(steps)
    assert result["trace"][-1]["operation"] == "read"
    assert result["trace"][-1]["measurement"]["kind"] == "synthetic_state_readout"
    # Each trace entry names the instrument the learner wrote, a move included.
    assert [e["device_id"] for e in result["trace"]] == [s["instrument"] for s in steps]


def test_a_move_carries_the_sample_and_frees_its_slot():
    steps = [
        step("cell-incubator", "load", 200, slot="5"),
        step("plate-reader", "transfer"),
        step("cell-incubator", "transfer", slot="5"),
    ]
    trace = cw.check(steps)["trace"]
    assert (trace[0]["location"], trace[0]["site"]) == ("cell-incubator", "5")
    assert trace[1]["location"] == "plate-reader"
    assert trace[1]["source_site"] == "5"
    # Slot 5 was freed by the move away, so the plate can return to it.
    assert (trace[2]["location"], trace[2]["site"]) == ("cell-incubator", "5")


@pytest.mark.parametrize(
    ("steps", "at", "layer", "words"),
    [
        ([step("plate-reader", "transfer")], 1, "state", "load plate before moving"),
        (
            [step("plate-reader", "load", 200), step("plate-reader", "transfer")],
            2,
            "state",
            "already at",
        ),
        (
            [step("cell-incubator", "load", 1000), step("plate-reader", "transfer")],
            2,
            "volume",
            "300 µL limit",
        ),
        (
            [step("plate-reader", "load", 100), step("flash-chromatography", "transfer")],
            2,
            "container",
            "accepts a tube, not a plate",
        ),
        ([step("thermocycler", "load", 50), step("thermocycler", "read")], 2, "state", "read"),
        (
            [step("cell-incubator", "load", 200), step("cell-incubator", "heat", 60)],
            2,
            "constraint",
            "33–50 °C",
        ),
        (
            [step("plate-washer", "load", 200), step("plate-washer", "wait", 900)],
            2,
            "constraint",
            "600 s",
        ),
        (
            [step("plate-reader", "load", 100), step("plate-reader", "mix", 30, sample="tube-b")],
            2,
            "state",
            "transfer tube-b",
        ),
        (
            [
                step("plate-reader", "load", 100),
                step("plate-reader", "load", 100, sample="second"),
            ],
            2,
            "resource",
            "no free slot",
        ),
        ([step("cell-incubator", "load", 100, slot="21")], 1, "resource", "no slot 21"),
    ],
)
def test_the_first_broken_rule_names_its_step(steps, at, layer, words):
    result = cw.check(steps)
    assert not result["ok"] and result["trace"] == []
    assert result["error"]["step"] == at
    assert result["error"]["layer"] == layer
    assert words in result["error"]["message"]


def test_tips_run_out_on_the_liquid_handler():
    steps = [step("robotic-sample-preparation", "load", 200)] + [
        step("robotic-sample-preparation", "mix", 5)
    ] * 31
    assert cw.check(steps)["ok"]
    stock = cw.check(steps)["trace"][-1]["consumables"]["robotic-sample-preparation"]
    assert stock == {"Pipette tips": 96 - 31}


def test_draft_check_saves_nothing(client):
    result = client.post(
        "/api/cloudlab/workflow/check",
        json={"steps": [step("plate-reader", "load", 900)]},
    ).json()
    assert result["error"]["layer"] == "volume"
    assert client.get("/api/cloudlab/workflow").json()["version"] == 0


def test_steps_outside_the_designer_are_rejected(client):
    for bad in (
        step("nmr", "load", 100),  # not one of the designer's instruments
        step("plate-reader", "read", slot="1"),  # only loads and moves choose a slot
        step("cell-incubator", "heat", 200),  # outside every teaching twin
    ):
        assert save(client, [bad]).status_code == 422
    assert save(client, [step("plate-reader", "load")] * (cw.MAX_STEPS + 1)).status_code == 422


def test_saved_workflow_runs_with_expected_versions(client):
    empty = client.get("/api/cloudlab/workflow").json()
    assert empty["version"] == 0 and empty["steps"] == [] and empty["runs"] == []
    assert empty["evidence"] == "synthetic"
    assert "not the cloud lab's instrument specification" in empty["statement"]
    assert client.post("/api/cloudlab/workflow/run", json={"expected_version": 0}).status_code == (
        422
    )

    steps = cw.STARTERS["cell-assay"]["steps"]
    saved = save(client, steps, "Viability readout").json()
    assert saved["version"] == 1 and saved["title"] == "Viability readout"
    assert saved["check"]["ok"]
    # A stale version is refused, not merged.
    stale = client.put(
        "/api/cloudlab/workflow",
        json={"expected_version": 0, "title": "Other", "steps": []},
    )
    assert stale.status_code == 409
    assert client.post("/api/cloudlab/workflow/run", json={"expected_version": 0}).status_code == (
        409
    )

    ran = client.post("/api/cloudlab/workflow/run", json={"expected_version": 1}).json()
    assert ran["version"] == 2
    [run] = ran["runs"]
    assert run["evidence"] == "synthetic" and run["steps"] == saved["steps"]
    assert run["trace"][-1]["measurement"]["kind"] == "synthetic_state_readout"
    assert client.get("/api/cloudlab/workflow").json()["runs"] == ran["runs"]


def test_a_broken_draft_saves_but_does_not_run(client):
    broken = [step("plate-reader", "load", 100), step("flash-chromatography", "transfer")]
    saved = save(client, broken).json()
    assert saved["check"]["error"]["step"] == 2
    refused = client.post("/api/cloudlab/workflow/run", json={"expected_version": 1})
    assert refused.status_code == 422
    assert refused.json()["detail"]["layer"] == "container"
    assert client.get("/api/cloudlab/workflow").json()["version"] == 1


def test_runs_are_kept_per_learner_and_bounded(client, app):
    from fastapi.testclient import TestClient

    save(client, cw.STARTERS["pcr-sizing"]["steps"])
    for _ in range(cw.KEPT_RUNS + 2):
        version = client.get("/api/cloudlab/workflow").json()["version"]
        client.post("/api/cloudlab/workflow/run", json={"expected_version": version})
    assert len(client.get("/api/cloudlab/workflow").json()["runs"]) == cw.KEPT_RUNS
    with TestClient(app) as other:
        assert other.post("/api/auth/guest", json={"name": "Grace"}).status_code == 200
        assert other.get("/api/cloudlab/workflow").json()["steps"] == []


def test_a_learner_keeps_several_workflows_apart(client):
    first = save(client, cw.STARTERS["cell-assay"]["steps"], "First").json()
    assert first["id"] == "" and first["saved"] == [{"id": "", "title": "First", "steps": 9}]

    other = "0b1f6c1e-3d0a-4c58-9d2e-7a4f1c2b3d4e"
    blank = client.get("/api/cloudlab/workflow", params={"id": other}).json()
    assert blank["version"] == 0 and blank["steps"] == [] and blank["id"] == other
    body = {"id": other, "title": "Second", "steps": cw.STARTERS["pcr-sizing"]["steps"]}
    second = client.put("/api/cloudlab/workflow", json={**body, "expected_version": 0}).json()
    assert [w["title"] for w in second["saved"]] == ["First", "Second"]

    # Saving and running one leaves the other as it was.
    ran = client.post("/api/cloudlab/workflow/run", json={"id": other, "expected_version": 1})
    assert ran.status_code == 200 and len(ran.json()["runs"]) == 1
    kept = client.get("/api/cloudlab/workflow").json()
    assert kept["title"] == "First" and kept["version"] == 1 and kept["runs"] == []
    assert client.get("/api/cloudlab/workflow", params={"id": "nope"}).status_code == 422


def test_deleting_a_workflow_needs_its_version_and_keeps_the_rest(client):
    save(client, cw.STARTERS["cell-assay"]["steps"], "First")
    other = "0b1f6c1e-3d0a-4c58-9d2e-7a4f1c2b3d4e"
    body = {"id": other, "title": "Second", "steps": [step("plate-reader", "load")]}
    client.put("/api/cloudlab/workflow", json={**body, "expected_version": 0})
    for stale in (0, 5):
        refused = client.post(
            "/api/cloudlab/workflow/delete", json={"id": other, "expected_version": stale}
        )
        assert refused.status_code == 409
    left = client.post("/api/cloudlab/workflow/delete", json={"id": other, "expected_version": 1})
    assert [w["title"] for w in left.json()["saved"]] == ["First"]
    assert client.get("/api/cloudlab/workflow", params={"id": other}).json()["version"] == 0


def test_saved_workflows_are_bounded(client):
    from uuid import uuid4

    steps = [step("plate-reader", "load")]
    for n in range(cw.MAX_SAVED):
        body = {"id": str(uuid4()), "title": f"W{n}", "steps": steps, "expected_version": 0}
        assert client.put("/api/cloudlab/workflow", json=body).status_code == 200
    extra = {"id": str(uuid4()), "title": "One more", "steps": steps, "expected_version": 0}
    refused = client.put("/api/cloudlab/workflow", json=extra)
    assert refused.status_code == 422 and "Delete one" in refused.text
    # One already saved can still be changed.
    again = {**body, "title": "Renamed", "expected_version": 1}
    assert client.put("/api/cloudlab/workflow", json=again).status_code == 200
