#!/usr/bin/env python3
"""Write the current ngrok SSH endpoint line to a file on a remote host over SSH."""
import shlex
import subprocess

REMOTE = "root@vdsn2"
REMOTE_FILE = "/root/pi5home_ngrok_endpoint.txt"
SSH = "/usr/bin/ssh"
SSH_OPTIONS = (
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "StrictHostKeyChecking=yes",
)
TIMEOUT = 30


class PublishError(Exception):
    pass


def remote_command(path):
    tmp = f"{path}.tmp"
    return f"umask 077; cat > {shlex.quote(tmp)} && mv -f {shlex.quote(tmp)} {shlex.quote(path)}"


def publish(line, remote=REMOTE, path=REMOTE_FILE, run=subprocess.run):
    argv = [SSH, *SSH_OPTIONS, remote, remote_command(path)]
    try:
        result = run(
            argv, input=(line + "\n").encode("utf-8"),
            capture_output=True, timeout=TIMEOUT, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublishError(f"ssh to {remote} failed: {type(exc).__name__}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[:200]
        raise PublishError(f"ssh to {remote} exited {result.returncode}: {detail}")
    return True
