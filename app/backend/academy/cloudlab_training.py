"""Cloud lab onboarding: a portable training module and the record it hands a cloud lab.

A learner who has never used an Opentrons Flex learns its deck and container rules,
repairs a workflow with an injected fault and writes one of their own. Every workflow
is checked against the rules in `opentrons_check` and against what it was meant to do,
so removing the faulty step never counts as a repair.

The training record is evidence for a cloud lab's operators, never permission. It is
signed with Ed25519 over its exact bytes, so a portal holding only the published public
key can tell it was issued here and not edited, without calling back or seeing anything
else about the learner. It names the rules version it was earned under, so a record from
older rules reads as out of date rather than as passed. Everything here is synthetic:
no robot, Isaac/GPU or chemistry.
"""

import base64
import binascii
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import Depends, HTTPException
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey
from pydantic import Field

from . import opentrons_check
from .auth import identify
from .models import Action, StrictModel
from .store import Conflict

MODULE = "flex-transfer"
RULES = "cloudlab-flex-transfer/1"
RECORD_TYPE = "academy.training-record/1"
ENVELOPE = "academy.signed-record/1"
VALID_DAYS = 90
KEY = f"cloudlab-training#{MODULE}"
STOCK_START = 5000.0
LAYOUT = {"stock": "D1", "plate": "D2", "tips": "B1", "waste": "D3"}
STATEMENT = (
    "Training evidence from synthetic exercises. It does not authorize use of any "
    "instrument; the cloud lab's own safety review and access policy decide that."
)

QUESTIONS = [
    {
        "id": "waste",
        "prompt": "Where does a used tip go on the Flex?",
        "options": ["Into the waste chute in D3", "Into any free deck slot", "Back into the stock"],
        "answer": 0,
    },
    {
        "id": "pipette",
        "prompt": "What is the most the Flex 1-Channel 1000 µL pipette can aspirate at once?",
        "options": ["300 µL", "1,000 µL", "2,000 µL"],
        "answer": 1,
    },
    {
        "id": "plate",
        "prompt": "How much does one well of the 96 deep-well plate hold?",
        "options": ["300 µL", "2,000 µL", "15,000 µL"],
        "answer": 1,
    },
    {
        "id": "tip",
        "prompt": "What has to happen before the pipette aspirates?",
        "options": ["It picks up a tip", "It drops its tip", "Nothing"],
        "answer": 0,
    },
]


def step(kind, well="stock", volume=100):
    return {"kind": kind, "well": well, "volume": volume}


TASKS = {
    "orient": {
        "title": "Learn the deck and container rules",
        "kind": "questions",
    },
    "fault": {
        "title": "Repair a workflow with an injected fault",
        "kind": "workflow",
        "goal": "Put 600 µL of stock into A1 and 600 µL into A2.",
        "target": {"A1": 600, "A2": 600, "A3": 0},
        "fresh_tip_per_well": False,
        # One aspiration of 1,200 µL: more than the 1,000 µL tip holds.
        "start": [
            step("pickup"),
            step("aspirate", "stock", 1000),
            step("aspirate", "stock", 200),
            step("dispense", "A1", 600),
            step("dispense", "A2", 600),
            step("drop"),
        ],
    },
    "own": {
        "title": "Write your own workflow",
        "kind": "workflow",
        "goal": "Put 250 µL of stock into A1, A2 and A3, with a fresh tip for each well.",
        "target": {"A1": 250, "A2": 250, "A3": 250},
        "fresh_tip_per_well": True,
        "start": [],
    },
}
WORKFLOW_TASKS = [key for key, task in TASKS.items() if task["kind"] == "workflow"]


class Revision(StrictModel):
    expected_version: int = Field(ge=0, strict=True)


class StartTraining(Revision):
    module_id: Literal["flex-transfer"] = MODULE


class Answers(Revision):
    answers: dict[str, int] = Field(max_length=len(QUESTIONS))


class WorkflowValidation(Revision):
    task: Literal["fault", "own"]
    actions: list[Action] = Field(max_length=64)


class RecordCheck(StrictModel):
    record: dict


def now():
    return datetime.now(UTC)


def stamp(moment=None):
    return (moment or now()).isoformat(timespec="seconds")


def capabilities():
    profile = opentrons_check.PROFILES["flex"]
    return {
        "modules": [
            {
                "id": MODULE,
                "title": "Opentrons Flex: first pipetting workflow",
                "rules_version": RULES,
                "tasks": [{"id": key, "title": task["title"]} for key, task in TASKS.items()],
            }
        ],
        "instrument": {
            "id": "flex",
            "name": "Opentrons Flex",
            "pipette": profile["pipette_name"],
            "volume_ul": [profile["min_ul"], profile["max_ul"]],
            "tips": profile["tips"],
            "plate": opentrons_check.PLATE,
            "stock": opentrons_check.STOCK,
            "layout": LAYOUT,
            "simulator_rules": f"opentrons_simulate, API {opentrons_check.API_LEVEL}",
        },
        "evidence": "synthetic",
    }


def experiment(actions):
    return {
        "instrument": "flex",
        "source_volume": STOCK_START,
        "diluent_volume": 0,
        "layout": LAYOUT,
        "actions": actions,
    }


def outcome(actions):
    """Final well volumes, and the wells each tip dispensed into."""
    wells = {"stock": STOCK_START, "A1": 0.0, "A2": 0.0, "A3": 0.0}
    tips, current = [], None
    for action in actions:
        if action["kind"] == "pickup":
            current = set()
            tips.append(current)
        elif action["kind"] == "aspirate":
            wells[action["well"]] -= action["volume"]
        elif action["kind"] == "dispense":
            wells[action["well"]] += action["volume"]
            if current is not None and action["well"] != "stock":
                current.add(action["well"])
        else:
            current = None
    return wells, tips


def judge(task_id, actions):
    """What the simulator rules say, then whether the workflow does what the task asks."""
    task = TASKS[task_id]
    rules = opentrons_check.check(experiment(actions))
    problems = [
        {"source": "rules", "step": s["step"], "message": s["message"]} for s in rules["stops"]
    ] + [
        {"source": "rules", "step": s["step"], "message": s["message"]} for s in rules["unnoticed"]
    ]
    if not problems:
        wells, tips = outcome(actions)
        for well, wanted in task["target"].items():
            if abs(wells[well] - wanted) > 1e-6:
                problems.append(
                    {
                        "source": "goal",
                        "step": None,
                        "message": f"{well} ends with {wells[well]:g} µL; the goal is {wanted:g} µL",
                    }
                )
        if task["fresh_tip_per_well"] and any(len(used) > 1 for used in tips):
            problems.append(
                {
                    "source": "goal",
                    "step": None,
                    "message": "One tip dispenses into more than one well; use a fresh tip each time",
                }
            )
    return {
        "valid": not problems,
        "stops": len(rules["stops"]),
        "problems": problems,
        "rules_version": RULES,
        "evidence": "synthetic",
    }


def new_training(started):
    task = {"status": "open", "attempts": 0, "first_attempt_at": None, "passed_at": None}
    return {
        "module_id": MODULE,
        "rules_version": RULES,
        "version": 1,
        "started_at": started,
        "tasks": {
            key: {
                **task,
                "title": spec["title"],
                "errors": [],
                **({"actions": spec["start"]} if spec["kind"] == "workflow" else {}),
            }
            for key, spec in TASKS.items()
        },
        "last_check": None,
    }


def attempt(task, passed, errors):
    moment = stamp()
    task["attempts"] += 1
    task["first_attempt_at"] = task["first_attempt_at"] or moment
    if passed and task["status"] != "passed":
        task.update(status="passed", passed_at=moment)
    # Keep the mistakes made on the way, not a full log.
    for message in errors:
        if message not in task["errors"] and len(task["errors"]) < 12:
            task["errors"].append(message)


def subject(owner):
    """A stable pseudonym for the learner; the record never carries the account id."""
    return hashlib.sha256(f"academy-training-subject:{owner}".encode()).hexdigest()[:24]


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unb64url(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def signing_key(settings):
    """The issuer key, derived from the app secret; without one nothing is signed."""
    if not settings.secret:
        raise HTTPException(
            503, "Training records cannot be signed here: no record key is configured"
        )
    seed = hmac.new(settings.secret.encode(), b"academy-training-record-ed25519-v1", "sha256")
    return SigningKey(seed.digest())


def public_jwk(settings):
    raw = bytes(signing_key(settings).verify_key)
    kid = hashlib.sha256(raw).hexdigest()[:16]
    return {
        "kty": "OKP",
        "crv": "Ed25519",
        "alg": "EdDSA",
        "use": "sig",
        "kid": kid,
        "x": b64url(raw),
    }


def sign(record, settings):
    """An envelope whose signature covers the payload bytes exactly as they travel."""
    payload = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode()
    return {
        "format": ENVELOPE,
        "alg": "EdDSA",
        "kid": public_jwk(settings)["kid"],
        "payload": b64url(payload),
        "signature": b64url(signing_key(settings).sign(payload).signature),
    }


def opened(envelope, settings):
    """The record inside an envelope, or None when the signature does not hold."""
    key = signing_key(settings).verify_key
    try:
        if (
            envelope.get("format") != ENVELOPE
            or envelope.get("alg") != "EdDSA"
            or envelope.get("kid") != public_jwk(settings)["kid"]
        ):
            return None
        payload = unb64url(envelope["payload"])
        key.verify(payload, unb64url(envelope["signature"]))
        found = json.loads(payload)
    except (KeyError, TypeError, ValueError, binascii.Error, BadSignatureError):
        return None
    return found if isinstance(found, dict) else None


def seconds_between(start, end):
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())


def record(owner, training, settings):
    issued = now()
    tasks = []
    for key, task in training["tasks"].items():
        tasks.append(
            {
                "id": key,
                "title": task["title"],
                "status": task["status"],
                "attempts": task["attempts"],
                "retries": max(0, task["attempts"] - 1),
                "errors": task["errors"],
                "passed_at": task["passed_at"],
            }
        )
    valid_at = [training["tasks"][key]["passed_at"] for key in WORKFLOW_TASKS]
    first_valid = min((t for t in valid_at if t), default=None)
    complete = all(t["status"] == "passed" for t in tasks)
    # Fetching the record again never extends it: it lapses a fixed time after the
    # training was completed (or, until then, after it was started).
    anchor = max(t["passed_at"] for t in tasks) if complete else training["started_at"]
    return sign(
        {
            "type": RECORD_TYPE,
            "issuer": "Digital Twin Academy",
            "subject": subject(owner),
            "issued_at": stamp(issued),
            "expires_at": stamp(datetime.fromisoformat(anchor) + timedelta(days=VALID_DAYS)),
            "module": {
                "id": training["module_id"],
                "rules_version": training["rules_version"],
                "instrument": "Opentrons Flex",
                "simulator_rules": capabilities()["instrument"]["simulator_rules"],
            },
            "complete": complete,
            "tasks": tasks,
            "time_to_first_valid_workflow_s": first_valid
            and seconds_between(training["started_at"], first_valid),
            "evidence": "synthetic",
            "statement": STATEMENT,
        },
        settings,
    )


def verify(envelope, settings):
    """Whether a presented record was issued here unedited, and whether it is still current.

    Reads nothing about the learner: a portal learns only what the record itself says.
    """
    record = opened(envelope, settings)
    authentic = record is not None
    record = record or {}
    module = record.get("module")
    known = record.get("type") == RECORD_TYPE
    same_rules = isinstance(module, dict) and module.get("rules_version") == RULES
    expires = record.get("expires_at")
    try:
        lapse = datetime.fromisoformat(expires) if isinstance(expires, str) else None
        # A timestamp without a zone cannot be compared, so it does not count as current.
        expired = lapse is None or lapse.tzinfo is None or lapse < now()
    except ValueError:
        expired = True
    complete = record.get("complete") is True
    problems = [
        message
        for failed, message in [
            (not authentic, "The signature does not match: edited, or not issued here"),
            (authentic and not known, "This is not an Academy training record"),
            (
                authentic and not same_rules,
                "Earned under rules that have since changed; retrain first",
            ),
            (authentic and expired, "The record has expired"),
            (authentic and not complete, "Not every training task has been passed"),
        ]
        if failed
    ]
    return {
        "authentic": authentic,
        "current": authentic and known and same_rules and not expired,
        "complete": authentic and complete,
        "problems": problems,
        "rules_version": RULES,
        "record": record if authentic else None,
    }


def install(app, *, store):
    settings = app.state.settings

    def current(owner, expected):
        training = store.get(owner, KEY)
        if training is None:
            raise HTTPException(404, "Start the training first")
        if training["version"] != expected:
            raise Conflict
        return training

    def save(owner, training, expected):
        training["version"] = expected + 1
        store.put(owner, KEY, training, expected)
        return view(training)

    def view(training):
        return {
            **training,
            "questions": [{k: q[k] for k in ("id", "prompt", "options")} for q in QUESTIONS],
            "goals": {key: TASKS[key]["goal"] for key in WORKFLOW_TASKS},
        }

    @app.get("/api/cloudlab/issuer")
    def record_issuer():
        """What a verifier needs and nothing else: the public key and the current rules."""
        return {
            "issuer": "Digital Twin Academy",
            "format": ENVELOPE,
            "keys": [public_jwk(settings)] if settings.secret else [],
            "rules": {MODULE: RULES},
            # A verifier judges expiry by this clock, not the learner's.
            "now": stamp(),
        }

    @app.get("/api/cloudlab/capabilities")
    def cloudlab_capabilities(_owner: str = Depends(identify)):
        return capabilities()

    @app.get("/api/cloudlab/training-sessions/current")
    def current_training(owner: str = Depends(identify)):
        training = store.get(owner, KEY)
        return {"training": training and view(training)}

    @app.post("/api/cloudlab/training-sessions", status_code=201)
    def start_training(data: StartTraining, owner: str = Depends(identify)):
        """Start, or start over: starting over needs the version the learner last saw."""
        existing = store.get(owner, KEY)
        if existing is None:
            if data.expected_version != 0:
                raise Conflict
            training = new_training(stamp())
            store.put(owner, KEY, training, None)
            return view(training)
        if existing["version"] != data.expected_version:
            raise Conflict
        return save(owner, new_training(stamp()), data.expected_version)

    @app.post("/api/cloudlab/training-sessions/answers")
    def answer_questions(data: Answers, owner: str = Depends(identify)):
        training = current(owner, data.expected_version)
        wrong = [q for q in QUESTIONS if data.answers.get(q["id"]) != q["answer"]]
        # Only how many are wrong, so the quiz cannot be solved by elimination.
        attempt(
            training["tasks"]["orient"],
            not wrong,
            [f"{len(wrong)} of {len(QUESTIONS)} answers wrong"] if wrong else [],
        )
        training["last_check"] = {"task": "orient", "valid": not wrong, "wrong": len(wrong)}
        return save(owner, training, data.expected_version)

    @app.post("/api/cloudlab/workflow-validations")
    def validate_workflow(data: WorkflowValidation, owner: str = Depends(identify)):
        training = current(owner, data.expected_version)
        actions = [a.model_dump() for a in data.actions]
        result = judge(data.task, actions)
        task = training["tasks"][data.task]
        task["actions"] = actions
        attempt(task, result["valid"], [p["message"] for p in result["problems"]])
        training["last_check"] = {"task": data.task, **result}
        return save(owner, training, data.expected_version)

    @app.get("/api/cloudlab/qualifications/me")
    def training_record(owner: str = Depends(identify)):
        training = store.get(owner, KEY)
        if training is None:
            raise HTTPException(404, "Start the training first")
        return record(owner, training, settings)

    @app.post("/api/cloudlab/records/verify")
    def verify_record(data: RecordCheck, _owner: str = Depends(identify)):
        return verify(data.record, settings)
