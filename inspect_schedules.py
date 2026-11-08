"""Read-only snapshot of four radiator weekly schedules.

Uses GET devices and GET states only: does NOT call refreshTimeProgram,
setTimeProgram or any heater-changing command.

Raw responses are saved only in .private/ (Git ignored). The console shows a
privacy-filtered structural preview; review it before sharing.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pyoverkiz.auth.credentials import UsernamePasswordCredentials
from pyoverkiz.client import OverkizClient

from config import get_credentials
from dashboard import HEATER_TYPE, VENDORS, load_mapping, private_id

OUT_DIR = Path(__file__).resolve().parent / ".private"
STATE_NAMES = (
    "core:TimeProgramState",
    "io:AutoProgramState",
    "io:InternalExternalSchedulingTypeState",
    "core:OperatingModeState",
)
BLOCKED_KEYS = ("url", "id", "token", "password", "secret", "email", "owner", "address", "key", "serial", "mac", "uuid")
SAFE_STRING = re.compile(r"^(?:[0-2]?\\d:[0-5]\\d(?::[0-5]\\d)?|[a-zA-Z _./:+-]{1,40})$")


def jsonable(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump(mode="json"))
    if hasattr(value, "value"):
        return jsonable(value.value)
    return str(value)


def safe_preview(value, depth=0):
    """Redact identifier-like fields, strings and overly deep data."""
    if depth > 8:
        return "[depth limit]"
    if isinstance(value, dict):
        result = {}
        for key, val in list(value.items())[:80]:
            key = str(key)
            if any(blocked in key.lower() for blocked in BLOCKED_KEYS):
                result[key] = "[redacted]"
            else:
                result[key] = safe_preview(val, depth + 1)
        return result
    if isinstance(value, list):
        return [safe_preview(v, depth + 1) for v in value[:100]]
    if isinstance(value, str):
        if "://" in value or "@" in value or len(value) > 40 or not SAFE_STRING.fullmatch(value):
            return "[string redacted]"
        return value
    if isinstance(value, (float, int, bool)) or value is None:
        return value
    return "[other value]"


async def main():
    choice, username, password = get_credentials()
    mapping = load_mapping()
    if not mapping or sorted(mapping.values()) != sorted(("Living room", "Bedroom", "Hall", "Kitchen")):
        raise SystemExit("Verified rooms.json mapping required; no positional guesses.")
    async with OverkizClient(
        server=VENDORS[choice][1],
        credentials=UsernamePasswordCredentials(username, password),
    ) as client:
        await client.login(register_event_listener=False)
        devices = await client.get_devices()
        heaters = [d for d in devices if getattr(d, "controllable_name", "") == HEATER_TYPE]
        if len(heaters) != 4 or {private_id(d) for d in heaters} != set(mapping):
            raise SystemExit("Device mapping/inventory mismatch. No data saved.")
        report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(),
                  "note": "Read-only cloud GET snapshot; NOT a proven restorable schedule.",
                  "rooms": {}}
        for heater in heaters:
            room = mapping[private_id(heater)]
            states = {str(s.name): jsonable(s.value) for s in await client.get_state(heater.device_url)}
            selection = {k: states.get(k, "[not present]") for k in STATE_NAMES}
            report["rooms"][room] = selection
            print(f"\\n--- {room} ---")
            for key, value in selection.items():
                print(f"{key}:")
                preview = json.dumps(safe_preview(value), ensure_ascii=False, indent=2)
                print(preview[:12000] + ("\\n[preview truncated]" if len(preview) > 12000 else ""))
        OUT_DIR.mkdir(exist_ok=True)
        destination = OUT_DIR / "schedules_latest.json"
        destination.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print("\\nSaved raw READ-ONLY schedule snapshot locally to .private/schedules_latest.json")
        print("This directory is Git-ignored. Do NOT share the raw file or commit it.")
        print("If core:TimeProgramState is absent, do not infer an empty schedule.")
        print("No device refresh, schedule write, or heating command was sent.")


if __name__ == "__main__":
    asyncio.run(main())
