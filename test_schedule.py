"""Single-day, single-radiator weekly schedule experiment.

Dry run by default. With --apply, changes only Hall's Monday first Comfort
period from 05:00–23:00 to 09:00–24:00 in a full seven-day program payload.
Requires an explicit typed confirmation and verifies readback.

Never changes temperatures, Eco reductions, operating modes or pairing.
Keep the original .private backup: use --restore to resend the separately
saved immediate pre-write program, but only after inspecting current state.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from pyoverkiz.auth.credentials import UsernamePasswordCredentials
from pyoverkiz.client import OverkizClient
from pyoverkiz.models import Action, Command

from config import get_credentials
from dashboard import HEATER_TYPE, VENDORS, private_id, load_mapping
from preview_schedule import index_days

PRIVATE = Path(__file__).resolve().parent / ".private"
SAVED = PRIVATE / "hall_prewrite_schedule.json"
STATE = "core:TimeProgramState"
ROOM = "Hall"
DAY = "monday"
NEW_START = "09:00"
NEW_END = "24:00"


def extract(states):
    result = {str(x.name): x.value for x in states}
    program = result.get(STATE)
    if not isinstance(program, list):
        raise ValueError("Schedule is absent or not a list")
    index_days(program)  # Validate full 7-day, 3-slot structure.
    return program


def modify(program):
    changed = copy.deepcopy(program)
    matches = [element[DAY] for element in changed if isinstance(element, dict) and DAY in element]
    if len(matches) != 1 or len(matches[0]) != 3:
        raise ValueError("Monday schedule structure unexpected")
    if matches[0][1:] != [{"start": "00:00", "end": "00:00"}] * 2:
        raise ValueError("Other Monday Comfort slots occupied")
    matches[0][0] = {"start": NEW_START, "end": NEW_END}
    index_days(changed)
    return changed


async def run(args):
    mapping = load_mapping()
    if not mapping or ROOM not in mapping.values():
        raise SystemExit("rooms.json mapping missing.")
    choice, username, password = get_credentials()
    async with OverkizClient(
        server=VENDORS[choice][1],
        credentials=UsernamePasswordCredentials(username, password),
    ) as client:
        await client.login(register_event_listener=False)
        devices = await client.get_devices()
        heaters = [d for d in devices if getattr(d, "controllable_name", "") == HEATER_TYPE]
        if len(heaters) != 4 or {private_id(h) for h in heaters} != set(mapping):
            raise SystemExit("Heater inventory differs from saved mapping. No write.")
        matching = [h for h in heaters if mapping[private_id(h)] == ROOM]
        if len(matching) != 1:
            raise SystemExit("Hall mapping ambiguous. No write.")
        heater = matching[0]
        if not heater.supports_command("setTimeProgram"):
            raise SystemExit("This heater does not advertise setTimeProgram.")
        original = extract(await client.get_state(heater.device_url))
        if args.restore:
            if not SAVED.exists():
                raise SystemExit("No immediate pre-write backup exists.")
            saved = json.loads(SAVED.read_text(encoding="utf-8"))
            proposed = saved["program"]
            index_days(proposed)
            if original == proposed:
                print("Already matches the saved original. No write.")
                return
            label = "RESTORE Hall"
            print("Restore is a separate write. Compare Monday and other days before confirming.")
        else:
            proposed = modify(original)
            if original == proposed:
                print("Already configured as proposed. Nothing to do.")
                return
            label = "APPLY Hall Monday"
        before = index_days(original)
        after = index_days(proposed)
        print("Hall Monday:")
        print("  Current: ", before[DAY])
        print("  Proposed:", after[DAY])
        other_differences = [day for day in before if day != DAY and before[day] != after[day]]
        if other_differences and not args.restore:
            raise SystemExit("Unexpected changes on other days. No write.")
        if not args.apply:
            print("DRY RUN: no schedule commands issued.")
            return
        if not args.restore:
            PRIVATE.mkdir(exist_ok=True)
            if SAVED.exists():
                raise SystemExit("Existing pre-write backup present: refusing to overwrite. Move it aside after reviewing.")
            # Save original before sending any command.
            SAVED.write_text(json.dumps({"recorded_at": datetime.now(timezone.utc).isoformat(),
                                         "room": ROOM, "program": original}, indent=2), encoding="utf-8")
            print("Immediate original saved to .private/hall_prewrite_schedule.json (Git-ignored).")
        reply = input(f"Type {label} to send a SINGLE schedule command: ")
        if reply != label:
            print("Cancelled. No command sent.")
            return
        # Avoid a TOCTOU race with a changed schedule.
        latest = extract(await client.get_state(heater.device_url))
        if latest != original:
            print("Schedule changed after preview; refusing to write.")
            return
        execution_id = await client.execute_action_group(
            actions=[Action(device_url=heater.device_url,
                            commands=[Command(name="setTimeProgram", parameters=[proposed])])],
            label="CozytouchPanel one-room one-day schedule test",
        )
        print("Submitted one setTimeProgram command. Checking cloud execution history and state...")
        for seconds in (3, 5, 8):
            await asyncio.sleep(seconds)
            try:
                history = await client.get_execution_history()
                matching_exec = next((e for e in history if e.id == execution_id), None)
                if matching_exec:
                    print("Execution:", matching_exec.state, "failure:", matching_exec.failure_type)
            except Exception:
                print("Execution history unavailable.")
            try:
                observed = extract(await client.get_state(heater.device_url))
            except Exception as exc:
                print("Readback error:", type(exc).__name__)
                continue
            if observed == proposed:
                print("FULL READBACK MATCH: all seven days match proposed schedule.")
                print("Confirm Hall's Monday schedule in Cozytouch/on the radiator.")
                return
            print("Readback does not yet match the full proposed program.")
        print("UNVERIFIED: inspect Cozytouch before retrying or restoring. Do not send repeatedly.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Enable actual write with typed confirmation")
    parser.add_argument("--restore", action="store_true", help="Use saved original from immediate pre-write backup")
    asyncio.run(run(parser.parse_args()))
