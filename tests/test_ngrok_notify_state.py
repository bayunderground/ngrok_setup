import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ngrok_notify_state as state  # noqa: E402


class StateFileTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "nested" / "last_endpoint"

    def tearDown(self):
        self.dir.cleanup()

    def test_missing_file_reads_none(self):
        self.assertIsNone(state.read_last(self.path))

    def test_round_trip_writes_endpoint_and_newline(self):
        state.write_last(self.path, "7.tcp.eu.ngrok.io:17862")
        self.assertEqual(state.read_last(self.path), "7.tcp.eu.ngrok.io:17862")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "7.tcp.eu.ngrok.io:17862\n")

    def test_written_file_is_private(self):
        state.write_last(self.path, "h:1")
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode, 0o600)

    def test_overwrite_replaces_value_and_leaves_no_temp_files(self):
        state.write_last(self.path, "a:1")
        state.write_last(self.path, "b:2")
        self.assertEqual(state.read_last(self.path), "b:2")
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["last_endpoint"])

    def test_blank_file_reads_none(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("  \n", encoding="utf-8")
        self.assertIsNone(state.read_last(self.path))

    def test_failed_write_keeps_previous_value(self):
        state.write_last(self.path, "a:1")
        original = os.replace

        def boom(*args, **kwargs):
            raise OSError("disk full")

        state.os.replace = boom
        try:
            with self.assertRaises(OSError):
                state.write_last(self.path, "b:2")
        finally:
            state.os.replace = original
        self.assertEqual(state.read_last(self.path), "a:1")
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["last_endpoint"])


class ChangeDetectionTests(unittest.TestCase):
    def test_new_endpoint_is_a_change(self):
        self.assertTrue(state.endpoint_changed("h:1", None))

    def test_different_endpoint_is_a_change(self):
        self.assertTrue(state.endpoint_changed("h:2", "h:1"))

    def test_same_endpoint_is_not_a_change(self):
        self.assertFalse(state.endpoint_changed("h:1", "h:1"))

    def test_missing_current_endpoint_is_never_a_change(self):
        self.assertFalse(state.endpoint_changed(None, "h:1"))
        self.assertFalse(state.endpoint_changed(None, None))


class StatePathTests(unittest.TestCase):
    def test_env_override_wins(self):
        os.environ["NGROK_SSH_STATE"] = "/tmp/x/last"
        try:
            self.assertEqual(state.state_path(), Path("/tmp/x/last"))
        finally:
            del os.environ["NGROK_SSH_STATE"]

    def test_default_is_under_home_state_dir(self):
        self.assertEqual(state.state_path(), state.DEFAULT_STATE)


if __name__ == "__main__":
    unittest.main()
