"""Single-room temperature write with immutable local backup and readback.

Does not modify internal weekly programs or change operating modes. The
comfort action uses setTargetTemperature, previously observed as COMPLETED in
the customer's history, but its physical semantics remain experimental.
"""
from __future__ import annotations
import asyncio
import json
import math
import secrets
from datetime import datetime, timezone
from pathlib import Path

from pyoverkiz.auth.credentials import UsernamePasswordCredentials
from pyoverkiz.client import OverkizClient
from pyoverkiz.models import Action, Command

from scheduler_service import extract_program

F = {
    "comfort": ("setTargetTemperature", "core:TargetTemperatureState"),
    "reduction": ("setSetpointLoweringTemperatureInProgMode", "io:SetpointLoweringTemperatureInProgModeState"),
}
BACKUPS = Path(__file__).resolve().parent / ".private" / "temperature_backups"


def numeric(states, name):
    value = states.get(name)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


async def change(app, room_id, field, value, expected):
    if field not in F:
        raise ValueError("Unknown field")
    mapping = app.load_mapping()
    if not mapping or sorted(mapping.values()) != sorted(app.ROOM_NAMES) or room_id not in mapping:
        raise ValueError("Verified room mapping required")
    room = mapping[room_id]
    if not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value) or round(value * 2) != value * 2:
        raise ValueError("Use a temperature in 0.5-degree increments")
    if field == "comfort" and not 15 <= value <= 24:
        raise ValueError("Base temperature must be between 15 and 24°C")
    if field == "reduction" and not 0 <= value <= 8:
        raise ValueError("Eco reduction must be between 0 and 8°C")
    cmd, state = F[field]
    async with OverkizClient(server=app.SESSION["server"],
                             credentials=UsernamePasswordCredentials(app.SESSION["username"], app.SESSION["password"])) as client:
        await client.login(register_event_listener=False)
        devices = await client.get_devices()
        heaters = [d for d in devices if getattr(d, "controllable_name", None) == app.HEATER_TYPE]
        if len(heaters) != 4 or {app.private_id(d) for d in heaters} != set(mapping):
            raise ValueError("Radiator inventory differs from the verified room mapping")
        matches = [d for d in heaters if app.private_id(d) == room_id]
        if len(matches) != 1:
            raise ValueError("Ambiguous radiator identity")
        heater = matches[0]
        if not heater.supports_command(cmd):
            raise ValueError(f"Radiator does not advertise {cmd}")
        before_states = {str(s.name): s.value for s in await client.get_state(heater.device_url)}
        before = numeric(before_states, state)
        if before is None or abs(before - expected) > 0.01:
            raise ValueError("Target changed since preview. Refresh and review again.")
        if before_states.get("core:OperatingModeState") != "internal" or before_states.get("io:InternalExternalSchedulingTypeState") != "internal":
            raise ValueError("Only internal scheduling is supported; no write sent")
        _, week = extract_program(await client.get_state(heater.device_url))
        # Use cloud's exact weekly representation in backup, rather than a canonicalized copy.
        before_raw = next(x.value for x in await client.get_state(heater.device_url) if str(x.name) == "core:TimeProgramState")
        comfort = numeric(before_states, "core:ComfortRoomTemperatureState")
        reduction = numeric(before_states, "io:SetpointLoweringTemperatureInProgModeState")
        if comfort is None or reduction is None:
            raise ValueError("Cannot verify current programmed temperatures")
        if field == "comfort" and value - reduction < 15:
            raise ValueError("Base target minus Eco reduction cannot fall below 15°C")
        if field == "reduction" and comfort - value < 15:
            raise ValueError("Comfort minus reduction cannot fall below 15°C")
        if abs(before - value) < 0.01:
            return {"room": room, "field": field, "state": "already", "old": before,
                    "requested": value, "observed": before, "schedule_unchanged": True,
                    "execution_state": "not sent", "failure_type": "none"}
        # Establish fresh consistency prior to write; a parallel change aborts.
        fresh = {str(s.name): s.value for s in await client.get_state(heater.device_url)}
        if numeric(fresh, state) != before or fresh.get("core:TimeProgramState") != before_raw:
            raise ValueError("Cloud state changed before write; no command sent")
        BACKUPS.mkdir(parents=True, exist_ok=True)
        destination = BACKUPS / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + secrets.token_hex(4) + ".json")
        with destination.open("x", encoding="utf-8") as f:
            json.dump({"room": room, "field": field, "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                       "command": cmd, "old": before, "requested": value,
                       "temperatures": {key: before_states.get(key) for key in (
                           "core:ComfortRoomTemperatureState", "core:TargetTemperatureState",
                           "io:SetpointLoweringTemperatureInProgModeState",
                           "core:EcoRoomTemperatureState", "core:DerogatedTargetTemperatureState")},
                       "weekly_program": before_raw}, f, indent=2, ensure_ascii=False)
        result = {"room": room, "field": field, "state": "unverified",
                  "old": before, "requested": value, "observed": before,
                  "backup_name": destination.name,
                  "schedule_unchanged": None, "execution_state": "unknown", "failure_type": "unknown"}
        eid = await client.execute_action_group(
            actions=[Action(device_url=heater.device_url, commands=[Command(name=cmd, parameters=[float(value)])])],
            label="CozytouchPanel confirmed single-room temperature change")
        for delay in (3, 5, 8):
            await asyncio.sleep(delay)
            try:
                hist = await client.get_execution_history()
                match = next((x for x in hist if x.id == eid), None)
                if match:
                    result["execution_state"] = str(getattr(match.state, "value", match.state))
                    result["failure_type"] = str(match.failure_type)
            except Exception:
                pass
            try:
                states = {str(s.name): s.value for s in await client.get_state(heater.device_url)}
                result["observed"] = numeric(states, state)
                result["schedule_unchanged"] = states.get("core:TimeProgramState") == before_raw
                if field == "comfort":
                    # Both base target and Comfort must agree before reporting success.
                    target_ok = numeric(states, "core:TargetTemperatureState") == value
                    comfort_ok = numeric(states, "core:ComfortRoomTemperatureState") == value
                    verified = target_ok and comfort_ok
                else:
                    verified = result["observed"] == value
                # Explicitly never mark success on a failed recorded execution.
                if verified and result["schedule_unchanged"] and result["execution_state"] == "COMPLETED" and result["failure_type"] == "NO_FAILURE":
                    result["state"] = "verified"
                    break
            except Exception:
                pass
            if result["execution_state"] == "FAILED":
                break
        return result
