"""Read-only, privacy-filtered inspection of recent Overkiz executions.

Never prints device URLs, account IDs, execution IDs, tokens or raw payloads.
No heater commands are issued.
"""
import asyncio
from datetime import datetime
from pyoverkiz.auth.credentials import UsernamePasswordCredentials
from pyoverkiz.client import OverkizClient
from config import get_credentials
from dashboard import VENDORS, HEATER_TYPE, load_mapping, private_id

ALLOWED_COMMANDS = {
    "setEcoTemperature", "setSetpointLoweringTemperatureInProgMode",
    "setComfortTemperature", "setDerogatedTargetTemperature",
    "setHeatingLevel", "setOperatingMode", "setTimeProgram",
}
SAFE_STATES = {"COMPLETED", "FAILED", "PENDING", "IN_PROGRESS", "CANCELLED"}
SAFE_FAILURES = {"OVERRIDEMODE_ERROR", "NO_FAILURE"}

def flatten_safe(entry):
    if hasattr(entry, "model_dump"):
        return entry.model_dump(mode="json")
    if hasattr(entry, "dict"):
        return entry.dict()
    return {}

def safe_string(value, allowed):
    name = getattr(value, "name", value)
    value_str = str(name).split(".")[-1]
    return value_str if value_str in allowed else "other/unknown"

def find_commands(value, depth=0):
    if depth > 6:
        return set()
    if isinstance(value, list):
        result = set()
        for item in value:
            result |= find_commands(item, depth + 1)
        return result
    if isinstance(value, dict):
        result = set()
        for key, item in value.items():
            if key in ("name", "commandName") and isinstance(item, str) and item in ALLOWED_COMMANDS:
                result.add(item)
            elif key not in ("parameters", "token", "credentials", "password"):
                result |= find_commands(item, depth + 1)
        return result
    return set()

async def main():
    choice, username, password = get_credentials()
    async with OverkizClient(server=VENDORS[choice][1],
        credentials=UsernamePasswordCredentials(username, password)) as client:
        await client.login(register_event_listener=False)
        history = await client.get_execution_history()
        print("READ-ONLY execution history. No commands issued; no identifiers exposed.")
        for position, entry in enumerate(history[:15], 1):
            raw = flatten_safe(entry)
            state = safe_string(raw.get("state", getattr(entry, "state", None)), SAFE_STATES)
            failure = safe_string(raw.get("failureType", raw.get("failure_type", getattr(entry, "failure_type", None))), SAFE_FAILURES)
            commands = sorted(find_commands(raw))
            print(f"{position}: state={state}, failure={failure}, named commands={','.join(commands) if commands else 'not exposed'}")
            # No timestamps printed: API history ordering might not be chronological.
    print("If command names are absent, we cannot safely link failures to a test from this output alone.")

if __name__ == "__main__":
    asyncio.run(main())
