#!/usr/bin/env python3
"""Track the last endpoint that was successfully announced."""
import os
import tempfile
from pathlib import Path

DEFAULT_STATE = Path.home() / ".local" / "state" / "ngrok-ssh" / "last_endpoint"


def state_path():
    override = os.environ.get("NGROK_SSH_STATE")
    return Path(override) if override else DEFAULT_STATE


def read_last(path):
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return value or None


def write_last(path, endpoint):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".last_endpoint.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(endpoint + "\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def endpoint_changed(current, last):
    return bool(current) and current != last
