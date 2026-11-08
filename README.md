# CozytouchPanel

Local Windows dashboard for four Sauter TAHUAL io-homecontrol radiators via the Cozytouch/Overkiz cloud API.

## Quick start

1. `py -m pip install -r requirements.txt`
2. Copy `.env.example` to `.env`, fill in your Cozytouch credentials and set the backend used for discovery.
3. Keep your verified `rooms.json` in this folder. Never guess an unverified room mapping.
4. Run `py dashboard.py` and visit http://127.0.0.1:8765/.
5. Select **Weekly schedule editor**, or go to http://127.0.0.1:8765/schedule.

## Weekly editor (experimental)

- Load one radiator's current internal Monday–Sunday program.
- Edit up to three non-overlapping Comfort periods per day using HH:MM. Enter `24:00` explicitly for midnight. `00:00` to `00:00` represents an unused slot.
- **Copy Monday to all days** if desired. The editor shows exact differences before saving.
- Review the changes and type `APPLY <room name>` to authorize one `setTimeProgram` action on only that radiator.
- The server rereads the cloud schedule immediately before writing and refuses the write if it changed since preview.
- Each write creates a unique backup under `.private/schedule_backups/` before the API command is sent. Keep backups private; they may contain heating schedules.
- The server checks that execution history matches the returned execution ID and independently checks for a complete seven-day readback match. A successful readback does **not** prove the physical radiator has followed the new program; check Cozytouch or the radiator.
- If an execution fails or verification is uncertain, **do not retry blindly**. Inspect the official app and radiator first.

The weekly editor has not yet been live-tested against your gateway. The earlier Hall Monday `setTimeProgram` experiment did report `COMPLETED`, `NO_FAILURE`, and a full schedule readback match. This new UI uses the same command format but adds validation, backup, CSRF checks, and explicit confirmation.

## Temperature controls (experimental)

The room dashboard now offers two individually confirmed, single-room edits:

- **Eco reduction** uses `setSetpointLoweringTemperatureInProgMode`, observed in completed historical executions. It verifies `io:SetpointLoweringTemperatureInProgModeState`.
- **Comfort/base target** uses `setTargetTemperature` rather than the previously failed `setComfortTemperature`. This is an EXPERIMENTAL mapping, and requires both `core:TargetTemperatureState` and `core:ComfortRoomTemperatureState` to match before reporting verified.

Every write requires a fresh reading and room confirmation, a local backup in `.private/temperature_backups/`, a schedule invariance check, cloud execution-history matching, and temperature readback. A cloud completion alone does not prove success. Existing overrides remain untouched; they can still take precedence. No correction for the unverified ~1.5°C perceived temperature discrepancy is applied.

**Recommended first live test:** if you want a slightly warmer Hall at night, reduce its Eco reduction from 4.0 to 3.5°C (programmed Eco target becomes 16.5°C, assuming a 20°C Comfort setting and no override). This is a real heating change. Do not apply if you do not want the result. Verify it in Cozytouch before testing Comfort edits. Never retry an unverified/failed operation blindly.

Offline tests:

```powershell
py -m unittest test_scheduler_validation test_temperature_validation -v
```


## Check offline input validation

```powershell
py -m unittest test_scheduler_validation -v
```

These tests do not contact Cozytouch.

## Security

- `.env`, `rooms.json`, and `.private/` are excluded by `.gitignore`. Never force-add these files.
- The password is stored as plaintext locally in `.env` and loaded into process memory. Secure your Windows account.
- The server listens only on `127.0.0.1:8765`. Do not expose its port or run it behind a public proxy.
- `.gitignore` does not protect credentials that have already been committed. Rotate any compromised password.
- No automatic heating command is scheduled; internal programs continue operating independently if the dashboard stops.

## Diagnostics

Run `py diagnose.py` for read-only heater state diagnostics or `py inspect_schedules.py` for a raw local schedule backup. The latter writes to the Git-ignored `.private/` folder.
