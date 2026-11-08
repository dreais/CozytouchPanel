"""Inspect recent Cozytouch execution history without issuing any heater commands.

Shows only known room names, recognized command names, execution states and failure types.
Never displays raw device URLs, IDs, account data, command parameters, or descriptions.
"""
import asyncio
from datetime import datetime, timezone

from pyoverkiz.auth.credentials import UsernamePasswordCredentials
from pyoverkiz.client import OverkizClient

from config import get_credentials
from dashboard import VENDORS, load_mapping
import hashlib

KNOWN_COMMANDS = {
    "setEcoTemperature", "setSetpointLoweringTemperatureInProgMode",
    "setComfortTemperature", "setDerogatedTargetTemperature",
    "setHeatingLevel", "setOperatingMode", "setTimeProgram",
    "setTargetTemperature", "cancelHeatingLevel",
}

def safe_value(value):
    if value is None:
        return "unknown"
    return str(getattr(value, "value", value))[:60]

def room_name(device_url, mapping):
    # Same hashed prefix mapping as dashboard.private_id, without displaying the URL.
    base = str(device_url).split("#", 1)[0]
    room_id = hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]
    return mapping.get(room_id, "unknown device")

async def main():
    choice, username, password = get_credentials()
    mapping = load_mapping() or {}
    async with OverkizClient(server=VENDORS[choice][1],
        credentials=UsernamePasswordCredentials(username, password)) as client:
        await client.login(register_event_listener=False)
        history = await client.get_execution_history()
        print("READ-ONLY execution history. No commands sent. No identifiers or parameters printed.")
        for position, entry in enumerate(history[:15], 1):
            print(f"{position}: state={safe_value(entry.state)}, failure={safe_value(entry.failure_type)}")
            commands = getattr(entry, "commands", None) or []
            if not commands:
                print("   Commands not supplied in history response.")
                continue
            for cmd in commands:
                command = cmd.command if cmd.command in KNOWN_COMMANDS else "other command"
                room = room_name(cmd.device_url, mapping)
                print(f"   {room}: {command}; state={safe_value(cmd.state)}; failure={safe_value(cmd.failure_type)}")
        print("Read-only. Review the command-specific failures above before further writes.")

if __name__ == "__main__":
    asyncio.run(main())
