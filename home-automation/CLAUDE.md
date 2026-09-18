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
- **`shabbat_automation.py`** — the actual Shabbat/Yom Tov lighting
  automation, wiring `jewish_calendar.py` + `kasa_cli.py` together per
  the household's written spec (see "Shabbat automation" section
  below). Built and tested against real Hebcal data, but **not yet
  scheduled via cron and not yet run against real devices** -- see
  that section for what's left.

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

## Shabbat automation — status and what's left

`shabbat_automation.py` implements the household's full written spec
(a PDF listing every device's rules) as a `DEVICE_RULES` dict, one
entry per device that needs automation -- anything not in that dict is
deliberately left alone, since it has an existing schedule that runs
through the Kasa/Tapo app itself. Each rule is some combination of:
evening candle-lighting start, a fixed nightly cutoff, a relative
offset with a cap (e.g. "4 hours after candle-lighting, but by 11pm at
the latest"), a Yom Tov daytime on/off window, dimming with a sunrise
cutoff, or "Sukkot only."

It's designed to run every 5-10 min via cron rather than at precisely
timed moments (a one-shot cron entry can be missed if the Pi is busy or
rebooting; polling just catches up next cycle) and recomputes every
device's desired state from scratch each run, only issuing a
`kasa_cli.py` command when it actually changed -- self-healing against
a missed run or a manual override, tracked in
`.secrets/shabbat_state.json`. Every check and action is logged to
`shabbat_automation.log` (gitignored).

It's been tested extensively against real Hebcal data with synthetic
`now` values (see the commit messages for `shabbat_automation.py` for
the bugs that testing caught and fixed, including a subtle one where a
stale first-night candle-lighting could win over a fresher second-night
one once the lookback window was widened enough to span a full
weekend -- fixed by checking candle events most-recent-first). Per
household confirmation, `Bathroom Upstairs main` stays fully on all day
once its 7am trigger fires and dims to 10% at 11pm every night
regardless (no separate Yom Tov daytime cutoff needed) -- this is
implemented and tested, not an open question anymore.

Still to do:

1. **Not yet added to cron.** Something like:
   `*/5 * * * * cd ~/content-studio/home-automation && venv/bin/python3 shabbat_automation.py --zip 07666 --havdalah-minutes 42 >> cron.log 2>&1`
2. **Not yet run against real devices** -- only tested with synthetic
   timestamps against real Hebcal data, never actually fired a real
   `kasa_cli.py on/off/brightness` command against real hardware. Run
   `--dry-run` first, then without it, ideally around an actual
   upcoming candle-lighting/havdalah to watch it work end to end.
3. The two devices still resyncing per gotcha #1 (Family Room, Dining
   Room Chandelier) need to actually be reachable for their rules in
   `DEVICE_RULES` to do anything -- check `kasa_cli.py list` shows them
   before trusting a dry run that touches them.

## Working conventions

- Everything lives in `~/content-studio/home-automation` on this Pi,
  branch `claude/youthful-heisenberg-fhdhlf` of
  `github.com/yyman1/content-studio`.
- Python venv at `./venv` — always `source venv/bin/activate` first.
- Commit and push real progress the same way prior work in this repo
  has been committed (see `git log` for message style/tone).
