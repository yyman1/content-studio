#!/usr/bin/env python3
"""Yaakov Closet light follows the closet's Zigbee door sensor.

Door opens (contact=false) -> light on; door closes (contact=true) -> off.
Paused from candle-lighting to havdalah (Shabbat and Yom Tov): the door
does nothing, and the light stays however it was left.

Listens to Zigbee2MQTT via `mosquitto_sub` inside the `mosquitto`
container (~/zigbee), like door_sensor_test.py. Acts only when `contact`
changes -- the Aqara sensor also sends periodic heartbeat reports that
repeat the same value. The starting state comes from Zigbee2MQTT's saved
state.json, so a restart neither flips the light nor misses the next
open/close.

Long-running; cron starts it every 5 minutes and the lock makes extra
copies exit at once, so it comes back within 5 minutes of a crash or
reboot.

Usage:
    python3 closet_door_light.py --zip 07666 --havdalah-minutes 42
"""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import jewish_calendar as jc
import weekday_automation as wa

HERE = Path(__file__).parent
LOCK_PATH = HERE / ".secrets" / "closet_door_light.lock"
LOG_PATH = HERE / "closet_door_light.log"
KASA_CLI = HERE / "kasa_cli.py"
SENSOR = "Door Sensor"
SENSOR_IEEE = "0x00158d008c8bdcc9"
Z2M_STATE_PATH = Path.home() / "zigbee" / "z2m-data" / "state.json"
DEVICE = "Yaakov Closet"


def _log(msg: str) -> None:
    with LOG_PATH.open("a") as f:
        f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n")


def in_shabbat(zip_code: str, havdalah_minutes: int) -> bool:
    """True from candle-lighting to havdalah. If the calendar can't be
    loaded at all, err on the side of pausing."""
    try:
        events = wa.load_events(zip_code, havdalah_minutes)  # 6h disk cache
        spans = jc.fetch_spans(zip_code, havdalah_minutes, events=events)
    except Exception as ex:  # noqa: BLE001
        _log(f"calendar unavailable ({type(ex).__name__}); pausing to be safe")
        return True
    now = datetime.now().astimezone()
    return any(s.start <= now < s.end for s in spans)


def saved_contact():
    """The sensor's last known contact value from Zigbee2MQTT, or None."""
    try:
        return json.loads(Z2M_STATE_PATH.read_text()).get(SENSOR_IEEE, {}).get("contact")
    except (OSError, ValueError):
        return None


def listen(zip_code: str, havdalah_minutes: int) -> None:
    sub = subprocess.Popen(
        ["docker", "exec", "mosquitto", "mosquitto_sub", "-t", f"zigbee2mqtt/{SENSOR}"],
        stdout=subprocess.PIPE,
        text=True,
    )
    last_contact = saved_contact()
    try:
        for line in sub.stdout:
            try:
                contact = json.loads(line).get("contact")
            except (json.JSONDecodeError, AttributeError):
                continue
            if contact is None or contact == last_contact:
                continue
            first, last_contact = last_contact is None, contact
            if first:  # no saved state to compare against; just record it
                continue
            state = "off" if contact else "on"
            if in_shabbat(zip_code, havdalah_minutes):
                _log(f"door {'closed' if contact else 'opened'}; Shabbat/Yom Tov, leaving {DEVICE} alone")
                continue
            r = subprocess.run(
                [sys.executable, str(KASA_CLI), state, DEVICE], capture_output=True, text=True
            )
            out = (r.stdout + r.stderr).strip().splitlines()
            _log(f"door {'closed' if contact else 'opened'} -> {DEVICE} {state}: {out[0] if out else r.returncode}")
    finally:
        sub.terminate()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", required=True)
    parser.add_argument("--havdalah-minutes", type=int, default=42)
    args = parser.parse_args()

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock = LOCK_PATH.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return  # already running

    _log("started")
    while True:  # mosquitto_sub exits if the container restarts; resubscribe
        listen(args.zip, args.havdalah_minutes)
        _log("subscription ended; reconnecting in 10s")
        time.sleep(10)


if __name__ == "__main__":
    main()
