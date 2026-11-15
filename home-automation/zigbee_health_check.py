#!/usr/bin/env python3
"""Email a warning if a Zigbee sensor has gone quiet or a Kasa/Tapo device is down.

The sensors check in on their own even when nothing happens (the motion
sensor about every 10 minutes, the door sensor about hourly), so a long
silence means a device has dropped off the network -- as the motion sensor
did on 2026-10-12, unnoticed for four days. Works with nobody home.

Run from cron once a day (plus a retry). Each run reads every device's
`lastSeen` from Zigbee2MQTT's database and, if any is older than
STALE_AFTER, sends one email (at most one per day) through Claude Code's
Gmail connector, the same way schedule_email.py does. Skipped from
candle-lighting to havdalah; the next weekday run catches it.

The same email also covers Kasa/Tapo switches and plugs (kasa_health.py):
any scheduled device that doesn't answer right now, or whose recent
scheduled switches all failed. The Blech plug went offline around
2026-10-30 and missed three Shabbatot unnoticed; the Friday-morning run
now flags that before candle-lighting.

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

import kasa_health
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

    # Shabbat check first when sending, so the Kasa probe never runs then.
    if args.send and not args.print_ and in_shabbat(args.zip, args.havdalah_minutes):
        return 0
    try:
        kasa_down = kasa_health.unreachable()
    except Exception as ex:  # noqa: BLE001 -- report it rather than skip the Zigbee part
        kasa_down = [f"couldn't run the check ({type(ex).__name__}: {ex})"]
    kasa_failing = [
        f for f in kasa_health.failing_in_logs(now)
        if not any(d.startswith(f.split(":")[0] + " (") for d in kasa_down)
    ]

    if args.print_ or not args.send:
        print("\n".join(problems) or "All Zigbee devices checked in recently.")
        print("\n".join(kasa_down + kasa_failing) or "All scheduled Kasa/Tapo devices responding.")
        return 0
    if not (problems or kasa_down or kasa_failing):
        return 0

    today = now.date().isoformat()
    sent = json.loads(SENT_PATH.read_text()) if SENT_PATH.exists() else {}
    if today in sent:
        return 0  # the earlier run today already sent it
    offline = [p.split(":")[0] for p in problems] + [d.split(" (")[0] for d in kasa_down] \
        + [f.split(":")[0] for f in kasa_failing]
    subject = "Device offline: " + ", ".join(offline)
    sections = []
    if problems:
        sections.append(
            "These Zigbee sensors haven't checked in with the Pi for over "
            f"{STALE_AFTER.seconds // 3600} hours, so automations that use them aren't working:\n\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\n\nTo fix: reseat or replace the batteries. If it still doesn't come back, turn on "
            "Permit join at http://192.168.97.194:8080 and hold the sensor's button until it blinks."
        )
    if kasa_down:
        sections.append(
            "These Kasa/Tapo devices didn't answer the Pi (two tries, 30 seconds apart), "
            "so their schedules won't run:\n\n"
            + "\n".join(f"- {d}" for d in kasa_down)
            + "\n\nTo fix: check it's plugged in and the outlet/breaker has power, then unplug it "
            "for 10 seconds. If it still doesn't show up in the Kasa app, re-add it there. If it "
            "came back on a new IP, run `venv/bin/python3 kasa_cli.py discover --save` on the Pi."
        )
    if kasa_failing:
        sections.append(
            "These answered just now, but their recent scheduled switches all failed:\n\n"
            + "\n".join(f"- {f}" for f in kasa_failing)
            + "\n\nIf it says \"Server response doesn't match our challenge\", see gotcha #1 in "
            "CLAUDE.md (reset the TP-Link password)."
        )
    body = "\n\n".join(sections)
    problems = problems + kasa_down + kasa_failing
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
