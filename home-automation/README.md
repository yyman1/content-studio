# Home automation scripts

Personal scripts for controlling home devices: an ecobee thermostat and
Kasa/Tapo smart plugs.

## Ecobee

Ecobee closed public developer-portal registration, so the classic
PIN/API-key flow isn't available to new users anymore. `ecobee_auth.py`
instead logs in the same way ecobee.com's own website does: an OAuth
Authorization Code + PKCE flow against ecobee's Auth0 tenant, using your
ordinary ecobee.com email + password. This is not a documented public
API -- it mirrors the community `ha-ecobee` Home Assistant integration
(https://github.com/pjordanandrsn/ha-ecobee), which exists for the exact
same reason. It can break if ecobee changes their login pages, and if
that happens the fix is updating the constants/steps in `ecobee_auth.py`
to match ecobee's current Auth0 flow.

Your password is only ever sent directly to `auth.ecobee.com` (never
stored) and is typed via a hidden prompt, not passed as a command-line
argument. What gets persisted locally is a **refresh token**, in
`.secrets/ecobee_token.json` (gitignored, chmod 600) -- functionally
equivalent to a long-lived API credential. Treat that file like a
password: don't commit it, don't share it.

### Setup

```bash
cd home-automation
pip install -r requirements.txt
python ecobee_cli.py login
```

You'll be prompted for your email and password. If your account has MFA
enabled, you'll get a follow-up prompt for the 6-digit code.

### Usage

```bash
python ecobee_cli.py status                                  # current temp/mode/holds
python ecobee_cli.py set-temp --heat 68 --cool 76             # hold until next scheduled change
python ecobee_cli.py set-temp --heat 65 --hold-type indefinite
python ecobee_cli.py away                                     # apply the 'away' comfort setting
python ecobee_cli.py home                                     # apply the 'home' comfort setting
python ecobee_cli.py resume                                   # clear holds, back to schedule
```

All commands operate on your first registered thermostat by default; pass
`--thermostat-id <identifier>` (shown in `status` output) to target a
specific one if you have more than one.

## Kasa / Tapo

Uses the community [`python-kasa`](https://github.com/python-kasa/python-kasa)
library, which controls both Kasa- and Tapo-branded devices through one
API. Most newer devices (all Tapo, and newer Kasa models like the KP125M)
require your TP-Link account email/password even for local control -- it's
used to derive a local encryption key; commands still go directly to the
device on your LAN, not through the cloud.

### Setup

```bash
cd home-automation
pip install -r requirements.txt
python kasa_cli.py login       # only needed if any of your devices require auth
python kasa_cli.py discover --save
```

`discover` scans your network (devices must be powered on and connected to
Wi-Fi) and prints what it finds, including individual outlets on any power
strip. `--save` writes a name -> IP map to `.secrets/kasa_devices.json` so
later commands can use the alias you gave the device in the Kasa/Tapo app
instead of an IP address.

### Usage

```bash
python kasa_cli.py list                          # show saved devices
python kasa_cli.py status "Living Room Lamp"
python kasa_cli.py on "Living Room Lamp"
python kasa_cli.py off "Living Room Lamp"
python kasa_cli.py toggle "Living Room Lamp"

# power strips: target one outlet with --child (alias or child_id from discover/status)
python kasa_cli.py on "Office Strip" --child "Monitor"
```

If a saved device stops responding, your router probably handed it a new
DHCP lease -- re-run `discover --save` to refresh `.secrets/kasa_devices.json`
(or set a DHCP reservation for each device in your router so the IP never
changes).
