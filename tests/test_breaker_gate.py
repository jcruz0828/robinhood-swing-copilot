import copy
import unittest

from helpers import RULES, swing


def brk(**kw):
    base = {"as_of": "2026-11-19T17:00:00", "equity": 10000.0, "peak_equity": 10000.0,
            "account_size": 10000.0, "closed_trades": []}
    base.update(kw)
    return swing.breaker(base, RULES)


class TestBreaker(unittest.TestCase):
    def test_clean_allows(self):
        b = brk()
        self.assertEqual(b["recommendation"], "TRADING_ALLOWED")
        self.assertEqual(b["risk_mult"], 1.0)

    def test_daily_threshold_boundary(self):
        just_under = brk(closed_trades=[{"exit_time": "2026-11-19T11:00:00", "pnl": -199}])
        at = brk(closed_trades=[{"exit_time": "2026-11-19T11:00:00", "pnl": -200}])
        self.assertEqual(just_under["recommendation"], "TRADING_ALLOWED")
        self.assertEqual(at["recommendation"], "HALTED")
        self.assertEqual(at["triggered_rules"][0]["active_until"], "2026-11-20T09:30:00")

    def test_weekly(self):
        # Mon 16th -300 and Tue 17th -250: week -5.5%; streak cooldown long expired
        b = brk(closed_trades=[{"exit_time": "2026-11-16T11:00:00", "pnl": -300},
                               {"exit_time": "2026-11-17T11:00:00", "pnl": -250},
                               {"exit_time": "2026-11-18T11:00:00", "pnl": 10}])
        rules = {r["rule"] for r in b["triggered_rules"]}
        self.assertEqual(rules, {"weekly_loss"})
        self.assertEqual(b["triggered_rules"][0]["active_until"], "2026-11-23T09:30:00")

    def test_monthly(self):
        trades = [{"exit_time": f"2026-11-{d:02d}T11:00:00", "pnl": -200} for d in (3, 5)] + \
                 [{"exit_time": "2026-11-09T11:00:00", "pnl": 10},
                  {"exit_time": "2026-11-10T11:00:00", "pnl": -450},
                  {"exit_time": "2026-11-12T11:00:00", "pnl": 5}]
        b = brk(closed_trades=trades)
        self.assertIn("monthly_loss", {r["rule"] for r in b["triggered_rules"]})
        self.assertEqual(b["recommendation"], "HALTED")

    def test_losing_streak_cooldown_then_half_risk(self):
        trades = [{"exit_time": "2026-11-18T10:00:00", "pnl": -40},
                  {"exit_time": "2026-11-18T15:00:00", "pnl": -40}]
        during = brk(closed_trades=trades, as_of="2026-11-19T09:00:00")
        after = brk(closed_trades=trades, as_of="2026-11-19T16:00:00")
        self.assertEqual(during["recommendation"], "COOLDOWN")
        self.assertEqual(after["recommendation"], "TRADING_ALLOWED")
        self.assertEqual(after["risk_mult"], 0.5)

    def test_breakeven_resets_streak(self):
        b = brk(closed_trades=[{"exit_time": "2026-11-18T10:00:00", "pnl": -40},
                               {"exit_time": "2026-11-18T12:00:00", "pnl": 0},
                               {"exit_time": "2026-11-18T15:00:00", "pnl": -40}])
        self.assertEqual(b["metrics"]["consecutive_losses"], 1)

    def test_peak_lock_sticky_and_clear(self):
        b = brk(equity=8400.0, peak_equity=10000.0)
        self.assertEqual(b["recommendation"], "HALTED")
        state = b["new_state"]
        self.assertTrue(state["peak_lock"])
        # still locked after recovery
        again = brk(equity=9500.0, peak_equity=10000.0, peak_lock=True, peak_lock_since=state["peak_lock_since"])
        self.assertEqual(again["recommendation"], "HALTED")
        detail = [r for r in again["triggered_rules"] if r["rule"] == "peak_drawdown_lock"][0]["detail"]
        code = detail.split()[-1]
        wrong = swing.clear_halt({"state": state, "text": "CLEAR HALT nope", "equity": 9500})
        self.assertFalse(wrong["cleared"])
        ok = swing.clear_halt({"state": state, "text": f"CLEAR HALT {code}", "equity": 9500})
        self.assertTrue(ok["cleared"])
        self.assertEqual(ok["new_state"]["peak_equity"], 9500.0)

    def test_halt_file(self):
        self.assertEqual(brk(halt_file=True)["recommendation"], "HALTED")

    def test_missing_and_malformed_fail_closed(self):
        self.assertEqual(swing.breaker({"as_of": "2026-11-19"}, RULES)["recommendation"], "HALTED")
        bad = brk(closed_trades=[{"exit_time": "not-a-date", "pnl": 1}])
        self.assertEqual(bad["recommendation"], "HALTED")


BASE_GATE = {
    "as_of": "2026-11-19T17:00:00",
    "mode": "live",
    "approvals_setting": "on",
    "settings": {"max_positions": 3, "risk_pct": 0.5},
    "breaker": {"recommendation": "TRADING_ALLOWED", "risk_mult": 1.0},
    "regime": {"state": "GREEN", "limits": RULES["regime"]["states"]["GREEN"]},
    "portfolio": {"equity": 10000.0, "settled_cash": 10000.0, "positions": []},
    "recent_losses": [],
    "candidates": [{
        "symbol": "AAA", "sector": "Technology", "entry": 100.0, "trigger": 100.0, "stop": 96.0,
        "target": 108.0, "shares": 10, "atr": 2.0, "earnings_date": "2026-12-15",
        "in_written_plan": True, "signal_setup": True, "tradable": True,
    }],
}


def run_gate(mutate=None):
    g = copy.deepcopy(BASE_GATE)
    if mutate:
        mutate(g)
    return swing.gate(g, RULES)


class TestGate(unittest.TestCase):
    def assertNoGo(self, out, fragment):
        self.assertEqual(out["overall_decision"], "NO_GO", out)
        reasons = " | ".join(out["general_reasons"] + [r for c in out["candidate_results"] for r in c["reasons"]])
        self.assertIn(fragment, reasons)

    def test_clean_go(self):
        out = run_gate()
        self.assertEqual(out["overall_decision"], "GO", out)

    def test_missing_input_is_no_go(self):
        out = run_gate(lambda g: g.pop("breaker"))
        self.assertNoGo(out, "missing input: breaker")

    def test_approvals_off(self):
        self.assertNoGo(run_gate(lambda g: g.update(approvals_setting="off")), "approvals are OFF")

    def test_approvals_off_with_chat_only_consent(self):
        out = run_gate(lambda g: g.update(approvals_setting="off", chat_only_consent=True))
        self.assertEqual(out["overall_decision"], "GO")

    def test_approvals_unchecked(self):
        self.assertNoGo(run_gate(lambda g: g.pop("approvals_setting")), "not checked")

    def test_paper_mode_ignores_approvals(self):
        out = run_gate(lambda g: (g.update(mode="paper"), g.pop("approvals_setting")))
        self.assertEqual(out["overall_decision"], "GO")

    def test_breaker_and_regime(self):
        self.assertNoGo(run_gate(lambda g: g["breaker"].update(recommendation="COOLDOWN")), "breaker is COOLDOWN")
        self.assertNoGo(run_gate(lambda g: g.update(regime={"state": "RED"})), "REDUCE_ONLY")

    def test_halt_file(self):
        self.assertNoGo(run_gate(lambda g: g.update(halt_file=True)), "HALT")

    def test_earnings_within_buffer_and_unknown(self):
        self.assertNoGo(run_gate(lambda g: g["candidates"][0].update(earnings_date="2026-11-23")), "earnings")
        self.assertNoGo(run_gate(lambda g: g["candidates"][0].update(earnings_date=None)), "unknown")
        ok = run_gate(lambda g: g["candidates"][0].update(earnings_date="2026-11-25"))  # 4 trading days
        self.assertEqual(ok["overall_decision"], "GO")

    def test_gap_above_trigger_do_not_chase(self):
        self.assertNoGo(run_gate(lambda g: g["candidates"][0].update(live_price=102.5)), "do not chase")

    def test_rr_at_live_price(self):
        out = run_gate(lambda g: g["candidates"][0].update(live_price=101.5, atr=5.0))
        self.assertNoGo(out, "reward/risk")

    def test_too_much_risk(self):
        self.assertNoGo(run_gate(lambda g: g["candidates"][0].update(shares=20)), "risk $")

    def test_position_limit_and_holding(self):
        def full(g):
            g["portfolio"]["positions"] = [
                {"symbol": s, "sector": f"S{i}", "entry": 50, "stop": 50, "shares": 1, "market_value": 50}
                for i, s in enumerate(["X", "Y", "Z"])]
            g["candidates"][0]["max_correlation"] = 0.1
        self.assertNoGo(run_gate(full), "position count")

    def test_sector_names_cap(self):
        def two_tech(g):
            g["portfolio"]["positions"] = [
                {"symbol": s, "sector": "Technology", "entry": 50, "stop": 50, "shares": 1, "market_value": 50}
                for s in ("X", "Y")]
            g["candidates"][0]["max_correlation"] = 0.1
        self.assertNoGo(run_gate(two_tech), "names in Technology")

    def test_heat_cap(self):
        def hot(g):
            g["portfolio"]["positions"] = [{"symbol": "X", "sector": "Energy", "entry": 100, "stop": 50,
                                            "shares": 12, "market_value": 1200}]  # $600 + $40 = 6.4%
            g["candidates"][0]["max_correlation"] = 0.1
        self.assertNoGo(run_gate(hot), "portfolio heat")

    def test_unknown_stop_counts_as_unbounded_risk(self):
        def unprotected(g):
            g["portfolio"]["positions"] = [{"symbol": "X", "sector": "Energy", "entry": 100, "stop": None,
                                            "shares": 1, "market_value": 100}]
            g["candidates"][0]["max_correlation"] = 0.1
        self.assertNoGo(run_gate(unprotected), "portfolio heat")

    def test_correlation(self):
        def corr(g):
            g["portfolio"]["positions"] = [{"symbol": "X", "sector": "Energy", "entry": 50, "stop": 50,
                                            "shares": 1, "market_value": 50}]
            g["candidates"][0]["max_correlation"] = 0.85
        self.assertNoGo(run_gate(corr), "correlation 0.85")

    def test_correlation_missing_is_review(self):
        def nocorr(g):
            g["portfolio"]["positions"] = [{"symbol": "X", "sector": "Energy", "entry": 50, "stop": 50,
                                            "shares": 1, "market_value": 50}]
        self.assertEqual(run_gate(nocorr)["overall_decision"], "REVIEW_REQUIRED")

    def test_reentry_cooldown_and_revenge(self):
        old = run_gate(lambda g: g.update(recent_losses=[{"symbol": "AAA", "exit_time": "2026-11-12T11:00:00"}]))
        self.assertNoGo(old, "re-entry cooldown")
        recent = run_gate(lambda g: g.update(recent_losses=[{"symbol": "ZZZ", "exit_time": "2026-11-19T10:00:00"}]))
        self.assertNoGo(recent, "revenge window")

    def test_not_in_plan_and_first_minutes(self):
        self.assertNoGo(run_gate(lambda g: g["candidates"][0].update(in_written_plan=False)), "written plan")
        self.assertNoGo(run_gate(lambda g: g.update(minutes_since_open=5)), "first 15 minutes")

    def test_veto_reasons_block(self):
        out = run_gate(lambda g: g["candidates"][0].update(veto_reasons=["pending merger vote (source: 8-K)"]))
        self.assertNoGo(out, "veto: pending merger")

    def test_macro_event(self):
        self.assertNoGo(run_gate(lambda g: g.update(macro_event_today="FOMC")), "macro event")

    def test_second_candidate_counts_first(self):
        def two(g):
            c2 = dict(g["candidates"][0], symbol="BBB", max_correlation=0.1)
            g["candidates"][0]["max_correlation"] = 0.1
            g["candidates"].append(c2)
            g["settings"]["max_positions"] = 1
        out = run_gate(two)
        decisions = [c["decision"] for c in out["candidate_results"]]
        self.assertEqual(decisions, ["GO", "NO_GO"])


if __name__ == "__main__":
    unittest.main()
