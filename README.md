# CozytouchPanel

Windows-local dashboard for Sauter TAHUAL radiators using the Cozytouch/Overkiz cloud API.

## Setup

1. Clone the repository and use the dashboard files from the CozytouchPanel Git-ready bundle.
2. Run `py -m pip install -r requirements.txt`.
3. Copy `.env.example` to `.env`, then edit `.env` with your email, password, and the backend used for discovery.
4. Keep your existing `rooms.json` beside `dashboard.py` (the file is Git-ignored). If absent, first-run mapping is by API order and must be checked against the Cozytouch app.
5. Run `py dashboard.py`, then open http://127.0.0.1:8765/.
6. Run `py diagnose.py` for read-only diagnostics.

**Security:** Never push `.env`. It contains plaintext credentials locally. `.gitignore` does not remove credentials that were previously committed. If a password is ever committed, rotate it.

**Important:** Do not keep retrying Eco-reduction writes until the gateway's execution result is understood. The existing radiator schedules are not changed by this repository's dashboard.
