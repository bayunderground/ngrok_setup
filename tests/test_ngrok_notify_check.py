import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ngrok_notify_check as check  # noqa: E402
import ngrok_notify_state as state  # noqa: E402
import ngrok_notify_telegram as tg  # noqa: E402


class CheckOnceTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.state_file = root / "state" / "last_endpoint"
        self.creds = root / "telegram.env"
        self.creds.write_text("TELEGRAM_BOT_TOKEN=tok\nTELEGRAM_CHAT_ID=1\n", encoding="utf-8")
        os.chmod(self.creds, 0o600)
        self.sent = []

    def tearDown(self):
        self.dir.cleanup()

    def send(self, token, chat_id, text):
        self.sent.append((token, chat_id, text))
        return True

    def lookup(self, endpoint):
        return (lambda: (endpoint, None)) if endpoint else (lambda: (None, "agent API unreachable"))

    def run_once(self, endpoint, send=None):
        return check.check_once(
            self.lookup(endpoint), self.state_file, self.creds, "bliss", send=send or self.send
        )

    def test_first_endpoint_is_announced_and_recorded(self):
        self.assertEqual(self.run_once("h:1"), "announced")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("ssh -p 1 bliss@h", self.sent[0][2])
        self.assertEqual(state.read_last(self.state_file), "h:1")

    def test_unchanged_endpoint_sends_nothing(self):
        self.run_once("h:1")
        self.assertEqual(self.run_once("h:1"), "unchanged")
        self.assertEqual(len(self.sent), 1)

    def test_changed_endpoint_is_announced_again(self):
        self.run_once("h:1")
        self.assertEqual(self.run_once("h:2"), "announced")
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(state.read_last(self.state_file), "h:2")

    def test_no_endpoint_is_a_skip_and_keeps_state(self):
        self.run_once("h:1")
        self.assertTrue(self.run_once(None).startswith("skip"))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(state.read_last(self.state_file), "h:1")

    def test_failed_send_does_not_record_endpoint(self):
        def failing(token, chat_id, text):
            raise tg.SendError("down")

        with self.assertRaises(tg.SendError):
            self.run_once("h:1", send=failing)
        self.assertIsNone(state.read_last(self.state_file))
        self.assertEqual(self.run_once("h:1"), "announced")


if __name__ == "__main__":
    unittest.main()
