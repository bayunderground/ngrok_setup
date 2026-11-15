#!/usr/bin/env python3
"""Debounced recovery for the ngrok SSH tunnel. Single owner of restarts."""
import fcntl
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
RUN_DIR = Path(os.environ.get("NGROK_SSH_RUN_DIR", "/run/ngrok-ssh"))
REQUEST_NAME = "recover.request"
LOCK_NAME = "recover.lock"
DEBOUNCE_SECONDS = 5
SERVICE = "ngrok-ssh.service"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


endpoint_helper = _load("ngrok_endpoint", "ngrok-endpoint.py")


def has_default_route():
    result = subprocess.run(
        ["ip", "-4", "route", "show", "default"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    return bool(result.stdout.strip())


def endpoint_up():
    endpoint, _ = endpoint_helper.lookup()
    return endpoint is not None


def restart_agent():
    subprocess.run(["systemctl", "restart", SERVICE], check=True, timeout=60)


def run_once(run_dir, has_route, endpoint_present, restart, now=None, debounce=DEBOUNCE_SECONDS):
    run_dir = Path(run_dir)
    request = run_dir / REQUEST_NAME
    if not request.exists():
        return "no-request"
    now = time.time() if now is None else now
    if now - request.stat().st_mtime < debounce:
        return "debouncing"
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / LOCK_NAME, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "busy"
        request.unlink(missing_ok=True)
        if not has_route():
            return "no-route"
        if endpoint_present():
            return "healthy"
        restart()
        return "restarted"


def main():
    try:
        result = run_once(RUN_DIR, has_default_route, endpoint_up, restart_agent)
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"recovery failed: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
