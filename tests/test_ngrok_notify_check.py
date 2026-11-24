import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ngrok_notify_check as check  # noqa: E402
import ngrok_notify_remote as remote  # noqa: E402
import ngrok_notify_state as state  # noqa: E402
import ngrok_notify_telegram as tg  # noqa: E402


class FakeSender:
    def __init__(self, fail=None):
        self.sent = []
        self.fail = fail

    def __call__(self, text):
        if self.fail:
            raise self.fail
        self.sent.append(text)


class CheckOnceTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.remote_state = root / "last_remote"
        self.tg_state = root / "last_endpoint"
        self.remote_sender = FakeSender()
        self.tg_sender = FakeSender()

    def tearDown(self):
        self.dir.cleanup()

    def channels(self, remote_sender=None, tg_sender=None, with_telegram=False):
        result = [check.Channel("remote", self.remote_state, check.remote_message,
                                remote_sender or self.remote_sender)]
        if with_telegram:
            result.append(check.Channel("telegram", self.tg_state, check.telegram_message,
                                        tg_sender or self.tg_sender))
        return result

    def run_once(self, endpoint, channels=None):
        lookup = (lambda: (endpoint, None)) if endpoint else (lambda: (None, "agent API unreachable"))
        return check.check_once(lookup, channels or self.channels(), "bliss")

    def statuses(self, results):
        return {name: status for name, status, _ in results}

    def test_first_endpoint_is_published_as_single_ssh_line(self):
        self.assertEqual(self.statuses(self.run_once("2.tcp.eu.ngrok.io:25605")),
                         {"remote": "published"})
        self.assertEqual(self.remote_sender.sent, ["ssh -p 25605 bliss@2.tcp.eu.ngrok.io"])
        self.assertEqual(state.read_last(self.remote_state), "2.tcp.eu.ngrok.io:25605")

    def test_unchanged_endpoint_sends_nothing(self):
        self.run_once("h:1")
        self.assertEqual(self.statuses(self.run_once("h:1")), {"remote": "unchanged"})
        self.assertEqual(len(self.remote_sender.sent), 1)

    def test_changed_endpoint_is_published_again(self):
        self.run_once("h:1")
        self.assertEqual(self.statuses(self.run_once("h:2")), {"remote": "published"})
        self.assertEqual(self.remote_sender.sent[-1], "ssh -p 2 bliss@h")

    def test_tunnel_down_is_published_once(self):
        self.run_once("h:1")
        self.assertEqual(self.statuses(self.run_once(None)), {"remote": "published"})
        self.assertEqual(self.remote_sender.sent[-1], "ngrok tunnel is down")
        self.assertEqual(self.statuses(self.run_once(None)), {"remote": "unchanged"})
        self.assertEqual(len(self.remote_sender.sent), 2)

    def test_failed_publish_is_not_recorded_and_retried_next_run(self):
        failing = FakeSender(fail=remote.PublishError("ssh down"))
        results = self.run_once("h:1", self.channels(remote_sender=failing))
        self.assertEqual(results, [("remote", "failed", "ssh down")])
        self.assertIsNone(state.read_last(self.remote_state))
        self.assertEqual(self.statuses(self.run_once("h:1")), {"remote": "published"})

    def test_telegram_failure_does_not_block_remote_channel(self):
        failing = FakeSender(fail=tg.SendError("telegram down"))
        channels = self.channels(tg_sender=failing, with_telegram=True)
        results = self.run_once("h:1", channels)
        self.assertEqual(self.statuses(results), {"remote": "published", "telegram": "failed"})
        self.assertEqual(state.read_last(self.remote_state), "h:1")
        self.assertIsNone(state.read_last(self.tg_state))

    def test_telegram_gets_its_own_message_and_state(self):
        self.run_once("h:1", self.channels(with_telegram=True))
        self.assertIn("ssh -p 1 bliss@h", self.tg_sender.sent[0])
        self.run_once(None, self.channels(with_telegram=True))
        self.assertIn("ngrok SSH tunnel is down", self.tg_sender.sent[-1])
        self.assertEqual(state.read_last(self.tg_state), state.DOWN)
        self.assertEqual(len(self.tg_sender.sent), 2)


class BuildChannelsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.creds = Path(self.dir.name) / "telegram.env"
        self.old_state = os.environ.get("NGROK_SSH_STATE_DIR")
        os.environ["NGROK_SSH_STATE_DIR"] = self.dir.name

    def tearDown(self):
        if self.old_state is None:
            os.environ.pop("NGROK_SSH_STATE_DIR", None)
        else:
            os.environ["NGROK_SSH_STATE_DIR"] = self.old_state
        self.dir.cleanup()

    def test_remote_only_when_no_telegram_credentials(self):
        channels, error = check.build_channels("bliss", self.creds)
        self.assertIsNone(error)
        self.assertEqual([c.name for c in channels], ["remote"])

    def test_telegram_added_when_credentials_present(self):
        self.creds.write_text("TELEGRAM_BOT_TOKEN=t\nTELEGRAM_CHAT_ID=1\n", encoding="utf-8")
        os.chmod(self.creds, 0o600)
        channels, error = check.build_channels("bliss", self.creds)
        self.assertIsNone(error)
        self.assertEqual([c.name for c in channels], ["remote", "telegram"])

    def test_invalid_telegram_credentials_are_reported_not_fatal(self):
        self.creds.write_text("TELEGRAM_CHAT_ID=1\n", encoding="utf-8")
        os.chmod(self.creds, 0o600)
        channels, error = check.build_channels("bliss", self.creds)
        self.assertEqual([c.name for c in channels], ["remote"])
        self.assertIn("TELEGRAM_BOT_TOKEN", error)


class RemoteMessageTests(unittest.TestCase):
    def test_up_and_down_messages(self):
        self.assertEqual(check.remote_message("h:22", "bliss"), "ssh -p 22 bliss@h")
        self.assertEqual(check.remote_message(state.DOWN, "bliss"), "ngrok tunnel is down")


if __name__ == "__main__":
    unittest.main()
