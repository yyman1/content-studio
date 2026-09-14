"""Auth0 Authorization Code + PKCE + universal-login against ecobee's tenant.

ecobee shut down public developer-portal API-key registration, so the
old PIN/API-key flow can no longer be set up by new users. This module
logs in with a plain ecobee.com email + password instead, by driving the
same Auth0 Authorization Code + PKCE + universal-login flow ecobee.com's
own website uses. MFA is handled natively by Auth0's hosted prompt
pages -- we just follow the redirect chain and, if a code-entry prompt
shows up, ask the caller for the code.

This is not a documented public API: it is the same flow the ecobee
website itself performs, adapted from the community ha-ecobee Home
Assistant integration (https://github.com/pjordanandrsn/ha-ecobee),
which exists for the same reason (dev-portal registration is closed).
It can break if ecobee changes their Auth0 login pages.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
import urllib.parse
from typing import Optional

import requests

AUTH0_DOMAIN = "auth.ecobee.com"

# /authorize is the universal-login entry point. We GET it with the PKCE
# challenge + state and follow the redirect to /u/login/identifier.
AUTHORIZE_URL = f"https://{AUTH0_DOMAIN}/authorize"

# /authorize/resume is what Auth0 redirects to after every /u/* prompt
# step (login, MFA, T&C). It either chains to another /u/* page or
# redirects to REDIRECT_URI with the auth code.
RESUME_URL = f"https://{AUTH0_DOMAIN}/authorize/resume"

# /u/login/identifier accepts the email; /u/login/password accepts the
# password. Both are POSTed with form-encoded bodies.
IDENTIFIER_URL = f"https://{AUTH0_DOMAIN}/u/login/identifier"
PASSWORD_URL = f"https://{AUTH0_DOMAIN}/u/login/password"

# code -> tokens, refresh_token -> tokens.
TOKEN_URL = f"https://{AUTH0_DOMAIN}/oauth/token"

# The web-app callback URL. Auth0 redirects here with ?code=&state= after
# a successful login. We never actually navigate to it -- we just parse
# the params from the Location header on the final redirect.
REDIRECT_URI = "https://www.ecobee.com/home/authCallback"

# The public web-app client_id ecobee.com itself ships in plain JS. No
# client_secret is needed for an Auth0 public client doing
# authorization-code + PKCE.
WEB_CLIENT_ID = "183eORFPlXyz9BbDZwqexHPBQoVjgadh"

# Audience claim Auth0 audits the access_token against.
AUDIENCE = "https://prod.ecobee.com/api/v1"

# offline_access is what makes Auth0 issue a refresh_token; without it
# we'd need to interactively re-login on every access-token expiry.
SCOPES = "openid smartRead smartWrite piiRead piiWrite offline_access"

USER_AGENT_WEB = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.0 Safari/605.1.15"
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636 S256."""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class InvalidGrantError(Exception):
    """The refresh token has been invalidated server-side; re-login needed."""


class InvalidCredentialsError(Exception):
    """The supplied email/password was rejected at login."""


class MFACodeRequiredError(Exception):
    """Auth0 surfaced a code-entry MFA prompt; caller must supply a code.

    Carries everything needed to resume via continue_with_mfa_code().
    """

    def __init__(
        self,
        *,
        prompt_url: str,
        state: str,
        challenge_type: str,
        verifier: str = "",
        email: str = "",
    ) -> None:
        super().__init__(f"MFA code required: type={challenge_type}")
        self.prompt_url = prompt_url
        self.state = state
        self.challenge_type = challenge_type
        self.verifier = verifier
        self.email = email


class MFACodeInvalidError(Exception):
    """The submitted MFA code was rejected by Auth0."""


class MFACodeExpiredError(Exception):
    """The MFA prompt's state expired (~10 min); restart from login()."""


# ---------------------------------------------------------------------------
# Login flow (one-shot, run once to obtain a refresh token)
# ---------------------------------------------------------------------------


def _authorize(session: requests.Session, state: str, challenge: str) -> str:
    """GET /authorize and follow the redirect to /u/login/identifier."""
    params = {
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "audience": AUDIENCE,
        "state": state,
        "client_id": WEB_CLIENT_ID,
        "prompt": "login",
    }
    headers = {"User-Agent": USER_AGENT_WEB, "Accept": "text/html,*/*"}
    resp = session.get(
        AUTHORIZE_URL, params=params, headers=headers, allow_redirects=False
    )
    if resp.status_code not in (302, 303):
        raise RuntimeError(
            f"step=authorize: expected 302/303, got {resp.status_code}; "
            f"body={resp.text[:200]!r}"
        )
    loc = resp.headers["Location"]
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    if "state" not in qs:
        raise RuntimeError(f"step=authorize: no state in redirect loc={loc!r}")
    return qs["state"][0]


def _post_login_form(
    session: requests.Session, url: str, state: str, form: dict
) -> str:
    """POST a /u/login/* form. Return the redirect Location on success."""
    headers = {
        "User-Agent": USER_AGENT_WEB,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/html,*/*",
        "Origin": f"https://{AUTH0_DOMAIN}",
        "Referer": f"{url}?state={state}",
    }
    resp = session.post(
        url, params={"state": state}, data=form, headers=headers, allow_redirects=False
    )
    if resp.status_code not in (302, 303):
        text = resp.text
        m = re.search(r'data-error-code="([^"]+)"', text)
        code = m.group(1) if m else None
        if code:
            if any(
                s in code.lower()
                for s in ("password", "credential", "user", "lock", "blocked")
            ):
                raise InvalidCredentialsError(f"login rejected ({code})")
            raise RuntimeError(
                f"step=login_form url={url} status={resp.status_code} auth0_code={code}"
            )
        raise RuntimeError(
            f"step=login_form url={url} status={resp.status_code} "
            f"no_code body={text[:200]!r}"
        )
    return resp.headers["Location"]


def _identifier_step(session: requests.Session, state: str, email: str) -> str:
    """POST /u/login/identifier with the email; advance to /u/login/password."""
    form = {
        "state": state,
        "username": email,
        "js-available": "true",
        "webauthn-available": "true",
        "is-brave": "false",
        "webauthn-platform-available": "true",
        "action": "default",
    }
    loc = _post_login_form(session, IDENTIFIER_URL, state, form)
    parsed = urllib.parse.urlparse(loc)
    if not parsed.path.endswith("/u/login/password"):
        raise InvalidCredentialsError("email not recognized")
    return urllib.parse.parse_qs(parsed.query)["state"][0]


def _password_step(
    session: requests.Session, state: str, email: str, password: str
) -> str:
    """POST /u/login/password; advance to /authorize/resume."""
    form = {"state": state, "username": email, "password": password, "action": "default"}
    loc = _post_login_form(session, PASSWORD_URL, state, form)
    parsed = urllib.parse.urlparse(loc)
    if not parsed.path.endswith("/authorize/resume"):
        raise InvalidCredentialsError(f"step=password: rejected loc={loc!r}")
    return urllib.parse.parse_qs(parsed.query)["state"][0]


def _resume_to_code(session: requests.Session, resume_state: str) -> str:
    """GET /authorize/resume and turn the eventual web callback into a code.

    Loops to handle Auth0 prompt redirects (T&C updates, cookie consent,
    MFA challenges, profile completion, etc.) that chain between password
    submit and the final code redirect.
    """
    headers = {"User-Agent": USER_AGENT_WEB, "Accept": "text/html,*/*"}
    for _ in range(5):
        resp = session.get(
            RESUME_URL, params={"state": resume_state}, headers=headers, allow_redirects=False
        )
        if resp.status_code not in (302, 303):
            raise RuntimeError(
                f"step=resume: expected 302/303, got {resp.status_code}; "
                f"body={resp.text[:200]!r}"
            )
        loc = resp.headers["Location"]

        if loc.startswith(REDIRECT_URI) or loc.startswith(
            "https://www.ecobee.com/home/authCallback"
        ):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
            if "code" not in qs:
                raise RuntimeError(f"step=resume: no code in redirect loc={loc!r}")
            return qs["code"][0]

        if "/u/" in loc:
            resume_state = _handle_custom_prompt(session, loc)
            continue

        raise RuntimeError(f"step=resume: unexpected scheme loc={loc!r}")

    raise RuntimeError(
        "step=resume: 5 consecutive Auth0 prompts without reaching the "
        "callback redirect. Sign in to https://www.ecobee.com from a "
        "browser, complete any pending prompts (T&C, MFA setup, profile "
        "completion), then retry."
    )


def _handle_custom_prompt(session: requests.Session, loc: str) -> str:
    """POST an Auth0 /u/* prompt page back to itself; return next resume state.

    Auth0 universal-login pages are React-rendered, so the visible form
    can't be found by static HTML parsing. The POST endpoint is always
    the same path the GET landed on, and the body is always
    state=<state>&action=default for the primary button.

    Code-entry MFA prompts (a 6-digit code the user must type) can't be
    auto-submitted this way -- those raise MFACodeRequiredError instead.
    """
    abs_url = loc if loc.startswith("http") else f"https://{AUTH0_DOMAIN}{loc}"
    parsed = urllib.parse.urlparse(abs_url)
    qs = urllib.parse.parse_qs(parsed.query)
    state = qs.get("state", [""])[0]
    if not state:
        raise RuntimeError(f"step=custom-prompt: no state in url={abs_url!r}")

    if re.search(r"/u/mfa-(otp|sms|recovery-code)(-challenge)?(/|\?|$)", parsed.path):
        challenge_type = (
            "otp" if "otp" in parsed.path else ("sms" if "sms" in parsed.path else "recovery")
        )
        raise MFACodeRequiredError(prompt_url=abs_url, state=state, challenge_type=challenge_type)

    headers_post = {
        "User-Agent": USER_AGENT_WEB,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/html,*/*",
        "Origin": f"https://{AUTH0_DOMAIN}",
        "Referer": abs_url,
    }
    body = {"state": state, "action": "default"}
    resp = session.post(abs_url, data=body, headers=headers_post, allow_redirects=False)
    if resp.status_code not in (302, 303):
        raise RuntimeError(
            f"step=custom-prompt: POST {abs_url[:120]} -> {resp.status_code} "
            f"(expected 302/303). The prompt likely requires interactive "
            f"action (email verification, MFA setup, profile completion). "
            f"Sign in to https://www.ecobee.com from a browser, complete "
            f"any pending step shown there, then retry."
        )
    new_loc = resp.headers["Location"]

    parsed_new = urllib.parse.urlparse(new_loc)
    if parsed_new.path.endswith("/authorize/resume"):
        new_qs = urllib.parse.parse_qs(parsed_new.query)
        if "state" not in new_qs:
            raise RuntimeError(f"step=custom-prompt: no state in loc={new_loc!r}")
        return new_qs["state"][0]
    if "/u/" in new_loc:
        chained_state = urllib.parse.parse_qs(parsed_new.query).get("state", [""])[0]
        if not chained_state:
            raise RuntimeError(f"step=custom-prompt: chained prompt has no state: {new_loc!r}")
        return chained_state
    raise RuntimeError(f"step=custom-prompt: unexpected redirect target loc={new_loc!r}")


def _exchange_code(session: requests.Session, code: str, verifier: str) -> dict:
    """POST /oauth/token grant_type=authorization_code; return token payload."""
    body = {
        "grant_type": "authorization_code",
        "client_id": WEB_CLIENT_ID,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    resp = session.post(TOKEN_URL, data=body, headers=headers)
    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text}
    if resp.status_code == 200:
        return payload
    raise RuntimeError(f"code exchange failed: {resp.status_code} {payload}")


# ---------------------------------------------------------------------------
# EcobeeAuth -- the main reusable handle
# ---------------------------------------------------------------------------


class EcobeeAuth:
    """Holds the long-lived refresh token and mints fresh access tokens."""

    _ACCESS_TOKEN_LEEWAY = 60

    def __init__(self, refresh_token: str, *, email: Optional[str] = None) -> None:
        self._session = requests.Session()
        self._refresh_token = refresh_token
        self._email = email
        self._access_token: Optional[str] = None
        self._access_token_exp: float = 0.0

    @classmethod
    def login(cls, email: str, password: str) -> "EcobeeAuth":
        """Run the full Auth0 universal-login flow and return a ready instance.

        Raises InvalidCredentialsError, MFACodeRequiredError, or
        RuntimeError on unexpected failures.
        """
        session = requests.Session()
        verifier, challenge = _make_pkce()
        state = _b64url(secrets.token_bytes(32))

        login_state = _authorize(session, state, challenge)
        pw_state = _identifier_step(session, login_state, email)
        resume_state = _password_step(session, pw_state, email, password)
        try:
            code = _resume_to_code(session, resume_state)
        except MFACodeRequiredError as ex:
            ex.verifier = verifier
            ex.email = email
            ex.prompt_url = getattr(ex, "prompt_url", "")
            # Stash the session on the exception so continue_with_mfa_code
            # can reuse the same cookie jar.
            ex.session = session  # type: ignore[attr-defined]
            raise
        tokens = _exchange_code(session, code, verifier)

        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise RuntimeError(
                "login: no refresh_token returned (scope did not include offline_access?)"
            )
        auth = cls(refresh_token, email=email)
        auth._session = session
        auth._access_token = tokens["access_token"]
        auth._access_token_exp = time.time() + int(tokens.get("expires_in", 0))
        return auth

    @classmethod
    def continue_with_mfa_code(cls, mfa_error: MFACodeRequiredError, code: str) -> "EcobeeAuth":
        """Resume login after the user provides an MFA code.

        `mfa_error` is the MFACodeRequiredError raised by login().
        """
        session = getattr(mfa_error, "session")
        body = {"state": mfa_error.state, "code": code}
        headers = {
            "User-Agent": USER_AGENT_WEB,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,*/*",
            "Origin": f"https://{AUTH0_DOMAIN}",
            "Referer": mfa_error.prompt_url,
        }
        resp = session.post(
            mfa_error.prompt_url, data=body, headers=headers, allow_redirects=False
        )
        if resp.status_code == 200:
            page = resp.text.lower()
            if "expired" in page:
                raise MFACodeExpiredError("MFA prompt expired; restart from login().")
            raise MFACodeInvalidError("MFA code rejected by Auth0; check the code and retry.")
        if resp.status_code not in (302, 303):
            raise RuntimeError(f"continue_with_mfa_code: POST -> {resp.status_code}")
        new_loc = resp.headers["Location"]

        parsed = urllib.parse.urlparse(new_loc)
        if parsed.path.endswith("/authorize/resume"):
            new_state = urllib.parse.parse_qs(parsed.query).get("state", [""])[0]
            if not new_state:
                raise RuntimeError(f"continue_with_mfa_code: no state in {new_loc!r}")
            auth_code = _resume_to_code(session, new_state)
        elif new_loc.startswith("https://www.ecobee.com/home/authCallback"):
            auth_code = urllib.parse.parse_qs(parsed.query).get("code", [""])[0]
            if not auth_code:
                raise RuntimeError(f"continue_with_mfa_code: callback had no code: {new_loc!r}")
        else:
            raise RuntimeError(f"continue_with_mfa_code: unexpected redirect loc={new_loc!r}")

        tokens = _exchange_code(session, auth_code, mfa_error.verifier)
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("continue_with_mfa_code: no refresh_token returned")
        auth = cls(refresh_token, email=mfa_error.email)
        auth._session = session
        auth._access_token = tokens["access_token"]
        auth._access_token_exp = time.time() + int(tokens.get("expires_in", 0))
        return auth

    @classmethod
    def from_storage(cls, refresh_token: str, *, email: Optional[str] = None) -> "EcobeeAuth":
        """Construct an instance from a previously stored refresh token."""
        return cls(refresh_token, email=email)

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    @property
    def email(self) -> Optional[str]:
        return self._email

    def ensure_access_token(self) -> str:
        """Return a non-expired access token, refreshing if necessary."""
        if self._access_token and time.time() < self._access_token_exp - self._ACCESS_TOKEN_LEEWAY:
            return self._access_token
        self._refresh()
        assert self._access_token is not None
        return self._access_token

    def _refresh(self) -> None:
        body = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": WEB_CLIENT_ID,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        resp = self._session.post(TOKEN_URL, data=body, headers=headers)
        try:
            payload = resp.json()
        except ValueError:
            payload = {"raw": resp.text}

        if resp.status_code == 200:
            self._access_token = payload["access_token"]
            self._access_token_exp = time.time() + int(payload.get("expires_in", 0))
            new_rt = payload.get("refresh_token")
            if new_rt and new_rt != self._refresh_token:
                self._refresh_token = new_rt
            return

        if resp.status_code == 400 and payload.get("error") == "invalid_grant":
            raise InvalidGrantError(payload.get("error_description") or "refresh_token invalid_grant")

        raise RuntimeError(f"ecobee refresh failed: status={resp.status_code} payload={payload}")
