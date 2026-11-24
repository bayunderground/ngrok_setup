import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ngrok_notify_telegram as tg  # noqa: E402


class FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_opener(responses):
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)

    opener.calls = calls
    return opener


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "telegram.env"

    def tearDown(self):
        self.dir.cleanup()

    def write(self, text, mode=0o600):
        self.path.write_text(text, encoding="utf-8")
        os.chmod(self.path, mode)

    def test_reads_token_and_chat_id(self):
        self.write("# comment\nTELEGRAM_BOT_TOKEN=abc:123\nTELEGRAM_CHAT_ID=42\n")
        self.assertEqual(tg.read_credentials(self.path), ("abc:123", "42"))

    def test_rejects_group_or_world_readable_file(self):
        self.write("TELEGRAM_BOT_TOKEN=a\nTELEGRAM_CHAT_ID=1\n", mode=0o640)
        with self.assertRaises(tg.CredentialError):
            tg.read_credentials(self.path)

    def test_rejects_missing_values(self):
        self.write("TELEGRAM_CHAT_ID=1\n")
        with self.assertRaises(tg.CredentialError):
            tg.read_credentials(self.path)


class MessageTests(unittest.TestCase):
    def test_message_contains_endpoint_ssh_line_and_timestamp(self):
        now = datetime(2026, 11, 15, 12, 30, 0, tzinfo=timezone.utc)
        text = tg.build_message("7.tcp.eu.ngrok.io:17862", "bliss", now=now)
        self.assertEqual(
            text,
            "ngrok SSH endpoint changed\n"
            "ssh -p 17862 bliss@7.tcp.eu.ngrok.io\n"
            "2026-11-15 12:30:00 UTC",
        )


    def test_down_message_says_tunnel_is_down(self):
        now = datetime(2026, 11, 15, 12, 30, 0, tzinfo=timezone.utc)
        self.assertEqual(
            tg.build_down_message(now=now),
            "ngrok SSH tunnel is down\n2026-11-15 12:30:00 UTC",
        )


class SendTests(unittest.TestCase):
    def test_success_on_first_attempt(self):
        opener = fake_opener([200])
        self.assertTrue(tg.send_message("tok", "1", "hi", opener=opener, sleep=lambda s: None))
        self.assertEqual(len(opener.calls), 1)

    def test_request_targets_bot_url_with_form_body_and_timeout(self):
        opener = fake_opener([200])
        tg.send_message("tok", "1", "hi there", opener=opener, sleep=lambda s: None)
        request, timeout = opener.calls[0]
        self.assertEqual(request.full_url, "https://api.telegram.org/bottok/sendMessage")
        self.assertEqual(request.data, b"chat_id=1&text=hi+there")
        self.assertEqual(timeout, tg.TIMEOUT)

    def test_retries_then_succeeds(self):
        sleeps = []
        opener = fake_opener([OSError("boom"), 200])
        self.assertTrue(tg.send_message("tok", "1", "hi", opener=opener, sleep=sleeps.append))
        self.assertEqual(len(opener.calls), 2)
        self.assertEqual(sleeps, [tg.BACKOFF_SECONDS[0]])

    def test_gives_up_after_bounded_attempts(self):
        sleeps = []
        opener = fake_opener([OSError("a"), OSError("b"), OSError("c")])
        with self.assertRaises(tg.SendError):
            tg.send_message("tok", "1", "hi", opener=opener, sleep=sleeps.append)
        self.assertEqual(len(opener.calls), tg.ATTEMPTS)
        self.assertEqual(len(sleeps), tg.ATTEMPTS - 1)

    def test_http_error_is_reported_without_token(self):
        err = urllib.error.HTTPError("https://api.telegram.org/bottok/sendMessage", 401, "x", {}, None)
        opener = fake_opener([err, err, err])
        with self.assertRaises(tg.SendError) as ctx:
            tg.send_message("tok", "1", "hi", opener=opener, sleep=lambda s: None)
        self.assertIn("HTTP 401", str(ctx.exception))
        self.assertNotIn("tok", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
