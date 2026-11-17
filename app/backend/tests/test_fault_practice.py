"""Find-the-fault practice: predict, name the cause, repair; the answer stays hidden until then."""

from academy.fault_practice import CAUSES, ITEMS, _plan, outcome


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
