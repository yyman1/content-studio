#!/usr/bin/env python3
"""Check devices that only get plugged in before Shabbat, an hour before candle-lighting.

The Blech is only connected an hour or two before candle-lighting, so the
9am daily check (kasa_health.py, via zigbee_health_check.py) skips it --
it would flag it as offline every weekday. Instead, this runs from cron
every 5 minutes and does something only in the window from PRE_CHECK
before the first candle-lighting of each Shabbat/Yom Tov until
candle-lighting itself:

  1. Probe each PRE_SHABBAT_DEVICES device (two tries, 30s apart).
  2. If one doesn't answer, run `kasa_cli.py discover --save` (it came back
     on a new IP once, 2026-11-18) and probe again.
  3. If it still doesn't answer, email (at most once per span). Later runs
     in the window keep probing and rescanning quietly, so a plug that comes
     back late -- even on a new IP -- is picked up before candle-lighting.
     Once it answers, the rest of the window is a no-op. Nothing runs after
     candle-lighting.

State (which spans are done) is in .secrets/pre_shabbat_check_state.json.

Usage:
    python3 pre_shabbat_check.py --zip 07666            # what cron runs
    python3 pre_shabbat_check.py --zip 07666 --now      # probe right now; print, don't send
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import jewish_calendar as jc
import kasa_health
from schedule_email import _send_via_claude

HERE = Path(__file__).parent
LOG_PATH = HERE / "pre_shabbat_check.log"
STATE_PATH = HERE / ".secrets" / "pre_shabbat_check_state.json"
PRE_CHECK = timedelta(hours=1)
PRE_SHABBAT_DEVICES = sorted(kasa_health.PLUGGED_IN_BEFORE_SHABBAT)


def _log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def _probe_with_rediscover() -> list[str]:
    down = kasa_health.unreachable(PRE_SHABBAT_DEVICES)
    if not down:
        return []
    _log("Not answering: " + "; ".join(down) + " -- running discover --save")
    subprocess.run(
        [sys.executable, str(HERE / "kasa_cli.py"), "discover", "--save"],
        cwd=str(HERE), capture_output=True, timeout=120,
    )
    return kasa_health.unreachable(PRE_SHABBAT_DEVICES)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--zip", required=True)
    p.add_argument("--havdalah-minutes", type=int, default=42)
    p.add_argument("--now", action="store_true", help="Probe right now and print; don't send.")
    args = p.parse_args()

    if args.now:
        down = _probe_with_rediscover()
        print("\n".join(down) or "All pre-Shabbat devices responding.")
        return 0

    now = datetime.now().astimezone()
    span = next(
        (s for s in jc.fetch_spans(args.zip, args.havdalah_minutes) if s.start - PRE_CHECK <= now < s.start),
        None,
    )
    if span is None:
        return 0  # the normal case: not in the hour before candle-lighting
    key = span.start.isoformat()
    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    if state.get(key) == "ok":
        return 0  # already passed for this span

    down = _probe_with_rediscover()
    if not down:
        state[key] = "ok"
        _log(f"OK before {span.label} ({span.start:%a %-I:%M %p})")
    elif key in state:
        return 0  # already emailed; keep probing (and rescanning) quietly until candle-lighting
    else:
        subject = "Not connected before candle-lighting: " + ", ".join(d.split(" (")[0] for d in down)
        body = (
            f"Candle-lighting for {span.label} is at {span.start:%-I:%M %p}, and these didn't answer "
            "the Pi (two tries, 30 seconds apart, plus a fresh network scan), so they won't turn on "
            "on schedule:\n\n"
            + "\n".join(f"- {d}" for d in down)
            + "\n\nTo fix: check it's plugged in and the outlet has power, then unplug it for 10 "
            "seconds. If it doesn't show up in the Kasa app, re-add it there. The Pi checks again "
            "every 5 minutes until candle-lighting and picks up a new IP on its own."
        )
        if not _send_via_claude(subject, body):
            _log(f"FAILED to send {subject!r}; the next run will retry")
            return 1
        state[key] = down
        _log(f"Sent: {subject}")
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
