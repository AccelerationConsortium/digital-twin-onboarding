"""Cognito admission policy. Email ownership remains Cognito's responsibility."""

import json
import os
import re


def invitation(event):
    """The email an operator's invitation sends, linked to the inviting deployment."""
    request = event.get("request", {})
    username, code = request.get("usernameParameter"), request.get("codeParameter")
    if not username or not code:
        return event
    # Only IAM-authorized callers can create users, so this link is the operator's own.
    url = (request.get("clientMetadata") or {}).get("app_url", "")
    link = (
        f'Sign in at <a href="{url}">{url}</a> with:'
        if isinstance(url, str) and re.fullmatch(r"https://[a-z0-9.-]+", url)
        else "Sign in with:"
    )
    event["response"] = {
        **(event.get("response") or {}),
        "emailSubject": "Your Lab Onboarding invitation",
        "emailMessage": (
            "You have been invited to Lab Onboarding.<br><br>"
            f"{link}<br>Email: {username}<br>Temporary password: {code}<br><br>"
            "You will choose your own password the first time you sign in. "
            "The temporary password expires in 7 days."
        ),
    }
    return event


def handler(event, context):
    trigger = event.get("triggerSource")
    if trigger == "CustomMessage_AdminCreateUser":
        return invitation(event)
    if isinstance(trigger, str) and trigger.startswith("CustomMessage_"):
        # Verification and recovery messages keep Cognito's own wording.
        return event
    if trigger == "PreSignUp_AdminCreateUser":
        # Operators invite learners from other domains, here or through the application.
        return event
    if trigger != "PreSignUp_SignUp":
        raise ValueError("This registration method is not enabled.")

    domains = json.loads(os.environ.get("SELF_SIGNUP_EMAIL_DOMAINS", "[]"))
    if (
        not isinstance(domains, list)
        or not domains
        or not all(
            isinstance(domain, str)
            and re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,}", domain)
            for domain in domains
        )
    ):
        raise ValueError("Self-registration is not configured.")
    email = event.get("request", {}).get("userAttributes", {}).get("email", "")
    if (
        not isinstance(email, str)
        or not re.fullmatch(r"[^\s@]+@[^\s@]+", email)
        or email.rsplit("@", 1)[1].lower() not in domains
    ):
        raise ValueError("Use an eligible university email, or request access on the welcome page.")

    # Never trust client metadata or supplied email_verified to bypass the email challenge.
    event["response"] = {
        "autoConfirmUser": False,
        "autoVerifyEmail": False,
        "autoVerifyPhone": False,
    }
    return event
