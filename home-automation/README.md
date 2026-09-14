# Home automation scripts

Personal scripts for controlling home devices: an ecobee thermostat, and
(next) Kasa/Tapo smart plugs.

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

Not built yet -- next step.
