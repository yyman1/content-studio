#!/usr/bin/env python3
"""Heated-blanket schedule for the "Blanket " plug.

Every night (Shabbat and Yom Tov included): on at 21:00 on Friday and
22:00 every other night, off at 23:30. On every Shabbat/Yom Tov day
(14:00 falls inside a candle-lighting -> havdalah span): on at 14:00,
off at 16:00.

An "on" is skipped when the outside temperature (Open-Meteo, Teaneck) is
WARM_F or warmer at the time the "on" fires. The decision is made once
per event and is not revisited if it cools off later in the window. If
the temperature can't be fetched, the blanket goes on anyway.

Like led_schedule.py, these are events, not states: each run finds the
most recent event (yesterday's or today's) and fires it once, recording
its date+time+action token in .secrets/blanket_state.json. So a missed
run is caught up on the next one, a plug that didn't respond is retried
every run until it does, and a manual flip is left alone until the next
event. Run from cron every 5 minutes.

Usage:
    python3 blanket_schedule.py --zip 07666 --havdalah-minutes 42 [--dry-run] [--now ISO]
"""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

import requests

import jewish_calendar as jc
import weekday_automation as wa

HERE = Path(__file__).parent
STATE_PATH = HERE / ".secrets" / "blanket_state.json"
LOCK_PATH = HERE / ".secrets" / "blanket_schedule.lock"
LOG_PATH = HERE / "blanket_schedule.log"
KASA_CLI = HERE / "kasa_cli.py"

DEVICE = "Blanket "
FRIDAY = 4  # datetime.weekday()
NIGHT_ON_FRIDAY = time(21, 0)
NIGHT_ON = time(22, 0)
NIGHT_OFF = time(23, 30)
DAY_ON = time(14, 0)
DAY_OFF = time(16, 0)
WARM_F = 68.0
LAT, LON = 40.89, -74.01  # Teaneck, NJ 07666
RETRIES = 2  # extra attempts per run; kasa switches often fail the first handshake


def _log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def is_yomtov_day(day: date, tz, spans: list[jc.Span]) -> bool:
    noonish = datetime.combine(day, DAY_ON, tzinfo=tz)
    return any(s.start <= noonish < s.end for s in spans)


def latest_event(now: datetime, spans: list[jc.Span]) -> tuple[str, str]:
    """(token, "on"|"off") for the most recent blanket event at or before `now`."""
    events = []
    for day in (now.date() - timedelta(days=1), now.date()):
        night_on = NIGHT_ON_FRIDAY if day.weekday() == FRIDAY else NIGHT_ON
        events.append((datetime.combine(day, night_on, tzinfo=now.tzinfo), "on"))
        events.append((datetime.combine(day, NIGHT_OFF, tzinfo=now.tzinfo), "off"))
        if is_yomtov_day(day, now.tzinfo, spans):
            events.append((datetime.combine(day, DAY_ON, tzinfo=now.tzinfo), "on"))
            events.append((datetime.combine(day, DAY_OFF, tzinfo=now.tzinfo), "off"))
    dt, action = max((e for e in events if e[0] <= now), key=lambda e: e[0])
    return f"{dt.isoformat(timespec='minutes')}|{action}", action


def outside_temp_f() -> Optional[float]:
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": LAT, "longitude": LON, "current": "temperature_2m", "temperature_unit": "fahrenheit"},
            timeout=15,
        )
        resp.raise_for_status()
        return float(resp.json()["current"]["temperature_2m"])
    except Exception as ex:  # noqa: BLE001 -- any network/parse failure
        _log(f"outside temperature unavailable ({type(ex).__name__}: {ex})")
        return None


def set_power(action: str) -> bool:
    cmd = [sys.executable, str(KASA_CLI), action, DEVICE]
    for _ in range(RETRIES + 1):
        if subprocess.run(cmd, check=False, capture_output=True).returncode == 0:
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", required=True, help="US zip code for the Jewish calendar.")
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
    events = wa.load_events(args.zip, args.havdalah_minutes)
    spans = jc.fetch_spans(args.zip, args.havdalah_minutes, events=events)
    token, action = latest_event(now, spans)
    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    if state.get(DEVICE) == token:
        return

    prefix = "[dry-run] " if args.dry_run else ""
    if action == "on":
        temp = outside_temp_f()
        if temp is not None and temp >= WARM_F:
            _log(f"{prefix}Blanket: skipping on, outside is {temp:.0f}F ({token})")
            if not args.dry_run:
                state[DEVICE] = token
                STATE_PATH.write_text(json.dumps(state, indent=2))
            return
        temp_note = f", outside {temp:.0f}F" if temp is not None else ""
    else:
        temp_note = ""

    if args.dry_run:
        _log(f"[dry-run] Blanket: {action} ({token}{temp_note})")
        return
    if set_power(action):
        state[DEVICE] = token
        _log(f"Blanket: {action} ({token}{temp_note})")
    else:
        _log(f"Blanket: {action} FAILED, will retry next run")
    STATE_PATH.write_text(json.dumps(state, indent=2))
    STATE_PATH.chmod(0o600)


if __name__ == "__main__":
    main()
