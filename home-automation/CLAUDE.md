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
  below). **Live on cron as of 2026-09-18**, running every 5 minutes --
  see that section for what's still open (first real-device run hasn't
  been verified yet).

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

All 29 Kasa/Tapo devices are confirmed working as of 2026-09-18,
including the two ("Family Room", "Dining Room Chandelier") that had
been resyncing per gotcha #1 above -- they recovered after a few
`discover --save` retries. `python3 kasa_cli.py list` should show all
29; if any regress, that gotcha is still the first thing to check.

`kasa_cli.py` also has a `fade` command (steps a dimmable device down
through brightness levels, then quickly back up to 100%) alongside
`brightness` -- these were developed in parallel on two different
sessions (this one and a Pi-local session) and had to be merged by
hand once; both are intentional, not duplicates to clean up.

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

There's also a `before_havdalah_hours` rule field (with its own
`_havdalah_desired()` helper), added for Master Bathroom: it turns on
N hours before the *actual* havdalah event (not a fixed clock time),
off at the same `nightly_cutoff` its evening rule already uses. This
is deliberately keyed off `events.havdalahs` rather than a clock time
so it tracks the real end of Shabbat/Yom Tov week to week (havdalah
time changes) instead of drifting. Checked in `desired_state()` right
after `_yomtov_desired()` and before the evening/candle branch.

Cron entry (live since 2026-09-18):
```
*/5 * * * * cd /home/yerlichman/content-studio/home-automation && venv/bin/python3 shabbat_automation.py --zip 07666 --havdalah-minutes 42 >> cron.log 2>&1
```

Still to do:

1. **First live run against real devices not yet verified end-to-end.**
   Cron is running every 5 min starting the afternoon of Fri 2026-09-18
   (candle-lighting 6:41pm that evening, havdalah 7:40pm Sat 9/19) --
   this is the very first Shabbat it's controlling real hardware, not
   just synthetic-timestamp dry runs. Check `cron.log` (no tracebacks)
   and `shabbat_automation.log` (state transitions logged as expected)
   after it's had a chance to run through a full cycle, and spot-check
   a few actual devices against the schedule that was emailed out.
2. An email summarizing the schedule for this specific Shabbat (grouped
   by the household's original PDF categories: First Floor, Master
   Bedroom/Bathrooms, Kids Bathroom, Basement, Entryways/Outdoor; two
   columns, Night vs. Day) was sent 2026-09-18 to confirm the rules
   read correctly before they ran live. If you're asked to do this
   again for a future Shabbat/Yom Tov, the pattern is: pull the actual
   candle-lighting/havdalah times via `jewish_calendar.py`, derive each
   device's on/off times from its `DeviceRule` (don't hand-copy old
   numbers -- compute fresh, rules can change), group by the comments
   in `DEVICE_RULES` (they mirror the PDF's categories), and send via
   the Gmail MCP tool.

## Door sensor project — in progress, not built yet

Household wants a door-open -> light-on trigger. Decided against Tapo's
own T110/H100 (proprietary hub, would be a second closed ecosystem) and
against routing through Alexa (extra cloud hop, household finds Alexa
routines annoying to manage). Landed on: **Zigbee2MQTT + Mosquitto on
this Pi**, feeding a small Python listener that calls `kasa_cli.py`
directly -- same local-only philosophy as the rest of this project, no
new cloud dependency.

Hardware status as of 2026-09-24: **SONOFF Zigbee 3.0 USB Dongle
Plus-E is plugged into the Pi.** Household also has an **Aqara
door/window sensor** (MCCGQ11LM or MCCGQ14LM -- check which; both work
with Zigbee2MQTT despite the box saying "Requires Aqara Hub", which is
just aimed at the average Aqara-app buyer, not us). Neither Mosquitto
nor Zigbee2MQTT is installed yet -- this is next.

Setup plan (not yet executed -- if you're picking this up, verify each
step actually happened rather than assuming it did just because it's
written here):

1. Find the dongle's persistent serial path: `ls -l
   /dev/serial/by-id/`. Use this path, not `/dev/ttyUSB0`, which can
   shift if another USB serial device is ever added.
2. `sudo apt install -y mosquitto mosquitto-clients && sudo systemctl
   enable --now mosquitto` -- local MQTT broker, default port 1883.
3. Node.js 20.x via nodesource, then clone Zigbee2MQTT into
   `/opt/zigbee2mqtt` and `npm ci` there.
4. Configure `/opt/zigbee2mqtt/data/configuration.yaml`: `mqtt.server:
   mqtt://localhost:1883`, `serial.port` set to the by-id path from
   step 1, `permit_join: true` while pairing (turn off once devices are
   paired, security -- don't leave it on indefinitely), `frontend.port:
   8080`.
5. Run once via `npm start` interactively to confirm the network comes
   up and the Aqara sensor joins (hold its reset button ~5s while
   permit_join is true) before wiring it into systemd as a persistent
   service.
6. Once the sensor is joined and publishing to
   `zigbee2mqtt/<friendly_name>` over MQTT, write a small Python
   listener (paho-mqtt, add to requirements.txt) that subscribes to
   that topic and calls `kasa_cli.py on <device>` via subprocess on the
   open/close event -- mirrors how `shabbat_automation.py` already
   shells out to `kasa_cli.py`, just event-triggered instead of polled.
7. If interference/flaky readings show up (Pi 5's USB 3.0 ports share
   the 2.4GHz band with Zigbee), move the dongle onto a cheap USB
   extension cable a few inches from the board -- known fix, don't
   need to re-diagnose from scratch.

**Open question, not yet answered -- do not assume an answer, ask the
household:** should the door-triggered light be suppressed entirely
during Shabbat/Yom Tov (checking `jewish_calendar.current_status()`
before acting, same function `shabbat_automation.py` already uses), or
does their halachic guidance distinguish this from other cases? This
is a household/rabbinic decision, not a technical one -- the code
supports either "fully suppressed" or something more granular equally
easily once the household says which they want.

## Working conventions

- Everything lives in `~/content-studio/home-automation` on this Pi,
  branch `claude/youthful-heisenberg-fhdhlf` of
  `github.com/yyman1/content-studio`.
- Python venv at `./venv` — always `source venv/bin/activate` first.
- Commit and push real progress the same way prior work in this repo
  has been committed (see `git log` for message style/tone).
