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

**Temperature controls remain disabled** pending clarification of Eco offsets and `OVERRIDEMODE_ERROR`. This editor does not alter Comfort temperatures, Eco reductions, device modes, or heater protection settings.

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
