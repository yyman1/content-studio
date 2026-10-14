#!/usr/bin/env python3
"""Bathroom lights follow the motion sensor's Zigbee occupancy.

Motion detected (occupancy=true) -> lights on; no motion (occupancy=false) -> off.
Paused from candle-lighting to havdalah (Shabbat and Yom Tov): the sensor
does nothing, and the lights stay however they were left.

Listens to Zigbee2MQTT via `mosquitto_sub` inside the `mosquitto`
container (~/zigbee). Acts only when `occupancy` changes -- the motion
sensor may send periodic heartbeat reports that repeat the same value.

Commands go straight to the switches over connections kept open between
events (~0.1s from sensor to lights), falling back to fresh connections and
then to kasa_cli.py if that fails. Each change is confirmed afterwards,
once the lights have already switched.

Long-running; cron starts it every 5 minutes and the lock makes extra
copies exit at once, so it comes back within 5 minutes of a crash or
reboot.

Usage:
    python3 motion_sensor_bathroom.py --zip 07666 --havdalah-minutes 42
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import sys
import time
from datetime import datetime, time as datetime_time
from pathlib import Path

import jewish_calendar as jc
import kasa_cli as kc
import weekday_automation as wa

HERE = Path(__file__).parent
LOCK_PATH = HERE / ".secrets" / "motion_sensor_bathroom.lock"
LOG_PATH = HERE / "motion_sensor_bathroom.log"
KASA_CLI = HERE / "kasa_cli.py"
SENSOR = "Motion Sensor"
SENSOR_IEEE = "0xb40e060fffe8484b"
Z2M_STATE_PATH = Path.home() / "zigbee" / "z2m-data" / "state.json"
DEVICES = ["Bathroom Upstairs main", "Bathroom Mirror "]


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


def in_quiet_hours() -> bool:
    """True between 11pm and 6am (when motion shouldn't auto-turn-on lights)."""
    now = datetime.now().time()
    return now >= datetime_time(23, 0) or now < datetime_time(6, 0)


def saved_occupancy():
    """The sensor's last known occupancy value from Zigbee2MQTT, or None."""
    try:
        return json.loads(Z2M_STATE_PATH.read_text()).get(SENSOR_IEEE, {}).get("occupancy")
    except (OSError, ValueError):
        return None


class Light:
    """A connection to a DEVICE kept open between motion events."""

    def __init__(self, device: str) -> None:
        self.device = device
        self.username, self.password = kc._load_credentials()
        self.dev = None

    async def _connect(self):
        try:
            self.dev = await kc._connect(kc._resolve_host(self.device), self.username, self.password)
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
            sys.executable, str(KASA_CLI), "on" if on else "off", self.device,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out = (await r.communicate())[0].decode().strip().splitlines()
        return f"direct failed ({err}); kasa_cli: {out[0] if out else r.returncode}"


async def _schedule_lights_off(delay_seconds: int, lights: list[Light]) -> None:
    """Turn off lights after delay, unless cancelled (motion detected again)."""
    try:
        await asyncio.sleep(delay_seconds)
        results = await asyncio.gather(*(light.set(on=False) for light in lights))
        _log(f"15-minute timeout -> lights off: {', '.join(results)}")
    except asyncio.CancelledError:
        pass  # Task was cancelled because motion was detected again


async def listen(zip_code: str, havdalah_minutes: int, lights: list[Light]) -> None:
    sub = await asyncio.create_subprocess_exec(
        "docker", "exec", "mosquitto", "mosquitto_sub", "-t", f"zigbee2mqtt/{SENSOR}",
        stdout=asyncio.subprocess.PIPE,
    )
    last_occupancy = saved_occupancy()
    off_task = None  # Timer to turn lights off after 15 min of no motion
    try:
        async for line in sub.stdout:
            try:
                occupancy = json.loads(line).get("occupancy")
            except (json.JSONDecodeError, AttributeError):
                continue
            if occupancy is None or occupancy == last_occupancy:
                continue
            first, last_occupancy = last_occupancy is None, occupancy
            if first:  # no saved state to compare against; just record it
                continue
            state = "detected" if occupancy else "cleared"
            if in_shabbat(zip_code, havdalah_minutes):
                _log(f"motion {state}; Shabbat/Yom Tov, leaving lights alone")
                continue
            if occupancy:  # Motion detected
                if off_task:
                    off_task.cancel()
                    off_task = None
                # Only turn on if not in quiet hours (11pm-6am)
                if in_quiet_hours():
                    _log(f"motion detected; quiet hours (11pm-6am), not turning on")
                else:
                    results = await asyncio.gather(*(light.set(on=True) for light in lights))
                    _log(f"motion detected -> lights on: {', '.join(results)}")
            else:  # Motion cleared
                # Schedule lights off after 15 minutes (900 seconds) if any are on
                any_on = any(light.dev and light.dev.is_on for light in lights if light.dev)
                if any_on or not lights[0].dev:  # Check if lights are on, or we haven't connected yet
                    off_task = asyncio.create_task(_schedule_lights_off(900, lights))
                    _log(f"motion cleared -> lights will turn off in 15 minutes")
                else:
                    _log(f"motion cleared; lights already off")
    finally:
        if sub.returncode is None:
            sub.terminate()
        if off_task:
            off_task.cancel()


async def run(zip_code: str, havdalah_minutes: int) -> None:
    lights = [Light(device) for device in DEVICES]
    for light in lights:
        try:
            await light._connect()  # warm up, so the first event is fast too
        except ConnectionError as ex:
            _log(f"couldn't pre-connect to {light.device} ({ex}); will retry on first event")
    while True:  # mosquitto_sub exits if the container restarts; resubscribe
        await listen(zip_code, havdalah_minutes, lights)
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
