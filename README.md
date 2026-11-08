# CozytouchPanel

Local Windows dashboard for four Sauter TAHUAL io-homecontrol radiators via the Cozytouch / Overkiz cloud API.

## Get started

1. `py -m pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in your Cozytouch account email and password. Set `COZYTOUCH_BACKEND` to whichever worked for discovery (1=Atlantic, 2=Thermor, 3=Sauter).
3. Copy `rooms.json` from your existing working dashboard into this folder. The file is intentionally ignored by Git to avoid sharing stable device identifiers. If it is absent, the app creates a first-run mapping by API order; verify it against Cozytouch before sending any commands.
4. Run `py dashboard.py` then visit http://127.0.0.1:8765/.
5. For read-only troubleshooting, run `py diagnose.py`.

**Privacy:** Never commit `.env` or share it in issues, screenshots, or chat. `.gitignore` only protects untracked files; if credentials are ever committed, remove them from history and rotate your password. The `.env` file stores the password unencrypted on your PC, so keep your Windows user account secured.

**Heating safety:** The current UI permits manual confirmed single-setting writes; the Eco reduction command is not yet verified to work on this gateway. Do not repeatedly send commands whose outcome is uncertain. No schedules are modified automatically.

---

# Cozytouch dashboard — manual setpoints (v2)

This extends the previously working read-only Windows dashboard for four Sauter TAHUAL io-homecontrol radiators. The default proposed Comfort and Eco reduction settings are:

| Room | Comfort | Eco reduction | Eco target (nominal) |
|---|---:|---:|---:|
| Living room | 21°C | 1.5°C | 19.5°C |
| Bedroom | 19.5°C | 1°C | 18.5°C |
| Hall | 19°C | 1°C | 18°C |
| Kitchen | 19.5°C | 1°C | 18.5°C |

**Proposals are not applied automatically.** Every individual setting requires Review → type `APPLY <room>` → Send. The readback is verified independently; an accepted API command isn't necessarily an executed command.

## Upgrade / install

1. Stop the previous dashboard (`Ctrl+C`). **Copy your existing `rooms.json`** into the new extracted folder; it preserves verified hashed device-to-room mappings. Do not overwrite your old folder until you've backed it up.
2. In PowerShell, run `py -m pip install -r requirements.txt` and then `py dashboard.py`.
3. Open http://127.0.0.1:8765/ and check room readings against Cozytouch.
4. **Suggested first test:** Living room → Eco reduction from 7.5°C to **1.5°C**. Review the target, type `APPLY Living room` and send. This is a genuine heating setting change and could immediately increase heating. Wait for the verification result and check the radiator screen / Cozytouch app. If needed, manually restore the previous value using the same control. Do not send repeated commands when outcome is uncertain.
5. Only then adjust its Comfort from 23.5°C to 21°C, and proceed one room at a time.

## Safety boundaries and caveats

- This version does not write schedules, operate modes, change calibration, disable protections, or automate any writes.
- Each write verifies the radiator identity against the stored hashed mapping; refuses unknown or changed device inventories; checks current value immediately before write; restricts values to 0.5°C steps, Comfort 15–24°C, Eco reduction 0–8°C, nominal Eco target >=15°C; and sends one API command at a time.
- The proposed **Eco reduction** is the difference from Comfort, *not* an absolute temperature. Your real effective target may be affected by local modes, overrides and internal schedules.
- It may take time for cloud readings to reflect commands. A verification failure does not imply no change occurred. Inspect the device before retrying.
- The `pyoverkiz` backend may reject a command despite advertising it. There is no unattended retry or automatic rollback.
- Heating may cost more when Eco reduction is decreased. Keep existing radiator schedules as fallback. The app cannot guarantee a physical minimum measured room temperature.
- Keep the dashboard on `127.0.0.1` only. Cloud credentials stay in running process memory. `rooms.json` holds only room names and hashed device identifiers. Only use the local page; never publish port 8765.
- Browser reflects fresh cloud values, not guaranteed real-time hardware temperatures.
- Firmware-level protection and built-in safety settings are not touched.

If you see a cloud error or an *unverified* result, use the official Cozytouch app to check whether the command took effect before making another change.
