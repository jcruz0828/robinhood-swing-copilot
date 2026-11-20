# Journaling: the private journal repo is the copilot's memory

Claude has no memory between chats, so all state lives in a **private GitHub
repo** (default `jcruz0828/robinhood-swing-journal`). It is read and written
through the GitHub connector in the Claude app, or `gh`/git in Claude Code.

**Facts vs intent**
- **Robinhood is the source of truth for FACTS:** positions, orders, fills,
  P&L, tax lots, watchlists, alerts.
- **The journal is the source of truth for INTENT:** the plan, thesis, card
  codes, approvals, breaker state, paper account, lessons.
- Every session, reconcile the two with `swing.py reconcile`.

## Layout

```
README.md                 what each file is, kept in the journal itself
settings.json             user settings (mode, risk_pct, max_positions, scheduled_runs, ...)
state.json                machine state: breaker, peak_equity, peak_lock, pending_card, last_code, approvals log
paper/account.json        paper account (cash, positions, orders, history, equity_curve)
plans/YYYY-MM-DD.md       one daily plan per trading day (templates/daily-plan.md)
trades/YYYY-MM-DD-SYM.md  one file per trade (templates/trade-journal.md)
reviews/YYYY-Www.md       weekly reviews;  reviews/YYYY-MM.md monthly reviews
HALT                      exists = kill switch on (contains reason + timestamp)
```

## settings.json fields

| Field | Meaning | Who changes it |
|---|---|---|
| `mode` | `paper` or `live` | the user, at the monthly review, after graduation |
| `starting_equity`, `paper_start_date` | paper baseline | set once |
| `risk_pct` | % of equity risked per trade (0.5 during rollout) | the monthly review only |
| `max_positions` | hard cap on top of the regime limit (3 during rollout) | the monthly review only |
| `scheduled_runs` | `strict` (read-only) or `broker_queue` | the user |
| `notify_email` | send a summary email after unattended runs (false) | the user |
| `chat_only_consent` | always false at rest; consent is per session and noted in the plan | never persisted true |
| `account_mask` | e.g. `••1234`, filled at the first live preflight | the agent |
| `saved_scan_name`, `watchlists` | Robinhood scan and watchlist names | the agent, at setup |
| `macro_event_dates` | ISO dates of FOMC/CPI days to skip | the user, from official calendars |

## state.json fields

- `breaker`, `peak_equity`, `peak_lock`, `peak_lock_since`, `consecutive_losses`:
  the `new_state` output of `swing.py breaker`.
- `pending_card`, `last_code`, `approvals`: the `new_state` output of
  `swing.py card`, `approve`, and `reject`.
- `open_trades`: `[{symbol, card_codes, ref_ids, entry, stop, target, shares, opened}]`.
- `cooldowns`: `{SYMBOL: "YYYY-MM-DD"}`, the date of the last losing exit.
- `last_session`: `{type: "eod"|"premarket"|..., at: ISO}`.

## Protocol

1. **Read before acting.** Load settings, state, HALT, today's plan, and the
   open trades during preflight.
2. **Write after each state change.** Do this after a card is approved or
   rejected, a paper step, a fill, or a breaker change. Do not batch it all to
   the end, because a chat can be cut off.
3. **Commit messages** are short and factual. Examples:
   - `eod 2026-11-19: regime YELLOW, 1 card (a1b2c3d4 approved), breaker OK`
   - `fill AAA 4 @ 219.84; PROTECT 9f8e7d6c pending`
   - `HALT: user typed KILL 2026-11-20T10:02`
4. **Never write:**
   - full account numbers, tokens, or other accounts' data
   - anything into the **public** skill repo
5. **Never delete** history, trades, or HALT. Corrections are new commits with
   an explanation.
6. **If the GitHub connector fails:**
   - Do not continue to trade.
   - Show the full intended state update as a JSON block and ask the user to
     save it.
   - Propose no entries until the journal is writable again. Protective
     actions are still allowed.

## Rebuilding lost state (live)

- **Rebuildable from Robinhood:**
  - positions and protective orders (`get_equity_positions`, `get_advanced_orders`)
  - realized P&L, the loss streak, and cooldowns (`get_pnl_trade_history`)
  - candidates (watchlists)
- **Not rebuildable:** theses, card history, `peak_equity`. Ask the user, and
  use the highest equity in the portfolio history if it is available.

While state is incomplete, the breaker returns HALTED, so no entries are made.
