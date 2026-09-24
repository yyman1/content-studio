#!/usr/bin/env python3
"""Non-Shabbat / non-Yom Tov ("weekday") lighting automation.

The household's written weekday spec, as a WEEKDAY_RULES dict. It is the
counterpart of shabbat_automation.py: that script owns candle-lighting ->
havdalah, this one owns everything else. Run from cron every 5 minutes.

How it differs from shabbat_automation.py: the weekday spec is a list of
*events* ("off at 10pm", "on at 6:30am"), not states. Nobody wants the
Living Room forced on at 9pm, only turned off at 10pm -- and a light
someone turns back on at 10:30pm must stay on. So each run finds each
device's most recent applicable event, and fires it only if it's not the
one we last fired (the event's date+time+action is the token kept in
.secrets/weekday_state.json). Manual changes made after an event are
therefore never fought; the next event still fires on schedule.

Rules that only apply outside Shabbat / Yom Tov are skipped for any event
falling inside a Shabbat regime (an hour before candle-lighting through
havdalah), so Friday's 10pm "off" or Saturday's 8:45am "off" never fire.
Rules marked always=True (Front Door, Mudroom Porch -- "even on Shabbat
and Yom Tov") ignore that gate.

Go-live: nothing regime-gated runs until the havdalah on GO_LIVE_HAVDALAH_DATE
(the always=True sunset/sunrise rules are live immediately). From
then on, devices with a weekday rule are also handed over by
shabbat_automation.py once Shabbat ends (see yields_to_weekday()) so its
post-havdalah cutoffs don't fight these times.

Usage:
    python3 weekday_automation.py --zip 07666 --havdalah-minutes 42
"""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from time import sleep as _sleep  # `time` above is datetime.time, not the module
from typing import Optional, Union

import requests

import jewish_calendar as jc

HERE = Path(__file__).parent
STATE_PATH = HERE / ".secrets" / "weekday_state.json"
ZMANIM_CACHE_PATH = HERE / ".secrets" / "zmanim_cache.json"
EVENTS_CACHE_PATH = HERE / ".secrets" / "events_cache.json"
LOCK_PATH = HERE / ".secrets" / "weekday_automation.lock"
LOG_PATH = HERE / "weekday_automation.log"
KASA_CLI = HERE / "kasa_cli.py"
ZMANIM_URL = "https://www.hebcal.com/zmanim"

# The weekday schedule takes over at the first havdalah on this date
# (Yom Kippur 5787 ends Mon 2026-09-21).
GO_LIVE_HAVDALAH_DATE = date(2026, 9, 21)

# Matches shabbat_automation: its "on" rules start an hour before candle-lighting.
REGIME_LEAD = timedelta(hours=1)
# A missed "on" (Pi down/rebooting) is only caught up this long afterwards; a
# kitchen light coming on at 2pm because of a 6:30am event would be wrong.
# Offs are always caught up, and "always" events (sunset/sunrise state) too.
MAX_ON_LATENESS = timedelta(hours=2)

YIELD_STATE = "weekday"  # what shabbat_automation records for a device while we own it

RETRY_INTERVAL_SECONDS = 60
MAX_RETRIES = 3

SUNRISE = "sunrise"
SUNSET = "sunset"
# datetime.weekday(): Monday=0 .. Sunday=6
MON_FRI = frozenset(range(5))
SUNDAY = frozenset({6})


@dataclass(frozen=True)
class Event:
    when: Union[time, str]  # a clock time, or SUNRISE / SUNSET
    action: str  # "on" | "off"
    days: Optional[frozenset] = None  # weekday() values it applies to; None = every day
    always: bool = False  # also runs during Shabbat / Yom Tov, and doesn't wait for go-live
    offset: timedelta = timedelta(0)  # shifts a SUNRISE/SUNSET event, e.g. -30 min before sunset


@dataclass
class WeekdayRule:
    events: list[Event]
    # "Turn off at 7:45 and check every 5 min until 9:45 that it's off": inside
    # each window, re-issue off on every run regardless of recorded state.
    enforce_off: list[tuple[time, time]] = field(default_factory=list)


def _t(hhmm: str) -> time:
    h, m = map(int, hhmm.split(":"))
    return time(h, m)


def off(when: Union[str, time], **kw) -> Event:
    return Event(_t(when) if isinstance(when, str) and ":" in when else when, "off", **kw)


def on(when: Union[str, time], **kw) -> Event:
    return Event(_t(when) if isinstance(when, str) and ":" in when else when, "on", **kw)


# From the household's written non-Shabbat spec. Devices that spec marks
# "do nothing" (Dining Room Dummy, Main Bedroom, Primary Lobby, Master
# Bathroom, Master Bathroom Toilet, Blanket, Mudroom Hallway) are omitted.
WEEKDAY_RULES: dict[str, WeekdayRule] = {
    "Living Room": WeekdayRule([off("22:00")]),
    "Bar": WeekdayRule([off("22:00")]),
    "Dining Room": WeekdayRule([off("23:30")]),
    "Dining Room Chandelier": WeekdayRule([off("22:00")]),
    "Kitchen": WeekdayRule(
        [on("06:30", days=MON_FRI), on("08:00", days=SUNDAY), off("08:45"), off("23:30")]
    ),
    "Table": WeekdayRule([on("07:00", days=MON_FRI), off("08:00", days=MON_FRI), off("22:00")]),
    "Bathroom First Floor": WeekdayRule([off("23:30")]),
    "Family Room": WeekdayRule([off("23:30")]),
    # Kids bathroom
    "Bathroom Upstairs main": WeekdayRule([off("23:00")]),
    "Bathroom Mirror": WeekdayRule([off("23:30")]),
    # Basement
    "Basement": WeekdayRule([off("22:00")]),
    "Basement Playroom": WeekdayRule([off("23:00")]),
    "Basement Hallway": WeekdayRule([off("22:00")]),
    "Basement Steps": WeekdayRule([off("07:45"), off("22:00")], enforce_off=[(_t("07:45"), _t("09:45"))]),
    # Entryways / outdoor. Front Door and Mudroom Porch run "even on Shabbat and Yom Tov":
    # on 30 minutes before sunset, from now (not from the go-live havdalah).
    "Front Door": WeekdayRule([on(SUNSET, always=True, offset=-timedelta(minutes=30)), off(SUNRISE, always=True)]),
    "Mudroom Porch": WeekdayRule(
        [on(SUNSET, always=True, offset=-timedelta(minutes=30)), off("23:30", always=True)]
    ),
    "Backyard overhead light": WeekdayRule([off("23:00")]),
    "Back Porch Side Light": WeekdayRule([off("23:00")]),
    "Driveway front": WeekdayRule([off("23:30")]),
    "Driveway Backyard / Side": WeekdayRule([off("23:30")]),
}


def _log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))
    STATE_PATH.chmod(0o600)


# --- calendar helpers (also imported by shabbat_automation) -------------------


def live_datetime(events: jc.Events) -> Optional[datetime]:
    """The moment the weekday schedule goes live: the havdalah on GO_LIVE_HAVDALAH_DATE."""
    return next((h for h in events.havdalahs if h.date() == GO_LIVE_HAVDALAH_DATE), None)


def in_shabbat_regime(dt: datetime, spans: list[jc.Span]) -> bool:
    return any(s.start - REGIME_LEAD <= dt < s.end for s in spans)


def yields_to_weekday(name: str, now: datetime, events: jc.Events, spans: list[jc.Span]) -> bool:
    """True when shabbat_automation must leave this device alone: it has a
    weekday rule, the weekday schedule is live, and Shabbat/Yom Tov is over.
    (Devices the weekday spec says "do nothing" for keep their Shabbat
    post-havdalah behavior, e.g. Master Bathroom's off at 11pm.)"""
    if name not in WEEKDAY_RULES:
        return False
    live = live_datetime(events)
    return live is not None and now >= live and not in_shabbat_regime(now, spans)


# --- cached network lookups ---------------------------------------------------


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def load_events(zip_code: str, havdalah_minutes: int) -> jc.Events:
    """jc.fetch_events with a 6h disk cache (this script polls every 5 min
    alongside shabbat_automation.py -- no need to double the Hebcal load),
    falling back to a stale cache if Hebcal is briefly unreachable."""
    cached = _load_json(EVENTS_CACHE_PATH)
    fresh = cached and cached.get("key") == [zip_code, havdalah_minutes] and (
        datetime.now().timestamp() - cached.get("fetched", 0) < 6 * 3600
    )
    if not fresh:
        try:
            ev = jc.fetch_events(zip_code, havdalah_minutes)
            EVENTS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            EVENTS_CACHE_PATH.write_text(json.dumps({
                "key": [zip_code, havdalah_minutes],
                "fetched": datetime.now().timestamp(),
                "candles": [d.isoformat() for d in ev.candles],
                "havdalahs": [d.isoformat() for d in ev.havdalahs],
                "holidays": [[d.isoformat(), t] for d, t in ev.holidays],
            }))
            return ev
        except Exception as ex:  # noqa: BLE001 -- any network/parse failure
            if not cached or cached.get("key") != [zip_code, havdalah_minutes]:
                raise
            _log(f"Hebcal unreachable ({type(ex).__name__}); using cached calendar")
    return jc.Events(
        candles=[datetime.fromisoformat(s) for s in cached["candles"]],
        havdalahs=[datetime.fromisoformat(s) for s in cached["havdalahs"]],
        holidays=[(datetime.fromisoformat(s), t) for s, t in cached["holidays"]],
    )


def zmanim(zip_code: str, day: date) -> dict[str, datetime]:
    """{"sunrise": dt, "sunset": dt} for `day`, cached on disk by date."""
    cache = _load_json(ZMANIM_CACHE_PATH)
    key = f"{zip_code}:{day.isoformat()}"
    if key not in cache:
        resp = requests.get(
            ZMANIM_URL, params={"cfg": "json", "geo": "zip", "zip": zip_code, "date": day.isoformat()}, timeout=15
        )
        resp.raise_for_status()
        times = resp.json()["times"]
        cache[key] = {"sunrise": times["sunrise"], "sunset": times["sunset"]}
        cutoff = (day - timedelta(days=10)).isoformat()  # keep the file small
        cache = {k: v for k, v in cache.items() if k.split(":", 1)[1] >= cutoff}
        ZMANIM_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ZMANIM_CACHE_PATH.write_text(json.dumps(cache))
    return {k: datetime.fromisoformat(v) for k, v in cache[key].items()}


# --- desired event ------------------------------------------------------------


def _event_dt(ev: Event, day: date, zip_code: str, tz) -> datetime:
    if isinstance(ev.when, time):
        return datetime.combine(day, ev.when, tzinfo=tz)
    return zmanim(zip_code, day)[ev.when] + ev.offset


def desired_event(
    rule: WeekdayRule, now: datetime, spans: list[jc.Span], live: datetime, zip_code: str
) -> Optional[tuple[str, str, bool]]:
    """Return (token, action, too_late) for the most recent event that
    should have fired by `now`, or None if there isn't one. Only
    yesterday's and today's events are considered.

    too_late marks a regime-gated "on" that is now older than
    MAX_ON_LATENESS. It stays the *latest* event on purpose -- if it were
    dropped instead, last night's "off" would become the latest and
    re-fire in the middle of the morning."""
    best: Optional[tuple[datetime, str, bool]] = None
    for day in (now.date() - timedelta(days=1), now.date()):
        for ev in rule.events:
            if ev.days is not None and day.weekday() not in ev.days:
                continue
            dt = _event_dt(ev, day, zip_code, now.tzinfo)
            if dt > now:
                continue
            if not ev.always and (dt < live or in_shabbat_regime(dt, spans)):
                continue
            if best is None or dt > best[0]:
                too_late = not ev.always and ev.action == "on" and now - dt > MAX_ON_LATENESS
                best = (dt, ev.action, too_late)
    if best is None:
        return None
    return f"{best[0].isoformat(timespec='minutes')}|{best[1]}", best[1], best[2]


# --- applying -----------------------------------------------------------------


def apply_action(name: str, action: str, retries: int = MAX_RETRIES) -> bool:
    """Run kasa_cli.py on/off (which confirms the device reports the new
    power state), retrying a minute apart like shabbat_automation does."""
    cmd = [sys.executable, str(KASA_CLI), action, name]
    for attempt in range(retries + 1):
        if subprocess.run(cmd, check=False).returncode == 0:
            return True
        if attempt < retries:
            _log(f"{name}: didn't confirm {action!r} (attempt {attempt + 1}/{retries + 1}), retrying in {RETRY_INTERVAL_SECONDS}s")
            _sleep(RETRY_INTERVAL_SECONDS)
    return False


def run_once(
    zip_code: str, now: datetime, events: jc.Events, spans: list[jc.Span], dry_run: bool, state: dict
) -> bool:
    """One polling pass. Mutates `state`; returns True if it changed."""
    go_live = live_datetime(events)
    is_live = go_live is not None and now >= go_live
    # Before go-live nothing regime-gated may fire: an event is only eligible at or after
    # `live`, so give it a moment in the future. "always" events ignore this entirely.
    live = go_live if is_live else now + timedelta(days=3650)
    dirty = False
    in_regime = in_shabbat_regime(now, spans)
    for name, rule in WEEKDAY_RULES.items():
        fired = False
        try:
            found = desired_event(rule, now, spans, live, zip_code)
        except Exception as ex:  # noqa: BLE001 -- e.g. sunset lookup down: skip just this device
            _log(f"{name}: couldn't work out its schedule ({type(ex).__name__}: {ex}); will retry next run")
            continue
        if found is not None:
            token, action, too_late = found
            if token != state.get(name) and not too_late:
                if dry_run:
                    _log(f"[dry-run] {name}: {action} ({token})")
                    ok = True
                else:
                    ok = apply_action(name, action)
                    _log(f"{name}: {action} ({token})" + ("" if ok else " FAILED, will retry next run"))
                if ok:
                    state[name] = token
                    dirty = True
                    fired = True
        if is_live and not fired and not in_regime:
            t = now.time()
            if any(start <= t < end for start, end in rule.enforce_off):
                if dry_run:
                    _log(f"[dry-run] {name}: enforce off")
                elif not apply_action(name, "off", retries=0):
                    _log(f"{name}: enforce-off didn't confirm; will retry next run")
    return dirty


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", required=True, help="US zip code for havdalah/sunrise/sunset times.")
    parser.add_argument("--havdalah-minutes", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="Log what would change, but don't actually act.")
    parser.add_argument("--now", help="ISO datetime to pretend it is (testing; combine with --dry-run).")
    args = parser.parse_args()

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock = LOCK_PATH.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return  # a previous run (retrying a flaky device) is still going

    now = datetime.fromisoformat(args.now).astimezone() if args.now else datetime.now().astimezone()
    events = load_events(args.zip, args.havdalah_minutes)
    spans = jc.fetch_spans(args.zip, args.havdalah_minutes, events=events)
    state = _load_state()
    if run_once(args.zip, now, events, spans, args.dry_run, state) and not args.dry_run:
        _save_state(state)


if __name__ == "__main__":
    main()
