# Workflow: the daily rhythm, step by step

All times are US/Eastern (ET). Central time is ET minus 1 hour. Every session
starts with **Preflight**. Run sessions in this order of importance: **EOD**
(required), **After a fill** (required whenever something filled),
**Pre-market** (recommended), **Intraday** (optional), **Weekly** and
**Monthly** reviews.

Notation: `RH:tool_name` is a Robinhood MCP call. `swing.py cmd` is
`python3 scripts/swing.py cmd --input <file>`, run from the skill folder. The
command reads JSON and prints JSON. Write tool output to a scratch file and
pass that file to swing.py. Never retype numbers by hand.

---

## 0. Preflight (every session, about 2 minutes)

1. **Load the journal.** Read these files from the private journal repo (see
   `journaling.md`): `settings.json`, `state.json`, `paper/account.json` (paper
   mode), `HALT` (exists or not), the latest `plans/*.md`, and the open trade
   files under `trades/`.
   - If `state.json` is missing or unreadable, **stop and fail closed**. Tell
     the user, offer to rebuild state from Robinhood facts, and propose no
     entries this session.
2. **Find the account.** Call `RH:get_accounts`. Pick the one account with
   `agentic_allowed: true`. Show it masked as `••1234`. Never print a full
   account number, and never write other accounts into the journal.
3. **Check approvals (live mode).** Call `RH:get_trade_approval_setting`.
   - **ON:** good. Every `place_*` call goes into Robinhood's approval queue,
     and the user taps approve in the Robinhood app.
   - **OFF:** show a **red banner**. Ask the user either to turn it ON
     (Robinhood app → MCP account → Agent Settings → Safety Controls → Trade
     approvals) or to type exactly `I ACCEPT CHAT-ONLY CONSENT` for this
     session only. Record the choice in `plans/<today>.md`. Until one of those
     happens, build no ENTRY cards.
   - **Error or unknown:** treat it as OFF.
4. **Pull the facts.** Call `RH:get_portfolio`, `RH:get_equity_positions`,
   `RH:get_equity_orders`, `RH:get_advanced_orders` and `RH:get_trade_approvals`
   (pending and recent). In paper mode, also step the paper account first (see
   `paper-trading.md`).
5. **Reconcile.** Run `swing.py reconcile` with the cards approved since the
   last session plus the orders, advanced orders and positions.
   - **UNPROTECTED:** that position's PROTECT card is the first card of the
     session.
   - **UNTRACKED_ORDER:** ask the user about it and journal it.
   - **NOT_FOUND_AT_BROKER:** check whether it's still waiting in
     `RH:get_trade_approvals`.
6. **Run the breaker.** Call `RH:get_realized_pnl` and `RH:get_pnl_trade_history`
   for the agentic account. In paper mode, use `paper/account.json` history
   instead. Build the breaker input (equity, peak_equity from state, closed
   trades, halt_file, peak_lock) and run `swing.py breaker`. Save `new_state`
   into `state.json`.
7. **Print the status header** at the top of the reply:
   `Mode | Account ••1234 | Approvals ON/OFF | Regime | Breaker | Equity | Open risk % | Positions n/max | Pending card`.

## 1. EOD: post-close main cycle (4:15-6:00 PM ET, about 15 minutes)

1. **Regime.** Call `RH:get_equity_historicals` for SPY, QQQ and IWM, daily
   bars, with no `interval`, so the server returns roughly 2,500 bars. You need
   at least 260. Unwrap the result with `swing.py unwrap`, then run
   `swing.py regime`. In RED, skip to step 9. Manage open positions only
   (REDUCE_ONLY).
   - **Data gap.** If the latest session's bar is missing or
     `interpolated: true` (Robinhood sometimes posts the daily bar late),
     re-fetch once. If it is still missing, fail closed: no signals and no
     ENTRY cards. Use the web (data-gap check, `web-use.md`) to tell the user
     how the session closed and whether a later re-run could change the
     regime. Never build the bar from web or fundamentals numbers.
   - **Market context.** Search the web for how SPY/QQQ/IWM closed, the main
     driver and the events coming up (`web-use.md`). Put 2-4 sourced lines in
     the plan's `## Market context` section. This never changes the regime.
2. **Screen.** Call `RH:run_scan` on the saved scan named in
   `settings.saved_scan_name`. The scan filters are:
   - price > $10
   - average volume > 1M
   - market cap > $2B
   - price > SMA200

   If the scan does not exist yet, create it once with the user via
   `RH:create_scan`. Rank the results by 63-day return and keep the top
   `screen.max_shortlist` (25).
3. **Bars.** Call `RH:get_equity_historicals` in batches of at most 10
   symbols, then `swing.py unwrap`.
4. **Signals.** Run `swing.py signal` with `meta`, which holds `market_cap`
   and `tradable` from `RH:get_equity_fundamentals` / `RH:get_equity_tradability`,
   plus `leveraged_etf`. Keep only `setup: true`.
5. **Cross-check (optional but recommended).** Call
   `RH:get_equity_technical_indicators` (RSI, SMA 50/200, ATR) for the setups,
   then run `swing.py indicators` with `robinhood_indicators`. If the
   `cross_check` list is not empty, mark that symbol REVIEW and say why.
6. **Earnings.** Call `RH:get_earnings_results` for each setup symbol. Do
   **not** use `get_earnings_calendar`; it can return about 350K characters.
   Record the next report date, or `null` if it is unknown.
7. **News check.** Search the web for each remaining setup and each holding,
   as many searches as needed (`references/web-use.md`). A credible red flag
   (pending merger, FDA/court date, offering, halt, investigation) is added to
   a setup as `veto_reasons`, or flagged on a holding in the plan. The web
   never adds candidates, never raises size, and never unblocks a rule.
8. **Size and gate.**
   - For each setup, run `swing.py size` with:
     - `entry = trigger`, `cash_price = limit`
     - equity and settled cash from the portfolio
     - `risk_pct` from settings
     - `risk_mult = regime.limits.risk_mult × breaker.risk_mult`
   - Run `swing.py corr` across the setups and the holdings. Use the 60-day
     correlation.
   - Build the gate input. It carries every candidate with its sector,
     `max_correlation`, `earnings_date`, `in_written_plan: true` and
     `signal_setup: true`.
   - Run `swing.py gate`. Keep only GO.
9. **Write the plan.** Fill `templates/daily-plan.md` and save it as
   `plans/<YYYY-MM-DD>.md`.
10. **Watchlists and alerts (live mode).**
   - Sync `SWING-CANDIDATES` (GO names) and `SWING-OPEN` (holdings) with
     `RH:add_to_watchlist` / `RH:remove_from_watchlist`.
   - Set price alerts at each trigger and stop with `RH:create_alert`.
11. **Cards, one at a time.** Show any PROTECT and EXIT cards first, then the
    ENTRY cards in rank order. For each one:
    - `RH:review_equity_order` (live) → copy the alerts verbatim into
      `review_warnings`
    - `swing.py card` → show the markdown → wait for `APPROVE <code>` →
      `swing.py approve`
    - if approved: `RH:place_equity_order`, a buy stop-limit with
      `stop_price = trigger`, `limit_price = limit`, `time_in_force = gfd`, the
      card's `ref_id`
    - paper mode: run `swing.py paper place` instead
    - record the approval id or order id in the plan

    Do not show a second card until the first is approved, rejected, or
    expired.
12. **Commit the journal.** Commit with the message
    `eod <date>: regime <state>, <n> cards, breaker <state>`.

## 2. Pre-market (8:45-9:25 AM ET, about 5 minutes, recommended)

1. Run Preflight steps 1-6. Steps 3-4 can be quick.
2. **Quotes.** Call `RH:get_equity_quotes` for the working entry symbols and
   the holdings, at most 20 symbols per call.
3. **Candidates with working entries.** Re-run `swing.py gate` with
   `live_price` = the pre-market quote. Then:
   - **Gapped more than 2% or 1×ATR above the trigger:** propose a CANCEL card
     ("do not chase").
   - **Gapped down below the stop:** cancel by default and re-evaluate tonight.
4. **Holdings gapping through their stop:** propose an EXIT card. Explain that
   the stop-market leg will fill at the open anyway, and that an EXIT card is
   only needed if the protective order is missing.
5. **Stale approvals.** Look in `RH:get_trade_approvals` for pending approvals
   older than the session, or ones whose card expired. Propose
   `RH:decline_trade_approval` (a CANCEL card).
6. **The open.** Propose no new entries in the first 15 minutes.

## 3. After a fill (as soon as an entry fills: required)

1. Confirm the fill: `RH:get_equity_orders` (state `filled`), `RH:get_equity_positions`.
2. Recompute the stop and the 2R target **from the actual fill price** with
   `swing.py size`, or keep the card's stop if it is wider.
3. Call `RH:review_advanced_order` with the arguments listed after this step,
   then build a **PROTECT** card → `APPROVE <code>` → `RH:place_advanced_order`
   with the same `ref_id`.
   - `side: sell`
   - `quantity`: the filled shares
   - `take_profit_limit_price`: the 2R target
   - `stop_loss_stop_price`: the stop
   - `time_in_force: gtc`
   - `market_hours: regular_hours`
4. Until the PROTECT order is confirmed live, label the position
   **UNPROTECTED** in every header.

## 4. Intraday (10:30 AM ET, optional 3:30 PM ET)

1. Run `swing.py reconcile`. Protect anything unprotected first.
2. **Breakeven.** For each holding where today's high has reached
   `entry + 1R` and the stop is still below entry, propose **one MOVE_STOP
   card**. It is a cancel/replace: `RH:cancel_advanced_order`, then
   `RH:review_advanced_order` and `RH:place_advanced_order` with the new stop
   at the entry price and the same target.
   - Only do it if the new stop is at least 0.25×ATR higher than the old one.
   - Stops only move up; `swing.py card` refuses a lower `new_stop`.
3. Nothing else. No new entries intraday unless a working stop-limit order
   fills by itself.

## 5. Exits checked at EOD

For each holding, from the daily bars:
- **Close below SMA20, held at least 2 trading days:** EXIT card for the next
  open. Use a market sell for the shares in regular hours, or a limit order
  near the close.
- **15 trading days held without ever reaching +1R:** EXIT card (time stop).
- Stops and targets are handled by the protective order at Robinhood. They need
  no action, only reconciliation.

## 6. Weekly (Friday after the close, about 30 minutes)

Follow `review.md`. Run `swing.py review` on the week's closed trades and fill
`templates/weekly-review.md`. **No rule changes.**

## 7. Monthly (first weekend, about 90 minutes)

Follow `review.md`. Do postmortems, the graduation check, and tax lots and wash
sales. This is the only place rules can change.

---

## Scheduled (unattended) runs

`settings.scheduled_runs` controls them:
- **`strict` (default):** read-only. Run Preflight, the EOD analysis and the
  plan, then stop. Leave the cards for the user to approve in an interactive
  chat. Never call `place_*`, `cancel_*` or `decline_*`.
- **`broker_queue` (live only, opt-in):** an unattended run may call
  `place_equity_order` (ENTRY) and `place_advanced_order` (PROTECT), but
  **only** if `get_trade_approval_setting` returns ON *in that same run*. Each
  order then waits in Robinhood for the user's tap. A run without verified
  approvals is strictly read-only.

The user should never turn off Claude's "always ask" permission for scheduled
tasks. That is how consent erodes quietly.
