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

Commands go straight to the switch over a connection kept open between
events (~0.1s from door to light), falling back to a fresh connection and
then to kasa_cli.py if that fails. Each change is confirmed afterwards,
once the light has already switched.

Long-running; cron starts it every 5 minutes and the lock makes extra
copies exit at once, so it comes back within 5 minutes of a crash or
reboot.

Usage:
    python3 closet_door_light.py --zip 07666 --havdalah-minutes 42
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import jewish_calendar as jc
import kasa_cli as kc
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


class Light:
    """A connection to DEVICE kept open between door events."""

    def __init__(self) -> None:
        self.username, self.password = kc._load_credentials()
        self.dev = None

    async def _connect(self):
        try:
            self.dev = await kc._connect(kc._resolve_host(DEVICE), self.username, self.password)
        except SystemExit as ex:  # kc._connect reports failures this way
            self.dev = None
            raise ConnectionError(str(ex)) from None

    async def set(self, on: bool) -> str:
        """Switch the light; return a short note for the log."""
        start = time.monotonic()
        for attempt in (1, 2):  # second try on a fresh connection
            try:
                if self.dev is None:
                    await self._connect()
                await (self.dev.turn_on() if on else self.dev.turn_off())
                ms = (time.monotonic() - start) * 1000
                await self.dev.update()
                if self.dev.is_on != on:
                    return f"sent in {ms:.0f}ms but switch still reports on={self.dev.is_on}"
                return f"{ms:.0f}ms"
            except Exception as ex:  # noqa: BLE001
                self.dev = None
                err = f"{type(ex).__name__}: {ex}"
        r = await asyncio.create_subprocess_exec(
            sys.executable, str(KASA_CLI), "on" if on else "off", DEVICE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out = (await r.communicate())[0].decode().strip().splitlines()
        return f"direct failed ({err}); kasa_cli: {out[0] if out else r.returncode}"


async def listen(zip_code: str, havdalah_minutes: int, light: Light) -> None:
    sub = await asyncio.create_subprocess_exec(
        "docker", "exec", "mosquitto", "mosquitto_sub", "-t", f"zigbee2mqtt/{SENSOR}",
        stdout=asyncio.subprocess.PIPE,
    )
    last_contact = saved_contact()
    try:
        async for line in sub.stdout:
            try:
                contact = json.loads(line).get("contact")
            except (json.JSONDecodeError, AttributeError):
                continue
            if contact is None or contact == last_contact:
                continue
            first, last_contact = last_contact is None, contact
            if first:  # no saved state to compare against; just record it
                continue
            door = "closed" if contact else "opened"
            if in_shabbat(zip_code, havdalah_minutes):
                _log(f"door {door}; Shabbat/Yom Tov, leaving {DEVICE} alone")
                continue
            note = await light.set(on=not contact)
            _log(f"door {door} -> {DEVICE} {'off' if contact else 'on'}: {note}")
    finally:
        if sub.returncode is None:
            sub.terminate()


async def run(zip_code: str, havdalah_minutes: int) -> None:
    light = Light()
    try:
        await light._connect()  # warm up, so the first door event is fast too
    except ConnectionError as ex:
        _log(f"couldn't pre-connect to {DEVICE} ({ex}); will retry on first event")
    while True:  # mosquitto_sub exits if the container restarts; resubscribe
        await listen(zip_code, havdalah_minutes, light)
        _log("subscription ended; reconnecting in 10s")
        await asyncio.sleep(10)


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
    asyncio.run(run(args.zip, args.havdalah_minutes))


if __name__ == "__main__":
    main()
