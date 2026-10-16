#!/usr/bin/env python3
"""Email a warning if a Zigbee sensor has gone quiet.

The sensors check in on their own even when nothing happens (the motion
sensor about every 10 minutes, the door sensor about hourly), so a long
silence means a device has dropped off the network -- as the motion sensor
did on 2026-10-12, unnoticed for four days. Works with nobody home.

Run from cron once a day (plus a retry). Each run reads every device's
`lastSeen` from Zigbee2MQTT's database and, if any is older than
STALE_AFTER, sends one email (at most one per day) through Claude Code's
Gmail connector, the same way schedule_email.py does. Skipped from
candle-lighting to havdalah; the next weekday run catches it.

Usage:
    python3 zigbee_health_check.py --zip 07666 --print   # show status; don't send
    python3 zigbee_health_check.py --zip 07666 --send    # what cron runs
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from motion_sensor_bathroom import in_shabbat
from schedule_email import _send_via_claude

HERE = Path(__file__).parent
LOG_PATH = HERE / "zigbee_health_check.log"
SENT_PATH = HERE / ".secrets" / "zigbee_health_check_sent.json"
Z2M_DIR = Path.home() / "zigbee" / "z2m-data"
STALE_AFTER = timedelta(hours=3)  # the hourly door sensor can miss a check-in or two


def _log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def _friendly_names() -> dict[str, str]:
    """IEEE address -> friendly name, from Zigbee2MQTT's configuration.yaml."""
    text = (Z2M_DIR / "configuration.yaml").read_text()
    return dict(re.findall(r"'?(0x[0-9a-f]{16})'?:\s*\n\s+friendly_name:\s*['\"]?([^'\"\n]+)", text))


def stale_devices(now: datetime) -> list[str]:
    """One line per device not heard from within STALE_AFTER."""
    names = _friendly_names()
    problems = []
    for line in (Z2M_DIR / "database.db").read_text().splitlines():
        dev = json.loads(line)
        if dev.get("type") == "Coordinator":
            continue
        name = names.get(dev["ieeeAddr"], dev["ieeeAddr"])
        if not dev.get("lastSeen"):
            problems.append(f"{name}: never seen")
            continue
        seen = datetime.fromtimestamp(dev["lastSeen"] / 1000)
        if now - seen > STALE_AFTER:
            problems.append(f"{name}: last heard from {seen:%a %b %-d at %-I:%M %p}")
    return problems


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--zip", required=True)
    p.add_argument("--havdalah-minutes", type=int, default=42)
    p.add_argument("--print", action="store_true", dest="print_", help="Print status; don't send.")
    p.add_argument("--send", action="store_true", help="Email if anything is stale (once per day).")
    args = p.parse_args()

    now = datetime.now()
    try:
        problems = stale_devices(now)
    except (OSError, ValueError, KeyError) as ex:
        problems = [f"couldn't read Zigbee2MQTT's device database ({type(ex).__name__}: {ex})"]

    if args.print_ or not args.send:
        print("\n".join(problems) or "All Zigbee devices checked in recently.")
        return 0
    if not problems:
        return 0
    if in_shabbat(args.zip, args.havdalah_minutes):
        return 0

    today = now.date().isoformat()
    sent = json.loads(SENT_PATH.read_text()) if SENT_PATH.exists() else {}
    if today in sent:
        return 0  # the earlier run today already sent it
    subject = "Zigbee sensor offline: " + ", ".join(p.split(":")[0] for p in problems)
    body = (
        "These Zigbee devices haven't checked in with the Pi for over "
        f"{STALE_AFTER.seconds // 3600} hours, so automations that use them aren't working:\n\n"
        + "\n".join(f"- {p}" for p in problems)
        + "\n\nTo fix: reseat or replace the batteries. If it still doesn't come back, turn on "
        "Permit join at http://192.168.97.194:8080 and hold the sensor's button until it blinks."
    )
    if _send_via_claude(subject, body):
        sent[today] = problems
        SENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SENT_PATH.write_text(json.dumps(sent, indent=2))
        _log(f"Sent: {subject}")
        return 0
    _log(f"FAILED to send {subject!r}; the later cron run will retry")
    return 1


if __name__ == "__main__":
    sys.exit(main())
