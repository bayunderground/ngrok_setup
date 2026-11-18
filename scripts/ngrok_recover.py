#!/usr/bin/env python3
"""Debounced recovery for the ngrok SSH tunnel. Single owner of restarts."""
import fcntl
import importlib.util
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
RUN_DIR = Path(os.environ.get("NGROK_SSH_RUN_DIR", "/run/ngrok-ssh"))
REQUEST_NAME = "recover.request"
LOCK_NAME = "recover.lock"
DEBOUNCE_SECONDS = 5
RESTART_COOLDOWN_SECONDS = 600
PROBE_TIMEOUT = 10
SERVICE = "ngrok-ssh.service"
COOLDOWN_NAME = "last-restart"


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


def probe_reachable(endpoint, timeout=PROBE_TIMEOUT):
    host, _, port = endpoint.rpartition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            return sock.recv(64).startswith(b"SSH-2.0-")
    except (OSError, ValueError):
        return False


def endpoint_up():
    endpoint, _ = endpoint_helper.lookup()
    return endpoint is not None and probe_reachable(endpoint)


def ssh_connections_open():
    result = subprocess.run(
        ["ss", "-Htn", "state", "established", "( sport = :22 )"],
        capture_output=True, text=True, timeout=10, check=True,
    )
    return len([line for line in result.stdout.splitlines() if line.strip()])


def restart_blocker(run_dir, now=None, cooldown=RESTART_COOLDOWN_SECONDS):
    if ssh_connections_open():
        return "sessions-active"
    marker = Path(run_dir) / COOLDOWN_NAME
    if not marker.exists():
        return None
    now = time.time() if now is None else now
    if now - marker.stat().st_mtime < cooldown:
        return "cooldown"
    return None


def record_restart(run_dir):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / COOLDOWN_NAME).write_text("restarted\n", encoding="utf-8")


def restart_agent():
    subprocess.run(["systemctl", "restart", SERVICE], check=True, timeout=60)


def restart_then_record(run_dir):
    restart_agent()
    record_restart(run_dir)


def service_enabled():
    result = subprocess.run(
        ["systemctl", "is-enabled", "--quiet", SERVICE],
        capture_output=True, timeout=10, check=False,
    )
    return result.returncode == 0


def run_once(run_dir, has_route, endpoint_present, restart, now=None,
             debounce=DEBOUNCE_SECONDS, enabled=lambda: True,
             blocker=lambda: None):
    if not enabled():
        return "disabled"
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
        reason = blocker()
        if reason:
            return reason
        restart()
        return "restarted"


def mark_if_stale(run_dir, has_route, endpoint_present, now=None):
    if not has_route() or endpoint_present():
        return False
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    request = run_dir / REQUEST_NAME
    if request.exists():
        return False
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if now is None else now))
    request.write_text(stamp + "\n", encoding="utf-8")
    return True


def main():
    try:
        if not service_enabled():
            print("disabled")
            return 0
        if "--watchdog" in sys.argv[1:]:
            mark_if_stale(RUN_DIR, has_default_route, endpoint_up)
        result = run_once(
            RUN_DIR, has_default_route, endpoint_up, lambda: restart_then_record(RUN_DIR),
            blocker=lambda: restart_blocker(RUN_DIR),
        )
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"recovery failed: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
