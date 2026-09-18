#!/usr/bin/env python3
"""Command-line tool for controlling Kasa and Tapo (TP-Link) smart plugs/strips.

Uses the community `python-kasa` library (https://github.com/python-kasa/
python-kasa), which supports both Kasa- and Tapo-branded devices through one
async API. Most newer devices (all Tapo, and newer Kasa models) require your
TP-Link account email/password even for purely local control -- the
credentials are used to derive a local encryption key, nothing is sent to
the cloud on every command.

Usage:
    python kasa_cli.py login                     # store TP-Link account creds
    python kasa_cli.py discover --save           # scan LAN, save name->IP map
    python kasa_cli.py list                       # show saved devices
    python kasa_cli.py status <name-or-ip>
    python kasa_cli.py on <name-or-ip> [--child <alias-or-id>]
    python kasa_cli.py off <name-or-ip> [--child <alias-or-id>]
    python kasa_cli.py toggle <name-or-ip> [--child <alias-or-id>]
    python kasa_cli.py brightness <name-or-ip> <0-100> [--child <alias-or-id>]

Run `discover --save` once (with devices powered on and connected to your
Wi-Fi) to build a name -> IP map in .secrets/kasa_devices.json, so later
commands can refer to devices by the alias you gave them in the Kasa/Tapo
app instead of typing IP addresses. IPs can change if your router doesn't
give devices a DHCP reservation -- re-run `discover --save` if a saved
device stops responding.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from pathlib import Path
from typing import Optional

from kasa import Device, Discover

SECRETS_DIR = Path(__file__).parent / ".secrets"
CREDENTIALS_PATH = SECRETS_DIR / "kasa_credentials.json"
DEVICES_PATH = SECRETS_DIR / "kasa_devices.json"


def _load_credentials() -> tuple[Optional[str], Optional[str]]:
    if CREDENTIALS_PATH.exists():
        data = json.loads(CREDENTIALS_PATH.read_text())
        return data.get("username"), data.get("password")
    return None, None


def _save_credentials(username: str, password: str) -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps({"username": username, "password": password}))
    CREDENTIALS_PATH.chmod(0o600)


def _load_devices() -> dict:
    if DEVICES_PATH.exists():
        return json.loads(DEVICES_PATH.read_text())
    return {}


def _save_devices(devices: dict) -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    DEVICES_PATH.write_text(json.dumps(devices, indent=2))
    DEVICES_PATH.chmod(0o600)


def _resolve_host(name_or_host: str) -> str:
    devices = _load_devices()
    if name_or_host in devices:
        return devices[name_or_host]["host"]
    return name_or_host


def cmd_login(_args: argparse.Namespace) -> None:
    print("This is your TP-Link account (the same login used by the Kasa app")
    print("and/or the Tapo app) -- required for most newer devices, even for")
    print("purely local control.")
    username = input("TP-Link account email: ").strip().lower()
    password = getpass.getpass("TP-Link account password: ").strip()
    _save_credentials(username, password)
    print(f"Saved credentials to {CREDENTIALS_PATH}.")


async def _discover(
    username: Optional[str], password: Optional[str], target: Optional[str]
) -> tuple[dict, list[tuple[str, str]]]:
    kwargs: dict = {}
    if username and password:
        kwargs["username"] = username
        kwargs["password"] = password
    if target:
        kwargs["target"] = target
    found = await Discover.discover(**kwargs)
    ok: dict = {}
    failed: list[tuple[str, str]] = []
    for host, dev in found.items():
        try:
            await dev.update()
        except Exception as ex:  # noqa: BLE001
            failed.append((host, str(ex)))
        else:
            ok[host] = dev
    return ok, failed


def cmd_discover(args: argparse.Namespace) -> None:
    username, password = _load_credentials()
    devices, failed = asyncio.run(_discover(username, password, args.target))

    if failed:
        print(f"{len(failed)} device(s) responded but couldn't be fully queried:")
        for host, err in failed:
            print(f"  {host}: {err}")
        if not (username and password):
            print(
                "These likely need your TP-Link account credentials. Run "
                "`python kasa_cli.py login`, then re-run `discover --save`.\n"
            )
        else:
            print(
                "Credentials are already saved, so this is something else "
                "(wrong password, or an unsupported device/firmware).\n"
            )

    if not devices:
        print(
            "No devices could be fully queried. Make sure they're powered on "
            "and on this Wi-Fi network."
        )
        return

    saved = {}
    for dev in devices.values():
        children = getattr(dev, "children", None) or []
        tag = " (power strip)" if children else ""
        print(f"{dev.alias!r}  host={dev.host}  model={dev.model}  on={dev.is_on}{tag}")
        entry: dict = {"host": dev.host, "model": dev.model}
        if children:
            entry["children"] = [{"id": c.device_id, "alias": c.alias} for c in children]
            for c in children:
                print(f"    outlet {c.alias!r}  child_id={c.device_id}  on={c.is_on}")
        saved[dev.alias] = entry

    if args.save:
        existing = _load_devices()
        existing.update(saved)
        _save_devices(existing)
        print(
            f"Saved {len(saved)} device(s) seen this run "
            f"({len(existing)} known in total) to {DEVICES_PATH}."
        )


def cmd_list(_args: argparse.Namespace) -> None:
    devices = _load_devices()
    if not devices:
        print("No saved devices. Run `python kasa_cli.py discover --save` first.")
        return
    for name, entry in devices.items():
        print(f"{name!r}  host={entry['host']}  model={entry.get('model')}")
        for child in entry.get("children", []):
            print(f"    outlet {child['alias']!r}  child_id={child['id']}")


async def _connect(host: str, username: Optional[str], password: Optional[str]) -> Device:
    kwargs: dict = {}
    if username and password:
        kwargs["username"] = username
        kwargs["password"] = password
    try:
        dev = await Discover.discover_single(host, **kwargs)
        await dev.update()
    except Exception as ex:  # noqa: BLE001
        hint = (
            "" if (username and password) else
            " Run `python kasa_cli.py login` if this device needs TP-Link "
            "account credentials."
        )
        raise SystemExit(f"Couldn't reach/query {host}: {ex}.{hint}") from ex
    return dev


def _find_child(dev: Device, child_ref: str):
    for c in getattr(dev, "children", None) or []:
        if c.alias == child_ref or c.device_id == child_ref:
            return c
    raise SystemExit(f"No outlet named or with id {child_ref!r} on {dev.alias!r}.")


def _target(dev: Device, child_ref: Optional[str]):
    return _find_child(dev, child_ref) if child_ref else dev


def cmd_status(args: argparse.Namespace) -> None:
    username, password = _load_credentials()
    host = _resolve_host(args.device)
    dev = asyncio.run(_connect(host, username, password))
    children = getattr(dev, "children", None) or []
    print(f"{dev.alias!r}  host={dev.host}  model={dev.model}  on={dev.is_on}")
    for c in children:
        print(f"  outlet {c.alias!r}  child_id={c.device_id}  on={c.is_on}")


async def _set_power(host: str, username, password, child_ref: Optional[str], on: bool) -> str:
    dev = await _connect(host, username, password)
    target = _target(dev, child_ref)
    if on:
        await target.turn_on()
    else:
        await target.turn_off()
    await dev.update()
    return target.alias


def cmd_on(args: argparse.Namespace) -> None:
    username, password = _load_credentials()
    host = _resolve_host(args.device)
    alias = asyncio.run(_set_power(host, username, password, args.child, True))
    print(f"Turned on {alias!r}.")


def cmd_off(args: argparse.Namespace) -> None:
    username, password = _load_credentials()
    host = _resolve_host(args.device)
    alias = asyncio.run(_set_power(host, username, password, args.child, False))
    print(f"Turned off {alias!r}.")


async def _toggle(host: str, username, password, child_ref: Optional[str]) -> tuple[str, bool]:
    dev = await _connect(host, username, password)
    target = _target(dev, child_ref)
    if target.is_on:
        await target.turn_off()
    else:
        await target.turn_on()
    await dev.update()
    return target.alias, target.is_on


def cmd_toggle(args: argparse.Namespace) -> None:
    username, password = _load_credentials()
    host = _resolve_host(args.device)
    alias, is_on = asyncio.run(_toggle(host, username, password, args.child))
    print(f"{alias!r} is now {'on' if is_on else 'off'}.")


async def _set_brightness(host: str, username, password, child_ref: Optional[str], percent: int) -> str:
    dev = await _connect(host, username, password)
    target = _target(dev, child_ref)
    await target.set_brightness(percent)
    await dev.update()
    return target.alias


def cmd_brightness(args: argparse.Namespace) -> None:
    if not 0 <= args.percent <= 100:
        raise SystemExit("Brightness percent must be between 0 and 100.")
    username, password = _load_credentials()
    host = _resolve_host(args.device)
    alias = asyncio.run(_set_brightness(host, username, password, args.child, args.percent))
    print(f"Set {alias!r} brightness to {args.percent}%.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="Store your TP-Link account email/password.").set_defaults(func=cmd_login)

    p_discover = sub.add_parser("discover", help="Scan the local network for devices.")
    p_discover.add_argument("--save", action="store_true", help="Save found devices to .secrets/kasa_devices.json")
    p_discover.add_argument("--target", help="Broadcast address to scan, if not 255.255.255.255")
    p_discover.set_defaults(func=cmd_discover)

    sub.add_parser("list", help="List saved devices.").set_defaults(func=cmd_list)

    p_status = sub.add_parser("status", help="Show a device's current state.")
    p_status.add_argument("device", help="Saved device name or IP address.")
    p_status.set_defaults(func=cmd_status)

    help_text = {"on": "Turn a device on.", "off": "Turn a device off.", "toggle": "Toggle a device's power state."}
    for name, fn in (("on", cmd_on), ("off", cmd_off), ("toggle", cmd_toggle)):
        p = sub.add_parser(name, help=help_text[name])
        p.add_argument("device", help="Saved device name or IP address.")
        p.add_argument("--child", help="Outlet alias or child_id, for a power strip.")
        p.set_defaults(func=fn)

    p_bright = sub.add_parser("brightness", help="Set a dimmable device's brightness.")
    p_bright.add_argument("device", help="Saved device name or IP address.")
    p_bright.add_argument("percent", type=int, help="Brightness percent, 0-100.")
    p_bright.add_argument("--child", help="Outlet alias or child_id, for a power strip.")
    p_bright.set_defaults(func=cmd_brightness)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
