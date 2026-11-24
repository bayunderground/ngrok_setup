#!/usr/bin/env python3
"""Publish the ngrok SSH endpoint, or a tunnel-down marker, when it changes.

The remote file is the primary channel. Telegram is optional and is enabled
only when its credentials file exists. Each channel keeps its own state, so a
failure in one channel does not repeat or block the other.
"""
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent


def _load(name, filename):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


endpoint_helper = _load("ngrok_endpoint", "ngrok-endpoint.py")
state = _load("ngrok_notify_state", "ngrok_notify_state.py")
telegram = _load("ngrok_notify_telegram", "ngrok_notify_telegram.py")
remote = _load("ngrok_notify_remote", "ngrok_notify_remote.py")


@dataclass
class Channel:
    name: str
    state_file: Path
    message: Callable
    send: Callable


def remote_message(value, user):
    if value == state.DOWN:
        return "ngrok tunnel is down"
    host, _, port = value.rpartition(":")
    return f"ssh -p {port} {user}@{host}"


def telegram_message(value, user):
    if value == state.DOWN:
        return telegram.build_down_message()
    return telegram.build_message(value, user)


def check_once(lookup, channels, user):
    endpoint, _ = lookup()
    current = endpoint or state.DOWN
    results = []
    for channel in channels:
        last = state.read_last(channel.state_file)
        if not state.endpoint_changed(current, last):
            results.append((channel.name, "unchanged", None))
            continue
        try:
            channel.send(channel.message(current, user))
        except (telegram.SendError, remote.PublishError) as exc:
            results.append((channel.name, "failed", str(exc)))
            continue
        state.write_last(channel.state_file, current)
        results.append((channel.name, "published", None))
    return results


def build_channels(user, creds):
    channels = [
        Channel("remote", state.state_path("last_remote"), remote_message, remote.publish),
    ]
    if not creds.exists():
        return channels, None
    try:
        token, chat_id = telegram.read_credentials(creds)
    except telegram.CredentialError as exc:
        return channels, str(exc)
    channels.append(Channel(
        "telegram",
        state.state_path("last_endpoint"),
        telegram_message,
        lambda text: telegram.send_message(token, chat_id, text),
    ))
    return channels, None


def main():
    user = os.environ.get("NGROK_SSH_USER", "bliss")
    creds = Path(os.environ.get("NGROK_SSH_ENV", REPO / ".env"))
    channels, config_error = build_channels(user, creds)
    failed = False
    if config_error:
        print(f"telegram: error: {config_error}", file=sys.stderr)
        failed = True
    for name, status, detail in check_once(endpoint_helper.lookup, channels, user):
        line = f"{name}: {status}" + (f" ({detail})" if detail else "")
        if status == "failed":
            print(line, file=sys.stderr)
            failed = True
        else:
            print(line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
