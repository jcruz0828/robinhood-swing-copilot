import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import HOOK, fixture

spec = importlib.util.spec_from_file_location("order_guard", HOOK)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

EVENTS = fixture("hook_events.json")


def decide(name, env=None, **extra):
    ev = dict(EVENTS[name], **extra)
    return guard.decide(ev, env or {})


class TestDecisions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_pass(self):
        self.assertIsNone(decide("read_quote", cwd=self.cwd))
        self.assertIsNone(decide("review_order", cwd=self.cwd))
        self.assertIsNone(decide("headless_read", cwd=self.cwd))

    def test_non_robinhood_ignored(self):
        self.assertIsNone(decide("non_robinhood", cwd=self.cwd))

    def test_order_writes_ask(self):
        for name in ("place_buy", "place_sell", "place_protect", "cancel"):
            self.assertEqual(decide(name, cwd=self.cwd)[0], "ask", name)

    def test_options_crypto_denied(self):
        self.assertEqual(decide("place_option", cwd=self.cwd)[0], "deny")
        self.assertEqual(decide("place_crypto", cwd=self.cwd)[0], "deny")

    def test_watchlist_passes(self):
        self.assertIsNone(decide("add_watchlist", cwd=self.cwd))

    def test_halt_blocks_entries_only(self):
        open(os.path.join(self.cwd, "HALT"), "w").close()
        self.assertEqual(decide("place_buy", cwd=self.cwd)[0], "deny")
        self.assertEqual(decide("place_sell", cwd=self.cwd)[0], "ask")
        self.assertEqual(decide("place_protect", cwd=self.cwd)[0], "ask")

    def test_halt_via_journal_env(self):
        j = os.path.join(self.cwd, "journal")
        os.makedirs(j)
        open(os.path.join(j, "HALT"), "w").close()
        self.assertEqual(decide("place_buy", env={"SWING_JOURNAL_DIR": j}, cwd="/nonexistent")[0], "deny")

    def test_headless_is_read_only(self):
        self.assertEqual(decide("headless_place_buy", cwd=self.cwd)[0], "deny")
        self.assertEqual(decide("place_sell", env={"SWING_COPILOT_HEADLESS": "1"}, cwd=self.cwd)[0], "deny")

    def test_broker_queue_mode(self):
        env = {"SWING_COPILOT_HEADLESS": "1", "SWING_COPILOT_SCHEDULED_MODE": "broker_queue"}
        self.assertIsNone(decide("place_buy", env=env, cwd=self.cwd))
        self.assertEqual(decide("cancel", env=env, cwd=self.cwd)[0], "deny")


class TestCLI(unittest.TestCase):
    def run_hook(self, payload):
        return subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True)

    def test_ask_output_shape(self):
        p = self.run_hook(json.dumps(dict(EVENTS["place_buy"], cwd=tempfile.gettempdir())))
        self.assertEqual(p.returncode, 0)
        out = json.loads(p.stdout)["hookSpecificOutput"]
        self.assertEqual((out["hookEventName"], out["permissionDecision"]), ("PreToolUse", "ask"))

    def test_silent_on_reads(self):
        p = self.run_hook(json.dumps(EVENTS["read_quote"]))
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_malformed_fails_closed(self):
        self.assertEqual(self.run_hook("{not json").returncode, 2)


if __name__ == "__main__":
    unittest.main()
