import unittest

from helpers import RULES, swing


class TestSize(unittest.TestCase):
    def test_atr_stop_and_position_cap(self):
        s = swing.size(100.0, 2.0, 97.0, 10000.0, 10000.0, RULES)
        # dist = max(4.0, 100 - 96.03) = 4.0 ; risk $50 -> 12 sh ; 10% cap -> 10 sh
        self.assertEqual((s["stop"], s["target"], s["shares"]), (96.0, 108.0, 10))
        self.assertEqual(s["binding_cap"], "max_position")
        self.assertEqual(s["risk_dollars"], 40.0)

    def test_swing_low_wider_than_atr(self):
        s = swing.size(100.0, 1.0, 95.0, 100000.0, 100000.0, RULES)
        # dist = max(2.0, 100 - 94.05 = 5.95) -> stop 94.05
        self.assertEqual(s["stop"], 94.05)
        self.assertEqual(s["shares"], 84)  # floor(500 / 5.95)
        self.assertEqual(s["binding_cap"], "risk")

    def test_settled_cash_cap(self):
        s = swing.size(100.0, 2.0, 99.0, 100000.0, 250.0, RULES)
        self.assertEqual(s["shares"], 2)
        self.assertEqual(s["binding_cap"], "settled_cash")

    def test_cash_price_uses_limit(self):
        s = swing.size(100.0, 2.0, 99.0, 100000.0, 1000.0, RULES, cash_price=101.0)
        self.assertEqual(s["caps"]["settled_cash"], 9)

    def test_risk_multiplier_halves(self):
        full = swing.size(50.0, 1.0, 49.0, 100000.0, 100000.0, RULES)
        half = swing.size(50.0, 1.0, 49.0, 100000.0, 100000.0, RULES, risk_mult=0.5)
        self.assertEqual(half["caps"]["risk"], full["caps"]["risk"] // 2)

    def test_zero_shares_when_budget_too_small(self):
        s = swing.size(500.0, 20.0, 480.0, 1000.0, 1000.0, RULES)
        self.assertEqual(s["shares"], 0)

    def test_whole_shares_floor(self):
        s = swing.size(33.33, 1.11, 32.0, 10000.0, 10000.0, RULES)
        self.assertIsInstance(s["shares"], int)
        self.assertLessEqual(s["risk_dollars"], s["risk_allowed_dollars"])

    def test_invalid_inputs(self):
        with self.assertRaises(swing.SwingError):
            swing.size(0, 1, 1, 1000, 1000, RULES)
        with self.assertRaises(swing.SwingError):
            swing.size(5.0, 4.0, 4.0, 1000, 1000, RULES)  # stop <= 0


if __name__ == "__main__":
    unittest.main()
