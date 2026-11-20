# Strategy: trend pullback, rules-first

**What it is:** buy a liquid, large-cap stock that is in an established
uptrend, after a short pullback, on the first day it turns back up. Get out
quickly if it fails, take profit at 2R, and cut trades that stall.

**What it is not:** a forecast, a signal service, or a proven edge. One public
backtest of a similar system (Vipuld14/LIVE-swing-trading-agent) lagged
buy-and-hold in 2009-2017, with lower drawdowns. Treat every threshold as a
hypothesis to test in paper mode first.

All numbers live in `config/rules.json`. This page explains them.

## 1. Market regime (SPY), via `swing.py regime`

| State | Condition | Max positions | Risk × | Max heat |
|---|---|---|---|---|
| GREEN | close > SMA200 **and** SMA50 > SMA200 **and** SMA50 rising **and** close > SMA50 | 6 | 1.0 | 6% |
| YELLOW | close > SMA200 but not GREEN (SMA50 flat/falling, or close ≤ SMA50) | 3 | 0.5 | 3% |
| RED | close ≤ SMA200 | 0 (REDUCE_ONLY) | 0 | 0% |

- "SMA50 rising" means SMA50 today is greater than SMA50 10 bars ago.
- **Volatility override:** if ATR(14)/close is above 2.5%, or SPY fell 3% or
  more today, drop one level (GREEN→YELLOW, YELLOW→RED).
- **Insufficient data** (fewer than 211 bars) counts as RED, so the check
  fails closed.
- `settings.max_positions` caps this further. During rollout it is 3.

## 2. Universe screen

All of these must hold:
- price ≥ $10
- 50-day average volume ≥ 1M shares
- market cap ≥ $2B
- tradable
- not a leveraged or inverse ETF
- ATR/price between 1% and 8%
- at least 250 daily bars (the warm-up for the indicators)

## 3. Entry, via `swing.py signal`

All of these must be true on today's daily close:
1. SMA50 > SMA200
2. close > SMA200
3. SMA50 rising (vs 10 bars ago)
4. **Pullback:** the lowest RSI(14) of the last 5 sessions is ≤ 45
5. **Turn:** RSI today > RSI yesterday
6. **Trigger:** close > the prior day's high

**Order for the next session:** a buy **stop-limit**, day order.
- `stop_price` = today's high + $0.01
- `limit_price` = stop + 0.5×ATR

If the stock gaps over the limit, it doesn't fill, which is intended: we
don't chase. At the open, skip it if the price is more than 2% or 1×ATR above
the trigger, or if reward:risk at the live price is below 1.5.

## 4. Exits (fixed-target model, chosen 2026-11-19)

- **Initial stop:** entry − max(2×ATR, entry − 5-day low × 0.99). It is placed
  as a stop-**market** leg of Robinhood's exit pair (`place_advanced_order`)
  right after the fill.
- **Target:** 2R, the take-profit **limit** leg of the same exit pair.
- **Breakeven:** when the high reaches entry + 1R, move the stop to the entry
  price (one MOVE_STOP card, cancel/replace).
- **Trend failure:** a close below SMA20 after at least 2 days held means exit
  at the next open.
- **Time stop:** 15 trading days without ever reaching +1R means exit at the
  next open.
- **No trailing/chandelier stop in v1.** With a 2R take-profit in place, a
  trail that starts at +2R could never act, and the one backtest we found
  favored fixed targets.

## 5. Indicator definitions (`swing.py`)

- **SMA(n):** the simple mean of the last n closes.
- **RSI(14):** Wilder. The first value uses simple averages of the first 14
  changes; after that, `avg = (avg×13 + x)/14`.
- **ATR(14):** Wilder smoothing of true range, `max(H−L, |H−Cprev|, |L−Cprev|)`.
- **Bollinger(20, 2):** the population standard deviation (for context only,
  not used in rules).
- **Correlation:** Pearson correlation of daily returns over the last 60
  common dates.

All five reference repos use Wilder smoothing. This is what TradingView and
most brokers display after a warm-up of 250 bars or more.

## 6. Why these choices (sources)

- **Trend filter, pullback entry, 2×ATR stop, SMA20 exit, 15-day time stop:**
  evanrc27/swing-agent. Ideas only; that repo has no license.
- **0.5% risk, 10% max position, 30% sector, 6% heat, 2R target:**
  tradermonty breakout-trade-planner (MIT).
- **SPY > 200-day gate:** wanweileee/swingtrade (ideas only).
- **2-day earnings block, block on unknown date, sticky kill switch:**
  hydrogen2/autoswing (ideas only).
- **Gap check, re-entry cooldown, math done in code:** kevmyung/swing-trading-agent
  (Apache-2.0).
- **Our own untested defaults:**
  - the YELLOW state and the volatility override
  - the 0.8 correlation cap
  - limit = stop + 0.5×ATR
  - the morning gap rules
  - the 63-day ranking
  - the paper fill rules

The full research is in `research/findings.md` at the repo root.
