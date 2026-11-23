"""External emails ask for access; only a lab operator's decision sends an invitation."""

import pytest
from academy.admission import Admission, CognitoInviter
from academy.main import create_app
from academy.settings import Settings
from botocore.exceptions import ClientError
from fastapi import HTTPException
from fastapi.testclient import TestClient

SECRET = "test-secret-that-is-at-least-32-characters"
ASK = {"email": "Guest@Example.com", "name": "Grace", "note": "Visiting from another lab"}


class Outbox:
    def __init__(self):
        self.sent = []
        self.fail = False

    def invite(self, email):
        if self.fail:
            raise HTTPException(502, "Cognito is unavailable")
        self.sent.append(email)


def lab(store, tmp_path, operator=True):
    app = create_app(
        Settings(
            allow_demo=True,
            local_operator=operator,
            secret=SECRET,
            data_path=str(tmp_path / "unused.sqlite"),
        ),
        store=store,
    )
    outbox = Outbox()
    app.state.admission.inviter = outbox
    app.state.admission.open_domains = {"utoronto.ca"}
    return app, outbox


def test_a_request_grants_nothing_until_an_operator_approves(store, tmp_path):
    app, outbox = lab(store, tmp_path)
    with TestClient(app) as visitor, TestClient(app) as operator:
        assert visitor.post("/api/access-requests", json=ASK).status_code == 202
        # Asking twice neither duplicates the request nor reveals that it exists.
        assert visitor.post("/api/access-requests", json=ASK).json() == {"received": True}
        assert visitor.get("/api/access-requests").status_code == 401
        assert outbox.sent == []

        operator.post("/api/auth/guest", json={"name": "Op"})
        [waiting] = operator.get("/api/access-requests").json()
        assert waiting["email"] == "guest@example.com" and waiting["status"] == "pending"
        decision = {"expected_version": waiting["version"]}
        approved = operator.post(f"/api/access-requests/{waiting['id']}/approve", json=decision)
        assert approved.json()["status"] == "invited"
        assert outbox.sent == ["guest@example.com"]
        # A stale decision is rejected instead of sending a second invitation.
        stale = operator.post(f"/api/access-requests/{waiting['id']}/approve", json=decision)
        assert stale.status_code == 409 and len(outbox.sent) == 1
        assert operator.get("/api/access").json()["admit_learners"] is True


def test_learners_cannot_decide_requests(store, tmp_path):
    app, outbox = lab(store, tmp_path, operator=False)
    with TestClient(app) as learner:
        learner.post("/api/access-requests", json=ASK)
        learner.post("/api/auth/guest", json={"name": "Ada"})
        assert learner.get("/api/access").json()["admit_learners"] is False
        assert learner.get("/api/access-requests").status_code == 403
        assert learner.post("/api/invitations", json={"email": "x@example.com"}).status_code == 403
        assert (
            learner.post(
                "/api/access-requests/anything/approve", json={"expected_version": 1}
            ).status_code
            == 403
        )
        assert outbox.sent == []


def test_declined_requests_stay_declined_until_an_operator_invites(store, tmp_path):
    app, outbox = lab(store, tmp_path)
    with TestClient(app) as operator:
        operator.post("/api/access-requests", json=ASK)
        operator.post("/api/auth/guest", json={"name": "Op"})
        [waiting] = operator.get("/api/access-requests").json()
        path = f"/api/access-requests/{waiting['id']}"
        declined = operator.post(f"{path}/decline", json={"expected_version": 1}).json()
        assert declined["status"] == "declined"
        assert (
            operator.post(
                f"{path}/approve", json={"expected_version": declined["version"]}
            ).status_code
            == 409
        )
        # Asking again does not reopen a declined request.
        operator.post("/api/access-requests", json=ASK)
        assert operator.get("/api/access-requests").json()[0]["status"] == "declined"
        invited = operator.post("/api/invitations", json={"email": "guest@example.com"}).json()
        assert invited["status"] == "invited" and invited["name"] == "Grace"
        assert outbox.sent == ["guest@example.com"]


def test_direct_invitation_and_resend(store, tmp_path):
    app, outbox = lab(store, tmp_path)
    with TestClient(app) as operator:
        operator.post("/api/auth/guest", json={"name": "Op"})
        first = operator.post("/api/invitations", json={"email": "new@example.org"}).json()
        assert first["status"] == "invited"
        again = operator.post("/api/invitations", json={"email": "NEW@example.org"}).json()
        assert again["version"] > first["version"]
        assert outbox.sent == ["new@example.org"] * 2
        assert len(operator.get("/api/access-requests").json()) == 1


def test_a_failed_invitation_leaves_the_request_waiting(store, tmp_path):
    app, outbox = lab(store, tmp_path)
    outbox.fail = True
    with TestClient(app) as operator:
        operator.post("/api/access-requests", json=ASK)
        operator.post("/api/auth/guest", json={"name": "Op"})
        [waiting] = operator.get("/api/access-requests").json()
        path = f"/api/access-requests/{waiting['id']}/approve"
        assert operator.post(path, json={"expected_version": 1}).status_code == 502
        [waiting] = operator.get("/api/access-requests").json()
        assert waiting["status"] == "pending"
        outbox.fail = False
        retry = operator.post(path, json={"expected_version": waiting["version"]})
        assert retry.json()["status"] == "invited"


@pytest.mark.parametrize(
    "body",
    [
        {**ASK, "email": "not-an-email"},
        {**ASK, "email": "a@b"},
        {**ASK, "email": "a b@example.com"},
        {**ASK, "email": "a@example.com@evil.example"},
        {**ASK, "name": ""},
        {**ASK, "note": "x" * 301},
        {**ASK, "role": "operator"},
    ],
)
def test_malformed_requests_rejected(client, body):
    assert client.post("/api/access-requests", json=body).status_code == 422


def test_open_domains_register_directly_and_requests_are_bounded(store, tmp_path, monkeypatch):
    app, _ = lab(store, tmp_path)
    monkeypatch.setattr("academy.admission.PENDING_LIMIT", 2)
    with TestClient(app) as visitor:
        direct = visitor.post("/api/access-requests", json={**ASK, "email": "me@utoronto.ca"})
        assert direct.status_code == 409
        for n in range(2):
            visitor.post("/api/access-requests", json={**ASK, "email": f"g{n}@example.com"})
        full = visitor.post("/api/access-requests", json={**ASK, "email": "g9@example.com"})
        assert full.status_code == 429


class FakeCognito:
    class exceptions:
        UsernameExistsException = type("UsernameExistsException", (ClientError,), {})
        UnsupportedUserStateException = type("UnsupportedUserStateException", (ClientError,), {})

    def __init__(self, existing=None):
        self.existing = existing
        self.calls = []

    def admin_create_user(self, **args):
        self.calls.append(args)
        resend = args.get("MessageAction") == "RESEND"
        if self.existing and not resend:
            raise self.exceptions.UsernameExistsException({"Error": {}}, "AdminCreateUser")
        if self.existing == "confirmed":
            raise self.exceptions.UnsupportedUserStateException({"Error": {}}, "AdminCreateUser")


ISSUER = "https://cognito-idp.ca-central-1.amazonaws.com/ca-central-1_Pool"


def test_cognito_creates_resends_and_refuses_existing_accounts():
    client = FakeCognito()
    CognitoInviter(ISSUER, "https://academy.example", client).invite("g@example.com")
    [call] = client.calls
    assert call["UserPoolId"] == "ca-central-1_Pool" and call["Username"] == "g@example.com"
    assert call["DesiredDeliveryMediums"] == ["EMAIL"] and "TemporaryPassword" not in call
    assert call["ClientMetadata"] == {"app_url": "https://academy.example"}

    client = FakeCognito(existing="waiting")
    CognitoInviter(ISSUER, "https://academy.example", client).invite("g@example.com")
    assert client.calls[-1]["MessageAction"] == "RESEND"

    with pytest.raises(HTTPException) as refused:
        CognitoInviter(ISSUER, "https://academy.example", FakeCognito("confirmed")).invite(
            "g@example.com"
        )
    assert refused.value.status_code == 409
    with pytest.raises(ValueError):
        CognitoInviter("https://evil.example/pool", "https://academy.example")


def test_admission_key_is_stable_per_address():
    assert Admission.key("a@example.com") == Admission.key("a@example.com")
    assert Admission.key("a@example.com") != Admission.key("b@example.com")
