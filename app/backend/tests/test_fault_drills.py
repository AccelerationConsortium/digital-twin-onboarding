import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from academy import agent_sandbox, fault_drills
from academy.main import create_app
from academy.mock_contract import PlanError, execute_mock
from academy.settings import Settings
from academy.simple_twins import TEMPLATES
from fastapi.testclient import TestClient
from test_cloudlab_training import finish


class Clock:
    def __init__(self):
        self.at = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)

    def __call__(self):
        return self.at

    def wait(self, seconds):
        self.at += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch):
    found = Clock()
    monkeypatch.setattr(fault_drills, "now", found)
    return found


def state(client):
    response = client.get("/api/fault-drills")
    assert response.status_code == 200, response.text
    return response.json()


def start(client, instrument="liquid-handler", family="tips", **extra):
    found = state(client)
    response = client.post(
        "/api/fault-drills/drills",
        json={
            "expected_version": found["version"],
            "instrument": instrument,
            "family": family,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def act(client, body, action, status=200):
    response = client.post(
        f"/api/fault-drills/drills/{body['drill']['id']}/actions",
        json={"expected_version": body["version"], "action": action},
    )
    assert response.status_code == status, response.text
    return response.json()


def fire(clock, drill):
    clock.wait(drill["fires_in_s"] + 2)


def respond(client, clock, body, actions):
    fire(clock, body["drill"])
    for action in actions:
        body = act(client, body, action)
    return body


TIPS = ["pause", "reload", "confirm", "resume"]


def test_families_follow_what_an_instrument_can_do():
    found = fault_drills.instruments()
    assert set(found) >= set(TEMPLATES)
    assert {"tips", "liquid", "labware", "door", "offline"} <= set(
        found["liquid-handler"]["families"]
    )
    assert {"gripper", "collision"} <= set(found["transfer-arm"]["families"])
    assert not {"tips", "labware"} & set(found["transfer-arm"]["families"])
    assert "tips" not in found["reader"]["families"]
    for instrument in found.values():
        for family in instrument["families"]:
            scenario = fault_drills.catalog_scenario(instrument["key"], family)
            assert 1 <= scenario["fault_step"] <= len(scenario["steps"])
            assert scenario["ending"] in fault_drills.ENDINGS


def test_a_new_instrument_slots_in_from_its_spec_or_its_declaration(monkeypatch):
    monkeypatch.setattr(fault_drills, "REGISTERED", {})
    monkeypatch.setattr(fault_drills, "DECLARED", {})
    spec = {
        **TEMPLATES["liquid-handler"],
        "name": "Benchtop dispenser",
        "operations": ["load", "aspirate", "dispense", "wait"],
        "consumables": [{"name": "Tips", "used_by": "aspirate", "per_use": 1, "stock": 8}],
    }
    fault_drills.register("dispenser", spec)
    assert {"tips", "liquid", "labware"} <= set(fault_drills.instruments()["dispenser"]["families"])
    scenario = fault_drills.catalog_scenario("dispenser", "tips")
    # The second aspiration, the one the tips run out on.
    assert scenario["fault_step"] == 5
    assert scenario["contract"] == {
        "layer": "consumable",
        "message": "Step 5: Benchtop dispenser has run out of Tips",
    }
    fault_drills.register("dispenser", spec, families=["offline", "not-a-family"])
    assert fault_drills.instruments()["dispenser"]["families"] == ["offline"]


def test_drill_faults_are_the_refusals_an_agent_meets():
    """The mock contract the agent sandbox runs refuses the same faults the same way."""
    tips = fault_drills.catalog_scenario("liquid-handler", "tips")["contract"]
    twins = agent_sandbox.twins_of("last-tip")
    handler = agent_sandbox.device_id("last-tip", "handler")
    steps = [
        agent_sandbox.as_step("last-tip", "load", {"device": "handler", "volume_ul": 100}),
        agent_sandbox.as_step("last-tip", "mix", {"device": "handler", "seconds": 30}),
        agent_sandbox.as_step("last-tip", "mix", {"device": "handler", "seconds": 30}),
    ]
    assert steps[0]["device_id"] == handler
    with pytest.raises(PlanError) as agent:
        execute_mock(twins, steps)
    assert agent.value.layer == tips["layer"] == "consumable"
    assert str(agent.value).split(": ", 1)[1] == tips["message"].split(": ", 1)[1]
    labware = fault_drills.catalog_scenario("reader", "labware")["contract"]
    assert labware == {
        "layer": "container",
        "message": "Step 2: Plate reader accepts a plate, not a tube",
    }
    offline = fault_drills.catalog_scenario("heater", "offline")
    assert offline["contract"]["layer"] == "state"
    assert offline["contract"]["message"].startswith(f"Step {offline['fault_step']}:")
    # Faults the contract does not model carry no refusal rather than a wrong one.
    assert fault_drills.catalog_scenario("transfer-arm", "collision")["contract"] is None


def test_a_drill_runs_then_faults_and_hides_its_answer_until_it_ends(client, clock):
    body = start(client)
    drill = body["drill"]
    assert drill["status"] == "open" and drill["fires_in_s"] == 3.5
    # Before the fault the learner sees the run, not what will go wrong.
    assert drill["symptom"] is None and drill["fault_step"] is None and "answer" not in drill
    assert drill["title"] is None and len(drill["steps"]) == 4
    ids = {a["id"] for a in drill["pool"]}
    assert set(TIPS[:-1]) <= ids and len(ids) == 6
    assert act(client, body, "pause", 409)["detail"] == "The fault has not happened yet"

    clock.wait(3.6)
    assert state(client)["open"]["symptom"].startswith("The liquid handler stops at step 4")
    clock.wait(1.4)
    for action in TIPS:
        body = act(client, body, action)
        clock.wait(1)
    drill = body["drill"]
    assert drill["status"] == "done"
    assert drill["result"] == {
        "response_s": 1.5,
        "total_s": 4.5,
        "unsafe_actions": 0,
        "recovery_correct": True,
        "ending": "resume",
        "timed_out": False,
        "passed": True,
    }
    assert [a["id"] for a in drill["answer"]["recovery"]] == TIPS[:-1]
    assert drill["answer"]["contract"]["layer"] == "consumable"
    assert body["summary"]["passed"] == 1 and body["open"] is None
    assert act(client, body, "resume", 409)["detail"] == "This drill has ended"


def test_unsafe_actions_and_the_wrong_ending_are_recorded(client, clock):
    body = start(client, "transfer-arm", "collision")
    body = respond(client, clock, body, ["jog", "hold", "clear", "record", "resume"])
    result = body["drill"]["result"]
    assert result["unsafe_actions"] == 1 and not result["recovery_correct"]
    assert not result["passed"] and result["ending"] == "resume"
    assert body["drill"]["answer"]["ending"] == "operator"
    assert set(body["drill"]["answer"]["unsafe"]) >= {"jog", "reset"}

    body = start(client, "transfer-arm", "collision")
    # The right steps in the wrong order are not the recovery.
    body = respond(client, clock, body, ["clear", "hold", "record", "operator"])
    assert body["drill"]["result"]["recovery_correct"] is False
    body = start(client, "transfer-arm", "collision")
    body = respond(client, clock, body, ["hold", "clear", "record", "operator"])
    assert body["drill"]["result"]["passed"] is True
    assert body["summary"] == {
        "drills": 3,
        "passed": 1,
        "unsafe_actions": 1,
        "median_response_s": 2.0,
        "checkrides_passed": 0,
    }


def test_actions_are_checked_and_one_drill_is_open_at_a_time(client, clock):
    body = start(client)
    fire(clock, body["drill"])
    assert act(client, body, "jog", 422)["detail"] == "Choose one of the actions offered"
    stale = {**body, "version": body["version"] - 1}
    act(client, stale, "pause", 409)
    body = act(client, body, "pause")
    assert act(client, body, "pause", 422)["detail"] == "You have already done that"
    response = client.post(
        "/api/fault-drills/drills",
        json={"expected_version": body["version"], "instrument": "reader", "family": "door"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Finish the drill you have open first"
    response = client.post(
        "/api/fault-drills/drills",
        json={"expected_version": body["version"], "instrument": "reader", "family": "tips"},
    )
    assert response.status_code in (409, 422)


def test_a_drill_left_too_long_times_out_and_fails(client, clock):
    body = start(client, "reader", "door")
    fire(clock, body["drill"])
    body = act(client, body, "hands")
    clock.wait(fault_drills.LIMIT_SECONDS + 1)
    found = state(client)
    assert found["open"] is None
    drill = found["drills"][0]
    assert drill["status"] == "timed_out"
    assert drill["result"]["timed_out"] and not drill["result"]["passed"]
    assert act(client, body, "close", 409)["detail"] == "Time ran out for this drill"
    # The timeout is kept once the learner does anything else.
    start(client, "reader", "offline")
    assert state(client)["drills"][1]["status"] == "timed_out"


def test_drills_belong_to_their_learner(client, app, clock):
    body = start(client)
    fire(clock, body["drill"])
    with TestClient(app) as other:
        assert other.post("/api/auth/guest", json={"name": "Grace"}).status_code == 200
        assert state(other)["drills"] == []
        act(other, {**body, "version": 0}, "pause", 404)


def payload(envelope):
    raw = envelope["payload"]
    return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


def right_actions(drill):
    """The catalog answer for a drill, found by the symptom it shows once fired."""
    for family in fault_drills.instruments()[drill["instrument"]]["families"]:
        scenario = fault_drills.catalog_scenario(drill["instrument"], family)
        if scenario["symptom"] == drill["symptom"]:
            return [a["id"] for a in scenario["recovery"]] + [scenario["ending"]]
    raise AssertionError("no scenario matches")


def ride(client, clock, passing=True):
    found = state(client)
    response = client.post(
        "/api/fault-drills/checkrides", json={"expected_version": found["version"]}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    for index in range(fault_drills.CHECKRIDE_SIZE):
        if index:
            response = client.post(
                f"/api/fault-drills/checkrides/{body['checkride']['id']}/next",
                json={"expected_version": body["version"]},
            )
            assert response.status_code == 200, response.text
            body = response.json()
        assert body["drill"]["checkride_id"] == body["checkride"]["id"]
        fire(clock, body["drill"])
        actions = right_actions(state(client)["open"])
        if not passing and index == 1:
            actions = actions[1:]
        for action in actions:
            body = act(client, body, action)
        if index < fault_drills.CHECKRIDE_SIZE - 1:
            # Inside a checkride, nothing is revealed until it is over.
            assert "answer" not in body["drill"] and body["drill"]["title"] is None
    return body


def test_a_passed_checkride_is_signed_into_the_training_record(client, clock):
    body = ride(client, clock)
    done = body["checkrides"][0]
    assert done["status"] == "done" and done["passed"] is True
    assert len({d["title"] for d in done["drills"]}) == fault_drills.CHECKRIDE_SIZE
    assert all("answer" in d for d in body["drills"])

    finish(client)
    envelope = client.get("/api/cloudlab/qualifications/me").json()
    record = payload(envelope)
    entry = record["fault_drills"]
    assert entry["rules_version"] == fault_drills.RULES and entry["evidence"] == "synthetic"
    assert len(entry["drills"]) == fault_drills.CHECKRIDE_SIZE
    assert entry["source"] == "fault-drills/checkride" and entry["ref"] == done["id"]
    assert {d["criterion"] for d in entry["drills"]} <= {"recover", "escalate"}
    assert all(d["instrument_kind"] in fault_drills.instruments() for d in entry["drills"])
    assert all(d["recovery_correct"] and d["unsafe_actions"] == 0 for d in entry["drills"])
    check = client.post("/api/cloudlab/records/verify", json={"record": envelope}).json()
    assert check["authentic"] and check["record"]["fault_drills"] == entry
    # Editing the entry breaks the signature like any other edit.
    edited = {**record, "fault_drills": {**entry, "attempts": 0}}
    forged = {
        **envelope,
        "payload": base64.urlsafe_b64encode(json.dumps(edited).encode()).rstrip(b"=").decode(),
    }
    assert (
        client.post("/api/cloudlab/records/verify", json={"record": forged}).json()["authentic"]
        is False
    )


def test_a_failed_checkride_adds_nothing_to_the_record(client, clock):
    body = ride(client, clock, passing=False)
    assert body["checkrides"][0]["passed"] is False
    finish(client)
    record = payload(client.get("/api/cloudlab/qualifications/me").json())
    assert "fault_drills" not in record


def test_checkride_drills_differ_and_block_practice(client, clock):
    found = state(client)
    body = client.post(
        "/api/fault-drills/checkrides", json={"expected_version": found["version"]}
    ).json()
    response = client.post(
        "/api/fault-drills/drills",
        json={"expected_version": body["version"], "instrument": "reader", "family": "door"},
    )
    assert response.status_code == 409
    for _ in range(20):
        families = [p["family"] for p in fault_drills.picks()]
        assert len(set(families)) == fault_drills.CHECKRIDE_SIZE


@pytest.fixture
def operator(store, tmp_path):
    app = create_app(
        Settings(
            allow_demo=True,
            local_operator=True,
            secret="test-secret-that-is-at-least-32-characters",
            data_path=str(tmp_path / "unused.sqlite"),
        ),
        store=store,
    )
    with TestClient(app) as client:
        assert client.post("/api/auth/guest", json={"name": "Lin"}).status_code == 200
        yield client


INCIDENT = {
    "title": "Plate left on the reader tray",
    "instrument": "reader",
    "family": "other",
    "step": 2,
    "symptom": "The reader refuses the plate: its tray already holds one.",
    "recovery": ["Pause the run", "Take out the old plate and label it", "Close the tray"],
    "unsafe": ["Push the new plate in on top"],
    "ending": "resume",
    "why": "Nothing was read yet, so the run can carry on.",
}


def test_an_operator_turns_an_incident_into_a_lab_drill(client, operator, clock):
    url = "/api/fault-drills/labs/bench-2/incidents"
    denied = client.post(url, json={"expected_version": 0, **INCIDENT})
    assert denied.status_code == 403
    for broken in [
        {**INCIDENT, "step": 9},
        {**INCIDENT, "unsafe": ["Pause the run"]},
        {**INCIDENT, "instrument": "centrifuge"},
        {**INCIDENT, "recovery": []},
    ]:
        assert operator.post(url, json={"expected_version": 0, **broken}).status_code == 422
    assert operator.post("/api/fault-drills/labs/Bad Lab/incidents", json={}).status_code in (
        404,
        422,
    )
    made = operator.post(url, json={"expected_version": 0, **INCIDENT})
    assert made.status_code == 201, made.text
    assert operator.post(url, json={"expected_version": 0, **INCIDENT}).status_code == 409
    incident = made.json()["incidents"][0]
    assert incident["recovery"] == INCIDENT["recovery"] and "author" not in incident
    assert state(operator)["can_author"] is True and state(client)["can_author"] is False

    # Learners see the drill but not its answer, and can run it.
    listed = client.get(url).json()
    assert listed["can_author"] is False
    assert "recovery" not in listed["incidents"][0] and "ending" not in listed["incidents"][0]
    assert client.get("/api/fault-drills/labs/bench-3/incidents").json()["incidents"] == []
    found = state(client)
    body = client.post(
        "/api/fault-drills/drills",
        json={
            "expected_version": found["version"],
            "lab": "bench-2",
            "incident_id": incident["id"],
        },
    ).json()
    assert body["drill"]["source"] == "lab" and body["drill"]["fires_in_s"] == 1.5
    body = respond(client, clock, body, ["r1", "r2", "r3", "resume"])
    assert body["drill"]["result"]["passed"] is True
    assert body["drill"]["title"] == INCIDENT["title"]
    missing = client.post(
        "/api/fault-drills/drills",
        json={
            "expected_version": body["version"],
            "lab": "bench-3",
            "incident_id": incident["id"],
        },
    )
    assert missing.status_code == 404
