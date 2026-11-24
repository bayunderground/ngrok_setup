import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ngrok_notify_remote as remote  # noqa: E402


class FakeRun:
    def __init__(self, returncode=0, stderr=b"", exc=None):
        self.returncode = returncode
        self.stderr = stderr
        self.exc = exc
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(argv, self.returncode, b"", self.stderr)


class PublishTests(unittest.TestCase):
    def test_sends_line_on_stdin_and_never_on_command_line(self):
        run = FakeRun()
        remote.publish("ssh -p 25605 bliss@2.tcp.eu.ngrok.io", run=run)
        argv, kwargs = run.calls[0]
        self.assertEqual(kwargs["input"], b"ssh -p 25605 bliss@2.tcp.eu.ngrok.io\n")
        self.assertNotIn("bliss@2.tcp", " ".join(argv))
        self.assertIn("root@vdsn2", argv)

    def test_uses_batch_mode_strict_host_keys_and_timeout(self):
        run = FakeRun()
        remote.publish("x", run=run)
        argv, kwargs = run.calls[0]
        self.assertEqual(argv[0], remote.SSH)
        self.assertIn("BatchMode=yes", argv)
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertEqual(kwargs["timeout"], remote.TIMEOUT)

    def test_remote_command_writes_private_temp_then_renames(self):
        command = remote.remote_command("/root/pi5home_ngrok_endpoint.txt")
        self.assertEqual(
            command,
            "umask 077; cat > /root/pi5home_ngrok_endpoint.txt.tmp"
            " && mv -f /root/pi5home_ngrok_endpoint.txt.tmp /root/pi5home_ngrok_endpoint.txt",
        )
        self.assertNotIn(">>", command)

    def test_nonzero_exit_is_publish_error_with_stderr(self):
        run = FakeRun(returncode=255, stderr=b"Permission denied (publickey).\n")
        with self.assertRaises(remote.PublishError) as ctx:
            remote.publish("x", run=run)
        self.assertIn("exited 255", str(ctx.exception))
        self.assertIn("Permission denied", str(ctx.exception))

    def test_timeout_is_publish_error(self):
        run = FakeRun(exc=subprocess.TimeoutExpired("ssh", remote.TIMEOUT))
        with self.assertRaises(remote.PublishError):
            remote.publish("x", run=run)

    def test_missing_ssh_binary_is_publish_error(self):
        run = FakeRun(exc=FileNotFoundError("ssh"))
        with self.assertRaises(remote.PublishError):
            remote.publish("x", run=run)


if __name__ == "__main__":
    unittest.main()
