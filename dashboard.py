"""Local Cozytouch dashboard. Manual, one-setting-at-a-time changes only.

No scheduling, bulk writes or automatic heater commands.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import math
from pathlib import Path
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
import scheduler_service
import temperature_service
import webbrowser

from config import get_credentials
from pyoverkiz.auth.credentials import UsernamePasswordCredentials
from pyoverkiz.client import OverkizClient
from pyoverkiz.enums import Server
from pyoverkiz.models import Action, Command

ROOM_NAMES = ["Living room", "Bedroom", "Hall", "Kitchen"]
HEATER_TYPE = "io:AtlanticElectricalHeaterWithAdjustableTemperatureSetpointIOComponent"
TEMP_TYPE = "io:TemperatureInCelciusIOSystemDeviceSensor"
ENERGY_TYPE = "io:CumulatedElectricalEnergyConsumptionIOSystemDeviceSensor"
CONTACT_TYPE = "io:ContactIOSystemDeviceSensor"
OCCUPANCY_TYPE = "io:OccupancyIOSystemDeviceSensor"
POLL_SECONDS = 60
HOST, PORT = "127.0.0.1", 8765
CONFIG_PATH = Path(__file__).with_name("rooms.json")
HTML_PATH = Path(__file__).with_name("index.html")
SCHEDULE_HTML_PATH = Path(__file__).with_name("schedule.html")
PROPOSALS = {"Living room": (21.0, 1.5), "Bedroom": (19.5, 1.0), "Hall": (19.0, 1.0), "Kitchen": (19.5, 1.0)}
TOKEN = secrets.token_urlsafe(32)
WRITE_LOCK = threading.Lock()
SESSION = {}
EVENTS = []
READING_FIELDS = {}  # Writes paused pending confirmed per-device execution and schedule semantics.
VENDORS = {"1": ("Atlantic", Server.ATLANTIC_COZYTOUCH),
           "2": ("Thermor", Server.THERMOR_COZYTOUCH),
           "3": ("Sauter", Server.SAUTER_COZYTOUCH)}

LOCK = threading.RLock()
STATUS = {"ok": False, "last_updated": None, "error": "Connecting to Cozytouch…", "rooms": [], "mapping_issue": None}


def state_map(device):
    """The pyoverkiz States object exposes mapping-like .values()."""
    collection = getattr(device, "states", None)
    if not collection:
        return {}
    values = collection.values() if hasattr(collection, "values") else collection
    return {str(getattr(s, "name", "")): getattr(s, "value", None) for s in values}


def base_address(device):
    # Ignore the endpoint number, e.g. io://gateway/123#1 and io://gateway/123#2.
    # Never expose this raw identifier to the browser or console.
    return str(getattr(device, "device_url", "")).split("#", 1)[0]


def private_id(device):
    return hashlib.sha256(base_address(device).encode("utf-8")).hexdigest()[:24]


def load_mapping():
    if not CONFIG_PATH.exists():
        return None
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("rooms.json has an unsupported format")
    return data.get("rooms", {})


def write_mapping(mapping):
    # Contains only hashed device IDs and room names. Never account details or raw device URLs.
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({"version": 1, "rooms": mapping}, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def build_rooms(devices, mapping):
    heaters = [d for d in devices if getattr(d, "controllable_name", "") == HEATER_TYPE]
    sensors = {}
    for dev in devices:
        kind = getattr(dev, "controllable_name", "")
        if kind in (TEMP_TYPE, ENERGY_TYPE, CONTACT_TYPE, OCCUPANCY_TYPE):
            sensors.setdefault(base_address(dev), {})[kind] = state_map(dev)

    # The discovery output established four heaters, in the specified initial order.
    # Only do the positional assignment once; subsequent runs exclusively use stable IDs.
    if mapping is None:
        if len(heaters) != len(ROOM_NAMES):
            raise ValueError(f"First-run mapping requires exactly 4 radiators; found {len(heaters)}. No mapping was written.")
        ids = [private_id(dev) for dev in heaters]
        if len(set(ids)) != len(ids):
            raise ValueError("Cannot uniquely identify radiators; mapping not saved.")
        mapping = dict(zip(ids, ROOM_NAMES))
        write_mapping(mapping)
        print("Created rooms.json: assigned the four radiators by FIRST-RUN API order.")
        print("Verify the room-to-device mapping by comparing the temperatures with Cozytouch.")

    found_ids = {private_id(dev) for dev in heaters}
    expected_ids = set(mapping.keys())
    if found_ids != expected_ids:
        raise ValueError("Device inventory changed. Room mapping was NOT reassigned. "
                         "Review rooms.json instead of assuming API order.")

    result = []
    for dev in heaters:
        s = state_map(dev)
        relatives = sensors.get(base_address(dev), {})
        temp = relatives.get(TEMP_TYPE, {})
        energy = relatives.get(ENERGY_TYPE, {})
        contact = relatives.get(CONTACT_TYPE, {})
        occupancy = relatives.get(OCCUPANCY_TYPE, {})
        result.append({
            "name": mapping[private_id(dev)],
            "id": private_id(dev),
            "temperature": temp.get("core:TemperatureState"),
            "comfort": s.get("core:ComfortRoomTemperatureState"),
            "eco_state": s.get("core:EcoRoomTemperatureState"),
            "derogated_target": s.get("core:DerogatedTargetTemperatureState"),
            "target_temperature": s.get("core:TargetTemperatureState"),
            "schedule_type": s.get("io:InternalExternalSchedulingTypeState"),
            "eco_reduction": s.get("io:SetpointLoweringTemperatureInProgModeState"),
            "effective_target": s.get("io:EffectiveTemperatureSetpointState"),
            "mode": s.get("io:TargetHeatingLevelState"),
            "operating_mode": s.get("core:OperatingModeState"),
            "status": s.get("core:StatusState"),
            "power_w": s.get("io:PowerState"),
            "working_rate": s.get("io:CurrentWorkingRateState"),
            "energy_raw": energy.get("core:ElectricEnergyConsumptionState"),
            "contact": contact.get("core:ContactState"),
            "occupancy": occupancy.get("core:OccupancyState"),
            "window_detection": s.get("core:OpenWindowDetectionActivationState"),
        })
    return sorted(result, key=lambda x: ROOM_NAMES.index(x["name"]))


async def fetch(server, username, password, mapping):
    async with OverkizClient(
        server=server,
        credentials=UsernamePasswordCredentials(username, password),
    ) as client:
        await client.login()
        devices = await client.get_devices()
        return build_rooms(devices, mapping)


def polling_loop(server, username, password):
    while True:
        try:
            # Scheduled reads have lower priority than user-initiated writes.
            # Skip this poll if a write/preview is underway; never queue a poll
            # behind it and steal the lock before the next user interaction.
            if not WRITE_LOCK.acquire(blocking=False):
                time.sleep(POLL_SECONDS)
                continue
            try:
                mapping = load_mapping()
                rooms = asyncio.run(fetch(server, username, password, mapping))
                with LOCK:
                    STATUS.update({"ok": True, "last_updated": datetime.now(timezone.utc).isoformat(),
                                   "error": None, "rooms": rooms, "mapping_issue": None})
            finally:
                WRITE_LOCK.release()
        except Exception as exc:
            # Do not print cloud errors, which may contain identifying URLs/account data.
            with LOCK:
                STATUS.update({"ok": False, "error": f"Refresh failed ({type(exc).__name__}). "
                              "Check credentials, connectivity and rooms.json. Existing readings may be stale."})
            print(f"Refresh failed: {type(exc).__name__} (no sensitive details printed)")
        time.sleep(POLL_SECONDS)


def room_for_id(room_id):
    mapping = load_mapping() or {}
    if room_id not in mapping or mapping[room_id] not in PROPOSALS:
        raise ValueError("Unknown radiator or missing verified room mapping")
    return mapping[room_id]


def make_plan(room_id, field, value):
    room = room_for_id(room_id)
    if field not in READING_FIELDS or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Invalid setting/value")
    if round(float(value)*2) != float(value)*2:
        raise ValueError("Temperature settings must be in 0.5-degree increments")
    if field == "comfort" and not (15 <= value <= 24):
        raise ValueError("Comfort must be between 15 and 24 °C")
    if field == "reduction" and not (0 <= value <= 8):
        raise ValueError("Eco reduction must be between 0 and 8 °C")
    return room, float(value)


async def perform_change(server, username, password, room_id, field, value, expected):
    # Never trust device URLs supplied from the browser.
    async with OverkizClient(server=server, credentials=UsernamePasswordCredentials(username, password)) as client:
        await client.login()
        devices = await client.get_devices()
        mapping = load_mapping()
        build_rooms(devices, mapping)  # Fail closed on inventory/mapping mismatch.
        matches = [d for d in devices if getattr(d, "controllable_name", "") == HEATER_TYPE and private_id(d) == room_id]
        if len(matches) != 1:
            raise ValueError("Radiator identity not unique or radiator unavailable")
        heater = matches[0]
        state_name, command_name = READING_FIELDS[field]
        if not heater.supports_command(command_name):
            raise ValueError("This radiator does not advertise the requested command")
        fresh = await client.get_state(heater.device_url)
        fresh_map = {str(s.name): s.value for s in fresh}
        old = fresh_map.get(state_name)
        if not isinstance(old, (int,float)) or abs(old - expected) > 0.01:
            raise ValueError("Cloud value changed since preview; refresh and try again")
        if field == "reduction":
            comfort = fresh_map.get("core:ComfortRoomTemperatureState")
            if not isinstance(comfort, (int,float)) or comfort - value < 15:
                raise ValueError("Eco target would fall below 15°C")
        if field == "comfort":
            reduction = fresh_map.get("io:SetpointLoweringTemperatureInProgModeState")
            if not isinstance(reduction, (int,float)) or value - reduction < 15:
                raise ValueError("Current Eco reduction would put target below 15°C. Set reduction first.")
        if abs(old-value) < 0.01:
            return {"state":"already", "old":old,"requested":value,"observed":old}
        exec_id = await client.execute_action_group(actions=[Action(device_url=heater.device_url, commands=[Command(name=command_name, parameters=[value])])],label="Cozytouch manual one-setting change")
        # Cloud may be eventually consistent. Report confirmation ONLY after fresh read.
        observed = None
        for delay in (2, 4, 7, 10):
            await asyncio.sleep(delay)
            new_state = await client.get_state(heater.device_url)
            updated = {str(s.name): s.value for s in new_state}
            observed = updated.get(state_name)
            if isinstance(observed, (int,float)) and abs(observed - value) < 0.01:
                return {"state":"verified", "old":old,"requested":value,"observed":observed}
        return {"state":"unverified", "old":old,"requested":value,"observed":observed}


def command_write(data):
    # A periodic cloud poll may already hold the lock. Give it time to finish
    # rather than rejecting an explicitly confirmed user operation immediately.
    if not WRITE_LOCK.acquire(timeout=30):
        raise ValueError("Cloud refresh still in progress after 30 seconds; nothing was sent")
    try:
        with LOCK:
            ok, last = STATUS["ok"], STATUS["last_updated"]
        if not ok or not last or (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() > 180:
            raise ValueError("Cloud readings are stale; wait for refresh")
        room_id, field = data.get("id"), data.get("field")
        room = room_for_id(room_id)
        if field not in ("comfort", "reduction"):
            raise ValueError("Unsupported temperature field")
        if data.get("room") != room or data.get("confirmation") != f"APPLY {room}":
            raise ValueError("Room confirmation did not match")
        value, expected = data.get("value"), data.get("expected")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (value, expected)):
            raise ValueError("Invalid requested/expected temperature")
        result = asyncio.run(temperature_service.change(
            __import__("sys").modules["__main__"], room_id, field, float(value), float(expected)))
        EVENTS.append({"time": datetime.now(timezone.utc).isoformat(), "room": room,
                       "field": field, "state": result["state"]})
        del EVENTS[:-20]
        with LOCK:
            STATUS["ok"] = False
            STATUS["error"] = "Temperature command finished; waiting for fresh cloud data."
        return result
    finally:
        WRITE_LOCK.release()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/schedule":
            return self.reply(200, "text/html; charset=utf-8", SCHEDULE_HTML_PATH.read_bytes())
        if path == "/api/schedule":
            try:
                query = parse_qs(urlsplit(self.path).query)
                room_values = query.get("room", [])
                if len(room_values) != 1:
                    raise ValueError("Select exactly one room")
                if not WRITE_LOCK.acquire(blocking=False):
                    raise ValueError("Another operation is in progress")
                try:
                    data = asyncio.run(scheduler_service.load_week(__import__("sys").modules["__main__"], room_values[0]))
                    data["csrf"] = TOKEN
                finally:
                    WRITE_LOCK.release()
                return self.reply(200, "application/json", json.dumps(data).encode())
            except ValueError as exc:
                return self.reply(400, "application/json", json.dumps({"error": str(exc)}).encode())
            except Exception as exc:
                return self.reply(502, "application/json", json.dumps({"error": f"Schedule read failed ({type(exc).__name__}); inspect server connection."}).encode())
        if path == "/api/status":
            with LOCK:
                data = dict(STATUS)
            data["proposals"] = {n:{"comfort":v[0],"reduction":v[1]} for n,v in PROPOSALS.items()}
            data["events"] = EVENTS[-10:]
            data["csrf"] = TOKEN
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.reply(200, "application/json; charset=utf-8", payload)
        elif path in ("/", "/index.html"):
            self.reply(200, "text/html; charset=utf-8", HTML_PATH.read_bytes())
        else:
            self.reply(404, "text/plain", b"Not found")

    def do_POST(self):
        if urlsplit(self.path).path in ("/api/schedule/preview", "/api/schedule/apply"):
            if (self.headers.get("Origin") != f"http://{HOST}:{PORT}"
                or self.headers.get("X-Cozy-CSRF") != TOKEN
                or self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json"):
                return self.reply(403, "application/json", b'{"error":"Request not authorized"}')
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384:
                    raise ValueError("Invalid request length")
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("Malformed JSON request")
                room = data.get("room")
                if not isinstance(room, str) or room not in ROOM_NAMES:
                    raise ValueError("Unknown room")
                if not WRITE_LOCK.acquire(blocking=False):
                    raise ValueError("Another operation is in progress")
                try:
                    app = __import__("sys").modules["__main__"]
                    if urlsplit(self.path).path == "/api/schedule/preview":
                        result = asyncio.run(scheduler_service.preview_week(app, room, data.get("days")))
                    else:
                        if data.get("confirmation") != f"APPLY {room}":
                            raise ValueError("Confirmation does not match")
                        preview_token = data.get("preview_token")
                        if not isinstance(preview_token, str) or len(preview_token) > 128:
                            raise ValueError("Missing preview")
                        result = asyncio.run(scheduler_service.apply_week(app, room, preview_token))
                        # Force the dashboard to refresh, rather than presenting stale values.
                        with LOCK:
                            STATUS["ok"] = False
                            STATUS["error"] = "Schedule write submitted; waiting for a fresh device poll."
                finally:
                    WRITE_LOCK.release()
                return self.reply(200, "application/json", json.dumps(result).encode())
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                return self.reply(400, "application/json", json.dumps({"error": str(exc)}).encode())
            except Exception as exc:
                return self.reply(502, "application/json", json.dumps({"error": f"Schedule operation error ({type(exc).__name__}); outcome may be unknown. Inspect Cozytouch before retrying."}).encode())
        if urlsplit(self.path).path != "/api/apply":
            return self.reply(404, "text/plain", b"Not found")
        if self.headers.get("Origin") != f"http://{HOST}:{PORT}" or self.headers.get("X-Cozy-CSRF") != TOKEN or self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self.reply(403, "application/json", b'{"error":"Request not authorized"}')
        try:
            size=int(self.headers.get("Content-Length", "0"))
            if not 0 < size < 2048:
                raise ValueError("Invalid request length")
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):
                raise ValueError("Invalid request")
            result=command_write(data)
            self.reply(200,"application/json",json.dumps(result).encode())
        except (ValueError, KeyError, TypeError) as exc:
            self.reply(400,"application/json",json.dumps({"error":str(exc)}).encode())
        except Exception as exc:
            # Cloud errors can contain private identifiers. Do not send details to browser.
            self.reply(502,"application/json",json.dumps({"error":f"Cloud command error ({type(exc).__name__}). Outcome unknown; inspect Cozytouch and refresh before retrying."}).encode())

    def reply(self, code, mime, body):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Avoid logging paths/queries that could include sensitive data.
        return


def main():
    print("Cozytouch dashboard – manual, confirmed changes only")
    choice, username, password = get_credentials()
    print(f"Using {VENDORS[choice][0]} backend from local .env")
    SESSION.update({"server":VENDORS[choice][1],"username":username,"password":password})
    worker = threading.Thread(target=polling_loop, args=(VENDORS[choice][1], username, password), daemon=True)
    worker.start()
    with ThreadingHTTPServer((HOST, PORT), Handler) as httpd:
        print(f"Dashboard: http://{HOST}:{PORT}")
        print("Only accessible from this PC. Press Ctrl+C to stop.")
        webbrowser.open(f"http://{HOST}:{PORT}")
        try:
            httpd.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
