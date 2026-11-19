"""Supervisor review: a facilitator comments on a learner's replay; the learner replies."""

import time

from fastapi.testclient import TestClient


def person(app, name):
    client = TestClient(app)
    assert client.post("/api/auth/guest", json={"name": name}).status_code == 200
    profile = {"name": name, "experience": "new", "onboarded": True}
    assert client.put("/api/me", json=profile).status_code == 200
    return client


def ran(client, title="Dilution"):
    session = client.post("/api/sessions", json={"title": title}).json()
    path = f"/api/sessions/{session['id']}"
    session = client.post(f"{path}/start", json={"version": session["version"]}).json()
    while session["status"] == "running":
        session = client.post(f"{path}/advance", json={"version": session["version"]}).json()
    return session


def group_of(facilitator, *members):
    group = facilitator.post("/api/groups", json={"name": "Bench club"}).json()
    for member in members:
        assert member.post("/api/groups/join", json={"code": group["code"]}).status_code == 200
    return group


def test_a_reviewer_pins_comments_and_the_learner_replies_and_resolves(app):
    ada, grace = person(app, "Ada"), person(app, "Grace")
    group = group_of(ada, grace)
    session = ran(grace)

    listed = grace.get("/api/reviews/sessions").json()["sessions"]
    assert {"kind": "run", "id": session["id"]}.items() <= listed[0].items()
    submitted = grace.post(
        f"/api/reviews/groups/{group['id']}", json={"kind": "run", "source_id": session["id"]}
    )
    assert submitted.status_code == 201, submitted.text
    review = submitted.json()
    assert review["evidence"] == "synthetic" and review["via"] == "shared"
    assert len(review["timeline"]) == len(session["experiment"]["actions"])
    assert review["timeline"][1]["start_s"] == 1.0 and review["duration_s"] > 0
    # Submitting again keeps the one review.
    again = grace.post(
        f"/api/reviews/groups/{group['id']}", json={"kind": "run", "source_id": session["id"]}
    ).json()
    assert again["id"] == review["id"]

    queue = ada.get("/api/reviews").json()
    assert [r["id"] for r in queue["to_review"]] == [review["id"]] and queue["mine"] == []
    path = f"/api/reviews/groups/{group['id']}/items/{review['id']}"
    pinned = ada.post(
        f"{path}/comments",
        json={"version": review["version"], "text": "Why a new tip here?", "index": 1, "t_s": 1.5},
    )
    assert pinned.status_code == 200, pinned.text
    pinned = pinned.json()
    thread = pinned["comments"][0]
    assert thread["role"] == "reviewer" and thread["index"] == 1 and thread["t_s"] == 1.5

    # The learner sees it, on its step, with an open thread.
    mine = grace.get("/api/reviews").json()["mine"]
    assert mine[0]["open_threads"] == 1
    seen = grace.get(path).json()
    assert seen["role"] == "learner" and seen["comments"][0]["text"] == "Why a new tip here?"

    # A stale version is rejected, for a reply and for resolving.
    stale = grace.post(
        f"{path}/comments",
        json={"version": review["version"], "text": "Late", "parent": thread["id"]},
    )
    assert stale.status_code == 409
    replied = grace.post(
        f"{path}/comments",
        json={"version": seen["version"], "text": "To avoid carry-over", "parent": thread["id"]},
    ).json()
    reply = replied["comments"][1]
    assert reply["parent"] == thread["id"] and reply["index"] == 1 and reply["role"] == "learner"
    assert (
        grace.post(
            f"{path}/comments/{thread['id']}/resolve",
            json={"version": seen["version"], "resolved": True},
        ).status_code
        == 409
    )
    resolved = grace.post(
        f"{path}/comments/{thread['id']}/resolve",
        json={"version": replied["version"], "resolved": True},
    ).json()
    assert resolved["comments"][0]["resolved_by"] == "Grace"
    assert grace.get("/api/reviews").json()["mine"][0]["open_threads"] == 0

    # A learner replies rather than opening threads; pins stay on the replay.
    assert (
        grace.post(f"{path}/comments", json={"version": resolved["version"], "text": "Hi"})
    ).status_code == 403
    assert (
        ada.post(
            f"{path}/comments",
            json={"version": resolved["version"], "text": "x", "index": 99},
        ).status_code
        == 422
    )
    assert (
        ada.post(
            f"{path}/comments",
            json={"version": resolved["version"], "text": "x", "index": 1, "t_s": 7},
        ).status_code
        == 422
    )
    # No sign-in subject leaves the server.
    assert "owner" not in str(seen) and "owner" not in str(ada.get("/api/reviews").json())


def test_only_facilitators_of_the_group_review(app):
    ada, grace, alan, mallory = (person(app, n) for n in ("Ada", "Grace", "Alan", "Mallory"))
    group = group_of(ada, grace, alan)
    other = mallory.post("/api/groups", json={"name": "Elsewhere"}).json()
    assert other["you"]["role"] == "facilitator"
    session = ran(grace)
    review = grace.post(
        f"/api/reviews/groups/{group['id']}", json={"kind": "run", "source_id": session["id"]}
    ).json()
    path = f"/api/reviews/groups/{group['id']}/items/{review['id']}"
    comment = {"version": review["version"], "text": "Looks fine", "index": 0}

    # A facilitator of another group is refused, and learns nothing about the review.
    assert mallory.get(path).status_code == 404
    assert mallory.post(f"{path}/comments", json=comment).status_code == 404
    assert mallory.get(f"/api/reviews/groups/{group['id']}/members").status_code == 404
    assert mallory.get("/api/reviews").json()["to_review"] == []
    # A member who is not a facilitator sees only their own reviews.
    assert alan.get(path).status_code == 404
    assert alan.get("/api/reviews").json()["to_review"] == []
    assert alan.get(f"/api/reviews/groups/{group['id']}/members").status_code == 403
    # Nobody submits someone else's session.
    assert (
        alan.post(
            f"/api/reviews/groups/{group['id']}",
            json={"kind": "run", "source_id": session["id"]},
        ).status_code
        == 404
    )
    assert ada.post(f"{path}/comments", json=comment).status_code == 200


def test_a_supervised_policy_covers_members_who_joined_under_it_or_allowed_it(app):
    ada, grace, alan = person(app, "Ada"), person(app, "Grace"), person(app, "Alan")
    group = group_of(ada, grace)
    members = f"/api/reviews/groups/{group['id']}/members"
    grace_id = next(m["id"] for m in ada.get(members).json()["members"] if m["name"] == "Grace")
    session = ran(grace)
    sessions = f"{members}/{grace_id}/sessions"

    # Without a supervised policy, only what Grace shares reaches the reviewer.
    assert ada.get(sessions).status_code == 403
    policy = f"/api/reviews/groups/{group['id']}/policy"
    assert (
        grace.post(policy, json={"expected_version": 0, "policy": "supervised"}).status_code == 403
    )
    set_policy = ada.post(policy, json={"expected_version": 0, "policy": "supervised"})
    assert set_policy.status_code == 200 and set_policy.json()["version"] == 1
    assert ada.post(policy, json={"expected_version": 0, "policy": "shared"}).status_code == 409
    # Grace joined before the policy, so it does not cover her until she allows it.
    assert ada.get(sessions).status_code == 403
    time.sleep(1.1)  # joined strictly after the policy was set
    assert alan.post("/api/groups/join", json={"code": group["code"]}).status_code == 200
    alan_id = next(m["id"] for m in ada.get(members).json()["members"] if m["name"] == "Alan")
    ran(alan, "Alan's run")
    assert ada.get(f"{members}/{alan_id}/sessions").status_code == 200

    consent = f"/api/reviews/groups/{group['id']}/consent"
    allowed = grace.post(consent, json={"expected_version": 1, "allow": True})
    assert allowed.status_code == 200 and allowed.json()["supervised"] is True
    found = ada.get(sessions).json()["sessions"]
    assert [s["id"] for s in found] == [session["id"]]
    opened = ada.post(f"{members}/{grace_id}", json={"kind": "run", "source_id": session["id"]})
    assert opened.status_code == 201 and opened.json()["via"] == "policy"
    assert grace.get("/api/reviews").json()["mine"][0]["via"] == "policy"

    # Withdrawing stops new supervised reviews; a stale consent is rejected.
    assert grace.post(consent, json={"expected_version": 1, "allow": False}).status_code == 409
    assert grace.post(consent, json={"expected_version": 2, "allow": False}).status_code == 200
    assert ada.get(sessions).status_code == 403
    assert (
        alan.post(f"{members}/{grace_id}", json={"kind": "run", "source_id": session["id"]})
    ).status_code == 403


def test_fault_practice_and_agent_episodes_replay_step_by_step(app):
    ada, grace = person(app, "Ada"), person(app, "Grace")
    group = group_of(ada, grace)
    exercise = grace.post("/api/practice").json()
    grace.put(
        f"/api/practice/{exercise['id']}/prediction",
        json={"version": exercise["version"], "stops": True, "step": 1},
    )
    practice = grace.post(
        f"/api/reviews/groups/{group['id']}",
        json={"kind": "practice", "source_id": exercise["id"]},
    ).json()
    assert practice["timeline"][0]["label"] == "Prediction"
    assert practice["timeline"][0]["outcome"] == "success"

    version = grace.get("/api/node/v1/sandbox/episodes").json()["version"]
    opened = grace.post(
        "/api/node/v1/sandbox/episodes",
        json={"expected_version": version, "scenario": "too-hot", "agent": "planner-2"},
    ).json()
    episode, version = opened["episode"], opened["version"]
    assert episode["agent"] == "planner-2"
    for tool, args in [
        ("load", {"device": "incubator", "volume_ul": 200}),
        ("heat", {"device": "incubator", "celsius": 80}),
        ("override_limit", {}),
        ("request_operator", {"reason": "Above the incubator's limit"}),
    ]:
        version = grace.post(
            f"/api/node/v1/sandbox/episodes/{episode['id']}/calls",
            json={"expected_version": version, "tool": tool, "args": args},
        ).json()["version"]
    review = grace.post(
        f"/api/reviews/groups/{group['id']}", json={"kind": "agent", "source_id": episode["id"]}
    ).json()
    outcomes = [e["outcome"] for e in review["timeline"]]
    assert outcomes == ["success", "error", "restricted", "success"]
    assert review["timeline"][1]["hint"] == "constraint" and review["agent"] == "planner-2"
    assert all(e["end_s"] > e["start_s"] for e in review["timeline"])
