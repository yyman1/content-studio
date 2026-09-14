"""Thin client for the ecobee REST API.

ecobee's API has one quirk worth pointing out: GET requests pass their
JSON-shaped `selection` object as a *query string* under
`?json=<urlencoded JSON>`. POST requests send a JSON body with a
`selection` object plus either a `thermostat` patch (for direct settings
updates) or a `functions` array (for hold-style operations like setHold /
resumeProgram).
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any, Optional

import requests

from ecobee_auth import EcobeeAuth, InvalidGrantError

API_BASE = "https://api.ecobee.com/1"
API_THERMOSTAT = f"{API_BASE}/thermostat"

REQUEST_TIMEOUT = 20

_SELECTION = {
    "selection": {
        "selectionType": "registered",
        "selectionMatch": "",
        "includeRuntime": True,
        "includeSensors": True,
        "includeProgram": True,
        "includeEquipmentStatus": True,
        "includeEvents": True,
        "includeSettings": True,
        "includeLocation": True,
    }
}


class EcobeeApiError(Exception):
    """Generic API failure (non-200, malformed JSON, network)."""


class EcobeeAuthError(Exception):
    """The supplied credentials/token were rejected by the API."""


class EcobeeClient:
    """Client for the ecobee thermostat API."""

    def __init__(self, auth: EcobeeAuth) -> None:
        self._auth = auth

    def get_thermostats(self) -> list[dict[str, Any]]:
        """Return the raw thermostatList from /1/thermostat."""
        try:
            access_token = self._auth.ensure_access_token()
        except InvalidGrantError as ex:
            raise EcobeeAuthError(str(ex)) from ex

        url = f"{API_THERMOSTAT}?json=" + urllib.parse.quote(
            json.dumps(_SELECTION, separators=(",", ":"))
        )
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as ex:
            raise EcobeeApiError(f"network error: {type(ex).__name__}: {ex}") from ex

        if resp.status_code == 401:
            raise EcobeeAuthError(f"GET {API_THERMOSTAT} -> 401")
        if resp.status_code != 200:
            raise EcobeeApiError(f"GET {API_THERMOSTAT} -> {resp.status_code}: {resp.text[:200]}")
        try:
            payload = resp.json()
        except ValueError as ex:
            raise EcobeeApiError(f"malformed JSON from {API_THERMOSTAT}: {ex}") from ex

        status_blob = payload.get("status") or {}
        if status_blob.get("code", 0) != 0:
            code = status_blob.get("code")
            msg = status_blob.get("message", "(no message)")
            if code in (14, 16):
                raise EcobeeAuthError(f"ecobee API auth code={code}: {msg}")
            raise EcobeeApiError(f"ecobee API code={code}: {msg}")

        thermostats = payload.get("thermostatList") or []
        return thermostats

    def _post_thermostat(self, body: dict[str, Any]) -> None:
        try:
            access_token = self._auth.ensure_access_token()
        except InvalidGrantError as ex:
            raise EcobeeAuthError(str(ex)) from ex

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json",
        }
        url = f"{API_THERMOSTAT}?format=json"
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as ex:
            raise EcobeeApiError(f"network error: {type(ex).__name__}: {ex}") from ex

        if resp.status_code == 401:
            raise EcobeeAuthError(f"POST {API_THERMOSTAT} -> 401")
        if resp.status_code != 200:
            raise EcobeeApiError(f"POST {API_THERMOSTAT} -> {resp.status_code}: {resp.text[:200]}")
        try:
            payload = resp.json()
        except ValueError as ex:
            raise EcobeeApiError(f"malformed JSON from POST {API_THERMOSTAT}: {ex}") from ex

        status_blob = payload.get("status") or {}
        code = status_blob.get("code", 0)
        if code != 0:
            msg = status_blob.get("message", "(no message)")
            if code in (14, 16):
                raise EcobeeAuthError(f"ecobee API auth code={code}: {msg}")
            raise EcobeeApiError(f"ecobee API code={code}: {msg}")

    @staticmethod
    def _selection(identifier: str) -> dict[str, Any]:
        return {"selectionType": "thermostats", "selectionMatch": identifier}

    def update_settings(self, identifier: str, settings: dict[str, Any]) -> None:
        """Patch the thermostat's `settings` object (e.g. hvacMode)."""
        self._post_thermostat(
            {"selection": self._selection(identifier), "thermostat": {"settings": settings}}
        )

    def set_hold(
        self,
        identifier: str,
        *,
        heat_hold_temp_f10: Optional[int] = None,
        cool_hold_temp_f10: Optional[int] = None,
        hold_climate_ref: Optional[str] = None,
        hold_type: str = "nextTransition",
        fan: Optional[str] = None,
    ) -> None:
        """Apply a temperature- or program-based hold via setHold.

        Supply explicit setpoints (heat_hold_temp_f10 / cool_hold_temp_f10,
        F * 10 integers) OR a hold_climate_ref ('home', 'away', 'sleep', a
        custom comfort setting). hold_type: 'nextTransition' (until next
        scheduled program change), 'indefinite' (sticky until resumed).
        """
        params: dict[str, Any] = {"holdType": hold_type}
        if heat_hold_temp_f10 is not None:
            params["heatHoldTemp"] = int(heat_hold_temp_f10)
        if cool_hold_temp_f10 is not None:
            params["coolHoldTemp"] = int(cool_hold_temp_f10)
        if hold_climate_ref is not None:
            params["holdClimateRef"] = hold_climate_ref
        if fan is not None:
            params["fan"] = fan
        self._post_thermostat(
            {
                "selection": self._selection(identifier),
                "functions": [{"type": "setHold", "params": params}],
            }
        )

    def resume_program(self, identifier: str, *, resume_all: bool = True) -> None:
        """Clear active holds and return to the schedule."""
        self._post_thermostat(
            {
                "selection": self._selection(identifier),
                "functions": [{"type": "resumeProgram", "params": {"resumeAll": bool(resume_all)}}],
            }
        )
