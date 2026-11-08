"""Opt-in, one-command Cozytouch ECO test. Dry-run unless --apply is specified.

Does not change schedules, modes, pairing, calibration, or overrides.
Run only when the dashboard is stopped so there are no concurrent API writes.
"""
import argparse
import asyncio
from pyoverkiz.auth.credentials import UsernamePasswordCredentials
from pyoverkiz.client import OverkizClient
from pyoverkiz.models import Action, Command
from config import get_credentials
from dashboard import VENDORS, HEATER_TYPE, private_id, load_mapping

ECO_STATE = "core:EcoRoomTemperatureState"
OFFSET_STATE = "io:SetpointLoweringTemperatureInProgModeState"
COMFORT_STATE = "core:ComfortRoomTemperatureState"
ROOMS = ("Living room", "Bedroom", "Hall", "Kitchen")

def state_dict(states):
    return {str(x.name): x.value for x in states}

async def main(args):
    if args.room not in ROOMS:
        raise SystemExit("Unknown room")
    if args.offset < 0 or args.offset > 8 or args.offset * 2 != round(args.offset * 2):
        raise SystemExit("Offset must be 0..8 in increments of 0.5°C")
    mapping = load_mapping()
    if not mapping or args.room not in mapping.values():
        raise SystemExit("Missing saved room mapping. Stop here; don't guess device ordering.")
    choice, username, password = get_credentials()
    async with OverkizClient(server=VENDORS[choice][1],
                             credentials=UsernamePasswordCredentials(username, password)) as client:
        await client.login(register_event_listener=False)
        devices = await client.get_devices()
        heaters = [d for d in devices if getattr(d, "controllable_name", "") == HEATER_TYPE]
        if len(heaters) != 4 or {private_id(d) for d in heaters} != set(mapping):
            raise SystemExit("Device inventory does not match rooms.json")
        matches = [d for d in heaters if mapping[private_id(d)] == args.room]
        if len(matches) != 1:
            raise SystemExit("Room mapping is ambiguous")
        heater = matches[0]
        states = state_dict(await client.get_state(heater.device_url))
        current = states.get(ECO_STATE)
        other = states.get(OFFSET_STATE)
        comfort = states.get(COMFORT_STATE)
        if not isinstance(current, (float, int)) or not isinstance(comfort, (float, int)):
            raise SystemExit("Current Eco offset or Comfort value unavailable")
        if abs(current - other) > .01:
            print("NOTE: Eco state and programmed reduction differ; test targets only core:EcoRoomTemperatureState.")
        if comfort - args.offset < 15:
            raise SystemExit("Nominal Eco target below safety test floor (15°C)")
        if abs(current - args.offset) < .01:
            print("Already at requested value; nothing sent.")
            return
        command = "setEcoTemperature"
        if not heater.supports_command(command):
            raise SystemExit("setEcoTemperature not advertised by this radiator")
        print(f"{args.room}: Comfort={comfort}°C, current Eco offset={current}°C")
        print(f"Proposed Eco offset={args.offset}°C (nominal target={comfort-args.offset}°C)")
        print(f"Command: {command}; single radiator; no schedule or override commands")
        if not args.apply:
            print("DRY RUN ONLY. To send this command, rerun with --apply.")
            return
        response = input(f"Type SEND {args.room} to execute one command: ").strip()
        if response != f"SEND {args.room}":
            print("Cancelled. No command sent.")
            return
        # Re-read before sending, to prevent using an obsolete preview.
        latest = state_dict(await client.get_state(heater.device_url))
        if latest.get(ECO_STATE) != current or latest.get(COMFORT_STATE) != comfort:
            raise SystemExit("Settings changed since preview; no command sent")
        execution_id = await client.execute_action_group(
            actions=[Action(device_url=heater.device_url,
                            commands=[Command(name=command, parameters=[args.offset])])],
            label="CozytouchPanel controlled Eco experiment",
        )
        # Do not print execution ID; it can be used to correlate account activity.
        print("API accepted request for execution; does not guarantee radiator acceptance.")
        for delay in (3, 5, 8):
            await asyncio.sleep(delay)
            latest = state_dict(await client.get_state(heater.device_url))
            observed = latest.get(ECO_STATE)
            observed_offset = latest.get(OFFSET_STATE)
            print(f"Readback after additional {delay}s: Eco offset={observed}, programmed reduction={observed_offset}")
            if (isinstance(observed, (int, float)) and
                isinstance(observed_offset, (int, float)) and
                abs(observed - args.offset) < 0.01 and
                abs(observed_offset - args.offset) < 0.01):
                print("VERIFIED: both Eco state fields match requested offset.")
                print(f"To restore previous value, run with --room \"{args.room}\" --offset {current} --apply.")
                return
        print("NOT VERIFIED. Do not repeat blindly; inspect physical radiator and Cozytouch first.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="One-command Eco test; dry-run by default.")
    parser.add_argument("--room", choices=ROOMS, default="Hall")
    parser.add_argument("--offset", type=float, default=4.0)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args()))
