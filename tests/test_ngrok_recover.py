import fcntl
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ngrok_recover as rec  # noqa: E402


class RunOnceTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.dir.name) / "run"
        self.run_dir.mkdir()
        self.request = self.run_dir / rec.REQUEST_NAME
        self.restarts = []

    def tearDown(self):
        self.dir.cleanup()

    def make_request(self, age):
        self.request.write_text("ts\n", encoding="utf-8")
        mtime = os.stat(self.request).st_mtime
        os.utime(self.request, (mtime - age, mtime - age))

    def restart(self):
        self.restarts.append(True)

    def run_once(self, route=True, endpoint=False, now=None):
        return rec.run_once(
            self.run_dir,
            lambda: route,
            lambda: endpoint,
            self.restart,
            now=now,
        )

    def test_disabled_service_is_left_alone(self):
        self.make_request(age=30)
        result = rec.run_once(
            self.run_dir, lambda: True, lambda: False, self.restart,
            enabled=lambda: False,
        )
        self.assertEqual(result, "disabled")
        self.assertEqual(self.restarts, [])
        self.assertTrue(self.request.exists())

    def test_no_request_does_nothing(self):
        self.assertEqual(self.run_once(), "no-request")
        self.assertEqual(self.restarts, [])

    def test_fresh_request_is_debounced_and_kept(self):
        self.make_request(age=1)
        self.assertEqual(self.run_once(), "debouncing")
        self.assertTrue(self.request.exists())
        self.assertEqual(self.restarts, [])

    def test_settled_request_without_endpoint_restarts_and_consumes_flag(self):
        self.make_request(age=30)
        self.assertEqual(self.run_once(route=True, endpoint=False), "restarted")
        self.assertEqual(len(self.restarts), 1)
        self.assertFalse(self.request.exists())

    def test_healthy_endpoint_is_not_restarted(self):
        self.make_request(age=30)
        self.assertEqual(self.run_once(route=True, endpoint=True), "healthy")
        self.assertEqual(self.restarts, [])
        self.assertFalse(self.request.exists())

    def test_no_default_route_does_not_restart(self):
        self.make_request(age=30)
        self.assertEqual(self.run_once(route=False, endpoint=False), "no-route")
        self.assertEqual(self.restarts, [])
        self.assertFalse(self.request.exists())

    def test_second_run_after_consumption_is_a_no_op(self):
        self.make_request(age=30)
        self.run_once(route=True, endpoint=False)
        self.assertEqual(self.run_once(route=True, endpoint=False), "no-request")
        self.assertEqual(len(self.restarts), 1)

    def test_busy_when_another_run_holds_the_lock(self):
        self.make_request(age=30)
        with open(self.run_dir / rec.LOCK_NAME, "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.run_once(route=True, endpoint=False), "busy")
        self.assertEqual(self.restarts, [])
        self.assertTrue(self.request.exists())

    def test_burst_of_events_results_in_single_restart(self):
        self.make_request(age=1)
        self.assertEqual(self.run_once(route=True, endpoint=False), "debouncing")
        self.make_request(age=30)
        self.assertEqual(self.run_once(route=True, endpoint=False), "restarted")
        self.assertEqual(len(self.restarts), 1)


class WatchdogMarkTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.dir.name) / "run"
        self.request = self.run_dir / rec.REQUEST_NAME

    def tearDown(self):
        self.dir.cleanup()

    def test_missing_endpoint_with_route_marks_request(self):
        self.assertTrue(rec.mark_if_stale(self.run_dir, lambda: True, lambda: False, now=0))
        self.assertTrue(self.request.exists())
        self.assertEqual(self.request.read_text(encoding="utf-8"), "1970-01-01T00:00:00Z\n")

    def test_existing_request_is_not_refreshed_so_debounce_can_elapse(self):
        self.run_dir.mkdir(parents=True)
        self.request.write_text("old\n", encoding="utf-8")
        os.utime(self.request, (0, 0))
        self.assertFalse(rec.mark_if_stale(self.run_dir, lambda: True, lambda: False, now=1000))
        self.assertEqual(os.stat(self.request).st_mtime, 0)

    def test_healthy_endpoint_does_not_mark(self):
        self.assertFalse(rec.mark_if_stale(self.run_dir, lambda: True, lambda: True))
        self.assertFalse(self.request.exists())

    def test_no_route_does_not_mark(self):
        self.assertFalse(rec.mark_if_stale(self.run_dir, lambda: False, lambda: False))
        self.assertFalse(self.request.exists())


if __name__ == "__main__":
    unittest.main()
