import json
import os
import re
import unittest

from helpers import ROOT, SKILL, RULES, swing


def load(*parts):
    with open(os.path.join(*parts), "r", encoding="utf-8") as fh:
        return json.load(fh)


class TestRules(unittest.TestCase):
    """rules.json must match the numbers documented in docs/spec.md section 4."""

    def test_documented_defaults(self):
        r = RULES
        self.assertEqual(r["regime"]["sma_slow"], 200)
        self.assertEqual(r["regime"]["states"]["GREEN"]["max_positions"], 6)
        self.assertEqual(r["regime"]["states"]["YELLOW"]["risk_mult"], 0.5)
        self.assertFalse(r["regime"]["states"]["RED"]["new_entries"])
        self.assertEqual(r["entry"]["rsi_pullback_max"], 45.0)
        self.assertEqual(r["entry"]["pullback_lookback"], 5)
        self.assertEqual(r["sizing"]["risk_pct_default"], 0.5)
        self.assertEqual(r["sizing"]["stop_atr_mult"], 2.0)
        self.assertEqual(r["sizing"]["max_position_pct"], 10.0)
        self.assertEqual(r["exits"]["target_r"], 2.0)
        self.assertEqual(r["exits"]["time_stop_days"], 15)
        self.assertEqual((r["breakers"]["daily_loss_pct"], r["breakers"]["weekly_loss_pct"],
                          r["breakers"]["monthly_loss_pct"]), (2.0, 5.0, 8.0))
        self.assertEqual(r["breakers"]["peak_drawdown_lock_pct"], 15.0)
        self.assertEqual(r["events"]["earnings_buffer_trading_days"], 2)
        self.assertFalse(r["consent"]["batch_approvals"])
        self.assertEqual(r["paper"]["slippage_pct"], 0.05)
        self.assertEqual(r["graduation"]["min_closed_trades"], 20)

    def test_version_matches_engine(self):
        self.assertEqual(RULES["version"], swing.VERSION)


class TestJournalSeeds(unittest.TestCase):
    J = os.path.join(SKILL, "templates", "journal")

    def test_settings(self):
        s = load(self.J, "settings.json")
        self.assertEqual(s["mode"], "paper")
        self.assertEqual(s["starting_equity"], 10000)
        self.assertEqual(s["scheduled_runs"], "strict")
        self.assertIs(s["notify_email"], False)
        self.assertIs(s["chat_only_consent"], False)
        self.assertEqual(s["rules_version"], RULES["version"])

    def test_state_is_clean(self):
        st = load(self.J, "state.json")
        self.assertEqual(st["breaker"], "TRADING_ALLOWED")
        self.assertIsNone(st["pending_card"])
        self.assertFalse(st["peak_lock"])

    def test_paper_account(self):
        a = load(self.J, "paper", "account.json")
        self.assertEqual((a["cash"], a["equity"], a["positions"], a["orders"]), (10000.0, 10000.0, [], []))

    def test_no_halt_seed(self):
        self.assertFalse(os.path.exists(os.path.join(self.J, "HALT")))


class TestClaudeCodeConfig(unittest.TestCase):
    def test_settings_cover_both_prefixes(self):
        s = load(ROOT, ".claude", "settings.json")
        ask, deny = s["permissions"]["ask"], s["permissions"]["deny"]
        for prefix in ("mcp__robinhood-trading__", "mcp__claude_ai_Robinhood__"):
            for tool in ("place_equity_order", "place_advanced_order", "cancel_equity_order",
                         "cancel_advanced_order", "decline_trade_approval"):
                self.assertIn(prefix + tool, ask)
            for tool in ("place_option_order", "place_crypto_order", "exercise_option"):
                self.assertIn(prefix + tool, deny)

    def test_hook_matcher(self):
        s = load(ROOT, ".claude", "settings.json")
        matcher = s["hooks"]["PreToolUse"][0]["matcher"]
        for name in ("mcp__robinhood-trading__place_equity_order", "mcp__claude_ai_Robinhood__cancel_advanced_order"):
            self.assertTrue(re.fullmatch(matcher, name), name)
        self.assertFalse(re.fullmatch(matcher, "Bash"))

    def test_mcp_json(self):
        m = load(ROOT, ".mcp.json")
        self.assertEqual(m["mcpServers"]["robinhood-trading"]["url"], "https://agent.robinhood.com/mcp/trading")


class TestSkillPackage(unittest.TestCase):
    def test_frontmatter(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        m = re.match(r"^---\nname: (.+)\ndescription: (.+)\n---\n", text)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), os.path.basename(SKILL))  # Claude app requires folder == name
        self.assertLessEqual(len(m.group(2)), 1024)

    def test_referenced_files_exist(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        for rel in set(re.findall(r"`((?:references|templates|scripts|config|evals)/[\w./-]+\.\w+)`", text)):
            self.assertTrue(os.path.exists(os.path.join(SKILL, rel)), rel)

    def test_evals(self):
        e = load(SKILL, "evals", "evals.json")
        ids = [x["id"] for x in e["evals"]]
        self.assertEqual(len(ids), len(set(ids)))
        for x in e["evals"]:
            self.assertTrue(x["prompt"] and x["expected_behavior"] and "must_not" in x, x["id"])

    def test_all_json_parses(self):
        for base, _, files in os.walk(ROOT):
            if ".git" in base:
                continue
            for f in files:
                if f.endswith(".json"):
                    load(base, f)


if __name__ == "__main__":
    unittest.main()


class TestCLI(unittest.TestCase):
    SCRIPT = os.path.join(SKILL, "scripts", "swing.py")

    def run_cli(self, args, stdin=""):
        import subprocess
        import sys
        return subprocess.run([sys.executable, self.SCRIPT] + args, input=stdin, capture_output=True, text=True)

    def test_selftest_ok(self):
        p = self.run_cli(["selftest"])
        self.assertEqual(p.returncode, 0)
        self.assertTrue(json.loads(p.stdout)["ok"])

    def test_bad_input_exit_2(self):
        for args, stdin in ((["size"], "{}"), (["size"], "{not json"), (["nope"], "{}"), (["paper"], "{}")):
            p = self.run_cli(args, stdin)
            self.assertEqual(p.returncode, 2, (args, p.stderr))
            self.assertIn("error", json.loads(p.stdout))

    def test_size_roundtrip(self):
        p = self.run_cli(["size"], '{"entry":100,"atr":2,"low_recent":97,"equity":10000}')
        self.assertEqual(json.loads(p.stdout)["shares"], 10)
