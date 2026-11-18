"""Find-the-fault practice: predict, name the cause, repair; the answer stays hidden until then."""

from academy.fault_practice import CAUSES, ITEMS, _plan, outcome
from academy.teaching import control, execute_step, new_session

# The model's own name for a cause, where it differs; tip_left fails an end check instead.
CODES = {"source_short": "source_empty", "dispense_more": "insufficient_liquid"}


def start(client):
    response = client.post("/api/practice")
    assert response.status_code == 201, response.text
    return response.json()


def save(client, exercise, **changes):
    session = client.get(f"/api/sessions/{exercise['session_id']}").json()
    response = client.put(
        f"/api/sessions/{session['id']}",
        json={"version": session["version"], "experiment": {**session["experiment"], **changes}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_every_item_fails_for_its_own_reason_and_its_original_works():
    assert len({item[0] for item in ITEMS}) == len(ITEMS) and {i[0] for i in ITEMS} <= set(CAUSES)
    for index in range(len(ITEMS)):
        faulty, correct = outcome(_plan(index)), outcome(_plan(index, faulty=False))
        assert not faulty["passed"], index
        assert correct["passed"] and not correct["stops"], index


def test_an_exercise_hides_its_answer_until_the_cause_is_named(client):
    exercise = start(client)
    assert exercise["phase"] == "predict" and exercise["number"] == 1
    assert "answer" not in exercise and "prediction_correct" not in exercise
    assert len(exercise["choices"]) == 4 and "no_tip" in {c["cause"] for c in exercise["choices"]}
    # The workflow to inspect is an ordinary Studio design the learner owns.
    session = client.get(f"/api/sessions/{exercise['session_id']}").json()
    assert session["experiment"]["course_id"] == "workflow-sandbox" and session["status"] == "draft"
    assert [a["kind"] for a in session["experiment"]["actions"]] == ["aspirate", "dispense", "drop"]
    # Another exercise waits until this one is finished.
    assert client.post("/api/practice").status_code == 409
    # Order is enforced: cause before prediction, repair before cause.
    body = {"version": exercise["version"]}
    assert (
        client.put(
            f"/api/practice/{exercise['id']}/diagnosis", json={**body, "cause": "no_tip"}
        ).status_code
        == 409
    )
    assert client.post(f"/api/practice/{exercise['id']}/repair", json=body).status_code == 409

    predicted = client.put(
        f"/api/practice/{exercise['id']}/prediction", json={**body, "stops": True, "step": 1}
    ).json()
    assert predicted["phase"] == "diagnose" and "answer" not in predicted
    stale = client.put(
        f"/api/practice/{exercise['id']}/diagnosis", json={**body, "cause": "no_tip"}
    )
    assert stale.status_code == 409
    named = client.put(
        f"/api/practice/{exercise['id']}/diagnosis",
        json={"version": predicted["version"], "cause": "no_tip"},
    ).json()
    assert named["phase"] == "repair"
    assert named["answer"] == {
        "cause": "no_tip",
        "text": CAUSES["no_tip"],
        "stops": True,
        "step": 1,
    }
    assert named["prediction_correct"] is True and named["diagnosis_correct"] is True

    # Checking before anything is changed: still broken, and the try is counted.
    checked = client.post(
        f"/api/practice/{exercise['id']}/repair", json={"version": named["version"]}
    ).json()
    assert (checked["repaired"], checked["attempts"]) == (False, 1)
    assert "still stops at step 1" in checked["last_check"]
    # A repair that runs but does something else is not accepted.
    save(client, exercise, actions=[{"kind": "pickup"}, {"kind": "drop"}])
    wrong = client.post(
        f"/api/practice/{exercise['id']}/repair", json={"version": checked["version"]}
    ).json()
    assert not wrong["repaired"] and "no longer does what it was meant to" in wrong["last_check"]
    session = client.get(f"/api/sessions/{exercise['session_id']}").json()
    save(
        client,
        exercise,
        actions=[
            {"kind": "pickup"},
            {"kind": "aspirate", "well": "stock", "volume": 100},
            {"kind": "dispense", "well": "A1", "volume": 100},
            {"kind": "drop"},
        ],
    )
    done = client.post(
        f"/api/practice/{exercise['id']}/repair", json={"version": wrong["version"]}
    ).json()
    assert (done["repaired"], done["attempts"], done["phase"]) == (True, 3, "done")
    summary = client.get("/api/practice").json()
    assert summary["evidence"] == "synthetic" and summary["total"] == len(ITEMS)
    assert summary["summary"] == {
        "answered": 1,
        "predicted": 1,
        "predicted_of": 1,
        "diagnosed": 1,
        "repaired": 1,
        "first_try": 0,
    }
    # The next exercise is the next item.
    assert start(client)["number"] == 2
    assert session["id"] == exercise["session_id"]


def test_a_prediction_made_after_running_is_kept_but_not_counted(client):
    exercise = start(client)
    session = client.get(f"/api/sessions/{exercise['session_id']}").json()
    ran = client.post(f"/api/sessions/{session['id']}/start", json={"version": session["version"]})
    assert ran.status_code == 200, ran.text
    late = client.put(
        f"/api/practice/{exercise['id']}/prediction",
        json={"version": exercise["version"], "stops": True, "step": 1},
    ).json()
    assert late["prediction"]["after_run"] is True
    wrong = client.put(
        f"/api/practice/{exercise['id']}/diagnosis",
        json={"version": late["version"], "cause": late["choices"][0]["cause"]},
    ).json()
    assert wrong["prediction_correct"] is False
    assert wrong["diagnosis_correct"] == (late["choices"][0]["cause"] == "no_tip")


def test_exercises_belong_to_their_learner(client, app):
    from fastapi.testclient import TestClient

    exercise = start(client)
    with TestClient(app) as other:
        assert other.post("/api/auth/guest", json={"name": "Grace"}).status_code == 200
        assert other.get("/api/practice").json()["exercises"] == []
        answer = other.put(
            f"/api/practice/{exercise['id']}/prediction",
            json={"version": 1, "stops": False},
        )
        assert answer.status_code == 404


def run(index):
    session = control(new_session(_plan(index)), "start")
    while session["status"] == "running":
        session = execute_step(session)
    return session


def test_each_item_faults_for_the_cause_it_teaches():
    for index, (cause, *_) in enumerate(ITEMS):
        session = run(index)
        if cause == "tip_left":
            failed = [c for c in session["assessment"]["checks"] if not c["passed"]]
            assert session["status"] == "completed" and "tip discarded" in failed[0]["label"]
        else:
            assert session["status"] == "faulted", cause
            assert session["events"][-1]["code"] == CODES.get(cause, cause), cause


def finish_to_repair(client):
    exercise = start(client)
    body = {"version": exercise["version"]}
    predicted = client.put(
        f"/api/practice/{exercise['id']}/prediction", json={**body, "stops": True, "step": 1}
    ).json()
    return client.put(
        f"/api/practice/{exercise['id']}/diagnosis",
        json={"version": predicted["version"], "cause": predicted["choices"][0]["cause"]},
    ).json()


def advance_to(client, number):
    """Finish exercises with their correct plans until the given item is open."""
    while True:
        exercise = finish_to_repair(client)
        if exercise["number"] == number:
            return exercise
        save(client, exercise, **_plan(exercise["number"] - 1, faulty=False).model_dump())
        done = client.post(
            f"/api/practice/{exercise['id']}/repair", json={"version": exercise["version"]}
        ).json()
        assert done["repaired"], done["last_check"]


def test_dropping_the_failing_module_step_is_not_a_repair(client):
    # Item 10 asks the heater for 20 °C; deleting the heat step makes the run pass.
    exercise = advance_to(client, 10)
    plan = _plan(9).model_dump()
    plan["actions"] = [a for a in plan["actions"] if a["kind"] != "heat"]
    save(client, exercise, **plan)
    checked = client.post(
        f"/api/practice/{exercise['id']}/repair", json={"version": exercise["version"]}
    ).json()
    assert (
        not checked["repaired"] and "no longer does what it was meant to" in checked["last_check"]
    )
    save(client, exercise, **_plan(9, faulty=False).model_dump())
    fixed = client.post(
        f"/api/practice/{exercise['id']}/repair", json={"version": checked["version"]}
    ).json()
    assert fixed["repaired"]


def test_emptying_extra_stock_is_not_a_repair(client):
    exercise = advance_to(client, 1)
    wasteful = _plan(0, faulty=False).model_dump()
    wasteful["actions"] = [
        {"kind": "pickup"},
        {"kind": "aspirate", "well": "stock", "volume": 200},
        {"kind": "dispense", "well": "A1", "volume": 100},
        {"kind": "drop"},
    ]
    save(client, exercise, **wasteful)
    checked = client.post(
        f"/api/practice/{exercise['id']}/repair", json={"version": exercise["version"]}
    ).json()
    assert not checked["repaired"]


def test_a_late_prediction_leaves_the_score_on_both_sides(client):
    exercise = start(client)
    session = client.get(f"/api/sessions/{exercise['session_id']}").json()
    client.post(f"/api/sessions/{session['id']}/start", json={"version": session["version"]})
    late = client.put(
        f"/api/practice/{exercise['id']}/prediction",
        json={"version": exercise["version"], "stops": True, "step": 1},
    ).json()
    client.put(
        f"/api/practice/{exercise['id']}/diagnosis",
        json={"version": late["version"], "cause": late["choices"][0]["cause"]},
    )
    summary = client.get("/api/practice").json()["summary"]
    assert (summary["answered"], summary["predicted"], summary["predicted_of"]) == (1, 0, 0)


def test_every_step_of_an_exercise_belongs_to_its_learner(client, app):
    from fastapi.testclient import TestClient

    exercise = finish_to_repair(client)
    with TestClient(app) as other:
        assert other.post("/api/auth/guest", json={"name": "Grace"}).status_code == 200
        version = {"version": exercise["version"]}
        assert (
            other.put(
                f"/api/practice/{exercise['id']}/diagnosis", json={**version, "cause": "no_tip"}
            ).status_code
            == 404
        )
        assert other.post(f"/api/practice/{exercise['id']}/repair", json=version).status_code == 404
        assert other.get(f"/api/sessions/{exercise['session_id']}").status_code == 404


def test_only_one_exercise_opens_even_when_starts_race(client, app, monkeypatch):
    import pytest
    from academy.store import Conflict

    practice = app.state.practice
    first = start(client)
    (owner,) = [
        o for o in _owners(practice.store) if practice.store.get(o, f"practice#{first['id']}")
    ]
    # A second start that read before the first was saved sees nothing open.
    monkeypatch.setattr(practice, "records", lambda _owner: [])
    stale_get = practice.store.get
    monkeypatch.setattr(
        practice.store,
        "get",
        lambda o, key: None if key == "practice-open" else stale_get(o, key),
    )
    with pytest.raises(Conflict):
        practice.start(owner)


def _owners(store):
    if hasattr(store, "path"):
        import sqlite3

        with sqlite3.connect(store.path) as db:
            return [row[0] for row in db.execute("SELECT DISTINCT owner FROM records")]
    return list({item["pk"] for item in store.table.scan()["Items"]})
