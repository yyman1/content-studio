#!/usr/bin/env python3
"""Find scheduled Kasa/Tapo devices that aren't responding.

The schedulers only notice a dead device when it's time to switch it, and
then they just retry every 5 minutes and log the failure. The Blech plug
dropped off the network around 2026-10-30 and missed three Shabbatot before
anyone noticed. zigbee_health_check.py calls this every morning (including
Friday, before Shabbat) and emails anything it reports. The Blech itself is
left out of that (it's only plugged in before Shabbat); pre_shabbat_check.py
checks it an hour before candle-lighting.

Two checks:
  - unreachable(): connect to every device a scheduler controls, right now.
  - failing_in_logs(): devices whose most recent switch attempts in the last
    LOG_LOOKBACK all failed -- catches devices that answer at 9am but not
    when they're actually scheduled.

Usage:
    python3 kasa_health.py    # print problems; doesn't send anything
"""

from __future__ import annotations

import asyncio
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import kasa_cli

HERE = Path(__file__).parent
PROBE_TIMEOUT_SECONDS = 20
PROBE_RETRY_DELAY_SECONDS = 30
LOG_LOOKBACK = timedelta(hours=72)  # reaches back over Shabbat plus a two-day Yom Tov
MIN_FAILED_RUNS = 3  # a single failed run is usually a transient handshake glitch
SCHEDULER_LOGS = [
    "shabbat_automation.log",
    "weekday_automation.log",
    "blanket_schedule.log",
    "led_schedule.log",
]
# Only plugged in an hour or two before candle-lighting, so a daily check
# would flag it every weekday. pre_shabbat_check.py checks it an hour before
# candle-lighting instead.
PLUGGED_IN_BEFORE_SHABBAT = {"Blech"}
_LINE = re.compile(r"^\[([0-9T:-]+)\] (?!\[dry-run\])([^:\[]+?): (.*)$")


def scheduled_devices() -> list[str]:
    """Every device name any scheduler controls (names stripped of stray spaces),
    minus PLUGGED_IN_BEFORE_SHABBAT."""
    import blanket_schedule, closet_auto_off, closet_door_light, led_schedule
    import motion_sensor_bathroom, shabbat_automation, weekday_automation

    names = (
        set(shabbat_automation.DEVICE_RULES) | set(weekday_automation.WEEKDAY_RULES)
        | set(led_schedule.LED_DEVICES) | set(closet_auto_off.CLOSETS)
        | set(motion_sensor_bathroom.DEVICES)
        | {blanket_schedule.DEVICE, closet_door_light.DEVICE}
    )
    return sorted({n.strip() for n in names} - PLUGGED_IN_BEFORE_SHABBAT)


async def _probe(host: str, user, password) -> str | None:
    """None if the device answers, else a short reason."""
    try:
        dev = await asyncio.wait_for(kasa_cli._connect(host, user, password), PROBE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return "no response"
    except SystemExit as ex:  # kasa_cli._connect reports failures this way
        msg = str(ex)
        if "Timed out" in msg:
            return "no response"
        return msg.split(": ", 1)[-1].split(". Run")[0].rstrip(".") or "no response"
    try:
        await dev.disconnect()
    except Exception:  # noqa: BLE001
        pass
    return None


async def _probe_all(names: list[str]) -> dict[str, str]:
    """One device at a time: parallel connections have collided with cron's
    own connections before (see CLAUDE.md, Mudroom Hallway 2026-09-20)."""
    user, password = kasa_cli._load_credentials()
    failed: dict[str, str] = {}
    pending = []
    for n in names:
        host = kasa_cli._resolve_host(n)
        if host == n:  # _resolve_host hands back the name when it isn't in the map
            failed[n] = "not in kasa_devices.json; run `kasa_cli.py discover --save`"
        else:
            pending.append((n, host))
    for attempt in range(2):
        if attempt:
            await asyncio.sleep(PROBE_RETRY_DELAY_SECONDS)
        still = []
        for n, host in pending:
            why = await _probe(host, user, password)
            if why:
                still.append((n, host))
                failed[n] = f"{host}: {why}"
            else:
                failed.pop(n, None)
        pending = still
        if not pending:
            break
    return failed


def unreachable(names: list[str] | None = None) -> list[str]:
    """One line per scheduled device that didn't answer two tries 30s apart."""
    failed = asyncio.run(_probe_all(names or scheduled_devices()))
    return [f"{n} ({why})" for n, why in sorted(failed.items())]


def failing_in_logs(now: datetime) -> list[str]:
    """Devices whose last MIN_FAILED_RUNS+ logged attempts all failed, within LOG_LOOKBACK."""
    since = now - LOG_LOOKBACK
    # name -> (failed runs in the current streak, first failure, last failure)
    streaks: dict[str, tuple[int, datetime, datetime]] = {}
    for log in SCHEDULER_LOGS:
        path = HERE / log
        if not path.exists():
            continue
        for line in path.read_text(errors="replace").splitlines():
            m = _LINE.match(line)
            if not m:
                continue
            try:
                ts = datetime.fromisoformat(m.group(1))
            except ValueError:
                continue
            if ts < since:
                continue
            name, text = m.group(2).strip(), m.group(3)
            if name in PLUGGED_IN_BEFORE_SHABBAT:
                continue
            if "retrying in" in text or name.startswith(("Done", "Hebcal", "outside")):
                continue  # mid-run retry notes and non-device lines
            if "will retry next run" in text:
                count, first, _ = streaks.get(name, (0, ts, ts))
                streaks[name] = (count + 1, first, ts)
            else:
                streaks.pop(name, None)  # it worked; streak over
    return [
        f"{name}: {count} scheduled switch attempts failed, "
        f"{first:%a %b %-d %-I:%M %p} - {last:%a %b %-d %-I:%M %p}"
        for name, (count, first, last) in sorted(streaks.items())
        if count >= MIN_FAILED_RUNS
    ]


def main() -> int:
    down = unreachable()
    logged = failing_in_logs(datetime.now())
    print("Not responding now:\n" + ("\n".join(f"- {d}" for d in down) or "- (none)"))
    print("Recent scheduled switches failing:\n" + ("\n".join(f"- {d}" for d in logged) or "- (none)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
