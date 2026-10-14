#!/usr/bin/env python3
"""Turn the closet lights off after they've been on for 15 minutes.

Run from cron every 5 minutes. Each run checks whether each device in
CLOSETS is on. The first run that sees a closet on records the time in
.secrets/closet_auto_off_state.json. Once it has been on for AUTO_OFF
(so 15-20 minutes, given the 5-minute cron), the light is turned off.
A run that finds it off clears the entry.

Paused from 1h before candle-lighting until havdalah (weekday_automation's
"Shabbat regime"), so it doesn't cut off shabbat_automation.py's SL Closet
windows (on 1h before candle-lighting, 9-12 on Yom Tov days, 1h before
havdalah). The calendar comes from weekday_automation's 6h cache and is
only consulted when a light is actually due to go off. If no calendar is
available at all, the light stays on, so a network hiccup can't switch a
light off on Shabbat.

Usage:
    python3 closet_auto_off.py --zip 07666 [--havdalah-minutes 42] [--dry-run] [--now ISO]
"""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import jewish_calendar as jc
import weekday_automation as wa

HERE = Path(__file__).parent
STATE_PATH = HERE / ".secrets" / "closet_auto_off_state.json"
LOCK_PATH = HERE / ".secrets" / "closet_auto_off.lock"
LOG_PATH = HERE / "closet_auto_off.log"
KASA_CLI = HERE / "kasa_cli.py"

CLOSETS = ["Yaakov Closet", "SL Closet"]
AUTO_OFF = timedelta(minutes=15)
RETRIES = 2  # extra attempts per run; kasa switches often fail the first handshake


def _log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def _kasa(*args: str) -> subprocess.CompletedProcess | None:
    cmd = [sys.executable, str(KASA_CLI), *args]
    for _ in range(RETRIES + 1):
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode == 0:
            return result
    return None


def is_on(name: str) -> bool | None:
    """True/False from the switch, or None if it couldn't be reached."""
    result = _kasa("status", name)
    if result is None:
        return None
    return "on=True" in result.stdout.splitlines()[0]


def paused(zip_code: str, havdalah_minutes: int, now: datetime) -> bool:
    events = wa.load_events(zip_code, havdalah_minutes)
    return wa.in_shabbat_regime(now, jc.fetch_spans(zip_code, havdalah_minutes, events=events))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", required=True, help="US zip code for candle-lighting/havdalah times.")
    parser.add_argument("--havdalah-minutes", type=int, default=42)
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
    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    on_shabbat: bool | None = None  # looked up lazily, at most once per run

    for name in CLOSETS:
        on = is_on(name)
        if on is None:
            continue  # unreachable; keep any recorded on-time and try next run
        if not on:
            state.pop(name, None)
            continue
        if name not in state:
            state[name] = now.isoformat(timespec="seconds")
            continue
        if now - datetime.fromisoformat(state[name]) < AUTO_OFF:
            continue

        if on_shabbat is None:
            try:
                on_shabbat = paused(args.zip, args.havdalah_minutes, now)
            except Exception as ex:  # noqa: BLE001
                _log(f"Hebcal lookup failed ({ex}); leaving closets on this run")
                break
        if on_shabbat:
            continue
        if args.dry_run:
            _log(f"[dry-run] {name}: on since {state[name]}, would turn off")
        elif _kasa("off", name):
            _log(f"{name}: on since {state[name]}, turned off")
            state.pop(name)
        else:
            _log(f"{name}: off FAILED, will retry next run")

    if not args.dry_run:
        STATE_PATH.write_text(json.dumps(state, indent=2))
        STATE_PATH.chmod(0o600)


if __name__ == "__main__":
    main()
