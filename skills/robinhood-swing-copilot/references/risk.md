# Risk: sizing, portfolio limits and circuit breakers

Everything on this page is enforced in code (`swing.py size`, `gate`,
`breaker`). The agent's job is to feed those commands correct inputs and obey
their output. It never second-guesses or overrides them.

## Position sizing (`swing.py size`)

```
risk_dollars_allowed = equity × risk_pct/100 × regime.risk_mult × breaker.risk_mult
stop_distance        = max(2 × ATR, entry − 5-day low × 0.99)
stop                 = round(entry − stop_distance, 2)
target               = entry + 2 × (entry − stop)
shares = floor(min( risk_dollars_allowed / (entry − stop),
                    equity × 10% / cash_price,
                    settled_cash / cash_price ))
```

- `cash_price` is the stop-limit's **limit** price, the worst-case fill.
- **Whole shares only.** Fractional shares are untested with the agent API.
- If `shares` is 0, the trade is skipped; never round up.
- `binding_cap` in the output says which limit decided the size.

**Worked example** ($10,000 equity, 0.5% risk, YELLOW regime so risk × 0.5):
- The allowed risk is $25.
- Entry 219.73 and ATR 5.03 give a stop distance of max(10.06, …) = 10.22,
  so the stop is 209.51.
- floor(25 / 10.22) = 2 shares, with $20.44 at risk.

## Portfolio limits (`swing.py gate`)

| Limit | Value |
|---|---|
| Max positions | min(regime limit, settings.max_positions) |
| Total open risk ("heat"), at stops | ≤ regime max_heat_pct (6% GREEN, 3% YELLOW) |
| Single position | ≤ 10% of equity |
| Sector | ≤ 30% of equity and ≤ 2 names |
| Gross exposure | ≤ 80% of equity |
| Correlation with any holding | ≤ 0.8 (60-day daily returns) |
| Re-entry after a loss in the same symbol | wait 10 trading days |
| Revenge window | no new entry within 24 h of any losing exit |
| No averaging down / pyramiding | already holding the symbol = NO_GO |

- A holding whose stop is unknown counts as **unbounded risk**, which forces
  NO_GO until it is protected.
- Positions at breakeven (stop ≥ entry) count as zero risk.

## Circuit breakers (`swing.py breaker`)

They are measured on **realized** P&L as a percent of account size (US/Eastern
calendar), matching tradermonty's drawdown-circuit-breaker:

| Rule | Trigger | Result | Lifts |
|---|---|---|---|
| Daily | realized today ≤ −2% | HALTED | next trading day 09:30 |
| Weekly | realized since Monday ≤ −5% | HALTED | next Monday's open |
| Monthly | realized since the 1st ≤ −8% | HALTED | first trading day of next month |
| Losing streak | 2 consecutive losing exits | COOLDOWN for 24 h after the last loss, then risk × 0.5 until a non-losing trade | automatic |
| Peak drawdown | equity ≥ 15% below peak | HALTED, **sticky** | only when the user types `CLEAR HALT <code>` |
| HALT file | `HALT` exists in the journal | HALTED | the user deletes HALT |
| Bad data | missing or unparseable state | HALTED | fix the state |

- A breakeven (P&L = 0) or winning trade resets the streak.
- `HALTED` and `COOLDOWN` both mean **no new entries**. Protective work
  (PROTECT, MOVE_STOP up, EXIT) is always allowed.
- **Clearing the peak lock:** run `swing.py clear-halt` with the user's exact
  text. It resets `peak_equity` to current equity. Suggest half risk for the
  next 5 trades.

## Events

- **Earnings:** no entry if the next report is within 2 trading days, or the
  date is unknown.
- **Macro:** no entries on dates listed in `settings.macro_event_dates` (FOMC
  decisions, CPI). The user keeps that list current from the official Fed and
  BLS calendars; the agent never guesses dates.

## Gap risk (read this)

- Stops are stop-market orders, so they fill on gaps, but **at the gap price**.
  An overnight gap can turn a 1R planned loss into 2-3R.
- The paper simulator models this: a gapped stop fills at the open.
- The only mitigation is small size and the earnings block. There is no way to
  stop-loss through a gap.

## Account mechanics

- **Cash accounts:** T+1 settlement. Selling a position bought with unsettled
  proceeds before they settle is a good-faith violation (GFV). The copilot
  sizes from **settled cash** only and treats any GFV as a hard block.
- **PDT:** FINRA replaced the $25k pattern-day-trader rule effective
  2026-06-04, with broker phase-in through 2027-10-20. This is a swing system
  (multi-day holds), so day-trade counts should rarely matter.
