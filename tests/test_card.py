import unittest

from helpers import RULES, swing

CARD = {"kind": "ENTRY", "symbol": "AAA", "account_mask": "••1234", "mode": "live",
        "action": "BUY 10 AAA stop-limit 100.00 / 101.00", "atr": 2.0, "price_at_card": 99.5,
        "stop": 96.0, "target": 108.0, "shares": 10, "ref_id": "fixed-ref"}


def stage(state=None, now="2026-11-19T17:00:00", card=None):
    return swing.card({"state": state or {"pending_card": None, "last_code": None},
                       "now": now, "card": dict(card or CARD)}, RULES)


class TestCardCode(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(stage()["code"], stage()["code"])
        self.assertEqual(len(stage()["code"]), 8)

    def test_changes_with_contents_time_and_parent(self):
        base = stage()["code"]
        self.assertNotEqual(base, stage(card=dict(CARD, shares=11))["code"])
        self.assertNotEqual(base, stage(now="2026-11-19T17:00:01")["code"])
        self.assertNotEqual(base, stage(state={"pending_card": None, "last_code": "abcd1234"})["code"])

    def test_expires_end_of_day(self):
        self.assertEqual(stage()["staged"]["expires_at"], "2026-11-19T23:59:59")

    def test_one_pending_at_a_time(self):
        first = stage()
        with self.assertRaises(swing.SwingError):
            stage(state=first["new_state"], now="2026-11-19T17:10:00")

    def test_expired_pending_can_be_replaced(self):
        first = stage()
        second = stage(state=first["new_state"], now="2026-11-20T09:00:00")
        self.assertNotEqual(first["code"], second["code"])

    def test_move_stop_only_up(self):
        with self.assertRaises(swing.SwingError):
            stage(card=dict(CARD, kind="MOVE_STOP", old_stop=96.0, new_stop=95.0))
        ok = stage(card=dict(CARD, kind="MOVE_STOP", old_stop=96.0, new_stop=100.0))
        self.assertEqual(ok["staged"]["kind"], "MOVE_STOP")

    def test_markdown_contains_approval_line(self):
        out = stage()
        self.assertIn(f"APPROVE {out['code']}", out["markdown"])
        self.assertIn("verbatim", out["markdown"])

    def test_bad_kind(self):
        with self.assertRaises(swing.SwingError):
            stage(card=dict(CARD, kind="YOLO"))


class TestApprove(unittest.TestCase):
    def setUp(self):
        self.staged = stage()
        self.state = self.staged["new_state"]
        self.code = self.staged["code"]

    def approve(self, text, now="2026-11-19T17:05:00", **kw):
        return swing.approve(dict({"state": self.state, "text": text, "now": now}, **kw), RULES)

    def test_exact_code(self):
        out = self.approve(f"APPROVE {self.code}", current_price=99.8)
        self.assertTrue(out["approved"])
        self.assertIsNone(out["new_state"]["pending_card"])
        self.assertEqual(out["new_state"]["last_code"], self.code)
        self.assertEqual(out["card"]["ref_id"], "fixed-ref")

    def test_refusals(self):
        for text in ("approve all", "APPROVE", f"approve {self.code}", f"APPROVE {self.code} {self.code}",
                     "yes", "APPROVE ALL", "APPROVE deadbeef"):
            self.assertFalse(self.approve(text)["approved"], text)

    def test_expired(self):
        out = self.approve(f"APPROVE {self.code}", now="2026-11-20T09:31:00")
        self.assertFalse(out["approved"])
        self.assertIn("expired", out["reason"])

    def test_reprice(self):
        out = self.approve(f"APPROVE {self.code}", current_price=101.0)  # moved 1.5 > 0.5*2
        self.assertFalse(out["approved"])
        self.assertIn("new card", out["reason"])

    def test_stale_code_after_new_card(self):
        ok = self.approve(f"APPROVE {self.code}")
        nxt = stage(state=ok["new_state"], now="2026-11-19T17:30:00", card=dict(CARD, symbol="BBB"))
        stale = swing.approve({"state": nxt["new_state"], "text": f"APPROVE {self.code}",
                               "now": "2026-11-19T17:31:00"}, RULES)
        self.assertFalse(stale["approved"])
        self.assertEqual(nxt["staged"]["parent"], self.code)

    def test_reject(self):
        bad = swing.reject({"state": self.state, "text": "REJECT nope"}, RULES)
        self.assertFalse(bad["rejected"])
        good = swing.reject({"state": self.state, "text": f"REJECT {self.code}"}, RULES)
        self.assertTrue(good["rejected"])
        self.assertIsNone(good["new_state"]["pending_card"])


if __name__ == "__main__":
    unittest.main()
