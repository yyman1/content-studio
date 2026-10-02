#!/usr/bin/env python3
"""One-time cool -> heat switchover, triggered by indoor temperature.

Starting at NOT_BEFORE, for each thermostat in TARGETS, the first run that sees its indoor
temperature at or below SWITCH_AT_F sets its hvacMode to "heat". Each
switch happens once: it's recorded in .secrets/heat_switch_state.json,
and that thermostat is never touched by this script again, so a later
manual change back to cool sticks. Once every target has switched, runs
are no-ops and the cron entry can be removed.

Only hvacMode changes. Setpoints, the program and any holds (e.g.
ecobee_yomtov.py's) are left as they are.

Run from cron every 10 minutes, offset from ecobee_yomtov.py so the two
don't refresh the rotating ecobee token at the same moment.

Usage:
    python3 ecobee_heat_switch.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from ecobee_cli import _get_thermostats, _persist_if_rotated, _refresh_wrapper

HERE = Path(__file__).parent
STATE_PATH = HERE / ".secrets" / "heat_switch_state.json"
LOG_PATH = HERE / "ecobee_heat_switch.log"

TARGETS = ["Bedroom", "Main Floor"]
SWITCH_AT_F = 69.0
NOT_BEFORE = datetime(2026, 10, 3, 16, 0)  # local time; nothing happens before this


def _log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Log what would change, but don't actually act.")
    parser.add_argument("--now", help="ISO datetime to pretend it is (testing; combine with --dry-run).")
    args = parser.parse_args()

    now = datetime.fromisoformat(args.now) if args.now else datetime.now()
    if now < NOT_BEFORE:
        return

    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    if all(name in state for name in TARGETS):
        return

    client, auth = _refresh_wrapper()
    original_rt = auth.refresh_token
    thermostats = _get_thermostats(client)
    _persist_if_rotated(auth, original_rt)

    for t in thermostats:
        name = t.get("name")
        if name not in TARGETS or name in state:
            continue
        temp = t["runtime"]["actualTemperature"] / 10
        mode = t["settings"]["hvacMode"]
        if temp > SWITCH_AT_F:
            continue
        prefix = "[dry-run] " if args.dry_run else ""
        if mode == "heat":
            _log(f"{prefix}{name}: {temp:.1f}F, already on heat")
        else:
            _log(f"{prefix}{name}: {temp:.1f}F, switching {mode} -> heat")
            if not args.dry_run:
                client.update_settings(t["identifier"], {"hvacMode": "heat"})
        if not args.dry_run:
            state[name] = datetime.now().isoformat(timespec="seconds")
            STATE_PATH.write_text(json.dumps(state, indent=2))
            STATE_PATH.chmod(0o600)


if __name__ == "__main__":
    main()
