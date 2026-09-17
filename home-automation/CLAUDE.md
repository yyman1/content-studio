# Home automation project — status and context

This project runs on a Raspberry Pi 5 (hostname `homepi.local`, user
`yerlichman`) that stays on 24/7 specifically so it can control devices
on a schedule even when other machines are off/asleep. If you're a
fresh Claude Code session starting here, read this whole file before
doing anything — it captures a lot of hard-won debugging context that
will save you from re-discovering the same bugs.

## What this is

Two connected home-automation pieces, plus a Jewish-calendar detector
meant to drive a Shabbat/holiday lighting routine:

- **`ecobee_auth.py` / `ecobee_client.py` / `ecobee_cli.py`** — controls
  an Ecobee thermostat via email/password login (Ecobee closed public
  API registration, so this drives the same Auth0 flow ecobee.com's
  website uses — see the file docstrings for why).
- **`kasa_cli.py`** — controls ~29 Kasa/Tapo smart switches/plugs on the
  local network via the `python-kasa` library. Devices are cached by
  name -> IP in `.secrets/kasa_devices.json`.
- **`jewish_calendar.py`** — queries the Hebcal API for the user's zip
  code (07666, Teaneck NJ, 42-minute havdalah custom) and reports
  whether "now" falls inside a Shabbat/Yom-Tov candle-lighting ->
  havdalah span. Multi-day chains (e.g. a holiday running into
  Shabbat) are correctly collapsed into one continuous span — see the
  module docstring for the algorithm.
- **`test_toggle.py`** — a one-off harness for validating scheduled
  device control end-to-end (waits for a start time, then
  alternates a device on/off at an interval). Already used
  successfully to confirm the Pi can run unattended scheduled actions.

## Credentials

`.secrets/` (gitignored) holds:
- `ecobee_token.json` — Ecobee refresh token
- `kasa_credentials.json` — TP-Link account email/password
- `kasa_devices.json` — cached device name -> host/model map

These already work on this Pi. Don't regenerate them unless something
is actually broken (see gotchas below for what "broken" really means
here, since the symptoms are misleading).

## Known gotchas — read before debugging auth issues

1. **"Server response doesn't match our challenge" on Kasa devices is
   NOT usually a `python-kasa` version bug**, despite how it looks. It
   was chased for a long time as a 0.10.x regression before the real
   cause was found: TP-Link devices cache a credential hash locally
   that goes stale independent of whether the account password is
   still correct. Fix: reset the TP-Link account password (Tapo app ->
   account/security settings), even to the same value — that forces
   devices to resync next time they phone home. It doesn't happen
   instantly for every device; retrying `discover --save` a few times
   over a few minutes recovers stragglers gradually. `python-kasa` is
   pinned to `0.7.7` in requirements.txt as a known-good baseline, but
   that pin was NOT the actual fix for this class of failure.
2. **`ZoneInfoNotFoundError: No time zone found with key EST`** — this
   Pi's Python can't find the system tz database and needs the
   `tzdata` PyPI package (already in requirements.txt). If you ever
   see this again after a fresh venv, it means `pip install -r
   requirements.txt` wasn't run, not a new bug.
3. **`kasa_cli.py discover --save` merges into the existing device
   file, it doesn't overwrite it** — this was a deliberate fix so a
   device that transiently doesn't respond during one scan doesn't
   vanish from `kasa_devices.json`. If you're tempted to "simplify" the
   save logic back to a plain overwrite, don't — that regressed this
   exact problem once already.
4. Also enable "Tapo Lab -> Third-Party Compatibility" in the Tapo app
   if you're setting up fresh credentials — it gates local API access
   entirely on some firmware, independent of correct credentials.

## Current state of the device roster

As of last check, 27 of ~29 Kasa/Tapo devices are confirmed working.
Two ("Family Room", "Dining Room Chandelier") were still resyncing per
gotcha #1 above — check `python3 kasa_cli.py list` for current status,
and retry `discover --save` a couple of times if any are still missing.

## What's NOT built yet — the actual next task

The Shabbat/holiday automation logic itself does not exist yet. What
exists is the two building blocks (`jewish_calendar.py` for "is it
Shabbat/Yom Tov right now, and when's the next transition" +
`kasa_cli.py` for device control) but nothing wires them together on a
schedule yet.

The user has grouped their devices into:
- First Floor areas (Living Room, Bar, Dining Room, Dining Room Dummy,
  Dining Room Chandelier, Kitchen, Table, Bathroom First Floor, Family
  Room)
- Master Bedrooms/bathrooms (Main Bedroom, Primary Lobby, Master
  Bathroom, Master Bathroom Toilet, Blanket)
- Kids bathroom (Bathroom Upstairs main, Bathroom Mirror)
- Basement (Basement, Basement Playroom, Basement Hallway, Basement
  Steps)
- Entryways/Outdoor (Front Door, Mudroom Hallway, Mudroom Porch,
  Backyard overhead light, Back Porch Side Light, Driveway front,
  Driveway Backyard/Side)
- Named for a person (Daddy's Light, Ima's Light)

**Still needed from the user**: the actual on/off behavior per group (or
per-device exceptions within a group) at candle-lighting vs. havdalah.
Ask for this if it hasn't been provided yet before building the
automation script.

Once you have that, build something like a `shabbat_automation.py`
that:
- Runs periodically via cron (every 5-10 min is reasonable — candle
  lighting/havdalah times don't need to-the-second precision, and
  frequent polling is more robust than a precisely-timed one-shot cron
  entry that could be missed if the Pi is briefly busy/rebooting)
- Calls `jewish_calendar.current_status()` to check if we're
  transitioning into or out of a Shabbat/holiday span
- Tracks last-applied state in a small local file so it doesn't
  needlessly re-issue the same on/off commands every poll
- Calls `kasa_cli.py` (or imports its functions directly) to apply the
  right action per device group
- **Logs every check and every action taken, with timestamps**, to a
  persistent log file — this runs unattended overnight/over Shabbat
  with nobody watching, so a durable audit trail matters more than for
  the interactive testing done so far.

## Working conventions

- Everything lives in `~/content-studio/home-automation` on this Pi,
  branch `claude/youthful-heisenberg-fhdhlf` of
  `github.com/yyman1/content-studio`.
- Python venv at `./venv` — always `source venv/bin/activate` first.
- Commit and push real progress the same way prior work in this repo
  has been committed (see `git log` for message style/tone).
