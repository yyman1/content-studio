#!/usr/bin/env python3
"""One-off test: toggle a device on/off at fixed intervals starting at a
given local time. Useful for validating that scheduled control of a
Kasa/Tapo device actually works end-to-end before wiring up real
automation logic.

Usage:
    python3 test_toggle.py "Table" --start 22:00 --interval-seconds 60 --toggles 6

Waits until the next occurrence of --start (today if it hasn't passed
yet, otherwise tomorrow), then alternates on/off every --interval-seconds,
for --toggles total commands.
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
import time


def next_occurrence(hhmm: str) -> datetime.datetime:
    now = datetime.datetime.now()
    hour, minute = map(int, hhmm.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("device", help="Saved device name or IP address.")
    parser.add_argument("--start", required=True, help="HH:MM in 24-hour local time.")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--toggles", type=int, default=6)
    args = parser.parse_args()

    target = next_occurrence(args.start)
    wait = (target - datetime.datetime.now()).total_seconds()
    print(f"Waiting {wait:.0f}s until {target} to start...", flush=True)
    if wait > 0:
        time.sleep(wait)

    state = "on"
    for i in range(args.toggles):
        print(f"[{datetime.datetime.now()}] {args.device} -> {state}", flush=True)
        subprocess.run([sys.executable, "kasa_cli.py", state, args.device], check=False)
        state = "off" if state == "on" else "on"
        if i < args.toggles - 1:
            time.sleep(args.interval_seconds)

    print("Done.", flush=True)


if __name__ == "__main__":
    main()
