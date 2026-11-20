import unittest

from helpers import RULES, bar, swing

SLIP = RULES["paper"]["slippage_pct"]
ORDER = {"symbol": "X", "shares": 10, "stop_price": 101.0, "limit_price": 102.0,
         "stop_loss": 97.0, "target": 109.0, "created": "2026-11-18", "card_code": "abcd1234"}


def account_with_order(**kw):
    acct = swing.paper_init(10000, "2026-11-18")
    return swing.paper_place(acct, dict(ORDER, **kw))


def step(acct, bars, through=None):
    return swing.paper_step(acct, {"X": bars}, RULES, through)


def buy(px):
    return swing._slip(px, "buy", SLIP)


def sell(px):
    return swing._slip(px, "sell", SLIP)


class TestEntryFills(unittest.TestCase):
    def test_fill_at_stop(self):
        out = step(account_with_order(), [bar("2026-11-19", 100, 101.5, 99.5, 101.2)])
        pos = out["account"]["positions"][0]
        self.assertEqual(pos["entry_price"], buy(101.0))
        self.assertEqual(out["account"]["cash"], round(10000 - buy(101.0) * 10, 4))

    def test_fill_at_open_between_stop_and_limit(self):
        out = step(account_with_order(), [bar("2026-11-19", 101.5, 103, 101.2, 102.5)])
        self.assertEqual(out["account"]["positions"][0]["entry_price"], buy(101.5))

    def test_no_fill_on_gap_over_limit(self):
        out = step(account_with_order(), [bar("2026-11-19", 102.5, 104, 102.2, 103)])
        self.assertEqual(out["account"]["positions"], [])
        self.assertEqual(out["account"]["orders"], [])
        self.assertIn("gapped over limit", out["events"][0]["reason"])

    def test_day_order_expires_if_not_triggered(self):
        out = step(account_with_order(), [bar("2026-11-19", 100, 100.9, 99, 100.5)])
        self.assertEqual(out["account"]["orders"], [])
        self.assertEqual(out["events"][0]["reason"], "trigger not reached")

    def test_same_day_stop_after_fill(self):
        out = step(account_with_order(), [bar("2026-11-19", 100, 101.5, 96.5, 97.2)])
        hist = out["account"]["history"][0]
        self.assertEqual(hist["reason"], "stop_same_day")
        self.assertEqual(hist["exit"], sell(97.0))

    def test_insufficient_cash(self):
        acct = account_with_order(shares=200)
        out = step(acct, [bar("2026-11-19", 100, 101.5, 99.5, 101.2)])
        self.assertEqual(out["events"][0]["event"], "order_rejected")

    def test_missed_session_expires(self):
        out = step(account_with_order(), [bar("2026-11-20", 100, 101.5, 99.5, 101.2)])
        self.assertEqual(out["account"]["positions"], [])
        self.assertTrue(any(e.get("reason") == "no bar for session" for e in out["events"]))


class TestExits(unittest.TestCase):
    def filled(self):
        return step(account_with_order(), [bar("2026-11-19", 100, 101.5, 99.5, 101.2)])["account"]

    def test_gap_through_stop_fills_at_open(self):
        out = step(self.filled(), [bar("2026-11-20", 96, 96.5, 95, 95.5)])
        h = out["account"]["history"][0]
        self.assertEqual((h["reason"], h["exit"]), ("stop_gap", sell(96)))
        self.assertLess(h["r_multiple"], -1.0)

    def test_stop_before_target_same_bar(self):
        out = step(self.filled(), [bar("2026-11-20", 101, 110, 96.9, 105)])
        self.assertEqual(out["account"]["history"][0]["reason"], "stop")

    def test_target(self):
        out = step(self.filled(), [bar("2026-11-20", 101, 109.5, 100.5, 109.2)])
        h = out["account"]["history"][0]
        self.assertEqual((h["reason"], h["exit"]), ("target", sell(109.0)))
        self.assertAlmostEqual(h["r_multiple"], (sell(109.0) - buy(101.0)) / (buy(101.0) - 97.0), places=3)

    def test_target_gap_fills_at_open(self):
        out = step(self.filled(), [bar("2026-11-20", 111, 112, 110, 111)])
        self.assertEqual(out["account"]["history"][0]["exit"], sell(111))

    def test_breakeven_move_then_exit(self):
        acct = self.filled()
        entry = acct["positions"][0]["entry_price"]
        one_r = entry + (entry - 97.0)
        out = step(acct, [bar("2026-11-20", 101.5, one_r + 0.1, 101, 104),
                          bar("2026-11-23", 103, 103.5, entry - 1, 100)])
        evs = [e["event"] for e in out["events"]]
        self.assertIn("stop_to_breakeven", evs)
        h = out["account"]["history"][0]
        self.assertEqual(h["reason"], "stop")  # stop at entry rounded is below the slipped entry
        self.assertAlmostEqual(h["r_multiple"], 0.0, delta=0.05)

    def test_time_stop(self):
        history = [bar(str(d), 101.2, 101.2, 101.2, 101.2) for d in swing.trading_dates("2026-10-15", 25)
                   if str(d) < "2026-11-19"]
        days = swing.trading_dates("2026-11-19", 18)
        bars = history + [bar(str(days[0]), 100, 101.5, 99.5, 101.3)] + \
            [bar(str(d), 101.3, 101.4, 101.2, 101.3) for d in days[1:]]
        out = step(account_with_order(), bars)
        h = out["account"]["history"][0]
        self.assertEqual(h["reason"], "time_stop")
        self.assertEqual(swing.trading_days_between("2026-11-19", h["exit_date"]), 16)

    def test_sma20_exit_next_open(self):
        history = [bar(str(d), 101, 101.5, 100.5, 101.0) for d in swing.trading_dates("2026-10-15", 30)
                   if str(d) < "2026-11-19"]
        bars = history + [bar("2026-11-19", 100, 101.5, 99.5, 101.3),
                          bar("2026-11-20", 101.3, 101.6, 101.0, 101.4),
                          bar("2026-11-23", 101.2, 101.3, 99.0, 99.5),   # held 2 days, close < SMA20
                          bar("2026-11-24", 99.8, 100.0, 99.0, 99.4)]
        out = step(account_with_order(), bars)
        h = out["account"]["history"][0]
        self.assertEqual((h["reason"], h["exit_date"], h["exit"]), ("sma20_close", "2026-11-24", sell(99.8)))


class TestCatchUpAndAccounting(unittest.TestCase):
    def test_catch_up_processes_every_missed_day(self):
        bars = [bar("2026-11-19", 100, 101.5, 99.5, 101.2), bar("2026-11-20", 101, 102, 100.5, 101.5),
                bar("2026-11-23", 101.5, 102, 101, 101.8), bar("2026-11-24", 101.8, 102.2, 101.4, 102)]
        out = step(account_with_order(), bars)
        self.assertEqual(out["days_processed"], ["2026-11-19", "2026-11-20", "2026-11-23", "2026-11-24"])
        acct = out["account"]
        self.assertEqual(acct["last_stepped"], "2026-11-24")
        self.assertAlmostEqual(acct["equity"], round(acct["cash"] + 10 * 102, 2))
        self.assertEqual(len(acct["equity_curve"]), 5)

    def test_skips_holidays(self):
        acct = swing.paper_init(10000, "2026-11-25")
        out = swing.paper_step(acct, {"X": [bar("2026-11-27", 1, 1, 1, 1)]}, RULES)
        self.assertEqual(out["days_processed"], ["2026-11-27"])

    def test_idempotent_when_up_to_date(self):
        acct = swing.paper_init(10000, "2026-11-19")
        out = swing.paper_step(acct, {"X": [bar("2026-11-19", 1, 1, 1, 1)]}, RULES)
        self.assertEqual(out["days_processed"], [])

    def test_place_validation(self):
        acct = swing.paper_init(10000, "2026-11-18")
        with self.assertRaises(swing.SwingError):
            swing.paper_place(acct, dict(ORDER, stop_loss=101.5))
        with self.assertRaises(swing.SwingError):
            swing.paper_place(acct, dict(ORDER, shares=0))
        with self.assertRaises(swing.SwingError):
            swing.paper_place(swing.paper_place(acct, ORDER), ORDER)  # duplicate symbol


if __name__ == "__main__":
    unittest.main()
