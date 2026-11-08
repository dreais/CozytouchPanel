"""Offline inspection and preview of saved Cozytouch weekly schedules.

Reads only .private/schedules_latest.json produced by inspect_schedules.py.
Does not authenticate, call the cloud API, or modify radiator settings.
Never prints identifiers or the full raw schedule snapshot.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKUP = ROOT / ".private" / "schedules_latest.json"
ROOMS = ("Living room", "Bedroom", "Hall", "Kitchen")
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

def minutes(value: str) -> int:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        raise ValueError("Expected HH:MM")
    hh, mm = value[:2], value[3:]
    if not (hh.isdigit() and mm.isdigit()):
        raise ValueError("Expected numeric HH:MM")
    h, m = int(hh), int(mm)
    if not (0 <= h <= 24 and 0 <= m < 60) or (h == 24 and m != 0):
        raise ValueError("Time must be between 00:00 and 24:00")
    return h * 60 + m

def index_days(program):
    if not isinstance(program, list):
        raise ValueError("TimeProgramState is not a list")
    by_day = {}
    for element in program:
        if not isinstance(element, dict) or len(element) != 1:
            raise ValueError("Unexpected day entry structure")
        day, slots = next(iter(element.items()))
        if day not in DAYS or day in by_day or not isinstance(slots, list):
            raise ValueError("Unexpected or duplicate day")
        if len(slots) != 3:
            raise ValueError(f"Expected three time slots for {day}, got {len(slots)}")
        validated = []
        for slot in slots:
            if not isinstance(slot, dict) or set(slot) != {"start", "end"}:
                raise ValueError(f"Unexpected slot structure for {day}")
            start, end = slot["start"], slot["end"]
            begin, finish = minutes(start), minutes(end)
            if begin > finish:
                raise ValueError(f"Unexpected overnight interval for {day}")
            if begin == finish and begin != 0:
                raise ValueError(f"Unexpected zero-length interval for {day}")
            validated.append((start, end))
        by_day[day] = validated
    if set(by_day) != set(DAYS):
        raise ValueError(f"Expected seven days, found {sorted(by_day)}")
    return by_day

def main():
    parser = argparse.ArgumentParser(description="Offline schedule summary and hypothetical change")
    parser.add_argument("--start", default="09:00")
    parser.add_argument("--end", default="24:00")
    args = parser.parse_args()
    start, end = minutes(args.start), minutes(args.end)
    if not 0 <= start < end <= 1440:
        raise SystemExit("A Comfort period must have an end later than its start")
    if not BACKUP.is_file():
        raise SystemExit("No private backup found. Run py inspect_schedules.py first.")
    report = json.loads(BACKUP.read_text(encoding="utf-8"))
    rooms = report.get("rooms")
    if not isinstance(rooms, dict) or set(rooms) != set(ROOMS):
        raise SystemExit("Missing rooms or unexpected backup structure")
    print("OFFLINE preview only — no Cozytouch API calls, no writes, no file modifications.\n")
    for room in ROOMS:
        program = rooms[room].get("core:TimeProgramState")
        if program is None:
            print(f"{room}: no TimeProgramState data — cannot preview")
            continue
        try:
            by_day = index_days(program)
        except ValueError as exc:
            print(f"{room}: unexpected format ({exc}); no preview")
            continue
        print(f"--- {room} ---")
        for day in DAYS:
            active = [f"{s}–{e}" for s,e in by_day[day] if (s,e) != ("00:00","00:00")]
            if not active:
                active = ["no Comfort periods"]
            existing = ", ".join(active)
            print(f"  {day:9} current: {existing}")
        if all(by_day[day][1:] == [("00:00","00:00"),("00:00","00:00")] for day in DAYS):
            print(f"  Proposed per day: {args.start}–{args.end} (first slot only; two empty slots preserved)")
        else:
            print("  Proposed change not generated: additional slots contain programmed periods")
        print()
    print("No schedule payload sent. This preview does not prove the gateway will accept a write.")

if __name__ == "__main__":
    main()
