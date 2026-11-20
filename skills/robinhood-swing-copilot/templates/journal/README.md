# robinhood-swing-journal (PRIVATE)

This repo is the **memory** of the
[robinhood-swing-copilot](https://github.com/jcruz0828/robinhood-swing-copilot)
Claude skill. Claude has no memory between chats, so every session starts by
reading this repo and ends by committing to it.

> **Keep this repo private.** It holds trading intent, P&L and a masked account
> reference. Never add full account numbers, passwords, tokens or data from
> other accounts.

Robinhood is the source of truth for **facts** (positions, orders, fills,
P&L). This repo is the source of truth for **intent** (plans, card codes,
approvals, breaker state, the paper account, lessons). The copilot reconciles
the two every session.

## Files

| Path | What it is | Written by | When |
|---|---|---|---|
| `settings.json` | Your settings: `mode` (paper/live), `risk_pct`, `max_positions`, `scheduled_runs`, `notify_email`, scan and watchlist names, `macro_event_dates` | **You** (the agent fills `account_mask` once) | Risk numbers change only at a monthly review |
| `state.json` | Machine state: breaker result, `peak_equity`, `peak_lock`, `consecutive_losses`, `pending_card`, `last_code`, the approvals log, open trades | The agent, via `swing.py` outputs | After every state change |
| `paper/account.json` | Simulated account: cash, positions, working orders, closed-trade history, equity curve | The agent, via `swing.py paper` | Each session in paper mode |
| `plans/YYYY-MM-DD.md` | The daily plan: regime, breaker, candidates and gate results, cards and their outcomes, deviations | The agent | Each EOD session; pre-market and intraday notes are appended |
| `trades/YYYY-MM-DD-SYMBOL.md` | One file per trade: the approved plan, executions, result, R, lesson | The agent | On entry approval; completed on exit |
| `reviews/YYYY-Www.md` | Weekly review (observe only) | The agent, with you | Fridays |
| `reviews/YYYY-MM.md` | Monthly review (the only time rules or risk change) | The agent, with you | First weekend of the month |
| `HALT` | **Kill switch.** If this file exists, the copilot proposes no new entries, only protective actions | You (or the agent when you type KILL/HALT) | Delete it yourself to resume |

## Current settings (initialized 2026-11-19)

- `mode: "paper"`. No real orders. The copilot simulates fills on real
  Robinhood daily bars.
- `starting_equity: 10000`, `risk_pct: 0.5` (about $50 risk per trade),
  `max_positions: 3`.
- `scheduled_runs: "strict"`: unattended or scheduled runs are read-only.
- `notify_email: false`.

## How to...

- **Stop all new trades now:** create a file named `HALT` in this repo (you
  can do it from the GitHub mobile app) with a one-line reason. Or type
  `KILL` in the chat.
- **Resume after HALT:** delete `HALT` yourself. The agent never deletes it.
- **Clear the −15% drawdown lock:** type the exact `CLEAR HALT <code>` that
  the copilot shows you.
- **Go live:** only after the monthly review shows graduation criteria met:
  4+ weeks, 20+ closed trades, positive expectancy, 95%+ rule adherence.
  Realistically that takes 3-5 months. Then change `mode` to `"live"`
  yourself, and keep Robinhood trade approvals **ON**.
- **Record FOMC/CPI days:** add ISO dates to `macro_event_dates`, taken from
  the official Federal Reserve and BLS calendars.

## Rules for commits

- Factual one-line messages, e.g.
  `eod 2026-11-19: regime YELLOW, 0 cards, breaker TRADING_ALLOWED`.
- Never rewrite history or delete trades. Fix mistakes with a new commit that
  says why.

Not financial advice. You are responsible for every order your agent places.
