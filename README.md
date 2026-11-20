# robinhood-swing-copilot

A **consent-gated, propose-only** swing-trading copilot for Claude and
Robinhood's agentic (MCP) trading account.

- It runs a deliberately boring, rules-first **trend-pullback** strategy.
- Every calculation happens in a tested Python script, and the AI does no
  math.
- Every order needs your explicit, typed approval for that one trade, plus
  your tap in the Robinhood app.
- It starts in **paper mode**, a built-in simulator on real Robinhood prices,
  because Robinhood has no paper environment.

> **Not financial advice.** Robinhood states you are ultimately responsible for
> every trade your AI agent places, and that agentic trading can lose your
> entire investment. This is a personal tool. Do not use it to give signals to
> anyone else.

---

## Contents

1. [Honest expectations](#1-honest-expectations)
2. [How it works](#2-how-it-works)
3. [What's in this repo](#3-whats-in-this-repo)
4. [Setup: Claude app](#4-setup-claude-app-recommended)
5. [Setup: Claude Code](#5-setup-claude-code)
6. [Daily use](#6-daily-use)
7. [Consent and safety](#7-consent-and-safety)
8. [Rollout: paper → live](#8-rollout-paper--live)
9. [The engine: swing.py](#9-the-engine-swingpy)
10. [Running tests](#10-running-tests)
11. [Changing the rules](#11-changing-the-rules)
12. [Credits and licenses](#12-credits-and-licenses)

---

## 1. Honest expectations

Read this before you fund anything.

- **There is no proven edge.** Trend-pullback is a well-known, widely used
  strategy. The only public backtest of a similar system that we found
  (Vipuld14/LIVE-swing-trading-agent) **lagged buy-and-hold SPY in 2009-2017**
  (about 9.4% vs 17.4% a year), with smaller drawdowns.
- **The numbers are small at this size.**
  - At $10,000 and 0.5% risk you risk about **$50 per trade**.
  - A good expectancy of +0.2R is about $10 per trade. At roughly 40 trades a
    year, that is around $400 before taxes.
  - Gains are short-term and taxed as ordinary income.
  - Buying and holding an index fund may well do better.
- **What it is good for:** discipline, a written track record, learning how
  the system behaves, and a safe way to try agentic trading with hard limits.
- **The paper phase is slow.** 20 closed trades usually takes **3-5 months**
  with these filters and 3 positions. Weeks with no setups are normal. Do not
  loosen rules to get more trades.
- **Gaps beat stops.** A stock that gaps down overnight fills your stop at the
  gap price. A planned 1R loss can become 2-3R.
- **The AI is not the edge.** Studies of live LLM trading (LiveTradeBench,
  Agent Market Arena, AlphaForgeBench) found LLMs trade poorly when they use
  judgment. Here Claude is only the operator: it fetches data, runs the script,
  shows you cards, and keeps the journal.

## 2. How it works

One evening session (about 15 minutes, after 4:15 PM ET):

1. **Preflight.** Claude reads your private **journal** repo (settings, state,
   paper account, HALT), checks Robinhood **trade approvals are ON**, pulls
   positions and orders, and runs the **circuit breaker**.
2. **Regime.** If SPY is below its 200-day average, no new buys are made
   (RED). If SPY is choppy (YELLOW), risk is halved and the copilot holds at
   most 3 positions.
3. **Scan and signals.** It runs your saved Robinhood scan, then
   `swing.py signal` finds stocks that pulled back in an uptrend (RSI ≤ 45)
   and turned up (closed above the prior day's high).
4. **Filters.** It blocks any stock with earnings within 2 trading days. It
   sizes each trade so a stop-out costs about 0.5% of equity, and checks the
   portfolio limits: total risk, sector, correlation, cooldowns.
5. **Trade card.** For each survivor it shows a card with the exact order, the
   stop, the 2R target, the shares, the risk in dollars, and an
   **8-character code**.
6. **You approve.** Type `APPROVE a1b2c3d4` to approve that one card.
   - **Paper mode:** the order goes into the simulator.
   - **Live mode:** Claude sends a buy stop-limit order, and with approvals ON
     it waits for **your tap in the Robinhood app**.
7. **After the fill.** A **PROTECT** card places the broker-side exit pair:
   the stop-loss plus the 2R take-profit. You're protected even when Claude is
   closed.
8. **Managing the trade.**
   - **+1R:** a card moves the stop to breakeven.
   - **Other exits:** a close below the 20-day average, or 15 trading days
     without progress.
9. **Journal.** Everything is committed to the private journal repo.

## 3. What's in this repo

```
skills/robinhood-swing-copilot/      <- the Claude skill (zip this folder for the Claude app)
  SKILL.md                           agent runbook: start here if you are an AI agent
  config/rules.json                  every threshold, in one place
  scripts/swing.py                   the engine (Python 3.9+, standard library only)
  references/                        detailed procedures:
    workflow.md                      daily rhythm, exact tool calls
    strategy.md                      regime/screen/entry/exit rules and why
    risk.md                          sizing formula, limits, breakers, gap risk
    consent.md                       approval layers, trade cards, kill switch
    robinhood-notes.md               Robinhood MCP tools, payloads, limits, gotchas
    journaling.md                    the journal repo: files, fields, commit protocol
    paper-trading.md                 simulator fill rules, catch-up, graduation
    review.md                        weekly and monthly reviews
    web-use.md                       web search for context; it can veto or warn, never create a trade
  templates/                         trade card, daily plan, trade journal, reviews
  templates/journal/                 seed files to start a new private journal repo
  evals/evals.json                   behaviour scenarios the skill must handle
.claude/settings.json                Claude Code: "ask" on every order tool, deny options/crypto, hook
.claude/hooks/order_guard.py         Claude Code PreToolUse guard
.mcp.json                            Claude Code: Robinhood MCP server
.github/workflows/tests.yml          CI: self-test + unit tests (no scheduled jobs)
tests/                               unit tests (standard-library unittest)
docs/spec.md                         the v1 implementation spec
research/findings.md                 all research behind the design, with sources
```

**Two repos:**
- **This public repo** (code, docs, research).
- **A private journal repo** (`robinhood-swing-journal`), which holds your
  settings and trading data. Your data never goes in this repo.

## 4. Setup: Claude app (recommended)

1. **Robinhood.**
   - Open the agentic (MCP) account in the Robinhood app.
   - Under **Agent Settings → Safety Controls**, turn **Trade approvals ON**.
     Leave it on forever.
   - Fund it only with money you can afford to lose. Paper mode needs no
     funding.
2. **Connectors** (Claude app → Settings → Connectors):
   - **Robinhood:** connect it, then set every `place_*`, `cancel_*` and
     `decline_*` tool to **"Ask"**, never "Always allow".
   - **GitHub:** connect it and give it **read/write** access to your private
     journal repo (github.com → Settings → Applications → the Claude GitHub
     app → Repository access).
   - **If writes fail with 403** "Resource not accessible by integration":
     re-grant the repo in the app installation, then revoke and reconnect.
3. **Code execution:** Settings → Capabilities → turn on code execution, so
   `swing.py` can run.
4. **Install the skill:**
   - Download this repo and zip the folder
     `skills/robinhood-swing-copilot`. The ZIP must contain the folder, and the
     folder name must stay `robinhood-swing-copilot`.
   - Upload it via **Customize → Skills → Upload a skill**.
5. **Journal repo.** Create a **private** repo named `robinhood-swing-journal`
   and copy in the files from `skills/robinhood-swing-copilot/templates/journal/`:
   `README.md`, `settings.json`, `state.json` and `paper/account.json`. Also
   create empty `plans/`, `trades/` and `reviews/` folders, each with a
   `.gitkeep`. Set `paper_start_date` and the paper account dates to today.
   Do this in the GitHub web UI or with git.
6. **First run:** in a new chat, say *"Run my swing copilot preflight and
   self-test."*

## 5. Setup: Claude Code

```bash
git clone https://github.com/jcruz0828/robinhood-swing-copilot
cd robinhood-swing-copilot
python3 skills/robinhood-swing-copilot/scripts/swing.py selftest   # must print "ok": true
claude   # .mcp.json registers robinhood-trading; approve it and log in via OAuth when asked
```

- **What this repo configures:**
  - `.claude/settings.json` sets every order tool to **ask** and denies
    options, crypto and exercises.
  - `order_guard.py` blocks new buys while a `HALT` file exists, and makes
    unattended runs read-only.
- **Point the hook at your journal:** clone the journal next to this repo
  (`../robinhood-swing-journal`) or set `SWING_JOURNAL_DIR`, so the hook can
  see `HALT`.
- **Unattended runs:** set `SWING_COPILOT_HEADLESS=1`. Only set
  `SWING_COPILOT_SCHEDULED_MODE=broker_queue` if you want unattended runs to
  queue orders. Even then, they only queue into Robinhood's approval list.
- **If your claude.ai Robinhood connector already shows up in Claude Code**
  (tools named `mcp__claude_ai_Robinhood__*`), you can skip `.mcp.json`. Both
  are guarded.

## 6. Daily use

| When (ET) | Say | What happens |
|---|---|---|
| After 4:15 PM, every trading day | "Run my evening swing session" | Preflight, regime, scan, signals, gate, plan, cards |
| 8:45-9:25 AM (recommended) | "Pre-market check" | Gap checks on working orders, cancel if they'd chase, decline stale approvals |
| After an entry fills | "AAA filled" (or the next session finds it) | PROTECT card for the exit pair |
| 10:30 AM (optional) | "Intraday check" | Breakeven stop moves (stops only move up) |
| Friday after close | "Weekly review" | Metrics and rule adherence; no rule changes |
| First weekend of the month | "Monthly review" | Postmortems, graduation check, the only time rules can change |
| Any time | `KILL` or `HALT` | Creates the HALT file; protective actions only from then on |

**Replying to a card:**
- `APPROVE <code>` approves that one card.
- `REJECT <code>` discards it.
- Anything else, including "yes", "approve all" or an old code, is refused.

## 7. Consent and safety

| Layer | What protects you |
|---|---|
| 1. Robinhood trade approvals ON | Orders wait for your tap in the Robinhood app. Checked every session; if OFF, you get a red banner |
| 2. Client "ask" permission | Claude must ask before any order, cancel, or decline tool call |
| 3. Typed approval code | One exact `APPROVE <code>` per card. No batches; codes expire daily; a price move above 0.5×ATR forces a new card |

- **Fail closed:** missing state, an unknown approval setting, a missing
  earnings date, or a tripped breaker all mean no new entries.
- **Never automated:**
  - raising risk, or clearing halts
  - options, crypto or shorts
  - moving a stop down, or averaging down
  - other accounts
  - turning approvals off
  - changing rules mid-week
- **Circuit breakers** (on realized P&L):

  | Trigger | Result |
  |---|---|
  | −2% day / −5% week / −8% month | halt until the period ends |
  | 2 losses in a row | 24 h cooldown, then half risk |
  | −15% from peak | locked until you type `CLEAR HALT <code>` |

- **The web informs, it never decides.** Claude searches the web for context
  every session: how the market closed and why, events coming up, news on
  your candidates and holdings, and what happened when Robinhood data is
  missing. A red flag can *veto* a candidate or warn you about a holding. It
  never uses the web to find, upgrade, resize or unblock trades, never feeds
  web prices into the math, and treats web pages as untrusted text. See
  `references/web-use.md`.
- **Kill switch:** type `KILL`, or add a file named `HALT` to the journal (you
  can do it from the GitHub app on your phone), or disconnect the agent in
  Robinhood.

Details are in `skills/robinhood-swing-copilot/references/consent.md` and
`risk.md`.

## 8. Rollout: paper → live

| Stage | Mode | Risk | Max positions | Move on when |
|---|---|---|---|---|
| 1 | paper | 0.5% | 3 | ≥ 4 weeks, ≥ 20 closed trades, expectancy > 0R, ≥ 95% rule adherence (realistically 3-5 months) |
| 2 | live | 0.5% | 3 | Same criteria met **on live trades**, and ≥ 10 weeks live |
| 3 | live | 1.0% | 6 | Your decision at a monthly review |

You decide every stage change at a monthly review. Never turn Robinhood
approvals off at any stage.

## 9. The engine: swing.py

The script is standard-library Python (3.9+), so it runs unchanged in the
Claude app sandbox, in Claude Code, and in CI. Every command reads JSON
(`--input file`, or stdin) and prints JSON.

```bash
cd skills/robinhood-swing-copilot/scripts
python3 swing.py selftest
python3 swing.py unwrap  --input rh_historicals.json         # Robinhood {data,guide} -> {SYM:[bars]}
python3 swing.py regime  --input spy_bars.json               # GREEN / YELLOW / RED
python3 swing.py signal  --input bars_and_meta.json          # setup + trigger/limit per symbol
echo '{"entry":100,"atr":2,"low_recent":97,"equity":10000}' | python3 swing.py size
python3 swing.py breaker --input breaker_input.json          # TRADING_ALLOWED / COOLDOWN / HALTED
python3 swing.py gate    --input gate_input.json             # GO / REVIEW_REQUIRED / NO_GO
python3 swing.py card    --input card_input.json             # card markdown + 8-char code
python3 swing.py approve --input approve_input.json          # validates "APPROVE <code>"
python3 swing.py paper init --equity 10000 --date 2026-11-19
python3 swing.py paper step --input step_input.json          # catches up every missed day
python3 swing.py review  --input trades.json                 # metrics + graduation
python3 swing.py reconcile --input reconcile_input.json      # UNPROTECTED / UNTRACKED / MATCHED
python3 swing.py calendar --date 2026-11-26                  # NYSE trading-day helper
```

- **Input and output fields:** see `docs/spec.md` §5 and the docstrings in
  `swing.py`.
- **Exit codes:** 0 ok, 1 selftest failed, 2 bad input or refused action.
- **The holiday table covers 2025-2027.** Extend `NYSE_HOLIDAYS` before 2028;
  the simulator warns when a date is outside it.

## 10. Running tests

```bash
python3 -m unittest discover -s tests -v
python3 skills/robinhood-swing-copilot/scripts/swing.py selftest
```

The suite needs nothing beyond Python 3.9+. It covers:
- indicators, checked against hand-computed Wilder values
- the NYSE calendar and Robinhood payload unwrapping
- regime and signal edge cases
- every sizing cap
- every breaker and gate rule
- card codes and approval refusals
- every paper fill rule, including gaps and catch-up
- review and reconcile
- the Claude Code hook
- config integrity

CI runs the same suite on Python 3.11-3.13 for every push and pull request.
There are no scheduled jobs.

## 11. Changing the rules

Rules live only in `skills/robinhood-swing-copilot/config/rules.json`.

- Change them **only at a monthly review**, with evidence from at least 20
  closed trades.
- Make the change through a pull request that bumps `version` and explains the
  reason.
- Update `rules_version` in your journal's `settings.json`.
- After changing the skill, re-zip and re-upload it in the Claude app.

## 12. Credits and licenses

This repo is MIT-licensed, and all of its code is original. The design draws
on the projects below; full details and sources are in `research/findings.md`.

| Project | License | What we took (ideas unless stated) |
|---|---|---|
| tradermonty/claude-trading-skills | MIT | Breaker thresholds and semantics, gate structure, risk defaults, SKILL.md layout |
| kevmyung/swing-trading-agent | Apache-2.0 | Three-cycle daily rhythm, math in code, gap and re-entry checks |
| evanrc27/swing-agent | none (ideas only) | Trend filter, pullback entry, 2×ATR stop, SMA20 exit, 15-day time stop, HALT file |
| andrewkng/robinhood-agent | none stated (ideas only) | Robinhood batch limits, payload handling, read-only hook pattern |
| TraderAlice/OpenAlice | - | Stage/commit/push approval with a chained hash |
| wanweileee/swingtrade, hydrogen2/autoswing, Vipuld14/LIVE-swing-trading-agent | none (ideas only) | SPY 200-day gate, earnings block, sticky kill switch, backtest evidence |
