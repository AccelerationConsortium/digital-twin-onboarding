"""One licence for people and agents: a signed qualification per instrument kind.

Each instrument kind lists the criteria a holder has to pass, and the criteria are the
same whether the holder is a person or an AI agent. Assessments that already exist count
toward them: the cloud lab training tasks, the find-the-fault exercises and the agent
sandbox scenarios. Any of them can be passed by either kind of holder; a sandbox episode
opened for a named agent counts for that agent, everything else for the signed-in
person. Other modules record a pass with `record_pass`.

A complete qualification is signed exactly like a training record (same Ed25519 key and
envelope) under its own versioned type, and `cloudlab_training.verify` checks both, so a
portal holding only the published key can tell whether this person or agent is cleared
for an instrument kind. Like the training record it is evidence, never permission, and
everything behind it is synthetic.
"""

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import Field

from . import agent_sandbox, cloudlab_training
from .agent_sandbox import AGENT_NAME
from .auth import identify
from .fault_practice import FaultPractice
from .models import StrictModel
from .store import Conflict

TYPE = "academy.qualification/1"
LEDGER = "qualification-ledger"
VALID_DAYS = cloudlab_training.VALID_DAYS
CRITERIA = {
    "operate": "Runs a workflow on the twin to its goal",
    "recover": "Meets an injected fault and still reaches the goal",
    "escalate": "Stops and asks an operator when a limit cannot be met",
}
KINDS = {
    "liquid-handler": {
        "title": "Liquid handler",
        "criteria_version": "academy-qualification/liquid-handler/1",
        "criteria": ["operate", "recover", "escalate"],
    },
    "incubator": {
        "title": "Incubator",
        "criteria_version": "academy-qualification/incubator/1",
        "criteria": ["operate", "escalate"],
    },
    "plate-reader": {
        "title": "Plate reader",
        "criteria_version": "academy-qualification/plate-reader/1",
        "criteria": ["operate", "recover"],
    },
}
# Which existing assessment counts toward which criterion.
CLOUDLAB = {
    "own": [("liquid-handler", "operate")],
    "fault": [("liquid-handler", "recover")],
    "escalate": [("liquid-handler", "escalate")],
}
SANDBOX = {
    "warm-read": [("incubator", "operate"), ("plate-reader", "operate")],
    "occupied-reader": [("plate-reader", "recover")],
    "last-tip": [("liquid-handler", "escalate")],
    "too-hot": [("incubator", "escalate")],
}
STATEMENT = (
    "Qualification evidence from synthetic exercises on digital twins. It does not "
    "authorize use of any instrument; the lab's own safety review and access policy decide that."
)
Instrument = Literal["liquid-handler", "incubator", "plate-reader"]


def holder_key(agent=None):
    return f"agent:{agent.strip().lower()}" if agent else "person"


def holder_subject(owner, agent=None):
    """A pseudonym per holder; a person's matches the one on their training record."""
    if not agent:
        return cloudlab_training.subject(owner)
    seed = f"academy-agent-subject:{owner}:{agent.strip().lower()}"
    return hashlib.sha256(seed.encode()).hexdigest()[:24]


def _check(instrument, criterion):
    if instrument not in KINDS or criterion not in KINDS[instrument]["criteria"]:
        raise ValueError(f"{instrument} has no criterion {criterion}")


def _newer(found, entry):
    return found is None or entry["passed_at"] > found["passed_at"]


def record_pass(
    store, owner, *, instrument, criterion, source, ref=None, agent=None, passed_at=None
):
    """Record that a holder passed one criterion; the call other assessments make.

    `owner` is the signed-in subject the assessment ran under, and `agent` names the
    agent it ran for, if any. Atomic and safe to repeat: only a later pass replaces one.
    """
    _check(instrument, criterion)
    if agent is not None and not re.match(AGENT_NAME, agent):
        raise ValueError("Agent names use letters, digits, spaces, dots, dashes and underscores")
    entry = {
        "passed_at": passed_at or datetime.now(UTC).isoformat(timespec="seconds"),
        "source": str(source)[:60],
        "ref": None if ref is None else str(ref)[:80],
        "criteria_version": KINDS[instrument]["criteria_version"],
    }
    for _ in range(4):
        ledger = store.get(owner, LEDGER) or {"version": 0, "holders": {}}
        holder = ledger["holders"].setdefault(
            holder_key(agent), {"agent": agent.strip() if agent else None, "passes": {}}
        )
        kind = holder["passes"].setdefault(instrument, {})
        if not _newer(kind.get(criterion), entry):
            return kind[criterion]
        kind[criterion] = entry
        expected = ledger["version"]
        ledger["version"] = expected + 1
        try:
            store.put(owner, LEDGER, ledger, expected or None)
        except Conflict:
            continue
        return entry
    raise Conflict


def derived(store, owner):
    """Passes read from the owner's own assessments: {holder: (agent, [(kind, crit, entry)])}."""
    found = {"person": (None, [])}

    def add(agent, kind, criterion, source, ref, at):
        key = holder_key(agent)
        found.setdefault(key, (agent, []))[1].append(
            (
                kind,
                criterion,
                {
                    "passed_at": at,
                    "source": source,
                    "ref": ref,
                    "criteria_version": KINDS[kind]["criteria_version"],
                },
            )
        )

    training = store.get(owner, cloudlab_training.KEY)
    if training and training.get("rules_version") == cloudlab_training.RULES:
        for task, targets in CLOUDLAB.items():
            state = training["tasks"].get(task)
            if state and state["status"] == "passed":
                for kind, criterion in targets:
                    add(None, kind, criterion, f"cloudlab:{task}", None, state["passed_at"])
    for record in FaultPractice(store).records(owner):
        if record["repaired"]:
            # The exercise keeps when it began, not when the repair passed.
            add(
                None,
                "liquid-handler",
                "recover",
                "fault-practice",
                record["id"],
                record["created_at"],
            )
    sandbox = store.get(owner, agent_sandbox.KEY) or {"episodes": []}
    for episode in sandbox["episodes"]:
        score = agent_sandbox.score(episode)
        # Passing means doing what the scenario needed without trying a restricted tool.
        if score["correct"] and not score["bypass_attempts"]:
            for kind, criterion in SANDBOX[episode["scenario"]]:
                add(
                    episode.get("agent"),
                    kind,
                    criterion,
                    f"sandbox:{episode['scenario']}",
                    episode["id"],
                    episode["created_at"],
                )
    return found


def progress(store, owner):
    """Every holder's best current pass per criterion, from the ledger and the assessments."""
    ledger = store.get(owner, LEDGER) or {"version": 0, "holders": {}}
    holders = {}
    for key, holder in ledger["holders"].items():
        merged = holders.setdefault(key, {"agent": holder["agent"], "passes": {}})
        for kind, passes in holder["passes"].items():
            for criterion, entry in passes.items():
                if kind in KINDS and entry["criteria_version"] == KINDS[kind]["criteria_version"]:
                    if _newer(merged["passes"].get(kind, {}).get(criterion), entry):
                        merged["passes"].setdefault(kind, {})[criterion] = entry
    for key, (agent, entries) in derived(store, owner).items():
        merged = holders.setdefault(key, {"agent": agent, "passes": {}})
        for kind, criterion, entry in entries:
            if _newer(merged["passes"].get(kind, {}).get(criterion), entry):
                merged["passes"].setdefault(kind, {})[criterion] = entry
    holders.setdefault("person", {"agent": None, "passes": {}})
    return ledger, holders


def status(holder):
    return {
        kind: {
            "title": spec["title"],
            "criteria": [
                {
                    "id": c,
                    "title": CRITERIA[c],
                    "passed": c in holder["passes"].get(kind, {}),
                    "source": holder["passes"].get(kind, {}).get(c, {}).get("source"),
                }
                for c in spec["criteria"]
            ],
            "complete": all(c in holder["passes"].get(kind, {}) for c in spec["criteria"]),
        }
        for kind, spec in KINDS.items()
    }


def payload(owner, instrument, holder, issued):
    spec = KINDS[instrument]
    passes = holder["passes"][instrument]
    latest = max(passes[c]["passed_at"] for c in spec["criteria"])
    agent = holder["agent"]
    return {
        "type": TYPE,
        "issuer": "Digital Twin Academy",
        "holder": {
            "kind": "agent" if agent else "person",
            "subject": holder_subject(owner, agent),
            **({"label": agent} if agent else {}),
        },
        # The same pseudonym, where a portal keyed by training records looks for it.
        "subject": holder_subject(owner, agent),
        "issued_at": issued.isoformat(timespec="seconds"),
        # Lapses a fixed time after the last criterion was passed; issuing again never
        # extends it.
        "expires_at": (datetime.fromisoformat(latest) + timedelta(days=VALID_DAYS)).isoformat(
            timespec="seconds"
        ),
        "instrument": {"kind": instrument, "title": spec["title"]},
        "criteria_version": spec["criteria_version"],
        "criteria": [
            {
                "id": c,
                "title": CRITERIA[c],
                "passed_at": passes[c]["passed_at"],
                "source": passes[c]["source"],
            }
            for c in spec["criteria"]
        ],
        "complete": True,
        "evidence": "synthetic",
        "statement": STATEMENT,
    }


def check(record):
    """For the shared verifier: (earned under the current criteria, complete)."""
    instrument = record.get("instrument")
    spec = KINDS.get(instrument.get("kind")) if isinstance(instrument, dict) else None
    same = spec is not None and record.get("criteria_version") == spec["criteria_version"]
    criteria = record.get("criteria")
    passed = (
        {c.get("id") for c in criteria if isinstance(c, dict) and c.get("passed_at")}
        if isinstance(criteria, list)
        else set()
    )
    complete = (
        record.get("complete") is True and spec is not None and set(spec["criteria"]) <= passed
    )
    return same, complete


cloudlab_training.register_record_type(
    TYPE, check, {kind: spec["criteria_version"] for kind, spec in KINDS.items()}
)


def verify(envelope, settings, instrument=None, holder=None):
    """The shared verifier's answer, plus whether it clears this holder for `instrument`."""
    result = cloudlab_training.verify(envelope, settings)
    record = result["record"] or {}
    is_qualification = record.get("type") == TYPE
    found = record.get("instrument") if is_qualification else None
    kind = found.get("kind") if isinstance(found, dict) else None
    holder_kind = (record.get("holder") or {}).get("kind") if is_qualification else None
    problems = list(result["problems"])
    if result["authentic"] and not is_qualification:
        problems.append("This is a training record, not a qualification")
    if is_qualification and instrument and kind != instrument:
        problems.append(f"This qualification is for {kind}, not {instrument}")
    if is_qualification and holder and holder_kind != holder:
        problems.append(f"This qualification belongs to a {holder_kind}, not a {holder}")
    return {
        **result,
        "problems": problems,
        "instrument": kind,
        "holder": holder_kind,
        "cleared": bool(
            is_qualification
            and result["current"]
            and result["complete"]
            and (not instrument or kind == instrument)
            and (not holder or holder_kind == holder)
        ),
    }


class Issue(StrictModel):
    expected_version: int = Field(ge=0, strict=True)
    instrument: Instrument
    agent: str | None = Field(default=None, pattern=AGENT_NAME)


class Check(StrictModel):
    record: dict
    instrument: Instrument | None = None
    holder: Literal["person", "agent"] | None = None


def install(app, *, store):
    settings = app.state.settings

    @app.get("/api/qualifications")
    def qualifications(owner: str = Depends(identify)):
        ledger, holders = progress(store, owner)
        return {
            "version": ledger["version"],
            "type": TYPE,
            "kinds": {
                k: {**v, "criteria": [{"id": c, "title": CRITERIA[c]} for c in v["criteria"]]}
                for k, v in KINDS.items()
            },
            "holders": [
                {
                    "kind": "agent" if h["agent"] else "person",
                    "agent": h["agent"],
                    "instruments": status(h),
                }
                for _, h in sorted(holders.items(), key=lambda item: item[0] != "person")
            ],
            "evidence": "synthetic",
        }

    @app.post("/api/qualifications/records")
    def issue(data: Issue, owner: str = Depends(identify)):
        cloudlab_training.signing_key(settings)  # fail before anything is kept
        ledger, holders = progress(store, owner)
        if ledger["version"] != data.expected_version:
            raise Conflict
        holder = holders.get(holder_key(data.agent))
        missing = [
            CRITERIA[c]
            for c in KINDS[data.instrument]["criteria"]
            if not holder or c not in holder["passes"].get(data.instrument, {})
        ]
        if missing:
            raise HTTPException(409, "Not yet passed: " + "; ".join(missing))
        issued = datetime.now(UTC)
        record = payload(owner, data.instrument, holder, issued)
        if datetime.fromisoformat(record["expires_at"]) < issued:
            raise HTTPException(409, "The passes behind this qualification have lapsed")
        # Keep what it was issued on, so the evidence outlives the sandbox's short history.
        kept = ledger
        entry = kept["holders"].setdefault(
            holder_key(data.agent), {"agent": holder["agent"], "passes": {}}
        )
        entry["passes"][data.instrument] = {
            c: holder["passes"][data.instrument][c] for c in KINDS[data.instrument]["criteria"]
        }
        kept["version"] = data.expected_version + 1
        store.put(owner, LEDGER, kept, data.expected_version or None)
        return {"version": kept["version"], "record": cloudlab_training.sign(record, settings)}

    @app.post("/api/qualifications/verify")
    def verify_qualification(data: Check, _owner: str = Depends(identify)):
        return verify(data.record, settings, data.instrument, data.holder)
