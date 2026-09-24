#!/usr/bin/env python3
"""Yom Tov thermostat automation -- replicate each thermostat's own
Saturday schedule on Yom Tov days, so nobody has to manually clear the
"away" block by hand every time a holiday falls on a weekday.

Plain weekly Shabbat is left alone entirely: each thermostat's native
Saturday program (day index 5, no "away" slot, later wake-up) is
already correct for it. Only a span whose jewish_calendar label isn't
"Shabbat" -- i.e. an actual holiday -- triggers an override, and only
on the portion of it that isn't already a Saturday.

Ecobee's schedule is a 7 (Sun=0..Sat=6) x 48 (half-hour slots) grid of
climateRefs per thermostat; Python's date.weekday() also returns 5 for
Saturday, so no remapping between the two is needed.

Run every 10 min via cron (see shabbat_automation.py for why polling
beats a precisely-timed one-shot -- same reasoning applies here). Each
run recomputes every thermostat's desired climate from scratch and
only calls the ecobee API when it actually changed since the last
poll (state file), so a missed run or a manual override self-heals on
the next one.

Usage:
    python3 ecobee_yomtov.py --zip 07666 --havdalah-minutes 42
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import jewish_calendar as jc
from ecobee_cli import _get_thermostats, _persist_if_rotated, _refresh_wrapper
from ecobee_client import EcobeeClient

HERE = Path(__file__).parent
STATE_PATH = HERE / ".secrets" / "yomtov_thermostat_state.json"
LOG_PATH = HERE / "ecobee_yomtov.log"

SATURDAY = 5  # both ecobee's schedule day index and date.weekday()


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))
    STATE_PATH.chmod(0o600)


def _log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def _slot_index(now: datetime) -> int:
    return now.hour * 2 + (1 if now.minute >= 30 else 0)


def _is_yomtov_span(span: jc.Span) -> bool:
    return span.label != "Shabbat"


def desired_climate(thermostat: dict[str, Any], now: datetime, spans: list[jc.Span]) -> Optional[str]:
    """Return the climateRef to hold, or None to leave the thermostat
    on its native program."""
    if now.weekday() == SATURDAY:
        return None
    span = next((s for s in spans if s.start <= now < s.end), None)
    if span is None or not _is_yomtov_span(span):
        return None
    schedule = thermostat.get("program", {}).get("schedule", [])
    if len(schedule) <= SATURDAY:
        return None
    saturday_row = schedule[SATURDAY]
    slot = _slot_index(now)
    if slot >= len(saturday_row):
        return None
    return saturday_row[slot]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", required=True, help="US zip code for candle-lighting/havdalah times.")
    parser.add_argument("--havdalah-minutes", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="Log what would change, but don't actually act.")
    args = parser.parse_args()

    now = datetime.now().astimezone()
    spans = jc.fetch_spans(args.zip, args.havdalah_minutes)

    client, auth = _refresh_wrapper()
    original_rt = auth.refresh_token
    thermostats = _get_thermostats(client)
    _persist_if_rotated(auth, original_rt)

    state = _load_state()
    changed = 0
    for t in thermostats:
        identifier = t["identifier"]
        name = t.get("name", identifier)
        desired = desired_climate(t, now, spans)
        previous = state.get(identifier)
        if desired == previous:
            continue
        changed += 1
        if args.dry_run:
            _log(f"[dry-run] {name}: {previous!r} -> {desired!r}")
        else:
            _log(f"{name}: {previous!r} -> {desired!r}")
            if desired is None:
                client.resume_program(identifier)
            else:
                client.set_hold(identifier, hold_climate_ref=desired, hold_type="indefinite")
        state[identifier] = desired

    if changed:
        if not args.dry_run:
            _save_state(state)
        _log(f"Done: {changed} thermostat(s) changed.")


if __name__ == "__main__":
    main()
