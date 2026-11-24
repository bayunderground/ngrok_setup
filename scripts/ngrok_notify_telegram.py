#!/usr/bin/env python3
"""Send Telegram messages for ngrok endpoint changes using only the stdlib."""
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 10
ATTEMPTS = 3
BACKOFF_SECONDS = (2, 5)


class CredentialError(Exception):
    pass


class SendError(Exception):
    pass


def read_credentials(path):
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise CredentialError(f"{path} must not be readable by group or others (mode {oct(mode)})")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    token = values.get("TELEGRAM_BOT_TOKEN")
    chat_id = values.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise CredentialError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set")
    return token, chat_id


def _stamp(now):
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S UTC")


def build_message(endpoint, user, now=None):
    host, _, port = endpoint.rpartition(":")
    return (
        "ngrok SSH endpoint changed\n"
        f"ssh -p {port} {user}@{host}\n"
        f"{_stamp(now)}"
    )


def build_down_message(now=None):
    return f"ngrok SSH tunnel is down\n{_stamp(now)}"


def send_message(token, chat_id, text, opener=urllib.request.urlopen, sleep=time.sleep):
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    url = API.format(token=token)
    last_error = None
    for attempt in range(ATTEMPTS):
        try:
            with opener(urllib.request.Request(url, data=body), timeout=TIMEOUT) as resp:
                if resp.status == 200:
                    return True
                last_error = f"HTTP {resp.status}"
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError) as exc:
            last_error = type(exc).__name__
        if attempt < ATTEMPTS - 1:
            sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
    raise SendError(f"Telegram send failed after {ATTEMPTS} attempts: {last_error}")
