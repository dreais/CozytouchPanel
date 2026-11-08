"""Safe cloud-backed weekly scheduler for CozytouchPanel.

All writes are opt-in and serialized by the dashboard lock. One radiator per
transaction, full seven-day schedule, no temperature/mode changes.
"""
from __future__ import annotations

import asyncio
import copy
import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from pyoverkiz.auth.credentials import UsernamePasswordCredentials
from pyoverkiz.client import OverkizClient
from pyoverkiz.models import Action, Command

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
STATE = "core:TimeProgramState"
EMPTY = {"start": "00:00", "end": "00:00"}
BACKUPS = Path(__file__).resolve().parent / ".private" / "schedule_backups"
PREVIEWS = {}
TTL_SECONDS = 300


def mins(s):
    if not isinstance(s, str) or len(s) != 5 or s[2] != ":" or not s[:2].isdigit() or not s[3:].isdigit():
        raise ValueError("Times must use HH:MM, including 24:00 for midnight")
    h, m = int(s[:2]), int(s[3:])
    if h > 24 or m > 59 or (h == 24 and m != 0):
        raise ValueError("Invalid time")
    return h * 60 + m


def validate_days(data):
    """Require all seven days, up to 3 non-overlapping ordered periods per day."""
    if not isinstance(data, dict) or set(data) != set(DAYS):
        raise ValueError("Exactly seven days are required")
    normalized = {}
    for day in DAYS:
        slots = data[day]
        if not isinstance(slots, list) or len(slots) > 3:
            raise ValueError(f"{day}: at most three Comfort periods")
        occupied = []
        for slot in slots:
            if not isinstance(slot, dict) or set(slot) != {"start", "end"}:
                raise ValueError(f"{day}: malformed period")
            start, end = slot["start"], slot["end"]
            a, b = mins(start), mins(end)
            if a == b == 0:
                continue
            if not 0 <= a < b <= 1440:
                raise ValueError(f"{day}: end must be after start, within the same day")
            occupied.append((a, b, start, end))
        if len(occupied) > 3:
            raise ValueError(f"{day}: too many Comfort periods")
        occupied.sort()
        for i in range(1, len(occupied)):
            if occupied[i][0] < occupied[i - 1][1]:
                raise ValueError(f"{day}: Comfort periods overlap")
        normalized[day] = [{"start": a[2], "end": a[3]} for a in occupied]
        normalized[day] += [copy.deepcopy(EMPTY) for _ in range(3 - len(occupied))]
    return normalized


def extract_program(states):
    items = {str(s.name): s.value for s in states}
    raw = items.get(STATE)
    if not isinstance(raw, list) or len(raw) != 7:
        raise ValueError("Cloud weekly program missing or unexpected")
    per_day = {}
    for entry in raw:
        if not isinstance(entry, dict) or len(entry) != 1:
            raise ValueError("Unexpected schedule entry")
        day, slots = next(iter(entry.items()))
        if day not in DAYS or day in per_day or not isinstance(slots, list) or len(slots) != 3:
            raise ValueError("Unexpected day/period structure")
        per_day[day] = slots
    normalized = validate_days(per_day)
    # Fail closed if normalization would silently discard or rearrange a slot.
    if any(per_day[day] != normalized[day] for day in DAYS):
        raise ValueError("Cloud program uses an unsupported layout; refusing to write")
    return raw, normalized


def build_payload(original, requested):
    # Retain backend's exact day order and its list-of-single-key-dicts format.
    return [{next(iter(entry)): copy.deepcopy(requested[next(iter(entry))])} for entry in original]


def safe_diff(original, proposed):
    return {day: {"before": original[day], "after": proposed[day]}
            for day in DAYS if original[day] != proposed[day]}


async def get_heater(client, app, room):
    if room not in app.ROOM_NAMES:
        raise ValueError("Unknown room")
    mapping = app.load_mapping()
    if not mapping or sorted(mapping.values()) != sorted(app.ROOM_NAMES):
        raise ValueError("Room mapping missing or invalid")
    devices = await client.get_devices()
    heaters = [d for d in devices if getattr(d, "controllable_name", None) == app.HEATER_TYPE]
    if len(heaters) != len(app.ROOM_NAMES) or {app.private_id(d) for d in heaters} != set(mapping):
        raise ValueError("Device inventory changed; no writes allowed")
    matched = [h for h in heaters if mapping[app.private_id(h)] == room]
    if len(matched) != 1:
        raise ValueError("Room identity ambiguous")
    return matched[0]


def client_for(app):
    cfg = app.SESSION
    return OverkizClient(server=cfg["server"],
                         credentials=UsernamePasswordCredentials(cfg["username"], cfg["password"]))


async def load_week(app, room):
    async with client_for(app) as client:
        await client.login(register_event_listener=False)
        heater = await get_heater(client, app, room)
        _, week = extract_program(await client.get_state(heater.device_url))
        return {"room": room, "days": week}


async def preview_week(app, room, requested):
    candidate = validate_days(requested)
    async with client_for(app) as client:
        await client.login(register_event_listener=False)
        heater = await get_heater(client, app, room)
        if not heater.supports_command("setTimeProgram"):
            raise ValueError("Radiator does not advertise setTimeProgram")
        original_raw, existing = extract_program(await client.get_state(heater.device_url))
        changes = safe_diff(existing, candidate)
        if not changes:
            return {"room": room, "changes": {}, "no_change": True}
        # Single-use token with a 5-minute lifetime. Only held in process RAM.
        now = time.monotonic()
        for k in list(PREVIEWS):
            if PREVIEWS[k]["expires"] < now:
                del PREVIEWS[k]
        token = secrets.token_urlsafe(24)
        PREVIEWS[token] = {"room": room, "original": original_raw,
                           "candidate": build_payload(original_raw, candidate),
                           "expires": now + TTL_SECONDS}
        return {"room": room, "changes": changes, "preview_token": token,
                "expires_in_seconds": TTL_SECONDS, "no_change": False}


async def apply_week(app, room, token):
    # Caller holds dashboard WRITE_LOCK throughout this transaction.
    preview = PREVIEWS.pop(token, None)
    if preview is None or preview["room"] != room or time.monotonic() > preview["expires"]:
        raise ValueError("Preview expired or already used; review again")
    original, proposed = preview["original"], preview["candidate"]
    async with client_for(app) as client:
        await client.login(register_event_listener=False)
        heater = await get_heater(client, app, room)
        if not heater.supports_command("setTimeProgram"):
            raise ValueError("Radiator no longer advertises setTimeProgram")
        fresh, _ = extract_program(await client.get_state(heater.device_url))
        if fresh != original:
            raise ValueError("Radiator schedule changed since preview. No write sent.")
        # Unique immutable backup BEFORE sending. Backup stays local and git-ignored.
        BACKUPS.mkdir(parents=True, exist_ok=True)
        backup = BACKUPS / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                            + "_" + secrets.token_hex(4) + ".json")
        record = {"room": room, "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                  "note": "Original before schedule write; not guaranteed restorable",
                  "program": original}
        with backup.open("x", encoding="utf-8") as fp:
            json.dump(record, fp, ensure_ascii=False, indent=2)
        result = {"room": room, "backup_name": backup.name,
                  "execution_state": "unknown", "failure_type": "unknown",
                  "readback_match": False}
        exec_id = await client.execute_action_group(
            actions=[Action(device_url=heater.device_url,
                            commands=[Command(name="setTimeProgram", parameters=[proposed])])],
            label="CozytouchPanel confirmed single-room schedule edit")
        # Only compare the execution with the exact ID just submitted.
        for delay in (3, 5, 8):
            await asyncio.sleep(delay)
            try:
                history = await client.get_execution_history()
                entry = next((e for e in history if e.id == exec_id), None)
                if entry is not None:
                    result["execution_state"] = str(getattr(entry.state, "value", entry.state))
                    result["failure_type"] = str(entry.failure_type)
            except Exception:
                pass
            try:
                observed, _ = extract_program(await client.get_state(heater.device_url))
                if observed == proposed:
                    result["readback_match"] = True
                    break
            except Exception:
                pass
        return result
