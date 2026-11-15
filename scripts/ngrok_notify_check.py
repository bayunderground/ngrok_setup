#!/usr/bin/env python3
"""Announce the active ngrok SSH endpoint over Telegram when it changes."""
import importlib.util
import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


endpoint_helper = _load("ngrok_endpoint", "ngrok-endpoint.py")
state = _load("ngrok_notify_state", "ngrok_notify_state.py")
telegram = _load("ngrok_notify_telegram", "ngrok_notify_telegram.py")


def check_once(lookup, state_file, creds_file, user, send=telegram.send_message):
    endpoint, error = lookup()
    if not endpoint:
        return f"skip: {error or 'no active endpoint'}"
    last = state.read_last(state_file)
    if not state.endpoint_changed(endpoint, last):
        return "unchanged"
    token, chat_id = telegram.read_credentials(creds_file)
    text = telegram.build_message(endpoint, user)
    send(token, chat_id, text)
    state.write_last(state_file, endpoint)
    return "announced"


def main():
    creds = Path(os.environ.get("NGROK_SSH_ENV", REPO / ".env"))
    user = os.environ.get("NGROK_SSH_USER", "bliss")
    try:
        result = check_once(endpoint_helper.lookup, state.state_path(), creds, user)
    except (telegram.CredentialError, telegram.SendError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
