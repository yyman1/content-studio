#!/usr/bin/env python3
"""Email the household a lighting schedule at 12pm on the day a Shabbat /
Yom Tov span begins (i.e. the day of candle-lighting).

Run from cron every day at 12:00 (and once more a bit later as a retry --
see --send). Each run:
  1. Asks jewish_calendar.py whether a candle-lighting -> havdalah span
     starts today. If not, exits quietly -- most days.
  2. Builds the schedule by replaying shabbat_automation.desired_state()
     over the whole span in 5-minute steps (the same cadence cron polls
     at), so the email is computed from DEVICE_RULES -- the actual logic
     that will run -- never hand-copied numbers.
  3. With --send, delivers it through Claude Code's Gmail connector
     (`claude -p`), then records the span in .secrets/schedule_email_sent.json
     so the retry run doesn't send a duplicate.

One email covers a whole multi-day chain (e.g. Yom Tov running into
Shabbat), sent on the day the chain starts.

Usage:
    python3 schedule_email.py --zip 07666 --havdalah-minutes 42            # print, only if a span starts today
    python3 schedule_email.py --zip 07666 --date 2026-09-20 --print        # print for an arbitrary date
    python3 schedule_email.py --zip 07666 --send                           # what cron runs
"""

from __future__ import annotations

import argparse
import functools
import json
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import jewish_calendar as jc
import shabbat_automation as sa

HERE = Path(__file__).parent
SENT_PATH = HERE / ".secrets" / "schedule_email_sent.json"
LOG_PATH = HERE / "schedule_email.log"

RECIPIENT = "yerlichman@gmail.com"
STEP = timedelta(minutes=5)  # matches the shabbat_automation cron cadence

# Same categories as the household's original PDF / the DEVICE_RULES comments.
GROUPS: list[tuple[str, list[str]]] = [
    (
        "FIRST FLOOR",
        ["Living Room", "Bar", "Dining Room", "Dining Room Chandelier", "Kitchen", "Table",
         "Bathroom First Floor", "Family Room"],
    ),
    ("MASTER BEDROOM / BATHROOMS", ["Main Bedroom", "Primary Lobby", "Master Bathroom", "Master Bathroom Toilet"]),
    ("KIDS BATHROOM", ["Bathroom Upstairs main", "Bathroom Mirror"]),
    ("BASEMENT", ["Basement", "Basement Playroom"]),
    ("ENTRYWAYS / OUTDOOR", ["Back Porch Side Light", "Driveway Backyard / Side"]),
]


def _log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%-I:%M%p").lower()


def _fmt_day(dt: datetime) -> str:
    return dt.strftime("%a")


def _fmt_long(dt: datetime) -> str:
    return dt.strftime("%A, %b %-d")


def _describe(state: str) -> str:
    if state.startswith("dim:"):
        return f"dim to {state.split(':', 1)[1]}%"
    return state


def _transitions(name: str, rule: sa.DeviceRule, span: jc.Span, events: jc.Events, spans: list[jc.Span]):
    """(time, new_state) for every change of this device's desired state
    across the span, from just before the evening start to the end of the
    havdalah day (late enough to catch nightly cutoffs after havdalah)."""
    start = span.start - timedelta(hours=2)
    start = start.replace(minute=start.minute - start.minute % 5, second=0, microsecond=0)
    end = datetime.combine(span.end.date(), datetime.max.time().replace(microsecond=0), tzinfo=span.end.tzinfo)
    out: list[tuple[datetime, str]] = []
    prev = "off"
    t = start
    while t <= end:
        cur = sa.desired_state(name, rule, t, events, spans)
        if cur != prev:
            out.append((t, cur))
            prev = cur
        t += STEP
    return out


def _device_line(name: str, transitions: list[tuple[datetime, str]], rule: sa.DeviceRule) -> str:
    if not transitions:
        return f"{name} — off the whole time"
    by_day: dict[date, list[str]] = {}
    days: dict[date, datetime] = {}
    for t, state in transitions:
        label = _describe(state)
        if state == "on" and rule.on_brightness is not None:
            label = f"on at {rule.on_brightness}%"
        elif state == "on" and rule.dimmable:
            label = "full on"
        by_day.setdefault(t.date(), []).append(f"{label} {_fmt_time(t)}")
        days[t.date()] = t
    parts = [f"{_fmt_day(days[d])}: " + ", ".join(items) for d, items in by_day.items()]
    return f"{name} — " + " | ".join(parts)


def build_email(zip_code: str, havdalah_minutes: int, today: date) -> Optional[tuple[str, str, jc.Span]]:
    """Return (subject, body, span) for the span that starts on `today`,
    or None if none does."""
    sa._ZIP = zip_code
    # desired_state() looks up sunrise over the network for devices that
    # dim-until-sunrise; cache it so a full-span replay is one call per date.
    jc.sunrise = functools.lru_cache(maxsize=None)(jc.sunrise)

    events = jc.fetch_events(zip_code, havdalah_minutes)
    spans = jc.fetch_spans(zip_code, havdalah_minutes, events=events)
    span = next((s for s in spans if s.start.date() == today), None)
    if span is None:
        return None

    candles = [c for c in events.candles if span.start <= c < span.end]
    lines = [f"Candle-lighting: {_fmt_long(c)} — {_fmt_time(c)}" for c in candles]
    lines.append(f"Havdalah: {_fmt_long(span.end)} — {_fmt_time(span.end)}")
    lines.append("")

    covered = set()
    for heading, names in GROUPS:
        section = []
        for name in names:
            rule = sa.DEVICE_RULES.get(name)
            if rule is None:
                continue
            covered.add(name)
            trans = _transitions(name, rule, span, events, spans)
            if not trans:
                skipped = any(span.start.date() <= d <= span.end.date() for d in sa.SKIP_ON_DATES.get(name, ()))
                section.append(f"{name} — stays off" + (" (skipped this time)" if skipped else " the whole time"))
            else:
                section.append(_device_line(name, trans, rule))
        if section:
            lines.append(heading)
            lines.extend(section)
            lines.append("")

    # A device added to DEVICE_RULES but not to GROUPS must not silently vanish from the email.
    extra = [n for n in sa.DEVICE_RULES if n not in covered]
    if extra:
        lines.append("OTHER")
        for name in extra:
            trans = _transitions(name, sa.DEVICE_RULES[name], span, events, spans)
            lines.append(_device_line(name, trans, sa.DEVICE_RULES[name]))
        lines.append("")

    lines.append("—")
    lines.append("Sent automatically at 12pm on the day of candle-lighting. Please confirm all times read correctly.")

    names = [n.strip() for n in span.label.split(",")]
    shown = [n for n in names if not n.startswith("Erev ")] or names
    title = ", ".join(dict.fromkeys(shown))
    subject = (
        f"{title} Lighting Schedule — {span.start.strftime('%a %-m/%-d')} (candles {_fmt_time(span.start)})"
        f" → {span.end.strftime('%a %-m/%-d')} (havdalah {_fmt_time(span.end)})"
    )
    return subject, "\n".join(lines), span


def _load_sent() -> dict:
    return json.loads(SENT_PATH.read_text()) if SENT_PATH.exists() else {}


def _send_via_claude(subject: str, body: str) -> bool:
    claude = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
    prompt = (
        f"Send exactly one email with the Gmail send_message tool to {RECIPIENT}. "
        "Use the subject and plain-text body below verbatim -- do not edit, summarize, or add to them. "
        "Do nothing else; reply 'sent' when the tool call succeeds.\n\n"
        f"SUBJECT: {subject}\n\nBODY:\n{body}"
    )
    res = subprocess.run(
        [claude, "-p", prompt, "--allowedTools", "mcp__claude_ai_Gmail__send_message"],
        capture_output=True, text=True, timeout=300, cwd=str(HERE),
    )
    _log(f"claude exit={res.returncode} out={res.stdout.strip()[:200]!r} err={res.stderr.strip()[:200]!r}")
    return res.returncode == 0 and "sent" in res.stdout.lower()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--zip", required=True)
    p.add_argument("--havdalah-minutes", type=int, default=42)
    p.add_argument("--date", help="YYYY-MM-DD to build for (default: today).")
    p.add_argument("--print", action="store_true", dest="print_", help="Print the email; don't send.")
    p.add_argument("--send", action="store_true", help="Send it (once per span) via the Gmail connector.")
    args = p.parse_args()

    today = date.fromisoformat(args.date) if args.date else datetime.now().astimezone().date()
    built = build_email(args.zip, args.havdalah_minutes, today)
    if built is None:
        return 0  # no Shabbat/Yom Tov starts today -- the normal case
    subject, body, span = built

    if args.print_ or not args.send:
        print(f"SUBJECT: {subject}\n\n{body}")
        return 0

    key = span.start.isoformat()
    sent = _load_sent()
    if key in sent:
        return 0  # the earlier run today already delivered it
    if _send_via_claude(subject, body):
        sent[key] = datetime.now().isoformat(timespec="seconds")
        SENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SENT_PATH.write_text(json.dumps(sent, indent=2))
        _log(f"Sent: {subject}")
        return 0
    _log(f"FAILED to send {subject!r}; the later cron run will retry")
    return 1


if __name__ == "__main__":
    sys.exit(main())
