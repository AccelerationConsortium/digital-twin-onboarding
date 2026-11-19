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

from . import competencies, fault_drills, opentrons_check
from .auth import identify
from .models import Action, StrictModel
from .store import Conflict

MODULE = "flex-transfer"
RULES = "cloudlab-flex-transfer/2"
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

# Other record types this issuer signs with the same key and envelope, by type. Each
# maps to a check saying whether a record was earned under the current rules and is
# complete; `verify` stays the one verifier for all of them.
RECORD_TYPES = {}
PUBLISHED_RULES = {}


def register_record_type(record_type, check, rules):
    RECORD_TYPES[record_type] = check
    PUBLISHED_RULES.update(rules)


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


def ask(qid, prompt, options, answer):
    """A question; a list answer means every listed option, and only those, is right."""
    return {"id": qid, "prompt": prompt, "options": options, "answer": answer}


# Tasks answered by choosing, each tied to a GASE position in `competencies`.
CHOICES = {
    "orient": {"context": None, "questions": QUESTIONS, "note": False},
    "assume": {
        "context": (
            "Your repaired workflow put 600 µL of stock into A1 and into A2. A result is "
            "only as good as what it quietly relies on."
        ),
        "questions": [
            ask(
                "relies",
                "Which of these does that result depend on? Choose every one that applies.",
                [
                    "The stock reservoir holds at least 1,200 µL when the run starts",
                    "A1 and A2 are empty when the run starts",
                    "There is at least one 1000 µL tip in B1",
                    "The liquid behaves like water, so the pipette's volumes are accurate",
                    "The plate is sealed during the run",
                    "The waste chute can sit in any deck slot",
                ],
                [0, 1, 2, 3],
            )
        ],
        "note": False,
    },
    "escalate": {
        "context": (
            "The SOP fixes 600 µL per well. Today's stock bottle holds 900 µL, and the dry "
            "check says the stock runs out at the second transfer."
        ),
        "questions": [
            ask(
                "next",
                "What do you do?",
                [
                    "Lower both transfers to 450 µL so the run fits",
                    "Run it anyway and note the shortfall afterwards",
                    "Stop, and escalate to the method owner with the check result",
                    "Delete the A2 transfer so the check passes",
                ],
                2,
            )
        ],
        "note": False,
    },
    "accept": {
        "context": (
            "Acceptance criteria, set before the comparison: the automated mean is within "
            "±5 % of the manual mean, and the automated CV is at most 5 %. Results: manual "
            "mean 100.0 µL, CV 2.1 %; automated mean 103.2 µL, CV 6.4 %."
        ),
        "questions": [
            ask("accuracy", "Is the accuracy criterion met?", ["Met", "Not met"], 0),
            ask("precision", "Is the precision (CV) criterion met?", ["Met", "Not met"], 1),
            ask(
                "verdict",
                "Is the automated method equivalent to the manual one?",
                [
                    "Yes: the mean is close enough",
                    "No: one criterion fails, so it is not equivalent yet",
                    "Yes, if the next run looks better",
                ],
                1,
            ),
        ],
        "note": False,
    },
    "report": {
        "context": (
            "Write up the fault you repaired so a colleague who was not there can trace it."
        ),
        "questions": [
            ask(
                "step",
                "Which step of the original workflow failed first?",
                ["Step 2", "Step 3", "Step 5"],
                1,
            ),
            ask(
                "expected",
                "What was expected at that step?",
                [
                    "The tip to hold all the liquid drawn so far",
                    "The plate to be sealed",
                    "A fresh tip for each aspiration",
                ],
                0,
            ),
            ask(
                "action",
                "What was done about it?",
                [
                    "Nothing; the run was repeated",
                    "The load was split into two trips and the workflow checked again",
                    "The tip volume limit was raised",
                ],
                1,
            ),
        ],
        "note": True,
    },
    "audit": {
        "context": (
            "A simulated audit of yesterday's run log. Records have to show who did what "
            "and when, be written at the time, and keep the original data."
        ),
        "questions": [
            ask(
                "findings",
                "Which entries would an auditor flag? Choose every one that applies.",
                [
                    "09:02 · ada · Loaded plate P-17 on the Flex",
                    "09:05 · (no user) · Changed the aspirate volume from 600 to 450 µL",
                    "09:40 · ada · Run finished; results exported to results.csv",
                    "09:41 · ada · Replaced results.csv with a cleaned copy; original deleted",
                    "09:42 · ada · Control well A12 read 3 % low, within its limit",
                    "Friday 16:00 · ada · Noted that the 09:05 change had been approved",
                ],
                [1, 3, 5],
            )
        ],
        "note": False,
    },
    "need": {
        "context": (
            "A lab fills 40 plates a week by hand, 45 minutes each. One plate in 25 has to "
            "be redone. Automating the fill would take about 6 weeks of setup and "
            "validation, after which a plate takes 10 minutes of attention."
        ),
        "questions": [
            ask(
                "hours",
                "About how many hours of hands-on time a week would automation save?",
                ["About 6", "About 23", "About 30"],
                1,
            ),
            ask(
                "inaction",
                "What is the cost of not automating?",
                [
                    "None; the lab already manages",
                    "About 30 hours a week of manual effort and the rework of redone plates",
                    "Only the robot's price",
                ],
                1,
            ),
            ask(
                "decision",
                "What do you recommend?",
                [
                    "Automate, and check the setup time against the weekly saving first",
                    "Do not automate; 6 weeks is too long",
                    "Automate without checking, since robots are always faster",
                ],
                0,
            ),
        ],
        "note": False,
    },
}


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
    "assume": {"title": "Record what the result depends on", "kind": "questions"},
    "escalate": {"title": "Know when to stop and escalate", "kind": "questions"},
    "accept": {"title": "Judge results against acceptance criteria", "kind": "questions"},
    "report": {"title": "Document the deviation", "kind": "questions"},
    "audit": {"title": "Audit a run log", "kind": "questions"},
    "need": {"title": "Decide whether to automate", "kind": "questions"},
}
WORKFLOW_TASKS = [key for key, task in TASKS.items() if task["kind"] == "workflow"]


class Revision(StrictModel):
    expected_version: int = Field(ge=0, strict=True)


class StartTraining(Revision):
    module_id: Literal["flex-transfer"] = MODULE


class Answers(Revision):
    task: Literal["orient", "assume", "escalate", "accept", "report", "audit", "need"] = "orient"
    answers: dict[str, int | list[int]] = Field(max_length=8)
    note: str = Field(default="", max_length=500)


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


def record(owner, training, settings, drills=None):
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
                **({"note": task["note"]} if task.get("note") else {}),
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
            "competencies": {
                "framework": competencies.FRAMEWORK["name"],
                "status": competencies.FRAMEWORK["status"],
                "evidence_toward": [
                    {
                        k: c[k]
                        for k in ("key", "tracks", "seniority", "step", "proficiency", "label")
                    }
                    for c in competencies.evidenced_by(
                        f"cloudlab:{t['id']}" for t in tasks if t["status"] == "passed"
                    )
                ],
            },
            # A passed fault-drill checkride, when there is one; it is signed with the rest.
            **({"fault_drills": drills} if drills else {}),
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
    other = None if record.get("type") == RECORD_TYPE else RECORD_TYPES.get(record.get("type"))
    known = record.get("type") == RECORD_TYPE or other is not None
    same_rules = isinstance(module, dict) and module.get("rules_version") == RULES
    if other is not None:
        same_rules, complete = other(record)
    expires = record.get("expires_at")
    try:
        lapse = datetime.fromisoformat(expires) if isinstance(expires, str) else None
        # A timestamp without a zone cannot be compared, so it does not count as current.
        expired = lapse is None or lapse.tzinfo is None or lapse < now()
    except ValueError:
        expired = True
    if other is None:
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
        if training.get("rules_version") != RULES:
            raise HTTPException(409, "The training has changed since this began. Start over.")
        return training

    def save(owner, training, expected):
        training["version"] = expected + 1
        store.put(owner, KEY, training, expected)
        return view(training)

    def view(training):
        return {
            **training,
            "outdated": training.get("rules_version") != RULES,
            "choices": {
                key: {
                    "context": spec["context"],
                    "note": spec["note"],
                    "questions": [
                        {
                            "id": q["id"],
                            "prompt": q["prompt"],
                            "options": q["options"],
                            "multiple": isinstance(q["answer"], list),
                        }
                        for q in spec["questions"]
                    ],
                }
                for key, spec in CHOICES.items()
            },
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
            **({"qualifications": PUBLISHED_RULES} if PUBLISHED_RULES else {}),
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
        if data.task not in training["tasks"]:
            raise HTTPException(409, "This training predates the current tasks. Start over.")
        spec = CHOICES[data.task]
        questions = spec["questions"]

        def right(q):
            given = data.answers.get(q["id"])
            if isinstance(q["answer"], list):
                # Repeating an option is not a valid answer, so no deduplication here.
                return isinstance(given, list) and sorted(given) == q["answer"]
            return given == q["answer"]

        wrong = [q for q in questions if not right(q)]
        note = data.note.strip()
        missing_note = spec["note"] and len(note) < 15
        # Only how many are wrong, so a task cannot be solved by elimination.
        errors = [f"{len(wrong)} of {len(questions)} wrong"] if wrong else []
        if missing_note:
            errors.append("The write-up needs a note of at least 15 characters")
        task = training["tasks"][data.task]
        attempt(task, not errors, errors)
        if spec["note"] and not errors:
            task["note"] = note
        training["last_check"] = {
            "task": data.task,
            "valid": not errors,
            "wrong": len(wrong),
            "note_missing": bool(missing_note),
        }
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
        drills = fault_drills.record_entry(store.get(owner, fault_drills.KEY))
        return record(owner, training, settings, drills)

    @app.post("/api/cloudlab/records/verify")
    def verify_record(data: RecordCheck, _owner: str = Depends(identify)):
        return verify(data.record, settings)
