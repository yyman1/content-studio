#!/usr/bin/env python3
"""Command-line tool for reading/controlling an ecobee thermostat.

Usage:
    python ecobee_cli.py login
    python ecobee_cli.py status
    python ecobee_cli.py set-temp --heat 68 --cool 76 [--hold-type indefinite]
    python ecobee_cli.py away
    python ecobee_cli.py home
    python ecobee_cli.py resume

Run `login` once interactively to get a refresh token stored locally in
.secrets/ecobee_token.json (gitignored). Every other command reuses it and
refreshes the access token automatically -- no browser interaction needed
after that, unless ecobee invalidates the refresh token (rare) or you have
MFA and are logging in fresh.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from ecobee_auth import (
    EcobeeAuth,
    InvalidCredentialsError,
    InvalidGrantError,
    MFACodeExpiredError,
    MFACodeInvalidError,
    MFACodeRequiredError,
)
from ecobee_client import EcobeeAuthError, EcobeeClient

TOKEN_PATH = Path(__file__).parent / ".secrets" / "ecobee_token.json"


def _load_auth() -> EcobeeAuth:
    if not TOKEN_PATH.exists():
        print("No saved credentials found. Run `python ecobee_cli.py login` first.", file=sys.stderr)
        sys.exit(1)
    data = json.loads(TOKEN_PATH.read_text())
    return EcobeeAuth.from_storage(data["refresh_token"], email=data.get("email"))


def _save_auth(auth: EcobeeAuth) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps({"email": auth.email, "refresh_token": auth.refresh_token}))
    TOKEN_PATH.chmod(0o600)


def cmd_login(_args: argparse.Namespace) -> None:
    email = input("Ecobee email: ").strip()
    password = getpass.getpass("Ecobee password: ")
    try:
        auth = EcobeeAuth.login(email, password)
    except MFACodeRequiredError as ex:
        print(f"MFA required ({ex.challenge_type}).")
        code = input("Enter the code: ").strip()
        try:
            auth = EcobeeAuth.continue_with_mfa_code(ex, code)
        except (MFACodeInvalidError, MFACodeExpiredError) as ex2:
            print(f"Login failed: {ex2}", file=sys.stderr)
            sys.exit(1)
    except InvalidCredentialsError as ex:
        print(f"Login failed: {ex}", file=sys.stderr)
        sys.exit(1)

    _save_auth(auth)
    print(f"Logged in as {auth.email}. Refresh token saved to {TOKEN_PATH}.")


def _refresh_wrapper() -> EcobeeClient:
    auth = _load_auth()
    client = EcobeeClient(auth)
    return client, auth


def _persist_if_rotated(auth: EcobeeAuth, original_refresh_token: str) -> None:
    if auth.refresh_token != original_refresh_token:
        _save_auth(auth)


def _get_thermostats(client: EcobeeClient) -> list[dict]:
    try:
        return client.get_thermostats()
    except EcobeeAuthError as ex:
        print(f"Auth error talking to ecobee: {ex}\nTry `python ecobee_cli.py login` again.", file=sys.stderr)
        sys.exit(1)


def cmd_status(_args: argparse.Namespace) -> None:
    client, auth = _refresh_wrapper()
    original_rt = auth.refresh_token
    thermostats = _get_thermostats(client)
    if not thermostats:
        print("No thermostats found on this account.")
        return
    for t in thermostats:
        runtime = t.get("runtime", {})
        temp = runtime.get("actualTemperature")
        humidity = runtime.get("actualHumidity")
        settings = t.get("settings", {})
        print(f"{t.get('name') or t.get('identifier')} (id={t.get('identifier')})")
        print(f"  mode: {settings.get('hvacMode')}")
        if temp is not None:
            print(f"  temperature: {temp / 10:.1f}F  humidity: {humidity}%")
        events = t.get("events", [])
        active_holds = [e for e in events if e.get("running") and e.get("type") == "hold"]
        if active_holds:
            h = active_holds[0]
            print(
                f"  active hold: heat={h.get('heatHoldTemp', 0) / 10:.1f}F "
                f"cool={h.get('coolHoldTemp', 0) / 10:.1f}F"
            )
        else:
            print("  no active hold (following schedule)")
    _persist_if_rotated(auth, original_rt)


def _first_identifier(client: EcobeeClient, thermostat_id: str | None) -> str:
    if thermostat_id:
        return thermostat_id
    thermostats = _get_thermostats(client)
    if not thermostats:
        print("No thermostats found on this account.", file=sys.stderr)
        sys.exit(1)
    return thermostats[0]["identifier"]


def cmd_set_temp(args: argparse.Namespace) -> None:
    client, auth = _refresh_wrapper()
    original_rt = auth.refresh_token
    identifier = _first_identifier(client, args.thermostat_id)
    client.set_hold(
        identifier,
        heat_hold_temp_f10=int(args.heat * 10) if args.heat is not None else None,
        cool_hold_temp_f10=int(args.cool * 10) if args.cool is not None else None,
        hold_type=args.hold_type,
    )
    print(f"Hold set on {identifier}: heat={args.heat} cool={args.cool} ({args.hold_type})")
    _persist_if_rotated(auth, original_rt)


def cmd_climate_hold(args: argparse.Namespace, climate_ref: str) -> None:
    client, auth = _refresh_wrapper()
    original_rt = auth.refresh_token
    identifier = _first_identifier(client, args.thermostat_id)
    client.set_hold(identifier, hold_climate_ref=climate_ref, hold_type=args.hold_type)
    print(f"Hold set on {identifier}: climate={climate_ref} ({args.hold_type})")
    _persist_if_rotated(auth, original_rt)


def cmd_away(args: argparse.Namespace) -> None:
    cmd_climate_hold(args, "away")


def cmd_home(args: argparse.Namespace) -> None:
    cmd_climate_hold(args, "home")


def cmd_resume(args: argparse.Namespace) -> None:
    client, auth = _refresh_wrapper()
    original_rt = auth.refresh_token
    identifier = _first_identifier(client, args.thermostat_id)
    client.resume_program(identifier)
    print(f"Resumed schedule on {identifier}.")
    _persist_if_rotated(auth, original_rt)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="Log in interactively and store a refresh token.").set_defaults(func=cmd_login)
    sub.add_parser("status", help="Print current thermostat state.").set_defaults(func=cmd_status)

    p_set = sub.add_parser("set-temp", help="Set a temperature hold.")
    p_set.add_argument("--heat", type=float, help="Heat setpoint in F.")
    p_set.add_argument("--cool", type=float, help="Cool setpoint in F.")
    p_set.add_argument("--hold-type", default="nextTransition", choices=["nextTransition", "indefinite"])
    p_set.add_argument("--thermostat-id", help="Target a specific thermostat identifier.")
    p_set.set_defaults(func=cmd_set_temp)

    for name, fn in (("away", cmd_away), ("home", cmd_home)):
        p = sub.add_parser(name, help=f"Apply the '{name}' comfort setting as a hold.")
        p.add_argument("--hold-type", default="nextTransition", choices=["nextTransition", "indefinite"])
        p.add_argument("--thermostat-id", help="Target a specific thermostat identifier.")
        p.set_defaults(func=fn)

    p_resume = sub.add_parser("resume", help="Clear holds and resume the schedule.")
    p_resume.add_argument("--thermostat-id", help="Target a specific thermostat identifier.")
    p_resume.set_defaults(func=cmd_resume)

    args = parser.parse_args()
    try:
        args.func(args)
    except InvalidGrantError:
        print("Refresh token was revoked/expired. Run `python ecobee_cli.py login` again.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
