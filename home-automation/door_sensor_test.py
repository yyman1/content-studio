#!/usr/bin/env python3
"""Test harness: drive a Kasa device from the Zigbee door sensor.

Magnets together (contact=true)  -> device off
Magnets apart    (contact=false) -> device on

Listens to Zigbee2MQTT's topic for the sensor via `mosquitto_sub` inside
the `mosquitto` container (~/zigbee), so no MQTT library is needed in the
venv. Only acts when `contact` actually changes -- the Aqara sensor also
sends periodic battery/heartbeat reports that repeat the same value.

Usage:
    python3 door_sensor_test.py                      # Door Sensor -> Table
    python3 door_sensor_test.py --device "Living Room" --sensor "Door Sensor"
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sensor", default="Door Sensor", help="Zigbee2MQTT friendly name.")
    parser.add_argument("--device", default="Table", help="Saved Kasa device name or IP.")
    args = parser.parse_args()

    topic = f"zigbee2mqtt/{args.sensor}"
    sub = subprocess.Popen(
        ["docker", "exec", "mosquitto", "mosquitto_sub", "-t", topic],
        stdout=subprocess.PIPE,
        text=True,
    )
    print(f"Listening on '{topic}', controlling '{args.device}' (Ctrl+C to stop)", flush=True)

    last_contact = None
    try:
        for line in sub.stdout:
            try:
                contact = json.loads(line).get("contact")
            except json.JSONDecodeError:
                continue
            if contact is None or contact == last_contact:
                continue
            last_contact = contact
            state = "off" if contact else "on"
            print(
                f"[{datetime.datetime.now():%H:%M:%S}] contact={contact} -> {args.device} {state}",
                flush=True,
            )
            subprocess.run([sys.executable, "kasa_cli.py", state, args.device], check=False)
    except KeyboardInterrupt:
        pass
    finally:
        sub.terminate()


if __name__ == "__main__":
    main()
