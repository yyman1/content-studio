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
- **`ecobee_yomtov.py`** — replicates each thermostat's own native
  Saturday schedule onto Yom Tov days (see "Yom Tov thermostat
  automation" section below), so nobody has to manually clear the
  "away" block by hand every time a holiday falls on a weekday. **Live
  on cron as of 2026-09-18**, running every 10 minutes.

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

**Update 2026-09-20: this email is now automated.** `schedule_email.py`
replays `shabbat_automation.desired_state()` over the whole
candle-lighting -> havdalah span in 5-minute steps (the cron cadence) and
turns the transitions into the email, so it always reflects the current
`DEVICE_RULES` and one-off overrides -- nothing to hand-edit. Cron runs it
at 12:00 daily (plus a 12:20 retry, since Hebcal/network blips are real --
see cron.log); it's a silent no-op unless a span *starts* that day, so one
email goes out at noon on the day of candle-lighting for every Shabbat and
Yom Tov (a multi-day chain gets a single email). Delivery is via
`claude -p` with only `mcp__claude_ai_Gmail__send_message` allowed
(the Pi has no SMTP creds); sent spans are recorded in
`.secrets/schedule_email_sent.json` so the retry can't duplicate. Sends to
yerlichman@gmail.com only, matching the 9/18 email. Preview any date with
`venv/bin/python3 schedule_email.py --zip 07666 --date YYYY-MM-DD --print`.
A new device in `DEVICE_RULES` should also be added to `GROUPS` in that file
(otherwise it lands under an "OTHER" heading rather than being dropped).
Log: `schedule_email.log` / `schedule_email_cron.log`.

```
0 12 * * *  cd /home/yerlichman/content-studio/home-automation && venv/bin/python3 schedule_email.py --zip 07666 --havdalah-minutes 42 --send >> schedule_email_cron.log 2>&1
20 12 * * * (same command -- retry, guarded by the sent marker)
```

**Update 2026-09-20:** `DeviceRule.on_brightness` (new) makes every "on"
for that device land at a fixed brightness instead of full/last-used.
Dining Room Chandelier is set to 15% (`on_brightness=15`). `apply_state`
runs `brightness <pct>` first (so it never flashes at the old level), then
a confirmed `on`. Desired state is still just "on"/"off" in the state file
-- only the command sequence and the schedule email ("on at 15%") differ.
First real run: Sun 2026-09-20 ~5:40pm; check `shabbat_automation.log`.

Two device-rule changes landed after the schedule email above went
out, both in `DEVICE_RULES`: Master Bathroom got a `yomtov_on=08:00,
yomtov_off=12:00` daytime window added on top of its existing evening/
before-havdalah rules, and Dining Room Chandelier got a one-time
`YOMTOV_ON_OVERRIDES[("Dining Room Chandelier", date(2026,9,19))] =
10:30` exception (auto-expires once that date passes -- see the
comment above that dict for the pattern if another one-off is needed).

## Weekday (non-Shabbat/Yom Tov) lighting — `weekday_automation.py`

Added 2026-09-20 from the household's written weekday spec
(`WEEKDAY_RULES`). Cron every 5 min (`weekday_cron.log`, `weekday_automation.log`).
**Goes live at Yom Kippur's havdalah, Mon 2026-09-21 ~7:37pm**
(`GO_LIVE_HAVDALAH_DATE`); before that only the two `always` lights
(Front Door, Mudroom Porch) act, everything else is a silent no-op.

- **Events, not states.** The spec is "off at 10pm" / "on at 6:30am", so each run
  fires a device's most recent applicable event once (token = date+time+action in
  `.secrets/weekday_state.json`). A light someone turns back on after its "off"
  stays on; the next event still fires. `enforce_off` (Basement Steps
  7:45-9:45) re-issues off every run in its window instead.
- **Skipped during Shabbat/Yom Tov.** Events falling inside a Shabbat regime
  (candle-lighting minus 1h through havdalah) never fire. `always=True` events
  (Front Door, Mudroom Porch: on 30 min before sunset / off at sunrise or
  11:30pm, "even on Shabbat and Yom Tov") ignore that, and are also live
  immediately rather than waiting for go-live (their app schedules were
  disabled, so they'd otherwise be dark until Mon 9/21 havdalah). Sunset/sunrise come from Hebcal
  zmanim, cached in `.secrets/zmanim_cache.json`; the calendar is cached 6h in
  `.secrets/events_cache.json` (falls back to stale if Hebcal is down).
- **Hand-off from `shabbat_automation.py`.** After havdalah, devices that have a
  weekday rule are skipped by the Shabbat script (`wd.yields_to_weekday`; it
  records state `"weekday"` so the next Shabbat's first "on" still fires).
  Without this, Shabbat's post-havdalah cutoffs (Living Room 11:30pm, Upstairs
  main dim-to-10% at 11pm, ...) would fight the weekday times. Devices the spec
  says "do nothing" for (Master Bathroom, Toilet, Main Bedroom, Primary Lobby)
  keep their Shabbat post-havdalah behavior.
- Test with a fake clock: `--now 2026-09-21T22:00:00-04:00 --dry-run` on either script.

Kasa-app (on-device) schedules that are still ENABLED and coexist with this
(re-read 2026-09-20 after the household disabled/removed the overlapping
ones; disabled rules are ignored): Mudroom Porch and Driveway front each on
5:30am / off 6:30am Tue+Fri (deliberately kept by the household -- the Pi
never issues anything in that window); Backyard overhead off 23:00 daily
(same time as the Pi rule); Driveway Backyard/Side off 23:59 daily. Front Door
and Back Porch Side Light have no enabled app rules (Pi is the only
controller). Household decisions: Table's 7am on / 8am off are Mon-Fri only;
Back Porch Side Light weekday off is 11pm. Mudroom Hallway failed auth once
during a scan on 2026-09-20 but was fine one-at-a-time -- that was parallel
connections colliding with cron, not the stale-credential gotcha; don't scan
devices in parallel while cron is running.

## Master Bathroom switch replaced (2026-09-25)

The Master Bathroom HS200 was replaced by a Tapo S505D(US) at .110 (the
HS200 now lives in Yaakov's closet as "Yaakov Closet", .147). The new
switch first advertised `encrypt_type: TPAP`, which no python-kasa version
supports (`UnsupportedDeviceError`). **Turning on Tapo Lab -> Third-Party
Compatibility (gotcha #4) switched it to a supported protocol.** It then
hit gotcha #1: a password reset fixed it, but knocked 9 other devices out
of sync for a while. Watch for `encrypt_type TPAP` on any new Tapo device.
Also, because `discover --save` merges (gotcha #3), a replaced device's
old entry keeps pointing at the old IP until the new one is found. The
rule was briefly commented out and is restored now.

Since it's dimmable, its 11pm off became dim-to-10% with `off_at_sunrise`,
including the night after havdalah. `_havdalah_desired()` now handles
dimmable rules for that. Also added "SL Closet" (S505D, .111): on 1h
before candle-lighting and 1h before havdalah, off 11pm, and 9-11am on
Shabbat/Yom Tov days. It isn't in
schedule_email's `GROUPS` yet, so it shows under "OTHER".

## Yaakov Closet door light — `closet_door_light.py` (2026-09-25)

The Aqara "Door Sensor" (Zigbee2MQTT, ~/zigbee) drives "Yaakov Closet":
open -> on, closed -> off. It's paused from candle-lighting to havdalah
(strict span, no 1h lead), so on Shabbat/Yom Tov the door does nothing.
It's a long-running `mosquitto_sub` listener, not a poller. Cron starts it
every 5 min and a lock in `.secrets/` makes the extras exit, so it
recovers from crashes and reboots within 5 minutes (no sudo on this Pi for
a system service, and no linger for a user one). The baseline door state
comes from `~/zigbee/z2m-data/state.json`, so a restart neither flips the
light nor swallows the next event. Log: `closet_door_light.log`.
`door_sensor_test.py` is the earlier test harness it grew from.

```
*/5 * * * * cd /home/yerlichman/content-studio/home-automation && venv/bin/python3 closet_door_light.py --zip 07666 --havdalah-minutes 42 >> closet_door_light_cron.log 2>&1
```

## Yom Tov thermostat automation — status

The household asked to "replicate the Shabbat schedule on Yom Tov" so
nobody has to manually intervene every time a holiday falls on a
weekday: each Ecobee thermostat's own native weekly program already
has a correct Saturday row (day index 5 -- no "away" block, later
wake-up), it's just that a Tuesday-Rosh-Hashana or similar still runs
its normal weekday "away" block during work hours since nobody's
actually at work.

`ecobee_yomtov.py` polls every 10 min (same self-healing,
recompute-from-scratch-and-diff design as `shabbat_automation.py`,
state in `.secrets/yomtov_thermostat_state.json`, log in
`ecobee_yomtov.log`). Each run, per thermostat:
- If `now` is a Saturday, or isn't inside an active
  `jewish_calendar` span, or the active span's label is plain
  "Shabbat" (no holiday overlapping it) -- leave it alone / resume the
  native program. Plain weekly Shabbat is intentionally never touched,
  since the native Friday+Saturday schedule already handles it; only
  a span whose label is an actual holiday name triggers anything.
  ("Shabbat" vs. a holiday name is exactly what
  `jewish_calendar._label_for()` already encodes, no extra logic
  needed.)
- Otherwise, read that thermostat's own Saturday schedule row
  (`program.schedule[5]`, 48 half-hour-slot climateRefs) for whatever
  slot `now` falls in, and hold that climateRef via `setHold` with
  `holdType=indefinite` (not `nextTransition` -- we want to keep
  overriding it ourselves on every poll, not have ecobee's own
  schedule engine silently reclaim it at its next transition).

Verified with synthetic-clock simulation against real Hebcal + ecobee
schedule data (Yom Kippur, a Sukkot chain that includes an actual
Saturday mid-holiday, and this week's plain Shabbat -- see conversation
history / commit message for the transition-by-transition results),
then a real one-off `set_hold`/`resume_program` smoke test against the
live Main Floor thermostat on 2026-09-18 before enabling cron.

**Known caveat, confirmed live during that smoke test:** `resume_program`
clears *all* holds on a thermostat, not just ones this script set. If a
`touSetback` (utility demand-response) or any other unrelated hold is
active when a Yom Tov ends, this script's havdalah-time resume will
clear that too. Hasn't caused a real problem yet, just something to
know if a thermostat's behavior looks off right after a holiday ends.

Cron entry (live since 2026-09-18):
```
*/10 * * * * cd /home/yerlichman/content-studio/home-automation && venv/bin/python3 ecobee_yomtov.py --zip 07666 --havdalah-minutes 42 >> ecobee_yomtov_cron.log 2>&1
```

Not yet verified against a real Yom Tov transition end-to-end via cron
(only the manual smoke test above) -- Yom Kippur (candle-lighting Sun
2026-09-20 6:40pm) will be the first real one. Check
`ecobee_yomtov.log` and `ecobee_yomtov_cron.log` (no tracebacks) after
it's had a chance to run through that.

## Door sensor project — built (2026-09-25); plan below kept for history

**Status:** built, but not the way the plan below describes. Mosquitto and
Zigbee2MQTT run as Docker containers in `~/zigbee` (not apt or
/opt/zigbee2mqtt), with the dongle's adapter set to `ember`. The Aqara
MCCGQ11LM paired as "Door Sensor". The listener is `closet_door_light.py`
(see its section below). It uses `mosquitto_sub` in the container rather
than paho-mqtt. The open Shabbat question is answered: the household chose
to pause it from candle-lighting to havdalah.

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
