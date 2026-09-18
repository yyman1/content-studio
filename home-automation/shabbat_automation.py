#!/usr/bin/env python3
"""Shabbat / Yom Tov lighting automation.

Run once per invocation (call this from cron every 5-10 minutes -- see
below for why that cadence, not a precisely-timed one-shot). Each run:
  1. Asks jewish_calendar.py what's happening right now and nearby.
  2. Computes the desired state for every configured device.
  3. Compares against the last state we recorded, and only issues a
     kasa_cli.py command when something actually needs to change.
  4. Logs every check and every action taken.

Design notes:

- Polling every 5-10 min rather than firing a single cron entry at each
  exact transition time is deliberate: a precisely-timed one-shot can
  be missed if the Pi is briefly busy, mid-reboot, or the network
  blips, and then never fires again that day. Polling instead means
  the worst case is being a few minutes late, and a missed run gets
  caught by the next one.
- Every device's desired state is recomputed from scratch each run
  (not "fire once at time X") -- this makes the whole thing
  self-healing: if a device got manually flipped, or a run was missed,
  the next poll just corrects it back to whatever it should currently
  be, without needing separate recovery logic.
- "Yom Tov" here means Shabbat too, per how the household actually
  uses the term -- see jewish_calendar.py's current_status(), whose
  "active" flag already covers both.
- Devices not listed in DEVICE_RULES (or listed with no rule) are
  deliberately left alone -- they have an existing schedule that runs
  through the Kasa/Tapo app itself, and this script must never fight
  with that.

Usage:
    python3 shabbat_automation.py --zip 07666 --havdalah-minutes 42
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

import jewish_calendar as jc

HERE = Path(__file__).parent
STATE_PATH = HERE / ".secrets" / "shabbat_state.json"
LOG_PATH = HERE / "shabbat_automation.log"
KASA_CLI = HERE / "kasa_cli.py"

# How far back/forward to look for candle-lighting events relevant to
# "right now". A dimmable device with no yomtov_off/nightly_cutoff
# falls back to re-checking its own dim_at every night of a Shabbat/
# Yom Tov, anchored to its *original* candle-lighting -- even on a
# plain one-candle weekly Shabbat's second night, which needs Friday's
# candle still "in range" as late as Saturday ~11:30pm (worst case:
# Friday's earliest possible candle-lighting, ~4:10pm at winter
# solstice here, to Saturday's latest-used cutoff, 11:30pm -- about
# 31h20m). 36h leaves comfortable margin without fetching the year.
LOOKBACK_HOURS = 36
LOOKFORWARD_HOURS = 3


@dataclass
class DeviceRule:
    evening_start: bool = False  # on from 1h before candle-lighting
    nightly_cutoff: Optional[time] = None  # fixed off time same evening
    relative_off_hours: Optional[float] = None  # off N hours after candle-lighting
    relative_off_cap: Optional[time] = None  # ...but never later than this (same evening)
    dim_at: Optional[time] = None  # dim instead of off, at this time
    dim_pct: int = 0
    off_at_sunrise: bool = False  # after dimming, fully off at the next sunrise
    yomtov_on: Optional[time] = None  # daytime on trigger (any Shabbat/Yom Tov day)
    yomtov_off: Optional[time] = None  # daytime off trigger (optional)
    sukkot_only: bool = False  # evening/nightly rules only apply during Sukkot
    dimmable: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.dimmable = self.dim_at is not None


def _t(hhmm: str) -> time:
    h, m = map(int, hhmm.split(":"))
    return time(h, m)


# From the household's written spec. "yom tov day" rules apply on any
# day covered by jewish_calendar's "active" span (Shabbat included).
# Bar/Dining Room Chandelier's 4-hour rule is capped at 23:00 per
# explicit follow-up ("should go off by 11pm at the latest").
DEVICE_RULES: dict[str, DeviceRule] = {
    # First Floor areas
    "Living Room": DeviceRule(evening_start=True, nightly_cutoff=_t("23:30"), yomtov_on=_t("08:30")),
    "Bar": DeviceRule(
        evening_start=True, relative_off_hours=4, relative_off_cap=_t("23:00"),
        yomtov_on=_t("12:00"), yomtov_off=_t("14:30"),
    ),
    "Dining Room": DeviceRule(evening_start=True, nightly_cutoff=_t("23:30")),
    # "Dining Room Dummy": do nothing -- omitted.
    "Dining Room Chandelier": DeviceRule(
        evening_start=True, relative_off_hours=4, relative_off_cap=_t("23:00"),
        yomtov_on=_t("12:00"), yomtov_off=_t("15:00"),
    ),
    "Kitchen": DeviceRule(evening_start=True, nightly_cutoff=_t("23:30"), yomtov_on=_t("08:00"), yomtov_off=_t("23:30")),
    "Table": DeviceRule(evening_start=True, nightly_cutoff=_t("23:30"), yomtov_on=_t("08:00"), yomtov_off=_t("22:00")),
    "Bathroom First Floor": DeviceRule(
        evening_start=True, nightly_cutoff=_t("23:30"), yomtov_on=_t("12:00"), yomtov_off=_t("23:00")
    ),
    "Family Room": DeviceRule(
        evening_start=True, nightly_cutoff=_t("23:30"), yomtov_on=_t("08:30"), yomtov_off=_t("23:30")
    ),
    # Master Bedrooms / bathrooms
    "Main Bedroom": DeviceRule(
        evening_start=True, relative_off_hours=2, relative_off_cap=_t("22:00"),
        yomtov_on=_t("09:30"), yomtov_off=_t("14:00"),
    ),
    "Primary Lobby": DeviceRule(evening_start=True, relative_off_hours=2, relative_off_cap=_t("22:00")),
    "Master Bathroom": DeviceRule(
        evening_start=True, nightly_cutoff=_t("23:00"), yomtov_on=_t("08:30"), yomtov_off=_t("12:00")
    ),
    # Overnight-only per household confirmation: no Yom Tov daytime behavior.
    "Master Bathroom Toilet": DeviceRule(
        evening_start=True, dim_at=_t("23:00"), dim_pct=15, off_at_sunrise=True
    ),
    # "Blanket": do nothing -- omitted.
    # Kids bathroom
    "Bathroom Upstairs main": DeviceRule(
        evening_start=True, dim_at=_t("23:00"), dim_pct=10, yomtov_on=_t("07:00")
    ),
    "Bathroom Mirror": DeviceRule(evening_start=True, nightly_cutoff=_t("23:00")),
    # Basement
    "Basement": DeviceRule(evening_start=True, nightly_cutoff=_t("23:00")),
    "Basement Playroom": DeviceRule(
        evening_start=True, nightly_cutoff=_t("23:00"), yomtov_on=_t("12:00"), yomtov_off=_t("18:00")
    ),
    # Basement Hallway / Basement Steps: do nothing -- omitted.
    # Entryways / Outdoor -- everything else does nothing; these two are Sukkot-only.
    "Back Porch Side Light": DeviceRule(evening_start=True, nightly_cutoff=_t("23:00"), sukkot_only=True),
    "Driveway Backyard / Side": DeviceRule(evening_start=True, nightly_cutoff=_t("23:00"), sukkot_only=True),
    # Named for a person: do nothing -- omitted.
}


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


def _is_sukkot(day: date, holidays: list[tuple[datetime, str]]) -> bool:
    return any(dt.date() == day and "Sukkot" in title for dt, title in holidays)


def _evening_desired(rule: DeviceRule, now: datetime, candle: datetime, holidays) -> Optional[str]:
    """Return this candle-lighting's contribution to the desired state,
    or None if `now` isn't inside its window."""
    if rule.sukkot_only and not _is_sukkot(candle.date(), holidays):
        return None

    window_start = candle - timedelta(hours=1)
    if now < window_start:
        return None

    if rule.dimmable:
        dim_at_dt = datetime.combine(candle.date(), rule.dim_at, tzinfo=candle.tzinfo)
        if now < dim_at_dt:
            return "on"
        if rule.off_at_sunrise:
            sunrise_dt = jc.sunrise(_ZIP, candle.date() + timedelta(days=1))
            return f"dim:{rule.dim_pct}" if now < sunrise_dt else None
        return f"dim:{rule.dim_pct}"

    if rule.nightly_cutoff is not None:
        cutoff_dt = datetime.combine(candle.date(), rule.nightly_cutoff, tzinfo=candle.tzinfo)
        return "on" if now < cutoff_dt else None

    if rule.relative_off_hours is not None:
        end_dt = candle + timedelta(hours=rule.relative_off_hours)
        if rule.relative_off_cap is not None:
            cap_dt = datetime.combine(candle.date(), rule.relative_off_cap, tzinfo=candle.tzinfo)
            end_dt = min(end_dt, cap_dt)
        return "on" if now < end_dt else None

    return "on"


def _active_at(dt: datetime, spans: list[jc.Span]) -> bool:
    return any(s.start <= dt < s.end for s in spans)


def _yomtov_desired(rule: DeviceRule, now: datetime, spans: list[jc.Span]) -> Optional[str]:
    if rule.yomtov_on is None:
        return None
    on_dt = datetime.combine(now.date(), rule.yomtov_on, tzinfo=now.tzinfo)
    # Check that on_dt itself falls inside a Shabbat/Yom Tov span -- not
    # just that "now" is active. On a plain Friday, "now" (evening) is
    # active once candles are lit, but that same Friday's *morning* was
    # not -- checking only "active now" let a stale "past this morning's
    # trigger time" reading fire off that morning's clock time even
    # though Shabbat hadn't started yet when it passed.
    if not _active_at(on_dt, spans):
        return None
    if now < on_dt:
        return None
    # If no explicit daytime off time was given, fall back to whatever
    # bound the evening rule uses -- a fixed nightly cutoff, or (for a
    # dimmable device with neither) its dim time, so e.g. Bathroom
    # Upstairs main goes back to its 10%-at-11pm dim that same night
    # instead of staying at full brightness with no bound at all.
    off_time = rule.yomtov_off or rule.nightly_cutoff or (rule.dim_at if rule.dimmable else None)
    if off_time is not None:
        off_dt = datetime.combine(now.date(), off_time, tzinfo=now.tzinfo)
        if now >= off_dt:
            return None
    return "on"


def desired_state(
    name: str, rule: DeviceRule, now: datetime, events: jc.Events, spans: list[jc.Span]
) -> str:
    # Yom Tov daytime is checked first: a dim-without-off_at_sunrise rule
    # (e.g. Bathroom Upstairs main) has no natural expiration of its own,
    # so it would otherwise keep "winning" straight through an explicit
    # daytime yomtov_on trigger the next morning and mask it entirely.
    result = _yomtov_desired(rule, now, spans)
    if result is not None:
        return result

    if rule.evening_start:
        # Most-recent-first: with LOOKBACK_HOURS wide enough to span a
        # full weekend, a multi-day chain's second candle-lighting and
        # its first can both be "in range" for the same `now`. A stale
        # first-night candle's indefinite dim-with-no-sunrise-cutoff
        # would otherwise win over the second night's fresher
        # "still lit, not yet its own dim time" window just because it
        # happened to be checked first.
        for candle in reversed(events.candles):
            if now - timedelta(hours=LOOKBACK_HOURS) <= candle <= now + timedelta(hours=LOOKFORWARD_HOURS):
                result = _evening_desired(rule, now, candle, events.holidays)
                if result is not None:
                    return result

    return "off"


def apply_state(name: str, state: str) -> None:
    if state.startswith("dim:"):
        pct = state.split(":", 1)[1]
        subprocess.run([sys.executable, str(KASA_CLI), "brightness", name, pct], check=False)
    elif state == "on":
        # Devices with a dim rule must be explicitly set to full brightness
        # for "on" -- a plain turn_on() would resume at whatever brightness
        # was last set (e.g. still 15% from last night's dim), not full.
        rule = DEVICE_RULES.get(name)
        if rule and rule.dimmable:
            subprocess.run([sys.executable, str(KASA_CLI), "brightness", name, "100"], check=False)
        else:
            subprocess.run([sys.executable, str(KASA_CLI), "on", name], check=False)
    else:
        subprocess.run([sys.executable, str(KASA_CLI), "off", name], check=False)


_ZIP = "07666"  # set from --zip in main(); module-level for _evening_desired's sunrise lookup


def main() -> None:
    global _ZIP
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", required=True, help="US zip code for candle-lighting/havdalah/sunrise times.")
    parser.add_argument("--havdalah-minutes", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="Log what would change, but don't actually act.")
    args = parser.parse_args()
    _ZIP = args.zip

    now = datetime.now().astimezone()
    events = jc.fetch_events(args.zip, args.havdalah_minutes)
    spans = jc.fetch_spans(args.zip, args.havdalah_minutes, events=events)
    status = jc.current_status(args.zip, args.havdalah_minutes, now, spans=spans)

    state = _load_state()
    changed = 0
    for name, rule in DEVICE_RULES.items():
        desired = desired_state(name, rule, now, events, spans)
        previous = state.get(name)
        if desired != previous:
            changed += 1
            if args.dry_run:
                _log(f"[dry-run] {name}: {previous!r} -> {desired!r}")
            else:
                _log(f"{name}: {previous!r} -> {desired!r}")
                apply_state(name, desired)
            state[name] = desired

    if changed:
        if not args.dry_run:
            _save_state(state)
        _log(f"Done: {changed} device(s) changed (active={status['active']}, label={status.get('label')}).")
    # No log line at all when nothing changed -- keeps the log readable
    # across weeks of 5-minute polling instead of a no-op line every run.


if __name__ == "__main__":
    main()
