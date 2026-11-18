import base64
import json

import pytest
from academy.cloudlab_training import QUESTIONS, TASKS
from fastapi.testclient import TestClient
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

RIGHT = {q["id"]: q["answer"] for q in QUESTIONS}


def step(kind, well="stock", volume=100):
    return {"kind": kind, "well": well, "volume": volume}


# The repaired fault: two trips with a fresh aspiration each.
REPAIRED = [
    step("pickup"),
    step("aspirate", "stock", 600),
    step("dispense", "A1", 600),
    step("aspirate", "stock", 600),
    step("dispense", "A2", 600),
    step("drop"),
]
OWN = [
    s
    for well in ("A1", "A2", "A3")
    for s in (
        step("pickup"),
        step("aspirate", "stock", 250),
        step("dispense", well, 250),
        step("drop"),
    )
]


def start(client):
    response = client.post("/api/cloudlab/training-sessions", json={"expected_version": 0})
    assert response.status_code == 201, response.text
    return response.json()


def check(client, training, task, actions):
    response = client.post(
        "/api/cloudlab/workflow-validations",
        json={"expected_version": training["version"], "task": task, "actions": actions},
    )
    assert response.status_code == 200, response.text
    return response.json()


def finish(client):
    training = start(client)
    training = client.post(
        "/api/cloudlab/training-sessions/answers",
        json={"expected_version": training["version"], "answers": RIGHT},
    ).json()
    training = check(client, training, "fault", REPAIRED)
    return check(client, training, "own", OWN)


def test_capabilities_name_the_instrument_rules_and_tasks(client):
    found = client.get("/api/cloudlab/capabilities").json()
    assert found["instrument"]["volume_ul"] == [5, 1000]
    assert found["modules"][0]["rules_version"] == "cloudlab-flex-transfer/1"
    assert [t["id"] for t in found["modules"][0]["tasks"]] == ["orient", "fault", "own"]
    assert found["evidence"] == "synthetic"


def test_the_injected_fault_is_stopped_by_the_simulator_rules(client):
    training = start(client)
    assert training["tasks"]["fault"]["actions"] == TASKS["fault"]["start"]
    result = check(client, training, "fault", TASKS["fault"]["start"])["last_check"]
    assert not result["valid"] and result["stops"] >= 1
    assert "room for 0 µL" in result["problems"][0]["message"]


def test_removing_the_faulty_step_is_not_a_repair(client):
    training = start(client)
    one_trip = [step("pickup"), step("aspirate", "stock", 600), step("dispense", "A1", 600)]
    trimmed = check(client, training, "fault", [*one_trip, step("drop")])
    result = trimmed["last_check"]
    assert not result["valid"] and result["stops"] == 0
    assert result["problems"] == [
        {"source": "goal", "step": None, "message": "A2 ends with 0 µL; the goal is 600 µL"}
    ]
    assert trimmed["tasks"]["fault"]["status"] == "open"
    repaired = check(client, trimmed, "fault", REPAIRED)
    assert repaired["last_check"]["valid"]
    task = repaired["tasks"]["fault"]
    assert (task["status"], task["attempts"]) == ("passed", 2)
    assert "A2 ends with 0 µL; the goal is 600 µL" in task["errors"]


def test_own_workflow_needs_a_fresh_tip_for_each_well(client):
    training = start(client)
    shared = [step("pickup")] + [
        s
        for well in ("A1", "A2", "A3")
        for s in (step("aspirate", "stock", 250), step("dispense", well, 250))
    ]
    result = check(client, training, "own", [*shared, step("drop")])["last_check"]
    assert [p["message"] for p in result["problems"]] == [
        "One tip dispenses into more than one well; use a fresh tip each time"
    ]


def test_wrong_answers_are_recorded_and_stale_commands_rejected(client):
    training = start(client)
    wrong = {**RIGHT, "pipette": 0}
    answered = client.post(
        "/api/cloudlab/training-sessions/answers",
        json={"expected_version": training["version"], "answers": wrong},
    ).json()
    assert answered["last_check"] == {"task": "orient", "valid": False, "wrong": ["pipette"]}
    assert answered["tasks"]["orient"]["status"] == "open"
    stale = client.post(
        "/api/cloudlab/training-sessions/answers",
        json={"expected_version": training["version"], "answers": RIGHT},
    )
    assert stale.status_code == 409
    assert (
        client.post("/api/cloudlab/training-sessions", json={"expected_version": 0}).status_code
        == 409
    )
    assert "answer" not in answered["questions"][0]


def payload(envelope):
    return json.loads(base64.urlsafe_b64decode(envelope["payload"] + "=="))


def reseal(envelope, record):
    """The same signature over different bytes, as an edited file would carry."""
    raw = json.dumps(record, separators=(",", ":")).encode()
    return {**envelope, "payload": base64.urlsafe_b64encode(raw).rstrip(b"=").decode()}


def test_a_signed_record_verifies_and_an_edit_does_not(client):
    finish(client)
    envelope = client.get("/api/cloudlab/qualifications/me").json()
    assert envelope["format"] == "academy.signed-record/1" and envelope["alg"] == "EdDSA"
    record = payload(envelope)
    assert record["complete"] and record["evidence"] == "synthetic"
    assert "does not authorize" in record["statement"]
    assert [t["retries"] for t in record["tasks"]] == [0, 0, 0]
    assert record["time_to_first_valid_workflow_s"] is not None
    assert "Ada" not in str(record)

    def verify(body):
        return client.post("/api/cloudlab/records/verify", json={"record": body}).json()

    assert verify(envelope) == {
        "authentic": True,
        "current": True,
        "complete": True,
        "problems": [],
        "rules_version": "cloudlab-flex-transfer/1",
        "record": record,
    }
    for edited in [
        {**record, "expires_at": "2099-01-01T00:00:00+00:00"},
        {**record, "subject": "someone-else"},
    ]:
        result = verify(reseal(envelope, edited))
        assert (result["authentic"], result["current"], result["record"]) == (False, False, None)
    assert verify({**envelope, "kid": "0" * 16})["authentic"] is False
    assert verify({"payload": "!!", "signature": "x"})["authentic"] is False


def test_a_portal_verifies_offline_with_only_the_published_key(client):
    finish(client)
    envelope = client.get("/api/cloudlab/qualifications/me").json()
    issuer = TestClient(client.app).get("/api/cloudlab/issuer").json()  # no sign-in
    assert issuer["rules"] == {"flex-transfer": "cloudlab-flex-transfer/1"}
    (jwk,) = issuer["keys"]
    assert jwk["kid"] == envelope["kid"] and "d" not in jwk
    key = VerifyKey(base64.urlsafe_b64decode(jwk["x"] + "="))
    raw = base64.urlsafe_b64decode(envelope["payload"] + "==")
    signature = base64.urlsafe_b64decode(envelope["signature"] + "==")
    assert key.verify(raw, signature) == raw
    with pytest.raises(BadSignatureError):
        key.verify(raw + b" ", signature)


def test_an_incomplete_record_is_authentic_but_not_complete(client):
    start(client)
    envelope = client.get("/api/cloudlab/qualifications/me").json()
    result = client.post("/api/cloudlab/records/verify", json={"record": envelope}).json()
    assert (result["authentic"], result["current"], result["complete"]) == (True, True, False)
    assert result["problems"] == ["Not every training task has been passed"]


def test_without_a_key_nothing_is_signed_or_published(store, tmp_path):
    from academy.main import create_app
    from academy.settings import Settings

    app = create_app(Settings(data_path=str(tmp_path / "x.sqlite")), store=store)
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/cloudlab/issuer").json()["keys"] == []


def test_each_learner_sees_only_their_own_training(app, client):
    finish(client)
    with TestClient(app) as other:
        other.post("/api/auth/guest", json={"name": "Grace"})
        assert other.get("/api/cloudlab/training-sessions/current").json() == {"training": None}
        assert other.get("/api/cloudlab/qualifications/me").status_code == 404
        record = client.get("/api/cloudlab/qualifications/me").json()
        mine = other.post("/api/cloudlab/records/verify", json={"record": record}).json()
        # A portal checks a record it is shown; it does not need the learner's account.
        assert mine["authentic"] and mine["complete"]
