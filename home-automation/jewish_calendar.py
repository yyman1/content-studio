#!/usr/bin/env python3
"""Determine whether it's currently Shabbat or a Jewish holiday (Yom Tov),
using the Hebcal API (https://www.hebcal.com/home/197/shabbat-times-rest-api)
for candle-lighting and havdalah times at a given US zip code.

Any "candles" event marks the start of Shabbat/holiday mode; the next
"havdalah" event marks its end. Hebcal already merges consecutive Yom
Tov/Shabbat days (e.g. a holiday running into or out of Shabbat) into one
continuous candle-lighting -> havdalah span, so this module doesn't need
to special-case which holiday it is -- it only needs the paired times.

Usage:
    python jewish_calendar.py status --zip 07666
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import requests

HEBCAL_URL = "https://www.hebcal.com/hebcal"
ZMANIM_URL = "https://www.hebcal.com/zmanim"


@dataclass
class Span:
    start: datetime  # candle lighting
    end: datetime  # havdalah
    label: str  # nearby holiday title(s), or "Shabbat"


@dataclass
class Events:
    candles: list[datetime]
    havdalahs: list[datetime]
    holidays: list[tuple[datetime, str]]


def _fetch_year(zip_code: str, havdalah_minutes: int, year: int) -> dict:
    params = {
        "v": "1",
        "cfg": "json",
        "maj": "on",
        "min": "on",
        "mod": "off",
        "nx": "off",
        "mf": "off",
        "ss": "off",
        "c": "on",
        "geo": "zip",
        "zip": zip_code,
        "m": str(havdalah_minutes),
        "year": str(year),
        "month": "x",
    }
    resp = requests.get(HEBCAL_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_events(zip_code: str, havdalah_minutes: int = 42) -> Events:
    """Return the raw candle-lighting/havdalah/holiday events for this
    Gregorian year and next (fetching two years keeps events that
    straddle a year boundary -- e.g. a candle-lighting on Dec 31 with
    havdalah in January -- intact).

    Unlike fetch_spans(), this does NOT collapse multi-day chains into
    one span -- each individual candle-lighting (e.g. both evenings of
    a 2-day Yom Tov) is kept separate. Needed for per-evening rules
    (e.g. "on from an hour before candle-lighting, off at a fixed
    time") that must fire on every relighting, not just the first.
    """
    this_year = datetime.now().year
    items: list[dict] = []
    for year in (this_year, this_year + 1):
        items.extend(_fetch_year(zip_code, havdalah_minutes, year)["items"])

    candles: list[datetime] = []
    havdalahs: list[datetime] = []
    holidays: list[tuple[datetime, str]] = []
    for item in items:
        cat = item.get("category")
        dt = datetime.fromisoformat(item["date"])
        if cat == "candles":
            candles.append(dt)
        elif cat == "havdalah":
            havdalahs.append(dt)
        elif cat == "holiday":
            holidays.append((dt, item["title"]))

    candles.sort()
    havdalahs.sort()
    # Some "holiday" items (e.g. nightly Chanukah candle-lighting) carry a
    # timezone-aware timestamp while most are date-only (naive, midnight);
    # sort by date alone to avoid comparing the two directly.
    holidays.sort(key=lambda h: h[0].date())
    return Events(candles=candles, havdalahs=havdalahs, holidays=holidays)


def fetch_spans(zip_code: str, havdalah_minutes: int = 42) -> list[Span]:
    """Return candle-lighting -> havdalah spans for this year and next.

    Fetching two Gregorian years keeps spans that straddle a year
    boundary (e.g. a candle-lighting on Dec 31 with havdalah in
    January) intact.
    """
    events = fetch_events(zip_code, havdalah_minutes)

    # Walk the merged timeline rather than pairing nearest-neighbour: a
    # "candles" event while already inside a span (e.g. Sukkot's second
    # candle-lighting, lit from the existing flame after Shabbat/Sukkot I
    # flows straight into Sukkot II with no havdalah in between) extends
    # the current span instead of starting a new, overlapping one.
    timeline = sorted(
        [(c, "candles") for c in events.candles] + [(h, "havdalah") for h in events.havdalahs]
    )
    spans = []
    span_start: Optional[datetime] = None
    for dt, kind in timeline:
        if kind == "candles" and span_start is None:
            span_start = dt
        elif kind == "havdalah" and span_start is not None:
            spans.append(Span(start=span_start, end=dt, label=_label_for(span_start, dt, events.holidays)))
            span_start = None
    return spans


def _label_for(start: datetime, end: datetime, holidays: list[tuple[datetime, str]]) -> str:
    names = [
        title
        for dt, title in holidays
        if start.date() <= dt.date() <= end.date()
    ]
    # dict.fromkeys() dedupes while preserving order (e.g. "Erev Pesach", "Pesach I").
    return ", ".join(dict.fromkeys(names)) if names else "Shabbat"


def current_status(
    zip_code: str, havdalah_minutes: int = 42, now: Optional[datetime] = None
) -> dict:
    """Return the current Shabbat/holiday state.

    {"active": True, "label": ..., "since": ..., "until": ...} while inside
    a candle-lighting -> havdalah span, otherwise
    {"active": False, "label": ..., "next_start": ...} with the next
    upcoming span, if any is known.
    """
    now = now or datetime.now().astimezone()
    spans = fetch_spans(zip_code, havdalah_minutes)
    for span in spans:
        if span.start <= now < span.end:
            return {
                "active": True,
                "label": span.label,
                "since": span.start.isoformat(),
                "until": span.end.isoformat(),
            }
    upcoming = next((s for s in spans if s.start > now), None)
    return {
        "active": False,
        "label": upcoming.label if upcoming else None,
        "next_start": upcoming.start.isoformat() if upcoming else None,
    }


def sunrise(zip_code: str, on_date: date) -> datetime:
    """Return the sunrise time for the given date at zip_code, via
    Hebcal's zmanim API (https://www.hebcal.com/home/1663/zmanim-rest-api)."""
    params = {"cfg": "json", "geo": "zip", "zip": zip_code, "date": on_date.isoformat()}
    resp = requests.get(ZMANIM_URL, params=params, timeout=15)
    resp.raise_for_status()
    return datetime.fromisoformat(resp.json()["times"]["sunrise"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="Print the current Shabbat/holiday state as JSON.")
    p_status.add_argument("--zip", required=True, help="US zip code")
    p_status.add_argument("--havdalah-minutes", type=int, default=42)

    p_upcoming = sub.add_parser("upcoming", help="List upcoming candle-lighting/havdalah spans.")
    p_upcoming.add_argument("--zip", required=True, help="US zip code")
    p_upcoming.add_argument("--havdalah-minutes", type=int, default=42)
    p_upcoming.add_argument("-n", type=int, default=10, help="Number of spans to show")

    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(current_status(args.zip, args.havdalah_minutes), indent=2))
    elif args.command == "upcoming":
        now = datetime.now().astimezone()
        spans = [s for s in fetch_spans(args.zip, args.havdalah_minutes) if s.end > now][: args.n]
        for s in spans:
            print(f"{s.label:30s} {s.start.strftime('%a %Y-%m-%d %H:%M')} -> {s.end.strftime('%a %Y-%m-%d %H:%M')}")


if __name__ == "__main__":
    main()
