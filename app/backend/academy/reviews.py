"""Supervisor review: a facilitator replays a learner's twin session and comments on its steps.

A learner submits one of their sessions to a study group they belong to: a workflow run
in the teaching model, a find-the-fault exercise or an agent sandbox episode. The review
keeps a snapshot of that session as a replay timeline, so what the reviewer comments on
cannot change under them. Facilitators of the group pin comments to a step and a moment
of the timeline; the learner reads them, replies and resolves them.

Only facilitators of a group review, and only sessions of that group's members. A
session reaches a reviewer when its learner submitted it, or when the facilitator opens
it under the group's supervised policy, which covers members who joined after the policy
was set or who allowed it themselves. A member can always withdraw. The group keeps a
private pointer from a member id to its sign-in subject so a supervised session can be
read; it is never returned. Everything replayed here is synthetic.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException
from pydantic import Field

from . import agent_sandbox
from .auth import identify
from .fault_practice import CAUSES, ITEMS, FaultPractice
from .learning import present
from .mock_contract import PlanError, execute_mock
from .models import StrictModel
from .recipes import MIXING
from .store import Conflict, Write

MAX_REVIEWS = 200
MAX_COMMENTS = 100
MAX_ENTRIES = 120
MAX_SOURCES = 100
POLICY = "review-policy"
POINTER = "reviewee#"
PREFIX = "review#"
Kind = Literal["run", "practice", "agent"]


class Submit(StrictModel):
    kind: Kind
    source_id: UUID


class Revision(StrictModel):
    expected_version: int = Field(ge=0, strict=True)


class SetPolicy(Revision):
    policy: Literal["shared", "supervised"]


class Consent(Revision):
    allow: bool


class Post(StrictModel):
    version: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=1000)
    index: int | None = Field(default=None, ge=0, le=MAX_ENTRIES)
    t_s: float | None = Field(default=None, ge=0, le=86400)
    parent: UUID | None = None


class Resolve(StrictModel):
    version: int = Field(ge=1)
    resolved: bool


class Removal(StrictModel):
    version: int = Field(ge=1)


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def pointer_record(member_id, owner):
    """Written with a membership: which subject a member id stands for, kept server-side."""
    return {"version": 1, "member_id": member_id, "owner": owner, "joined_at": now(), "allow": None}


# Timelines ------------------------------------------------------------------------------


def _action_label(action):
    kind = action["kind"]
    if kind == "pickup":
        return "Pick up a tip"
    if kind == "drop":
        return "Drop the tip"
    if kind in ("aspirate", "dispense"):
        verb = "Aspirate" if kind == "aspirate" else "Dispense"
        where = "from" if kind == "aspirate" else "into"
        return f"{verb} {action.get('volume', 0):g} µL {where} {action.get('well')}"
    if kind == "move":
        return f"Move the plate to {action.get('to')}"
    if kind in ("heat", "shake"):
        unit = "°C" if kind == "heat" else "rpm"
        return f"{kind.capitalize()} at {action.get('value', 0):g} {unit}"
    return kind.capitalize()


def _compact_state(state):
    if not state:
        return None
    return {
        "wells": {k: round(w["volume"], 3) for k, w in state["wells"].items()},
        "tip": state["pipette"]["tip"],
        "tip_volume": round(state["pipette"]["volume"], 3),
    }


def run_timeline(session):
    """One entry per planned step; each run step lasts one second of the teaching clock."""
    events = {e["step"]: e for e in session["events"]}
    entries = []
    for number, action in enumerate(session["experiment"]["actions"][:MAX_ENTRIES], 1):
        event = events.get(number)
        entries.append(
            {
                "index": number - 1,
                "step": number,
                "label": _action_label(action),
                "outcome": (event["level"] if event else "not_run"),
                "detail": (event["message"] if event else "Not reached"),
                "hint": (event.get("hint") or "") if event else "",
                "start_s": float(number - 1),
                "end_s": float(number),
                "state": _compact_state(event.get("state")) if event else None,
            }
        )
    return entries


def run_summary(session):
    status = session["status"]
    assessment = session.get("assessment") or {}
    if status == "completed":
        return (
            "Completed; the teaching checks passed"
            if assessment.get("passed")
            else ("Completed; some teaching checks did not pass")
        )
    if status == "faulted":
        return f"Stopped at step {session['events'][-1]['step']}"
    return {"draft": "Not run yet", "running": "Running", "paused": "Paused"}.get(status, status)


def practice_timeline(record, session):
    """The prediction and diagnosis, then the workflow as it last ran."""
    cause = ITEMS[record["item"]][0]
    prediction = record["prediction"]
    lead = []
    if prediction:
        said = f"Stops at step {prediction['step']}" if prediction["stops"] else "Runs to the end"
        lead.append(
            {
                "label": "Prediction",
                "outcome": "success" if record["prediction_correct"] else "error",
                "detail": said + (" (made after running)" if prediction.get("after_run") else ""),
            }
        )
    if record["diagnosis"]:
        lead.append(
            {
                "label": "Named cause",
                "outcome": "success" if record["diagnosis"] == cause else "error",
                "detail": CAUSES[record["diagnosis"]],
            }
        )
    if record["attempts"]:
        lead.append(
            {
                "label": "Repair checks",
                "outcome": "success" if record["repaired"] else "error",
                "detail": f"{record['attempts']} "
                f"{'check' if record['attempts'] == 1 else 'checks'} · {record['last_check']}",
            }
        )
    entries = [
        {
            **entry,
            "index": i,
            "step": None,
            "hint": "",
            "start_s": float(i),
            "end_s": float(i + 1),
            "state": None,
        }
        for i, entry in enumerate(lead)
    ]
    offset = len(entries)
    for entry in run_timeline(session) if session else []:
        entries.append(
            {
                **entry,
                "index": entry["index"] + offset,
                "start_s": entry["start_s"] + offset,
                "end_s": entry["end_s"] + offset,
            }
        )
    return entries[:MAX_ENTRIES]


def agent_timeline(episode):
    """Every call the agent made, in order, timed on the mock contract's clock."""
    name = episode["scenario"]
    setup = len(agent_sandbox.setup_steps(name))
    try:
        trace = execute_mock(agent_sandbox.twins_of(name), episode["steps"])
    except PlanError:
        trace = []
    clock, accepted, entries = 0.0, 0, []
    for call in episode["calls"][:MAX_ENTRIES]:
        start = clock
        if call["ok"] and call["tool"] in agent_sandbox.OPERATIONS:
            found = trace[setup + accepted] if setup + accepted < len(trace) else None
            accepted += 1
            if found:
                clock = float(found["elapsed_s"])
        args = ", ".join(f"{k}={v}" for k, v in call["args"].items())
        outcome = "success" if call["ok"] else "error"
        if call["tool"] in agent_sandbox.RESTRICTED:
            outcome = "restricted"
        entries.append(
            {
                "index": len(entries),
                "step": call["n"],
                "label": f"{call['tool']}({args})"[:120],
                "outcome": outcome,
                "detail": call.get("message")
                or ("Escalated to an operator" if call["tool"] == "request_operator" else "Done"),
                "hint": call.get("layer") or "",
                "start_s": start,
                # Calls that change nothing still take a moment on the replay.
                "end_s": clock if clock > start else start + 0.5,
                "state": None,
            }
        )
        clock = entries[-1]["end_s"]
    return entries


def agent_summary(episode):
    score = agent_sandbox.score(episode)
    result = "as expected" if score["correct"] else "not what the scenario needed"
    return f"{episode['status'].capitalize()}, {result} · {score['refused']} refused"


class Sources:
    """A learner's reviewable sessions, read only from their own partition."""

    def __init__(self, store):
        self.store = store

    def practice_records(self, owner):
        return FaultPractice(self.store).records(owner)

    def episodes(self, owner):
        return (self.store.get(owner, agent_sandbox.KEY) or {"episodes": []})["episodes"]

    def listing(self, owner):
        found = []
        practice = self.practice_records(owner)
        linked = {r["session_id"] for r in practice}
        sessions = self.store.partition(owner, "session#", MAX_SOURCES)
        for session in sessions:
            if session["id"] in linked or session["experiment"]["course_id"] == MIXING:
                continue
            if not session["events"]:
                continue
            found.append(
                {
                    "kind": "run",
                    "id": session["id"],
                    "title": present(session)["experiment"]["title"],
                    "at": session["created_at"],
                    "summary": run_summary(session),
                }
            )
        for record in practice:
            if record["prediction"] is None:
                continue
            found.append(
                {
                    "kind": "practice",
                    "id": record["id"],
                    "title": f"Find the fault {record['item'] + 1}",
                    "at": record["created_at"],
                    "summary": "Repaired" if record["repaired"] else f"Phase: {record['phase']}",
                }
            )
        for episode in self.episodes(owner):
            if not episode["calls"]:
                continue
            title = agent_sandbox.SCENARIOS[episode["scenario"]]["title"]
            found.append(
                {
                    "kind": "agent",
                    "id": episode["id"],
                    "title": f"{episode.get('agent') or 'Agent'} · {title}",
                    "at": episode["created_at"],
                    "summary": agent_summary(episode),
                }
            )
        return sorted(found, key=lambda s: s["at"], reverse=True)

    def snapshot(self, owner, kind, source_id):
        source_id = str(source_id)
        if kind == "run":
            session = self.store.get(owner, f"session#{source_id}")
            if session is None or session["experiment"]["course_id"] == MIXING:
                raise HTTPException(404, "Session not found")
            if not session["events"]:
                raise HTTPException(409, "Run the workflow before asking for a review")
            return {
                "title": present(session)["experiment"]["title"],
                "instrument": session["experiment"].get("instrument", "flex"),
                "summary": run_summary(session),
                "timeline": run_timeline(session),
            }
        if kind == "practice":
            record = self.store.get(owner, f"practice#{source_id}")
            if record is None:
                raise HTTPException(404, "Session not found")
            if record["prediction"] is None:
                raise HTTPException(409, "Make the prediction before asking for a review")
            session = self.store.get(owner, f"session#{record['session_id']}")
            return {
                "title": f"Find the fault {record['item'] + 1}",
                "instrument": ITEMS[record["item"]][1],
                "summary": "Repaired" if record["repaired"] else f"Phase: {record['phase']}",
                "timeline": practice_timeline(record, session),
            }
        episode = next((e for e in self.episodes(owner) if e["id"] == source_id), None)
        if episode is None:
            raise HTTPException(404, "Session not found")
        if not episode["calls"]:
            raise HTTPException(409, "The agent has made no calls yet")
        return {
            "title": agent_sandbox.SCENARIOS[episode["scenario"]]["title"],
            "instrument": None,
            "agent": episode.get("agent"),
            "summary": agent_summary(episode),
            "timeline": agent_timeline(episode),
        }


# Routes ---------------------------------------------------------------------------------


def install(app, *, store):
    sources = Sources(store)

    def membership(owner, group_id):
        found = store.get(owner, f"membership#{group_id}")
        group = found and store.get(f"group#{group_id}", "group")
        member = group and next(
            (m for m in group["members"] if m["id"] == found["member_id"]), None
        )
        if not member:
            raise HTTPException(404, "Study group not found")
        return group, member

    def facilitator(owner, group_id):
        group, member = membership(owner, group_id)
        if member["role"] != "facilitator":
            raise HTTPException(403, "Only a facilitator of this group reviews sessions")
        return group, member

    def policy_of(group_id):
        return store.get(f"group#{group_id}", POLICY) or {
            "version": 0,
            "policy": "shared",
            "since": None,
        }

    def pointer(group_id, member_id):
        return store.get(f"group#{group_id}", f"{POINTER}{member_id}")

    def supervised(group_id, member_id, policy=None):
        """Whether the group's policy lets a facilitator open this member's sessions."""
        policy = policy or policy_of(group_id)
        found = pointer(group_id, member_id)
        if policy["policy"] != "supervised" or found is None or found["allow"] is False:
            return False
        return found["allow"] is True or found["joined_at"] > policy["since"]

    def reviews(group_id):
        return store.partition(f"group#{group_id}", PREFIX, MAX_REVIEWS)

    def get_review(group_id, review_id):
        review = store.get(f"group#{group_id}", f"{PREFIX}{review_id}")
        if review is None:
            raise HTTPException(404, "Review not found")
        return review

    def access(owner, group_id, review_id):
        """The caller's role on a review; anyone else learns nothing about it."""
        group, member = membership(owner, group_id)
        review = get_review(group_id, review_id)
        if member["role"] == "facilitator":
            return group, member, review, "reviewer"
        if review["member_id"] == member["id"]:
            return group, member, review, "learner"
        raise HTTPException(404, "Review not found")

    def summary(group, review):
        threads = [c for c in review["comments"] if c["parent"] is None]
        return {
            "group_id": group["id"],
            "group": group["name"],
            **{
                k: review[k]
                for k in (
                    "id",
                    "version",
                    "member_id",
                    "learner",
                    "kind",
                    "title",
                    "summary",
                    "submitted_at",
                    "via",
                )
            },
            "comments": len(review["comments"]),
            "open_threads": sum(c["resolved_at"] is None for c in threads),
        }

    def view(group, review, role):
        return {**review, "group_id": group["id"], "group": group["name"], "role": role}

    def create(group, member, owner, data: Submit, via):
        key = f"{PREFIX}{member['id']}_{data.kind}_{data.source_id}"
        existing = store.get(f"group#{group['id']}", key)
        if existing:
            return existing
        if len(reviews(group["id"])) >= MAX_REVIEWS:
            raise HTTPException(409, "This group has reached its review limit")
        snapshot = sources.snapshot(owner, data.kind, data.source_id)
        timeline = snapshot.pop("timeline")
        review = {
            "id": key.removeprefix(PREFIX),
            "version": 1,
            "member_id": member["id"],
            "learner": member["name"],
            "kind": data.kind,
            "source_id": str(data.source_id),
            **snapshot,
            "submitted_at": now(),
            "via": via,
            # A replay of the teaching model or mock contract, never of an instrument.
            "evidence": "synthetic",
            "timeline": timeline,
            "duration_s": timeline[-1]["end_s"] if timeline else 0.0,
            "comments": [],
        }
        try:
            store.put(f"group#{group['id']}", key, review, None)
        except Conflict:
            return store.get(f"group#{group['id']}", key)
        return review

    def save(group_id, review, expected):
        review["version"] = expected + 1
        store.put(f"group#{group_id}", f"{PREFIX}{review['id']}", review, expected)
        return review

    @app.get("/api/reviews")
    def overview(owner: str = Depends(identify)):
        groups, mine, queue = [], [], []
        for found in store.partition(owner, "membership#", 20):
            group = store.get(f"group#{found['group_id']}", "group")
            member = group and next(
                (m for m in group["members"] if m["id"] == found["member_id"]), None
            )
            if not member:
                continue
            policy = policy_of(group["id"])
            mark = pointer(group["id"], member["id"])
            groups.append(
                {
                    "id": group["id"],
                    "name": group["name"],
                    "role": member["role"],
                    "policy": policy["policy"],
                    "policy_version": policy["version"],
                    "consent_version": mark["version"] if mark else 0,
                    "allow": mark["allow"] if mark else None,
                    "supervised": supervised(group["id"], member["id"], policy),
                }
            )
            for review in reviews(group["id"]):
                if review["member_id"] == member["id"]:
                    mine.append(summary(group, review))
                elif member["role"] == "facilitator":
                    queue.append(summary(group, review))
        newest = sorted(mine, key=lambda r: r["submitted_at"], reverse=True)
        return {
            "groups": groups,
            "mine": newest,
            "to_review": sorted(queue, key=lambda r: r["submitted_at"], reverse=True),
            "evidence": "synthetic",
        }

    @app.get("/api/reviews/sessions")
    def my_sessions(owner: str = Depends(identify)):
        return {"sessions": sources.listing(owner), "evidence": "synthetic"}

    @app.post("/api/reviews/groups/{group_id}", status_code=201)
    def submit(group_id: UUID, data: Submit, owner: str = Depends(identify)):
        group, member = membership(owner, group_id)
        review = create(group, member, owner, data, "shared")
        return view(group, review, "learner")

    @app.post("/api/reviews/groups/{group_id}/policy")
    def set_policy(group_id: UUID, data: SetPolicy, owner: str = Depends(identify)):
        facilitator(owner, group_id)
        current = policy_of(group_id)
        if current["version"] != data.expected_version:
            raise Conflict
        changed = {
            "version": current["version"] + 1,
            "policy": data.policy,
            # Members who joined before a supervised policy keep their sessions to
            # themselves until they allow it.
            "since": now() if data.policy == "supervised" else None,
        }
        store.put(f"group#{group_id}", POLICY, changed, current["version"] or None)
        return changed

    @app.post("/api/reviews/groups/{group_id}/consent")
    def consent(group_id: UUID, data: Consent, owner: str = Depends(identify)):
        _, member = membership(owner, group_id)
        found = pointer(group_id, member["id"])
        if (found["version"] if found else 0) != data.expected_version:
            raise Conflict
        changed = {
            **(found or pointer_record(member["id"], owner)),
            "version": data.expected_version + 1,
            "allow": data.allow,
        }
        store.put(
            f"group#{group_id}", f"{POINTER}{member['id']}", changed, data.expected_version or None
        )
        return {
            "version": changed["version"],
            "allow": changed["allow"],
            "supervised": supervised(group_id, member["id"]),
        }

    @app.get("/api/reviews/groups/{group_id}/members")
    def members(group_id: UUID, owner: str = Depends(identify)):
        group, _ = facilitator(owner, group_id)
        policy = policy_of(group_id)
        return {
            "policy": policy["policy"],
            "members": [
                {
                    "id": m["id"],
                    "name": m["name"],
                    "role": m["role"],
                    "supervised": supervised(group_id, m["id"], policy),
                }
                for m in group["members"]
            ],
        }

    def supervised_owner(owner, group_id, member_id):
        group, _ = facilitator(owner, group_id)
        learner = next((m for m in group["members"] if m["id"] == str(member_id)), None)
        if learner is None or not supervised(group_id, learner["id"]):
            raise HTTPException(
                403,
                "This member has not shared that session and the group policy does not cover it",
            )
        return group, learner, pointer(group_id, learner["id"])["owner"]

    @app.get("/api/reviews/groups/{group_id}/members/{member_id}/sessions")
    def member_sessions(group_id: UUID, member_id: UUID, owner: str = Depends(identify)):
        _, _, subject = supervised_owner(owner, group_id, member_id)
        return {"sessions": sources.listing(subject), "evidence": "synthetic"}

    @app.post("/api/reviews/groups/{group_id}/members/{member_id}", status_code=201)
    def open_supervised(
        group_id: UUID, member_id: UUID, data: Submit, owner: str = Depends(identify)
    ):
        group, learner, subject = supervised_owner(owner, group_id, member_id)
        review = create(group, learner, subject, data, "policy")
        return view(group, review, "reviewer")

    @app.get("/api/reviews/groups/{group_id}/items/{review_id}")
    def review_detail(group_id: UUID, review_id: str, owner: str = Depends(identify)):
        group, _, review, role = access(owner, group_id, review_id)
        return view(group, review, role)

    @app.post("/api/reviews/groups/{group_id}/items/{review_id}/comments")
    def post(group_id: UUID, review_id: str, data: Post, owner: str = Depends(identify)):
        group, member, review, role = access(owner, group_id, review_id)
        if review["version"] != data.version:
            raise Conflict
        if len(review["comments"]) >= MAX_COMMENTS:
            raise HTTPException(409, "This review is full")
        parent = None
        if data.parent:
            parent = next((c for c in review["comments"] if c["id"] == str(data.parent)), None)
            if parent is None or parent["parent"] is not None:
                raise HTTPException(422, "Reply to a comment of this review")
        elif role != "reviewer":
            raise HTTPException(403, "Reply to your reviewer's comments")
        index, t_s = (parent["index"], parent["t_s"]) if parent else (data.index, data.t_s)
        if index is not None:
            if index >= len(review["timeline"]):
                raise HTTPException(422, "Pin the comment to a step of this replay")
            entry = review["timeline"][index]
            if t_s is not None and not entry["start_s"] <= t_s <= entry["end_s"]:
                raise HTTPException(422, "That moment is outside the step")
        elif t_s is not None:
            raise HTTPException(422, "Pin a moment to a step")
        review["comments"].append(
            {
                "id": str(uuid4()),
                "member_id": member["id"],
                "author": member["name"],
                "role": role,
                "text": data.text.strip(),
                "index": index,
                "t_s": t_s if t_s is None else round(t_s, 2),
                "parent": parent["id"] if parent else None,
                "at": now(),
                "resolved_at": None,
                "resolved_by": None,
            }
        )
        return view(group, save(group_id, review, data.version), role)

    @app.post("/api/reviews/groups/{group_id}/items/{review_id}/comments/{comment_id}/resolve")
    def resolve(
        group_id: UUID,
        review_id: str,
        comment_id: UUID,
        data: Resolve,
        owner: str = Depends(identify),
    ):
        group, member, review, role = access(owner, group_id, review_id)
        if review["version"] != data.version:
            raise Conflict
        thread = next((c for c in review["comments"] if c["id"] == str(comment_id)), None)
        if thread is None or thread["parent"] is not None:
            raise HTTPException(404, "Comment not found")
        thread.update(
            resolved_at=now() if data.resolved else None,
            resolved_by=member["name"] if data.resolved else None,
        )
        return view(group, save(group_id, review, data.version), role)

    @app.post("/api/reviews/groups/{group_id}/items/{review_id}/remove")
    def remove(group_id: UUID, review_id: str, data: Removal, owner: str = Depends(identify)):
        _, _, review, _ = access(owner, group_id, review_id)
        store.transact([Write(f"group#{group_id}", f"{PREFIX}{review['id']}", None, data.version)])
        return {"removed": review["id"]}
