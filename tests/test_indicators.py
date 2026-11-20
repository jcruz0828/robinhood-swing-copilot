import unittest

from helpers import RULES, bar, fixture, swing


class TestSMA(unittest.TestCase):
    def test_values_and_warmup(self):
        out = swing.sma([1, 2, 3, 4, 5, 6], 3)
        self.assertEqual(out[:2], [None, None])
        self.assertEqual(out[2:], [2.0, 3.0, 4.0, 5.0])


class TestRSI(unittest.TestCase):
    def test_all_gains_is_100(self):
        self.assertEqual(swing.rsi([float(i) for i in range(30)], 14)[-1], 100.0)

    def test_all_losses_is_0(self):
        self.assertAlmostEqual(swing.rsi([float(30 - i) for i in range(30)], 14)[-1], 0.0)

    def test_warmup_is_none(self):
        r = swing.rsi([float(i) for i in range(20)], 14)
        self.assertTrue(all(x is None for x in r[:14]))
        self.assertIsNotNone(r[14])

    def test_wilder_smoothing_hand_computed(self):
        # 14 alternating changes of +1 / -1 -> ag = al = 0.5 -> RSI 50.
        closes = [10.0]
        for i in range(14):
            closes.append(closes[-1] + (1 if i % 2 == 0 else -1))
        r = swing.rsi(closes, 14)
        self.assertAlmostEqual(r[14], 50.0)
        # One more +2 change: ag = (0.5*13 + 2)/14, al = 0.5*13/14.
        closes.append(closes[-1] + 2)
        ag, al = (0.5 * 13 + 2) / 14, (0.5 * 13) / 14
        self.assertAlmostEqual(swing.rsi(closes, 14)[15], 100 - 100 / (1 + ag / al))

    def test_flat_is_50(self):
        self.assertEqual(swing.rsi([5.0] * 20, 14)[-1], 50.0)


class TestATR(unittest.TestCase):
    def test_constant_range(self):
        a = swing.atr([11.0] * 20, [9.0] * 20, [10.0] * 20, 14)
        self.assertAlmostEqual(a[-1], 2.0)

    def test_true_range_uses_gap(self):
        # gap up: prev close 10, today low 12 high 13 -> TR = 13 - 10 = 3
        tr = swing.true_ranges([10.5, 13.0], [9.5, 12.0], [10.0, 12.5])
        self.assertEqual(tr[1], 3.0)

    def test_wilder_update(self):
        h, l, c = [11.0] * 15, [9.0] * 15, [10.0] * 15
        h.append(14.0); l.append(10.0); c.append(13.0)  # TR = 4
        a = swing.atr(h, l, c, 14)
        self.assertAlmostEqual(a[15], (2.0 * 13 + 4.0) / 14)


class TestBollingerAndCorrelation(unittest.TestCase):
    def test_bollinger_flat(self):
        b = swing.bollinger([10.0] * 20)[-1]
        self.assertEqual((b["lower"], b["mid"], b["upper"]), (10.0, 10.0, 10.0))

    def test_correlation_identical_is_one(self):
        bars = swing.synthetic_bars("uptrend", 100)
        self.assertAlmostEqual(swing.correlation(bars, bars, 60), 1.0)

    def test_correlation_inverse(self):
        a = swing.synthetic_bars("uptrend", 100)
        b = swing.synthetic_bars("downtrend", 100)
        self.assertLess(swing.correlation(a, b, 60), -0.9)

    def test_correlation_insufficient(self):
        a = swing.synthetic_bars("uptrend", 10)
        self.assertIsNone(swing.correlation(a, a, 60))


class TestUnwrap(unittest.TestCase):
    def test_robinhood_shape(self):
        out = swing.unwrap(fixture("rh_historicals_spy.json"))
        self.assertEqual(sorted(out), ["QQQ", "SPY"])
        spy = out["SPY"]
        self.assertEqual([b["date"] for b in spy], ["2026-11-16", "2026-11-17", "2026-11-18"])
        self.assertEqual(spy[1]["close"], 737.0)  # duplicate date keeps the last
        self.assertIsInstance(spy[0]["open"], float)  # strings converted
        self.assertEqual(len(out["QQQ"]), 1)  # bar with null open dropped

    def test_plain_symbol_map_passthrough(self):
        bars = {"aapl": [bar("2026-11-18", 1, 2, 0.5, 1.5)]}
        self.assertEqual(list(swing._bars_from_input(bars)), ["AAPL"])

    def test_bad_payload(self):
        with self.assertRaises(swing.SwingError):
            swing.unwrap({"data": {"nothing": 1}})

    def test_unwrap_data_keeps_non_envelopes(self):
        self.assertEqual(swing.unwrap_data({"data": [1], "guide": "x"}), [1])
        self.assertEqual(swing.unwrap_data({"data": [1], "other": 2}), {"data": [1], "other": 2})


class TestCrossCheck(unittest.TestCase):
    def test_flags_out_of_tolerance(self):
        ours = {"rsi": 40.0, "sma50": 100.0, "atr": 2.0}
        issues = swing.cross_check(ours, {"rsi": "43", "sma50": "100.2", "atr": 2.5}, RULES)
        fields = {i["field"] for i in issues}
        self.assertEqual(fields, {"rsi", "atr"})


class TestCalendar(unittest.TestCase):
    def test_holidays(self):
        for d in ("2026-11-26", "2026-12-25", "2027-03-26", "2026-07-03"):
            self.assertFalse(swing.is_trading_day(d), d)
        self.assertTrue(swing.is_trading_day("2026-11-27"))

    def test_between_and_next(self):
        self.assertEqual(swing.trading_days_between("2026-11-25", "2026-11-30"), 2)
        self.assertEqual(swing.trading_days_between("2026-11-30", "2026-11-25"), -2)
        self.assertEqual(str(swing.next_trading_day("2026-11-25")), "2026-11-27")
        self.assertEqual(str(swing.prev_trading_day("2026-11-30")), "2026-11-27")

    def test_parse_dt_converts_utc(self):
        dt = swing.parse_dt("2026-11-19T21:00:00Z")
        self.assertEqual((dt.hour, dt.tzinfo), (16, None))


if __name__ == "__main__":
    unittest.main()
