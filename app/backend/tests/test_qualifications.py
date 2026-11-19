"""One qualification record for people and agents, signed and verified like a training record."""

import base64
import json

import pytest
from academy import qualifications
from academy.auth import identify
from academy.qualifications import KINDS, TYPE, record_pass
from fastapi.testclient import TestClient
from nacl.signing import VerifyKey
from tests.test_cloudlab_training import finish, reseal


def episode(client, scenario, calls, agent=None):
    version = client.get("/api/node/v1/sandbox/episodes").json()["version"]
    body = {"expected_version": version, "scenario": scenario}
    if agent:
        body["agent"] = agent
    opened = client.post("/api/node/v1/sandbox/episodes", json=body).json()
    version, status = opened["version"], opened["episode"]["status"]
    for tool, args in calls:
        response = client.post(
            f"/api/node/v1/sandbox/episodes/{opened['episode']['id']}/calls",
            json={"expected_version": version, "tool": tool, "args": args},
        )
        assert response.status_code == 200, response.text
        version, status = response.json()["version"], response.json()["status"]
    return status


WARM_READ = [
    ("load", {"device": "incubator", "volume_ul": 200}),
    ("heat", {"device": "incubator", "celsius": 37}),
    ("transfer", {"arm": "arm", "source": "incubator", "target": "reader"}),
    ("read", {"device": "reader"}),
]
TOO_HOT = [
    ("load", {"device": "incubator", "volume_ul": 200}),
    ("heat", {"device": "incubator", "celsius": 80}),
    ("request_operator", {"reason": "80 °C is above the incubator's limit"}),
]


def progress(client):
    return client.get("/api/qualifications").json()


def issue(client, instrument, agent=None, version=None):
    version = progress(client)["version"] if version is None else version
    return client.post(
        "/api/qualifications/records",
        json={"expected_version": version, "instrument": instrument, "agent": agent},
    )


def opened(envelope):
    raw = envelope["payload"]
    return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


def test_an_agent_earns_a_qualification_that_the_existing_verifier_accepts(client):
    assert episode(client, "warm-read", WARM_READ, agent="planner-2") == "goal"
    assert issue(client, "incubator", "planner-2").status_code == 409  # escalation still missing
    assert episode(client, "too-hot", TOO_HOT, agent="planner-2") == "escalated"

    holders = {h["agent"]: h for h in progress(client)["holders"]}
    assert holders["planner-2"]["kind"] == "agent"
    assert holders["planner-2"]["instruments"]["incubator"]["complete"]
    # The person did none of this, so nothing counts for them.
    assert not holders[None]["instruments"]["incubator"]["complete"]
    assert issue(client, "incubator").status_code == 409

    stale = issue(client, "incubator", "planner-2", version=5)
    assert stale.status_code == 409
    issued = issue(client, "incubator", "planner-2")
    assert issued.status_code == 200, issued.text
    envelope = issued.json()["record"]
    record = opened(envelope)
    assert record["type"] == TYPE and record["evidence"] == "synthetic"
    assert record["holder"]["kind"] == "agent" and record["holder"]["label"] == "planner-2"
    assert {c["id"] for c in record["criteria"]} == {"operate", "escalate"}
    assert "owner" not in json.dumps(record)

    # The one verifier the cloud lab portal and the node API already use.
    for path in ("/api/cloudlab/records/verify", "/api/node/v1/assess"):
        checked = client.post(path, json={"record": envelope}).json()
        assert checked["authentic"] and checked["current"] and checked["complete"], checked
    cleared = client.post(
        "/api/qualifications/verify",
        json={"record": envelope, "instrument": "incubator", "holder": "agent"},
    ).json()
    assert cleared["cleared"] and cleared["problems"] == []
    wrong = client.post(
        "/api/qualifications/verify",
        json={"record": envelope, "instrument": "plate-reader", "holder": "person"},
    ).json()
    assert not wrong["cleared"] and len(wrong["problems"]) == 2

    # Offline, with only the published key, and an edit breaks it.
    issuer = TestClient(client.app).get("/api/cloudlab/issuer").json()
    assert issuer["qualifications"]["incubator"] == KINDS["incubator"]["criteria_version"]
    key = issuer["keys"][0]
    raw = base64.urlsafe_b64decode(key["x"] + "=" * (-len(key["x"]) % 4))
    payload = envelope["payload"]
    VerifyKey(raw).verify(
        base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)),
        base64.urlsafe_b64decode(envelope["signature"] + "=" * (-len(envelope["signature"]) % 4)),
    )
    edited = reseal(envelope, {**record, "instrument": {"kind": "liquid-handler"}})
    assert not client.post("/api/qualifications/verify", json={"record": edited}).json()["cleared"]


def test_a_person_earns_the_same_kind_of_record_and_training_records_still_verify(client):
    finish(client)
    holders = {h["agent"]: h for h in progress(client)["holders"]}
    handler = holders[None]["instruments"]["liquid-handler"]
    assert handler["complete"]
    assert {c["source"] for c in handler["criteria"]} == {
        "cloudlab:own",
        "cloudlab:fault",
        "cloudlab:escalate",
    }
    envelope = issue(client, "liquid-handler").json()["record"]
    record = opened(envelope)
    training = client.get("/api/cloudlab/qualifications/me").json()
    # Same signer, same envelope, same pseudonym as the training record.
    assert envelope["format"] == training["format"] and envelope["kid"] == training["kid"]
    assert record["holder"] == {"kind": "person", "subject": opened(training)["subject"]}

    checked = client.post("/api/cloudlab/records/verify", json={"record": envelope}).json()
    assert checked["current"] and checked["complete"]
    old = client.post("/api/cloudlab/records/verify", json={"record": training}).json()
    assert old["authentic"] and old["current"] and old["complete"] and old["problems"] == []
    # A training record is not a qualification.
    as_qualification = client.post("/api/qualifications/verify", json={"record": training}).json()
    assert as_qualification["authentic"] and not as_qualification["cleared"]


def test_other_assessments_record_passes_for_either_holder(app, store):
    with pytest.raises(ValueError):
        record_pass(store, "x", instrument="incubator", criterion="recover", source="drill")
    app.dependency_overrides[identify] = lambda: "subject-1"
    try:
        client = TestClient(app)
        for criterion in ("operate", "recover", "escalate"):
            record_pass(
                store,
                "subject-1",
                instrument="liquid-handler",
                criterion=criterion,
                source="fault-drills:checkride",
                agent="planner-2",
            )
        # Recording the same pass again changes nothing.
        version = progress(client)["version"]
        record_pass(
            store,
            "subject-1",
            instrument="liquid-handler",
            criterion="operate",
            source="fault-drills:checkride",
            agent="planner-2",
            passed_at="2000-01-01T00:00:00+00:00",
        )
        assert progress(client)["version"] == version == 3
        holders = {h["agent"]: h for h in progress(client)["holders"]}
        assert holders["planner-2"]["instruments"]["liquid-handler"]["complete"]
        assert not holders[None]["instruments"]["liquid-handler"]["complete"]
        issued = issue(client, "liquid-handler", "planner-2").json()["record"]
        verdict = client.post(
            "/api/qualifications/verify", json={"record": issued, "holder": "agent"}
        ).json()
        assert verdict["cleared"]
    finally:
        app.dependency_overrides.clear()


def test_new_criteria_mark_earlier_qualifications_out_of_date(client, monkeypatch):
    episode(client, "warm-read", WARM_READ, agent="planner-2")
    episode(client, "too-hot", TOO_HOT, agent="planner-2")
    envelope = issue(client, "incubator", "planner-2").json()["record"]
    monkeypatch.setitem(
        qualifications.KINDS,
        "incubator",
        {**KINDS["incubator"], "criteria_version": "academy-qualification/incubator/2"},
    )
    checked = client.post("/api/cloudlab/records/verify", json={"record": envelope}).json()
    assert checked["authentic"] and not checked["current"]
    assert not client.post("/api/qualifications/verify", json={"record": envelope}).json()[
        "cleared"
    ]


def test_issued_passes_outlive_the_sandbox_history(client):
    episode(client, "warm-read", WARM_READ, agent="planner-2")
    episode(client, "too-hot", TOO_HOT, agent="planner-2")
    assert issue(client, "incubator", "planner-2").status_code == 200
    for _ in range(5):  # the sandbox keeps the latest five episodes
        episode(client, "last-tip", [], agent="planner-2")
    holders = {h["agent"]: h for h in progress(client)["holders"]}
    assert holders["planner-2"]["instruments"]["incubator"]["complete"]
