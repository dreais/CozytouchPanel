"""Read-only Comfort/Eco and temperature-sensor diagnostics.

Prints four verified room names and safe thermostat values only. Never prints
credentials, device identifiers, action parameters or raw device definitions.
Does not send heater commands.
"""
from __future__ import annotations
import asyncio
from pyoverkiz.auth.credentials import UsernamePasswordCredentials
from pyoverkiz.client import OverkizClient
from config import get_credentials
from dashboard import VENDORS, HEATER_TYPE, TEMP_TYPE, ROOM_NAMES, base_address, load_mapping, private_id, state_map

FIELDS = (
    "core:ComfortRoomTemperatureState",
    "core:EcoRoomTemperatureState",
    "io:SetpointLoweringTemperatureInProgModeState",
    "core:TargetTemperatureState",
    "io:EffectiveTemperatureSetpointState",
    "core:DerogatedTargetTemperatureState",
    "io:TargetHeatingLevelState",
    "core:OperatingModeState",
    "io:InternalExternalSchedulingTypeState",
    "core:OpenWindowDetectionActivationState",
)
# Known commands: only disclose whether advertised, never execute.
COMMANDS = (
    "setComfortTemperature",
    "setTargetTemperature",
    "setEcoTemperature",
    "setSetpointLoweringTemperatureInProgMode",
    "setDerogatedTargetTemperature",
    "setTimeProgram",
)

def display(v):
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (float, int)):
        return str(v)
    if isinstance(v, str) and v.lower() in ("comfort", "eco", "internal", "external", "off", "on", "true", "false", "unknown", "prog", "auto", "manual"):
        return v
    if v is None:
        return "not provided"
    return "[other value]"

async def main():
    mapping = load_mapping()
    if not mapping or sorted(mapping.values()) != sorted(ROOM_NAMES):
        raise SystemExit("Verified room mapping required; no positional guesses.")
    choice, username, password = get_credentials()
    async with OverkizClient(server=VENDORS[choice][1],
                            credentials=UsernamePasswordCredentials(username, password)) as client:
        await client.login(register_event_listener=False)
        devices = await client.get_devices()
        heaters = [d for d in devices if getattr(d, "controllable_name", "") == HEATER_TYPE]
        if len(heaters) != 4 or {private_id(d) for d in heaters} != set(mapping):
            raise SystemExit("Inventory mismatch; no diagnostics printed.")
        sensors = {base_address(d): state_map(d).get("core:TemperatureState")
                   for d in devices if getattr(d, "controllable_name", "") == TEMP_TYPE}
        for heater in sorted(heaters, key=lambda d: ROOM_NAMES.index(mapping[private_id(d)])):
            room = mapping[private_id(heater)]
            readings = {str(s.name): s.value for s in await client.get_state(heater.device_url)}
            print(f"\n--- {room} ---")
            print("Separate measured-temperature sensor:", display(sensors.get(base_address(heater))))
            for name in FIELDS:
                print(f"{name}: {display(readings.get(name))}")
            for command in COMMANDS:
                try:
                    advertised = heater.supports_command(command)
                except Exception:
                    advertised = False
                print(f"advertises {command}: {advertised}")
    print("\nREAD-ONLY. No temperature, Eco, mode, or schedule commands sent.")
    print("Measured temperature at/near radiator is not necessarily room-center temperature.")

if __name__ == "__main__":
    asyncio.run(main())
