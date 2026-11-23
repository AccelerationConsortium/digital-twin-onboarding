import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "pre_signup", Path(__file__).resolve().parents[3] / "platform/cognito/pre_signup.py"
)
signup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signup)


def event(email="learner@utoronto.ca", trigger="PreSignUp_SignUp"):
    return {
        "triggerSource": trigger,
        "request": {
            "userAttributes": {"email": email, "email_verified": "true"},
            "clientMetadata": {"role": "admin", "autoConfirmUser": "true"},
        },
        "response": {"autoConfirmUser": True, "autoVerifyEmail": True},
    }


@pytest.fixture(autouse=True)
def allowed_domains(monkeypatch):
    monkeypatch.setenv("SELF_SIGNUP_EMAIL_DOMAINS", '["utoronto.ca", "mail.utoronto.ca"]')


@pytest.mark.parametrize(
    "email",
    [
        "learner@utoronto.ca",
        "Learner+course@UTORONTO.CA",
        "student@mail.utoronto.ca",
        "Student@MAIL.UTORONTO.CA",
    ],
)
def test_eligible_learners_still_require_email_confirmation(email):
    result = signup.handler(event(email), None)
    assert result["response"] == {
        "autoConfirmUser": False,
        "autoVerifyEmail": False,
        "autoVerifyPhone": False,
    }
    assert "groupsToOverride" not in json.dumps(result["response"])


@pytest.mark.parametrize(
    "email",
    [
        "learner@gmail.com",
        "learner@sub.mail.utoronto.ca",
        "learner@mail.utoronto.ca.evil.example",
        "learner@notmail.utoronto.ca",
        "learner@utoronto.ca.evil.example",
        "learner@notutoronto.ca",
        "learner@utоronto.ca",  # Cyrillic o
        "learner@utoronto.ca ",
        " learner@utoronto.ca",
        "learner\n@utoronto.ca",
        "learner@utoronto.ca@evil.example",
        "@utoronto.ca",
        "",
        None,
    ],
)
def test_ineligible_or_malformed_email_rejected(email):
    with pytest.raises(ValueError, match="eligible university email"):
        signup.handler(event(email), None)


@pytest.mark.parametrize(
    "domains", ["[]", "null", '"utoronto.ca"', "{}", '["*"]', "[1]", "bad json"]
)
def test_missing_or_malformed_policy_fails_closed(monkeypatch, domains):
    monkeypatch.setenv("SELF_SIGNUP_EMAIL_DOMAINS", domains)
    with pytest.raises(ValueError):
        signup.handler(event(), None)


def test_absent_policy_and_email_fail_closed(monkeypatch):
    monkeypatch.delenv("SELF_SIGNUP_EMAIL_DOMAINS")
    with pytest.raises(ValueError):
        signup.handler(event(), None)
    monkeypatch.setenv("SELF_SIGNUP_EMAIL_DOMAINS", '["utoronto.ca", "mail.utoronto.ca"]')
    request = event()
    del request["request"]["userAttributes"]["email"]
    with pytest.raises(ValueError):
        signup.handler(request, None)


def test_operator_can_invite_other_domains_without_policy():
    request = event("invited@example.com", "PreSignUp_AdminCreateUser")
    request["response"] = {}
    assert signup.handler(request, None) == request


@pytest.mark.parametrize(
    "trigger", ["PreSignUp_ExternalProvider", "PostConfirmation_ConfirmSignUp", "", None]
)
def test_other_trigger_sources_rejected(trigger):
    with pytest.raises(ValueError, match="method is not enabled"):
        signup.handler(event(trigger=trigger), None)


def invited(metadata=None):
    return {
        "triggerSource": "CustomMessage_AdminCreateUser",
        "request": {
            "usernameParameter": "{username}",
            "codeParameter": "{####}",
            "clientMetadata": metadata,
        },
        "response": {"smsMessage": None, "emailMessage": None, "emailSubject": None},
    }


def test_invitation_email_carries_credentials_and_the_operators_link():
    message = signup.handler(invited({"app_url": "https://academy.example"}), None)["response"]
    assert "{username}" in message["emailMessage"] and "{####}" in message["emailMessage"]
    assert 'href="https://academy.example"' in message["emailMessage"]
    assert message["emailSubject"] == "Your Lab Onboarding invitation"


@pytest.mark.parametrize(
    "metadata",
    [None, {}, {"app_url": "javascript:alert(1)"}, {"app_url": 'https://a.example"><b>'}],
)
def test_invitation_email_never_embeds_an_untrusted_link(metadata):
    message = signup.handler(invited(metadata), None)["response"]["emailMessage"]
    assert "href" not in message and "{username}" in message and "{####}" in message


@pytest.mark.parametrize(
    "trigger", ["CustomMessage_SignUp", "CustomMessage_ForgotPassword", "CustomMessage_ResendCode"]
)
def test_verification_and_recovery_messages_are_untouched(trigger):
    request = invited()
    request["triggerSource"] = trigger
    assert signup.handler(request, None)["response"]["emailMessage"] is None
