import unittest

from helpers import RULES, swing

META = {"market_cap": 5e9}


class TestRegime(unittest.TestCase):
    def test_green(self):
        r = swing.regime(swing.synthetic_bars("uptrend"), RULES)
        self.assertEqual(r["state"], "GREEN")
        self.assertEqual(r["action"], "NEW_ENTRY_ALLOWED")
        self.assertEqual(r["limits"]["max_positions"], 6)

    def test_red(self):
        r = swing.regime(swing.synthetic_bars("downtrend"), RULES)
        self.assertEqual(r["state"], "RED")
        self.assertEqual(r["action"], "REDUCE_ONLY")
        self.assertEqual(r["limits"]["max_positions"], 0)

    def test_yellow_when_close_below_sma50(self):
        # the pullback dips below SMA50 while staying above SMA200
        r = swing.regime(swing.synthetic_bars("uptrend_pullback"), RULES)
        self.assertEqual(r["state"], "YELLOW")
        self.assertEqual(r["limits"]["risk_mult"], 0.5)

    def test_insufficient_data_fails_closed(self):
        r = swing.regime(swing.synthetic_bars("uptrend", 100), RULES)
        self.assertEqual(r["state"], "RED")
        self.assertIn("insufficient", r["reasons"][0])

    def test_vol_override_drops_one_level(self):
        bars = swing.synthetic_bars("uptrend")
        last = dict(bars[-1])
        prev_close = bars[-2]["close"]
        last["close"] = prev_close * 0.965  # -3.5% day
        last["low"] = last["close"] * 0.99
        bars[-1] = last
        r = swing.regime(bars, RULES)
        self.assertNotEqual(r["state"], "GREEN")
        self.assertTrue(any("volatility override" in x for x in r["reasons"]))


class TestSignal(unittest.TestCase):
    def test_pullback_setup_fires(self):
        s = swing.signal("TEST", swing.synthetic_bars("uptrend_pullback"), RULES, META)
        self.assertTrue(s["setup"], s["failed"])
        self.assertAlmostEqual(s["trigger"], round(swing.synthetic_bars("uptrend_pullback")[-1]["high"] + 0.01, 2))
        self.assertAlmostEqual(s["limit"], round(s["trigger"] + 0.5 * s["atr"], 2), places=2)
        self.assertEqual(s["order"]["type"], "buy_stop_limit")

    def test_no_setup_without_pullback(self):
        s = swing.signal("UP", swing.synthetic_bars("uptrend"), RULES, META)
        self.assertFalse(s["setup"])
        self.assertIn("rsi_pullback", s["failed"])

    def test_downtrend_fails_trend_template(self):
        s = swing.signal("DN", swing.synthetic_bars("downtrend"), RULES, META)
        self.assertFalse(s["setup"])
        self.assertIn("sma50_above_sma200", s["failed"])

    def test_missing_market_cap_fails(self):
        s = swing.signal("X", swing.synthetic_bars("uptrend_pullback"), RULES, {})
        self.assertIn("market_cap", s["failed"])

    def test_leveraged_etf_excluded(self):
        s = swing.signal("TQQQ", swing.synthetic_bars("uptrend_pullback"), RULES,
                         {"market_cap": 5e9, "leveraged_etf": True})
        self.assertIn("not_leveraged_etf", s["failed"])

    def test_low_price_and_volume(self):
        bars = swing.synthetic_bars("uptrend_pullback", base=2.0, volume=10_000)
        s = swing.signal("PENNY", bars, RULES, META)
        self.assertIn("price", s["failed"])
        self.assertIn("avg_volume_50", s["failed"])

    def test_short_history(self):
        s = swing.signal("NEW", swing.synthetic_bars("uptrend_pullback", 120), RULES, META)
        self.assertEqual(s["failed"], ["history"])

    def test_requires_close_above_prior_high(self):
        bars = swing.synthetic_bars("uptrend_pullback")
        last = dict(bars[-1])
        last["close"] = bars[-2]["high"] - 0.01
        bars[-1] = last
        s = swing.signal("T", bars, RULES, META)
        self.assertIn("close_above_prior_high", s["failed"])


if __name__ == "__main__":
    unittest.main()
