# Paper trading: the built-in simulator

Robinhood's agentic MCP has **no paper environment**, so the copilot simulates
one. It uses **real Robinhood daily bars**, but the orders exist only in the
journal's `paper/account.json`. Paper mode is the default and the required
first stage.

## Session flow in paper mode

1. **Preflight.** Load `paper/account.json` and read `last_stepped`.
2. **Catch up.** Collect daily bars from the day after `last_stepped` through
   the last completed session:
   - every symbol with an open paper position or order
   - at least 30 bars of history per symbol, so SMA20 exits work
   - fetched with `get_equity_historicals` in batches of 10

   Then run:
   ```
   swing.py paper step  --input step.json
   # step.json = {"account": <paper/account.json>, "bars": <raw RH payload or {SYM: bars}>}
   ```
   `step` processes **every missed trading day in order**, skipping weekends
   and NYSE holidays, and reports fills, exits, expired orders, and data gaps.
   Commit the new account.
3. **Rest of the session.** Run the normal EOD (regime, screen, signals,
   earnings, size, gate).
   - Use the **paper** account's equity and cash for sizing.
   - Use the paper history for the breaker.
4. **Approved ENTRY cards** go through `swing.py paper place` instead of
   `place_equity_order`. The order is a day order for the **next** trading
   session.
5. **No PROTECT or MOVE_STOP cards** are needed in paper mode. The simulator
   holds the stop and target, and applies the breakeven move and exits by
   rule. EXIT cards for discretionary exits are still allowed and must be
   logged as `rule_adherent: false`.

## Fill rules

**Entry (buy stop-limit):**

| Situation on the session bar | Result |
|---|---|
| open > limit | **no fill** (gapped over; we don't chase); the order expires |
| stop ≤ open ≤ limit | fill at the **open** |
| open < stop and high ≥ stop | fill at the **stop** |
| high < stop | no fill; the day order expires |
| no bar for that session (missed data) | expires as "no bar for session" |
| insufficient paper cash | rejected |

**Exits:**

| Situation | Result |
|---|---|
| open ≤ stop | stopped at the **open** (gap through; loss can exceed 1R) |
| low ≤ stop | stopped at the **stop** |
| open ≥ target | filled at the **open** |
| high ≥ target | filled at the **target** |
| stop and target both inside the same bar | **stop first** (conservative) |
| filled today and low ≤ stop the same day | stopped the same day (conservative) |
| high ≥ entry + 1R | stop moves to breakeven (entry) for the next bar |
| close < SMA20 and held ≥ 2 days | exit at the **next open** |
| held ≥ 15 trading days and never reached +1R | exit at the **next open** (time stop) |

- **Slippage:** 0.05% against you on every fill (buys up, sells down).
- **R multiple:** (exit − entry) / (entry − initial stop), with the entry
  after slippage.
- Each closed trade records MFE and MAE in R, for the monthly review.

## Graduation to live (from rules.json)

All four must hold. Check them with `swing.py review` using
`start_date = settings.paper_start_date`:

| Criterion | Need |
|---|---|
| Time in paper | ≥ 4 weeks |
| Closed trades | ≥ 20 |
| Expectancy | > 0 R |
| Rule adherence | ≥ 95% |

- **Realistic timeline:** with 3 positions and strict filters, 20 closed
  trades usually takes **3-5 months**, not 4 weeks.
- **Do not loosen rules to get more trades.** That defeats the test.
- **Going live is the user's decision,** made at a monthly review. They set
  `mode: "live"` themselves.
- **Live starts small:** 0.5% risk and 3 positions for 10 weeks before
  considering 1% and 6 (see `rules.json` rollout).

## Limits of the simulation

- Daily bars only, so the intraday order of events is unknown. That's why the
  stop always counts first.
- It does not model partial fills, halts, or liquidity at the open.
- No dividends or corporate actions. Avoid holding through splits.
- The latest bar may not be official until after the close. Step only
  completed sessions (after about 4:15 PM ET).
