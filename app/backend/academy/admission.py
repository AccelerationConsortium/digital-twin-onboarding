"""Admission of learners whose email is outside the self-registration domains.

Anyone may ask for access without an account; nothing is granted by asking. A lab
operator approves a request, or invites an email directly, and Cognito then creates
the account and emails its temporary password. Email ownership is proven by that
message, so an approved address never becomes an identity the API trusts by itself.
"""

import hashlib
import re
from datetime import UTC, datetime

from fastapi import Depends, HTTPException
from pydantic import Field, field_validator

from .auth import identify_operator
from .models import StrictModel
from .store import Conflict

ACCESS = "system#access"
PENDING_LIMIT = 200
EMAIL = re.compile(r"[^\s@]+@[a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,}")


def normalized(email: str) -> str:
    email = email.lower()
    if len(email) > 254 or not EMAIL.fullmatch(email):
        raise ValueError("Enter a complete email address")
    return email


class AccessRequest(StrictModel):
    email: str
    name: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=300)

    @field_validator("email")
    @classmethod
    def complete(cls, value: str) -> str:
        return normalized(value)

    @field_validator("name", "note")
    @classmethod
    def printable(cls, value: str) -> str:
        value = value.strip()
        if not value.isprintable():
            raise ValueError("Use plain text")
        return value


class Invitation(StrictModel):
    email: str

    @field_validator("email")
    @classmethod
    def complete(cls, value: str) -> str:
        return normalized(value)


class Decision(StrictModel):
    expected_version: int = Field(ge=1)


class CognitoInviter:
    """Creates the account; Cognito emails the temporary password to that address."""

    def __init__(self, issuer: str, app_url: str, client=None):
        match = re.fullmatch(
            r"https://cognito-idp\.([a-z0-9-]+)\.amazonaws\.com/([A-Za-z0-9_-]+)", issuer
        )
        if not match:
            raise ValueError("Learner invitations require a Cognito user pool issuer")
        self.region, self.pool = match.groups()
        self.app_url = app_url
        self._client = client

    def invite(self, email: str) -> None:
        if self._client is None:
            import boto3

            self._client = boto3.client("cognito-idp", region_name=self.region)
        args = {
            "UserPoolId": self.pool,
            "Username": email,
            "DesiredDeliveryMediums": ["EMAIL"],
            # Read by the pool's message trigger to link the invitation to this deployment.
            "ClientMetadata": {"app_url": self.app_url},
        }
        errors = self._client.exceptions
        try:
            self._client.admin_create_user(
                **args,
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "email_verified", "Value": "true"},
                ],
            )
        except errors.UsernameExistsException:
            try:
                # Still waiting on its temporary password: send a fresh one.
                self._client.admin_create_user(**args, MessageAction="RESEND")
            except errors.UnsupportedUserStateException:
                raise HTTPException(409, "This email already has an account") from None


class Admission:
    def __init__(self, store, *, open_domains=(), inviter=None):
        self.store = store
        self.open_domains = set(open_domains)
        self.inviter = inviter

    @staticmethod
    def key(email: str) -> str:
        return "request#" + hashlib.sha256(email.encode()).hexdigest()[:32]

    @staticmethod
    def now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")

    def requests(self):
        rows = self.store.partition(ACCESS, "request#", limit=500)
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return sorted(rows, key=lambda r: r["status"] != "pending")

    def request(self, data: AccessRequest):
        if data.email.rsplit("@", 1)[1] in self.open_domains:
            raise HTTPException(409, "This email can create an account directly. Choose sign in.")
        key = self.key(data.email)
        # The same answer whether or not this address has asked before or been decided.
        if not self.store.get(ACCESS, key):
            pending = sum(r["status"] == "pending" for r in self.requests())
            if pending >= PENDING_LIMIT:
                raise HTTPException(429, "Requests are paused for now. Try again later.")
            try:
                self.store.put(
                    ACCESS,
                    key,
                    {
                        "id": key.removeprefix("request#"),
                        "version": 1,
                        "email": data.email,
                        "name": data.name,
                        "note": data.note,
                        "status": "pending",
                        "created_at": self.now(),
                    },
                    None,
                )
            except Conflict:
                pass
        return {"received": True}

    def _send(self, email: str):
        if self.inviter:
            self.inviter.invite(email)

    def approve(self, operator: str, request_id: str, data: Decision):
        key = f"request#{request_id}"
        record = self.store.get(ACCESS, key)
        if not record:
            raise HTTPException(404, "Request not found")
        if record["status"] not in {"pending", "invited"}:
            raise HTTPException(409, "This request was declined")
        if record["version"] != data.expected_version:
            raise Conflict()
        # Claim the request first so two operators cannot both send an invitation.
        invited = {
            **record,
            "status": "invited",
            "version": record["version"] + 1,
            "decided_by": operator,
            "decided_at": self.now(),
        }
        self.store.put(ACCESS, key, invited, record["version"])
        try:
            self._send(record["email"])
        except Exception:
            self.store.put(
                ACCESS,
                key,
                {**record, "version": invited["version"] + 1},
                invited["version"],
            )
            raise
        return invited

    def decline(self, operator: str, request_id: str, data: Decision):
        key = f"request#{request_id}"
        record = self.store.get(ACCESS, key)
        if not record:
            raise HTTPException(404, "Request not found")
        if record["status"] != "pending":
            raise HTTPException(409, "Only a waiting request can be declined")
        declined = {
            **record,
            "status": "declined",
            "version": record["version"] + 1,
            "decided_by": operator,
            "decided_at": self.now(),
        }
        self.store.put(ACCESS, key, declined, data.expected_version)
        return declined

    def invite(self, operator: str, data: Invitation):
        key = self.key(data.email)
        record = self.store.get(ACCESS, key)
        if not record or record["status"] == "declined":
            # An operator's direct invitation overrides an earlier decline.
            record = {
                "id": key.removeprefix("request#"),
                "email": data.email,
                "name": "",
                "note": "",
                "created_at": self.now(),
                **(record or {}),
                "status": "pending",
                "version": record["version"] + 1 if record else 1,
            }
            self.store.put(ACCESS, key, record, record["version"] - 1 or None)
        return self.approve(operator, record["id"], Decision(expected_version=record["version"]))


def install(app, admission: Admission):
    @app.post("/api/access-requests", status_code=202)
    def ask(data: AccessRequest):
        return admission.request(data)

    @app.get("/api/access-requests")
    def waiting(operator: str = Depends(identify_operator)):
        return admission.requests()

    @app.post("/api/access-requests/{request_id}/approve")
    def approve(request_id: str, data: Decision, operator: str = Depends(identify_operator)):
        return admission.approve(operator, request_id, data)

    @app.post("/api/access-requests/{request_id}/decline")
    def decline(request_id: str, data: Decision, operator: str = Depends(identify_operator)):
        return admission.decline(operator, request_id, data)

    @app.post("/api/invitations")
    def invite(data: Invitation, operator: str = Depends(identify_operator)):
        return admission.invite(operator, data)
