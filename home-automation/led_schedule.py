#!/usr/bin/env python3
"""Nightly status-LED schedule for a few bedroom-area switches.

Every night (Shabbat and Yom Tov included) the LEDs in LED_DEVICES go off
at LED_OFF_AT and back on at sunrise. Run from cron every 5 minutes.

Like weekday_automation.py, these are events, not states: each run finds
the most recent event (yesterday's or today's) and fires it once per
device, recording its date+time+action token in .secrets/led_state.json.
So a missed run is caught up on the next one, and a device that didn't
respond is retried every run until it does.

Usage:
    python3 led_schedule.py --zip 07666 [--dry-run] [--now ISO]
"""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

import weekday_automation as wa

HERE = Path(__file__).parent
STATE_PATH = HERE / ".secrets" / "led_state.json"
LOCK_PATH = HERE / ".secrets" / "led_schedule.lock"
LOG_PATH = HERE / "led_schedule.log"
KASA_CLI = HERE / "kasa_cli.py"

LED_DEVICES = ["Main Bedroom ", "Primary Lobby ", "Yaakov Closet"]
LED_OFF_AT = time(23, 30)
RETRIES = 2  # extra attempts per run; kasa switches often fail the first handshake


def _log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def latest_event(zip_code: str, now: datetime) -> tuple[str, str]:
    """(token, "on"|"off") for the most recent LED event at or before `now`."""
    events = []
    for day in (now.date() - timedelta(days=1), now.date()):
        events.append((datetime.combine(day, LED_OFF_AT, tzinfo=now.tzinfo), "off"))
        events.append((wa.zmanim(zip_code, day)["sunrise"], "on"))
    dt, action = max((e for e in events if e[0] <= now), key=lambda e: e[0])
    return f"{dt.isoformat(timespec='minutes')}|{action}", action


def set_led(name: str, action: str) -> bool:
    cmd = [sys.executable, str(KASA_CLI), "led", name, action]
    for _ in range(RETRIES + 1):
        if subprocess.run(cmd, check=False, capture_output=True).returncode == 0:
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", required=True, help="US zip code for sunrise times.")
    parser.add_argument("--dry-run", action="store_true", help="Log what would change, but don't actually act.")
    parser.add_argument("--now", help="ISO datetime to pretend it is (testing; combine with --dry-run).")
    args = parser.parse_args()

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock = LOCK_PATH.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return

    now = datetime.fromisoformat(args.now).astimezone() if args.now else datetime.now().astimezone()
    token, action = latest_event(args.zip, now)
    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    for name in LED_DEVICES:
        if state.get(name) == token:
            continue
        if args.dry_run:
            _log(f"[dry-run] {name.strip()}: LED {action} ({token})")
            continue
        if set_led(name, action):
            state[name] = token
            _log(f"{name.strip()}: LED {action} ({token})")
        else:
            _log(f"{name.strip()}: LED {action} FAILED, will retry next run")
    if not args.dry_run:
        STATE_PATH.write_text(json.dumps(state, indent=2))
        STATE_PATH.chmod(0o600)


if __name__ == "__main__":
    main()
