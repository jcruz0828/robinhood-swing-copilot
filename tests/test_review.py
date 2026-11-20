import unittest

from helpers import RULES, swing


def trades(rs, adherent=True):
    return [{"r_multiple": r, "pnl": r * 50, "rule_adherent": adherent} for r in rs]


class TestReview(unittest.TestCase):
    def test_metrics(self):
        out = swing.review({"trades": trades([2, -1, -1, 2, 0.5])}, RULES)
        self.assertEqual(out["closed_trades"], 5)
        self.assertEqual(out["win_rate_pct"], 60.0)
        self.assertAlmostEqual(out["expectancy_r"], 0.5)
        self.assertAlmostEqual(out["profit_factor"], (100 + 100 + 25) / 100)
        self.assertEqual(out["max_consecutive_losses"], 2)
        self.assertEqual(out["avg_loss_r"], -1.0)

    def test_empty(self):
        out = swing.review({"trades": []}, RULES)
        self.assertIsNone(out["expectancy_r"])
        self.assertFalse(out["graduation"]["eligible"])

    def test_graduation_needs_all_criteria(self):
        ok = swing.review({"trades": trades([1, -1, 0.5] * 7), "start_date": "2026-10-01",
                           "as_of": "2026-11-19"}, RULES)
        self.assertTrue(ok["graduation"]["eligible"], ok["graduation"])
        few = swing.review({"trades": trades([1] * 19), "start_date": "2026-10-01", "as_of": "2026-11-19"}, RULES)
        self.assertFalse(few["graduation"]["criteria"]["closed_trades"]["pass"])
        short = swing.review({"trades": trades([1] * 25), "start_date": "2026-11-01", "as_of": "2026-11-19"}, RULES)
        self.assertFalse(short["graduation"]["criteria"]["weeks"]["pass"])
        sloppy = trades([1] * 18) + trades([1, 1], adherent=False)
        bad = swing.review({"trades": sloppy, "start_date": "2026-10-01", "as_of": "2026-11-19"}, RULES)
        self.assertFalse(bad["graduation"]["criteria"]["adherence_pct"]["pass"])
        neg = swing.review({"trades": trades([-1, 0.5] * 10), "start_date": "2026-10-01", "as_of": "2026-11-19"}, RULES)
        self.assertFalse(neg["graduation"]["criteria"]["expectancy_r"]["pass"])


class TestReconcile(unittest.TestCase):
    def test_matching_and_flags(self):
        out = swing.reconcile({
            "cards": [{"code": "c1", "ref_id": "r1", "symbol": "AAA", "side": "buy", "shares": 5},
                      {"code": "c2", "ref_id": "r2", "symbol": "BBB", "side": "buy", "shares": 3},
                      {"code": "c3", "symbol": "DDD", "side": "buy", "shares": 7}],
            "orders": {"data": {"results": [
                {"symbol": "AAA", "side": "buy", "quantity": "5", "state": "filled", "ref_id": "r1"},
                {"symbol": "CCC", "side": "buy", "quantity": "1", "state": "filled"},
                {"symbol": "DDD", "side": "buy", "quantity": "7.0", "state": "queued"}]}, "guide": ""},
            "advanced_orders": {"data": {"advanced_orders": [
                {"id": "a1", "contingency_type": "oco", "state": "active", "legs": [{"symbol": "AAA"}]}]}},
            "positions": [{"symbol": "AAA", "quantity": "5"}, {"symbol": "CCC", "quantity": "1"}],
        })
        types = {(f["type"], f.get("symbol")) for f in out["findings"]}
        self.assertIn(("MATCHED", "AAA"), types)
        self.assertIn(("MATCHED", "DDD"), types)  # matched by symbol/side/qty without ref_id
        self.assertIn(("NOT_FOUND_AT_BROKER", "BBB"), types)
        self.assertIn(("UNTRACKED_ORDER", "CCC"), types)
        self.assertEqual(out["unprotected"], ["CCC"])
        self.assertFalse(out["ok"])

    def test_clean(self):
        out = swing.reconcile({"cards": [], "orders": [], "advanced_orders": [], "positions": []})
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main()
