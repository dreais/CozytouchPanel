"""Load Cozytouch credentials from an ignored local .env file."""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"


def get_credentials():
    load_dotenv(dotenv_path=ENV_PATH, override=False)
    backend = os.environ.get("COZYTOUCH_BACKEND", "1").strip()
    email = os.environ.get("COZYTOUCH_EMAIL", "").strip()
    password = os.environ.get("COZYTOUCH_PASSWORD", "")
    if backend not in ("1", "2", "3"):
        raise SystemExit("Invalid COZYTOUCH_BACKEND in .env (expected 1, 2 or 3).")
    if not email or not password or password == "replace-me":
        raise SystemExit("Add COZYTOUCH_EMAIL and COZYTOUCH_PASSWORD to your local .env file (see .env.example).")
    return backend, email, password
