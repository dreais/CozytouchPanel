# Read-only troubleshooting

The previous v2 write was not confirmed by the radiator. Do not retry it until we've determined whether it was rejected or whether the state response is stale.

1. Stop the running dashboard (`Ctrl+C`).
2. Preserve your `rooms.json` when using this bundle.
3. From PowerShell in the extracted `cozytouch_dashboard` directory, run `py diagnose.py`.
4. Use the same backend as the dashboard. Credentials are entered locally and are not saved.
5. Share only the printed diagnostic results; inspect for private information first.

`diagnose.py` only uses authentication and read API calls (`get_devices`, `get_state`, `get_execution_history`). It does not call any `set*`, `refresh*`, `execute_action_group`, or device-update API.

The v2 dashboard remains included for read-only temperature viewing. Avoid using its Apply controls until this issue is resolved.
