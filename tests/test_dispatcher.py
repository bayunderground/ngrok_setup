import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "dispatcher" / "50-ngrok-ssh"


class DispatcherHookTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.dir.name) / "run"

    def tearDown(self):
        self.dir.cleanup()

    def invoke(self, iface, action):
        env = dict(os.environ, NGROK_SSH_RUN_DIR=str(self.run_dir))
        return subprocess.run(["sh", str(HOOK), iface, action], env=env, timeout=10)

    def test_relevant_events_set_request_flag(self):
        for action in ("up", "down", "vpn-up", "vpn-down", "connectivity-change", "dhcp4-change"):
            with self.subTest(action=action):
                (self.run_dir / "recover.request").unlink(missing_ok=True)
                result = self.invoke("anyif", action)
                self.assertEqual(result.returncode, 0)
                self.assertTrue((self.run_dir / "recover.request").exists())

    def test_irrelevant_events_are_ignored(self):
        for action in ("pre-up", "pre-down", "hostname", ""):
            with self.subTest(action=action):
                result = self.invoke("anyif", action)
                self.assertEqual(result.returncode, 0)
                self.assertFalse((self.run_dir / "recover.request").exists())

    def test_interface_name_does_not_affect_decision(self):
        self.assertEqual(self.invoke("eth0", "up").returncode, 0)
        self.assertTrue((self.run_dir / "recover.request").exists())
        (self.run_dir / "recover.request").unlink()
        self.assertEqual(self.invoke("happ-xray", "up").returncode, 0)
        self.assertTrue((self.run_dir / "recover.request").exists())

    def test_hook_is_fast_and_never_fails_the_caller(self):
        result = self.invoke("eth0", "up")
        self.assertEqual(result.returncode, 0)

    def test_request_contains_utc_timestamp(self):
        self.invoke("eth0", "up")
        text = (self.run_dir / "recover.request").read_text(encoding="utf-8").strip()
        self.assertRegex(text, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


if __name__ == "__main__":
    unittest.main()
