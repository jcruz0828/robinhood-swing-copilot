# Research findings: robinhood-swing-copilot

Compiled 2026-11-19 during the design of the robinhood-swing-copilot Claude skill.
Every threshold here is a starting hypothesis to validate in paper mode, not a proven edge.
"Verified" = read in code/docs; "secondhand" = README claims, third-party copies or search excerpts.

## TL;DR

- Build it as a PROPOSE-ONLY skill with three stacked consent layers:
  1. Robinhood's own Trade approvals toggle ON
  2. Claude connector permissions set to "always ask" for every place_/cancel_ tool
  3. an in-skill trade card that needs a typed `APPROVE <code>` per order
- Use a deliberately boring, rules-first strategy: the trend-pullback core from evanrc27/swing-agent, risk limits from tradermonty's breakout-trade-planner, and circuit breakers enforced in deterministic code before the LLM reasons.
- Live LLM-trading benchmarks agree: LLMs do badly as discretionary decision-makers but can work as disciplined executors of pre-written rules. The skill computes, checks and presents trades. It never improvises them.
- Consent can be enforced at the broker, not just in the prompt. Robinhood: trade approvals are on by default for its built-in agents and OFF by default for MCP (external) accounts. With approvals ON, the agent can only propose, and you place the order in the Robinhood app. Check get_trade_approval_setting every session.
- Rules (v1): trade only when SPY is above its 200-day SMA.
  - Entry (trend pullback): SMA50 above SMA200, close above SMA200, SMA50 rising, RSI(14) dipped to 45 or lower and turning up, close above the prior high.
  - Risk: 0.5-1% per trade with a 2xATR stop and a 2R target.
  - Exits: close below SMA20, or a 15-day time stop.
  - Limits: 10-15% per name, 6 positions, 6% total open risk, 30% per sector.
  - Halts: no new entries after a -2% day, -5% week or -8% month, or after 2 consecutive losses.
  - Earnings: no new entries within 2 trading days of a report.
- Robinhood constraints shape the design:
  - Agents can place market, limit, stop-limit and stop-market orders.
  - A take-profit/stop-loss pair works on an EXISTING position (place_advanced_order). There's no entry bracket and no trailing-stop order for agents, so stops go on after the fill and trailing is cancel + replace.
  - The PDT $25k rule was replaced on June 4, 2026, with broker phase-in through October 20, 2027.
  - Cash-account good-faith violations still apply.

## 1. Robinhood's agentic stack (verified from Robinhood support docs)

- **Launch:** Agentic Trading launched as a beta on May 27, 2026, equities first. Robinhood later added options (X post, July 6, 2026) and crypto (rollout Aug 17-31, 2026). The X posts were seen only as search excerpts.
- **Dedicated account:** the external agent trades only in a dedicated MCP account, but it can READ all of the customer's accounts (positions, balances, orders, watchlists, scans). Only one account has agentic_allowed: true.
- **Endpoint:** https://agent.robinhood.com/mcp/trading (Streamable HTTP, OAuth in the browser). In Claude Code: claude mcp add --transport http --scope project robinhood-trading https://agent.robinhood.com/mcp/trading
- **Agent order types:** market (shares), market (dollars), limit, stop limit, stop market. Robinhood's built-in agents also list take profit/stop loss. No multi-leg options orders.
- **Trade approvals:** ON means the agent proposes and you review and place the order in the Robinhood app. OFF means eligible trades go through without your confirmation. The toggle is under MCP account → Agent Settings → Safety Controls. Some trades may still need approval when it's off.
- **Approval tools:** get_trade_approval_setting, get_trade_approvals (pending and past) and decline_trade_approval. Finder.com (updated Oct 27, 2026) says approvals are still rolling out for outside agents, so check live and never assume.
- **Advanced orders:** get_advanced_orders, review_advanced_order, place_advanced_order, cancel_advanced_order. Per LangAlpha PR #630, an advanced order is a take-profit limit leg plus a stop-loss stop leg on the same symbol, side and quantity, and a fill on either leg fills the order. Robinhood's order-types page says no short selling, bracket orders, MOC or MOO. So the model is: entry first, then an exit pair after the fill.
- **Responsibility:** Robinhood says you're ultimately responsible for your agent's trades, and it doesn't control, supervise, monitor, recommend or audit agents.
- **Scheduling:** Robinhood lists "Agent Loops" (scheduled trading) as coming soon. Wall Street Survivor (Sep 3, 2026) found Claude's scheduled tasks needed the desktop app open, and that the author had flipped a setting to skip approvals for scheduled tasks. That's a warning: scheduled runs can quietly erode the consent gate.

## 2. Practical MCP notes (andrewkng/robinhood-agent README)

- **Batch limits:** quotes up to 20 symbols per call, historicals up to 10.
- **Earnings:** get_earnings_calendar can return about 350K characters, so prefer get_earnings_results per ticker. The official doc caps the calendar window at 31 days and offers a large-cap filter.
- **Orders:** use the idempotency ref_id, show review_* pre-trade alerts verbatim, never invent order size or type, and check approvals fresh every time.
- **Math:** do arithmetic in Python, not in the model's head.
- **Swing checklist:** per-ticker earnings, then batch rsi, bollinger_bands, sma 50/200 and atr, then check cross-account concentration and wash-sale risk.
- **Safety default:** read-only by default, with a PreToolUse hook guard for headless runs (Claude Code only).

## 3. Reference strategy rule sets

**evanrc27/swing-agent (verified README)**
- Trend: SMA50 above SMA200, close above SMA200, SMA50 rising.
- Entry: RSI(14) dipped to 45 or lower and turning up, and close above yesterday's high.
- Exits: stop 2xATR, target 4xATR, close below SMA20, or a 15-day time stop.
- Sizing: 1% risk, 15% max per name, 6 positions max, 80% max gross.
- Safety: halt new entries after a 3% daily drawdown. A state/HALT file is a kill switch. Bracket orders (Alpaca). Live trading needs a live URL AND SWING_AGENT_LIVE=YES (two-key arming).

**tradermonty breakout-trade-planner SKILL.md (verified)**
- Defaults: risk 0.5%, max position 10%, max sector 30%, max portfolio heat 6%, target 2R, stop buffer 1% below the contraction low, max chase 2%, pivot buffer 0.1%.
- Gate: valid VCP, good/strong/textbook rating, worst-case risk 8% or less, breakout volume confirmed, within max chase.
- Modes: pre_place (stop-limit) or post_confirm (limit after 5-minute confirmation).
- It notes FINRA replaced PDT effective 2026-06-04, with phase-in through 2027-10-20, and that its order templates are planning artifacts, not broker permission.

**tradermonty vcp-screener (docs site)**
- Max 3% above pivot, breakout volume 1.5x the 50-day average, trend minimum score 85.
- Minervini 7-point trend template over 260-day histories. Weights include trend template 25%, pivot proximity 15%, relative strength 15%.

**tradermonty market regime skills**
- uptrend-analyzer scores 0-100 from 5 components: breadth 30%, sector participation 25%, rotation 15%, momentum 20%, historical 10%.
- Zones: 80-100 Strong Bull → 100% exposure; 60-79 Bull → 80-100%; 40-59 Neutral → 60-80%; 20-39 Cautious → 30-60%.
- exposure-coach outputs an exposure ceiling plus NEW_ENTRY_ALLOWED / REDUCE_ONLY / CASH_PRIORITY.
- These rely on tradermonty's public breadth CSVs, which Robinhood MCP doesn't provide, so the skill uses an SPY index proxy instead.

**tradermonty drawdown-circuit-breaker and pre-trade-discipline-gate**
- Outputs: TRADING_ALLOWED / COOLDOWN / HALTED and GO / REVIEW / NO_GO.
- Gate checks: thesis, stop, size, heat, revenge window, mood and breaker. "Do not treat a missing upstream artifact as permission to trade." "Do not bypass a NO_GO by changing answers after the fact."
- Numbers -2% day, -5% week, -8% month and a cooldown after 2 losses come from a third-party port (irsyadfptr/mercury PR #1). Secondhand.

**tradermonty workflows**
- swing-opportunity-daily (about 40 min): vcp-screener → drawdown-circuit-breaker → technical-analyst → position-sizer → trader-memory-core → pre-trade-discipline-gate.
- Manifests include manual_review checklists ("semi-automated, not auto-execution"), and the journal destination is always trader-memory-core.
- monthly-performance-review takes about 90 minutes.

**kevmyung/swing-trading-agent (README only)**
- Three cycles: EOD signal at 4:00 PM ET, morning at 9:00 AM ET with gap and news triage, intraday from 10:30 AM with trailing-stop tightening.
- PM actions: enter/exit/hold/tighten/watch. 2% risk with ATR stops, chandelier trailing, sector caps, correlation limits, drawdown breakers. All indicators are computed in code; the LLM does no math.
- Built on AWS Bedrock with the Strands Agents SDK, Alpaca for paper and live, yfinance and Polygon data. 24 stars and 11 commits at the time.
- The exact thresholds in docs/design-*.md and playbook/ were NOT retrieved (fetch restrictions). The architecture is adopted; its numbers are replaced by the evanrc27/tradermonty values plus a standard 22-day/3xATR chandelier.

## 4. Consent pattern: OpenAlice "Trading-as-Git"

Trades are staged, committed with a rationale, then pushed. The push waits for human approval in the app or Telegram by default. Every commit gets an 8-character hash and a reviewable log, "Allow AI to push trades" is off by default, and tradingReject undoes a bad stage.

The mapping to Robinhood:
- **stage** = review_equity_order / review_advanced_order
- **commit** = trade card plus journal entry with a hash
- **push** = the user's typed approval, then place_*, which enters Robinhood's own approval queue when approvals are ON

## 5. What live evidence says about LLM trading agents

- **LiveTradeBench (ulab-uiuc):** 50 live trading days (Aug 18 - Oct 24, 2025), 21 LLMs. General LLM ability (LMArena) correlated slightly negatively with trading outcomes. Most agents had poor returns and weak risk management.
- **Agent Market Arena (WWW '26):** agent frameworks drove behavior more than model backbones, and agents collectively misjudged a sudden reversal. The workflow and guardrails matter more than the model.
- **AlphaForgeBench:** LLMs used as direct traders showed severe behavioral instability and rapid action flipping, so single-run evaluations are statistically unreliable.
- **LiveOption:** removing portfolio state roughly tripled mean max drawdown. Always feed live positions and P&L into every decision.
- **LLM-Trading-Lab (ChatGPT, $100, micro-caps, about 6 months, real money):**
  - high concentration (about 3 tickers) and sticky ticker theses
  - frequent re-entry into tickers with prior losses
  - large overnight gaps that made stops ineffective
  - Lessons: re-entry cooldown, liquidity floors, plan for gap risk.
- **AlphaCrafter:** role-play debate agents like TradingAgents were unstable across models, while structured factor workflows were more consistent. Use debate only as a written risk review, never as the signal.

## 6. Regulatory and account mechanics

- **PDT:** the SEC approved SR-FINRA-2025-017 on April 14, 2026 (Release No. 105226). FINRA Regulatory Notice 26-10: new intraday margin standards replace the day-trade count and the $25,000 minimum, effective June 4, 2026, with broker phase-in through October 20, 2027. The $2,000 margin minimum remains.
- **Cash accounts:** T+1 settlement. Selling a position bought with unsettled proceeds before they settle is a good-faith violation. Thresholds vary: JorgAI says 3 per 12 months at Schwab, Fidelity and E*TRADE (4 at Public) leads to settled-cash-only for 90 days; Wikipedia says 4 per year. No Robinhood-specific number was found, so treat any GFV as a hard block.

## 7. Recommended design

### 7a. Daily workflow (ET; CT = ET - 1)

**Session preflight (every run)**
1. get_accounts → the agentic account, masked (••1234).
2. get_trade_approval_setting → if OFF, show a red banner and require the user to enable it or type "I ACCEPT CHAT-ONLY CONSENT" for the session.
3. get_portfolio, get_equity_positions, get_equity_orders, get_advanced_orders, get_trade_approvals.
4. Read the journal and check for HALT.
5. Compute the breaker from get_realized_pnl and get_pnl_trade_history.

**Post-close / EOD (4:15-6:00 PM, main cycle)**
1. Regime: SPY/QQQ/IWM, 260 or more bars.
2. run_scan on a saved scan (price above $10, avg volume above 1M, cap above $2B, price above SMA200).
3. Shortlist up to 25 names, then pull historicals (batches of 10) and technical indicators, recomputing in Python as a cross-check.
4. Earnings filter per ticker.
5. Veto-only context: fundamentals, analyst ratings, recent 8-Ks.
6. Size each candidate and apply portfolio limits.
7. Write the daily plan.
8. Sync watchlists (SWING-CANDIDATES, SWING-OPEN) and set alerts at triggers and stops.
9. Show trade cards.

**Pre-market (8:45-9:25 AM)**
- Measure overnight gaps.
- Gap up more than 1xATR or 3% above the trigger: skip, don't chase.
- Gap down through a holding's stop: propose an exit.
- Gap down on a candidate: re-evaluate, cancel by default.
- Decline stale approvals.

**Open:** no new entries in the first 15 minutes.

**After a fill:** review_advanced_order → card → approval → place_advanced_order. This keeps the stop at the broker while Claude is offline.

**Intraday (10:30 AM, optional 3:30 PM):** trailing logic. If the new stop is higher than the current one by more than 0.25xATR, propose a cancel/replace as one card. Stops only move up.

**Weekly (Friday, about 30 min):** win rate, average R, expectancy, profit factor, rule adherence.

**Monthly (about 90 min):** postmortem on each closed trade, MAE/MFE, parameter drift, tax lots and wash sales. Rules change only here.

### 7b. Rule set

**Regime gate (SPY)**
- GREEN: close above SMA200, SMA50 above SMA200, SMA50 rising. Up to 6 positions, heat up to 6%.
- YELLOW: close above SMA200 but SMA50 flat or falling, or close below SMA50. Up to 3 positions, risk halved, heat up to 3%.
- RED: close below SMA200. REDUCE_ONLY.
- Vol override (ATR/close above 2.5% or SPY down 3% in a day): one level down.

**Screen:** price $10 or more, 50-day avg volume 1M or more, market cap $2B or more, tradable, no leveraged ETFs, trend template.

**Entry:** RSI(14) at 45 or lower within 5 sessions and rising, close above the prior high. Next-session buy stop-limit just above the high. Skip if more than 2% above the trigger at the open.

**Sizing**
- risk$ = equity x risk% (0.5% default)
- stop_dist = max(2xATR, entry - 5-day low x 0.99)
- shares = floor(risk$ / stop_dist), capped at 10% of equity and settled buying power, whole shares only. Computed in a script.

**Stops and targets**
- Initial stop 2xATR via the exit pair right after the fill, target 2R.
- Breakeven after +1R, chandelier (22-day high - 3xATR) after +2R.
- Exit on a close below SMA20 or after 15 days without reaching +1R.

**Portfolio**
- Positions by regime, open risk 6% or less, 30% per sector and 2 names per sector, gross 80% or less.
- New names correlated above 0.8 with a holding are blocked (60-day returns).
- 10-day re-entry cooldown after a loss.

**Breakers**
- -2% day, -5% week, -8% month: halt new entries for that period.
- 2 losses in a row: cooldown, with risk halved afterwards.
- -15% from peak: read-only until the user clears it.

**Events:** no entries within 2 trading days of earnings or when the date is unknown. No entries on FOMC/CPI days by default.

### 7c. Consent design
- **Three layers:** broker approvals, client tool permissions, typed approval code.
- **Card fields:** account, approvals, regime, breaker, action, thesis, stop/target, risk, portfolio after the trade, events, verbatim review warnings, exit plan.
- **Approval:** only an exact `APPROVE <code>` counts. No batch approvals. Codes expire at end of session/day. Price moved more than 0.5xATR means a new card.
- **Never automated:** raising risk, clearing halts, market orders outside regular hours, options/crypto/shorts, moving stops down, averaging down, other accounts, turning approvals off, changing rules mid-week.
- **Kill switch:** typed KILL/HALT, a HALT file, disconnecting in Robinhood, or a hard drawdown halt.

### 7d. Memory (journaling)
- Robinhood is the source of truth for FACTS: positions, orders, fills, P&L, tax lots, watchlists, alerts.
- The journal repo is the source of truth for INTENT: thesis, card codes, approvals, plans, breaker state, lessons.
- Every session, reconcile Robinhood fills against the cards.

### 7e. Skill folder layout
SKILL.md + config/rules.json + references/ (workflow, strategy, risk, consent, Robinhood notes, journaling, review) + scripts/ (indicators, regime, sizing, breaker, gate, card) + templates/ + evals/.

### 7f. Risks
- Overnight gaps defeat stops.
- A missing protective order after a fill (flag UNPROTECTED first).
- Fractional shares untested (whole shares only).
- No native trailing stop.
- Over-trading and action flipping.
- Tool/data errors (cross-check indicators).
- Approval-setting drift.
- The agent can read all accounts (mask numbers and keep other accounts out of the journal).
- Regulatory: personal tool only, don't publish personalized signals, disclaimers.
- No primary-source win-rate studies were gathered. One public backtest (Vipuld14/LIVE-swing-trading-agent) found a regime overlay helped in 2018-present but was "a wash" in other windows.

### 7g. Rollout
- Weeks 0-2: read-only or paper.
- Weeks 2-12: 0.5% risk and 3 positions.
- Month 3: move to 1% and 6 positions only with 95%+ rule adherence, 20+ closed trades and positive expectancy.
- Never turn Robinhood approvals off.

## 8. Follow-up findings (later in the session)

- **No paper trading:** Robinhood's agentic MCP has no paper environment. You fund a real account and every order is real (Medium writeup, July 2026). So the skill simulates paper trading itself using real Robinhood price data and stores the paper account in the private journal repo.
- **Response format:** Robinhood MCP responses come wrapped as {data, guide}, so unwrap data first. Learn the historicals field names on first run (likely begins_at, open_price, high_price, low_price, close_price, volume, to be verified).
- **Robinhood statements:** the CFO said agentic trading is "not in the app", so you connect through MCP. Robinhood's risk disclosure says agentic trading can lose your entire investment.
- **tradermonty/claude-trading-skills:**
  - 3.8k stars, 825 forks, MIT.
  - A toolkit for time-constrained investors: core long-term/ETF/dividend portfolio plus disciplined swing as a satellite. The aim is to structure review, risk, planning and journaling, not to outsource decisions. Not a signal service.
  - Five workflows: market-regime-daily, core-portfolio-weekly, swing-opportunity-daily, trade-memory-loop, monthly-performance-review.
  - No-API starter path: market-breadth-analyzer, uptrend-analyzer, position-sizer, trader-memory-core, signal-postmortem.
  - Most screeners need FMP (free tier 250 requests/day) or FINVIZ Elite; the portfolio skill uses Alpaca.
  - IBD distribution day = close down at least 0.2% on higher volume, expiring after 25 sessions.
  - PEAD setups: stop at the red-candle low, 2R target.
  - Dividend pullback screen: 12%+ dividend growth, 1.5%+ yield, RSI 40 or lower.
- **LLMQuant/awesome-trading-agents** (979 stars, CC0) "if you only read three":
  - Agents: TauricResearch/TradingAgents, virattt/ai-hedge-fund, HKUDS/AI-Trader.
  - MCPs: alpacahq/alpaca-mcp-server, krakenfx/kraken-cli, financial-datasets/mcp-server.
  - Skills: tradermonty/claude-trading-skills, himself65/finance-skills, RKiding/Awesome-finance-skills.
  - Also notable: TraderAlice/OpenAlice (approval workflow), NoFxAiOS/nofx (hard risk limits outside the LLM), mnemox-ai/tradememory-protocol (decision journaling), LuckyOne7777/LLM-Trading-Lab.
- **GitHub connector for Claude:**
  - GitHub's hosted MCP server is https://api.githubcopilot.com/mcp/ (custom connector, OAuth through the "Claude Github MCP Connector" GitHub App).
  - It can't create repos ("403 Resource not accessible by integration"), so create them by hand.
  - Repos must have a first commit, and the app needs write access under github.com/settings/installations → Configure → Repository access.
- **Claude app (not Claude Code) adjustments:**
  - No settings.json/hooks, so consent = Robinhood approvals + connector "always ask" + APPROVE codes.
  - No memory between chats, so a private GitHub journal repo holds state (settings.json, state.json, paper/account.json, plans/, trades/, reviews/, HALT).
  - Scheduled tasks are unattended and therefore read-only by default. Optional "broker queue" mode in live: an unattended run may submit ENTRY/PROTECT orders only when Robinhood approvals are verified ON in that run, so they wait for a tap in the Robinhood app.
  - Code execution must be enabled for scripts/swing.py.
- **Two repos:** public jcruz0828/robinhood-swing-copilot (MIT; skill, docs, research, templates) and private jcruz0828/robinhood-swing-journal (your settings and data).
- **Paper simulator rules:**
  - Buy stop-limit fills at the stop if the high reaches it, at the open if it opens between stop and limit, and not at all if it gaps over the limit.
  - A stop gapped through fills at the open.
  - Stop is assumed to hit before target on the same day.
  - 0.05% slippage.
  - Graduation: 4+ weeks, 20+ closed trades, positive expectancy, 95%+ adherence.

## 9. Credits: what came from where
- **evanrc27/swing-agent:** trend filter, pullback entry, 2xATR stop, SMA20 exit, 15-day time stop, 6 positions, 80% gross, halt file, two-key live arming. Made more conservative.
- **tradermonty/claude-trading-skills:** gate sequence, breakout-planner risk defaults, breaker thresholds (secondhand), review metrics, "semi-automated, not auto-execution".
- **kevmyung/swing-trading-agent:** daily three-cycle rhythm, action vocabulary, math in code. Numbers not retrieved.
- **OpenAlice:** stage/commit/approve with a per-trade hash.
- **andrewkng/robinhood-agent:** Robinhood batch limits, earnings calendar size, idempotency, verbatim warnings, read-only default.
- **LLM-Trading-Lab and the live benchmarks:** liquidity floors, re-entry cooldown, gap risk, deterministic rules, portfolio state, one approval per card.
- **hydrogen2/autoswing:** 2-day earnings buffer, block on unknown date.
- **wanweileee/swingtrade:** SPY above 200-day gate.
- **Own, untested defaults:** YELLOW state, vol override, 0.8 correlation cap, limit = stop + 0.5xATR, morning gap rules, 63-day ranking, indicator tolerances, paper fill rules.

## 10. Caveats
- **Verified:**
  - Robinhood support articles
  - tradermonty breakout-trade-planner SKILL.md and docs site
  - evanrc27 README, andrewkng README, OpenAlice docs
  - FINRA weekly archive
  - benchmark papers
- **Secondhand:**
  - kevmyung thresholds (not retrieved)
  - tradermonty breaker numbers (third-party port)
  - LangAlpha's description of place_advanced_order
  - Finder.com approvals rollout claim
  - Robinhood options/crypto rollout dates (X excerpts)
  - GFV counts
- **Not investigated in depth:** TradingAgents internals, NoFx, ai-hedge-fund, staskh/himself65/claude-equity-research skills, tradememory-protocol, lumibot, Alpha Arena results, Robinhood extended-hours and fractional rules for agents.

## 11. Repo verification (2026-11-19, Claude Code session)

Three research agents read the source repos directly (`gh api`, read-only) to verify or correct sections 2-4 and 10. Items marked secondhand above that are now verified are listed here; the build follows these values.

**tradermonty/claude-trading-skills (MIT) - breaker numbers now VERIFIED in code**
- `skills/drawdown-circuit-breaker/scripts/check_circuit_breaker.py` L53-57: `max_daily_loss_pct 2.0`, `losing_streak_n 2`, `cooldown_hours 24.0`, `weekly_drawdown_pct 5.0`, `monthly_drawdown_pct 8.0`.
- Measured on realized P&L as % of account size; week starts Monday, month on the 1st, America/New_York. Daily → HALTED until next ET weekday; weekly → next Monday; monthly → 1st of next month; streak → COOLDOWN until last loss + 24 h.
- `pnl >= 0` (breakeven) breaks a losing streak. Missing/conflicting state fails closed as HALTED; empty state = TRADING_ALLOWED.
- pre-trade-discipline-gate: decisions GO < NO_ACTIONABLE_ORDERS < REVIEW_REQUIRED < NO_GO (worst wins). NO_GO on: entry not in written plan, stop not predefined, size not within plan, actual risk > planned, losing exit within the revenge window (24 h), exposure REDUCE_ONLY/CASH_PRIORITY, breaker COOLDOWN/HALTED. REVIEW_REQUIRED on missing/NaN risk dollars or unreadable regime/breaker artifacts.
- position-sizer: `shares = floor(account × risk% / (entry − stop))`; ATR stop default 2.0×; caps by max position % and remaining sector room; always rounds down. Recommends total heat ≤ 6-8%.
- SKILL.md convention: frontmatter `name` + `description` only; sections Overview / When to Use / Prerequisites / Workflow (Step N) / Output Format / Resources / Key Principles. Tests: pytest per skill, CI with ruff + codespell.

**kevmyung/swing-trading-agent (Apache-2.0) - thresholds now RETRIEVED (`config/settings.py` L71-124)**
- 2% risk per trade; 8 soft / 12 hard max positions; 2.0× ATR stop; 15% max drawdown; 30% max sector; 8% portfolio heat ceiling; 4% correlated-heat cap at correlation > 0.7; min entry R:R 1.5; gap threshold 2%; re-entry cooldown 3 days; screener min avg volume 1M; ATR% between 1% and 8%.
- Drawdown tiers from high-water mark: 0-5% → 1.0× size, 5-10% → 0.75×, 10-15% → 0.5×, ≥ 15% → halt new entries.
- Trailing stop = highest **close** since entry − N×ATR (N 1.5-2.0 by conviction), skipped for positions held < 2 days, breakeven lock at +8%. Stops never widen. Earnings: hard block within 2 days.
- Indicators: TA-Lib or Wilder fallback (`ewm(alpha=1/n, min_periods=n, adjust=False)`).

**evanrc27/swing-agent (no license: ideas only)** - `strategy.py`: SMA50 rising = `sma50[-1] > sma50[-10]`; pullback `min(RSI yesterday, today) <= 45`; turn `RSI today > yesterday and close > yesterday's high`; ≥ 205 bars; exits in order stop → target (4×ATR = 2R) → 15-day time stop (counts weekdays, not holidays) → close < SMA20 once held ≥ 2 days; Wilder RSI/ATR.

**Vipuld14/LIVE-swing-trading-agent (no license)** - lost to buy-and-hold 2009-2017 (CAGR 9.38% vs 17.44%) with lower drawdown; an ATR trailing stop under-performed a fixed target in 4 of 5 periods (OOS Sharpe 0.79 → 0.26); a regime overlay helped.

**wanweileee/swingtrade (no license)** - buy-stop at the setup bar's high valid 5 days; breakeven at +1R, then chandelier from highest high since entry − 3×ATR; SPY > 200-day filter; RSI max 50 in v2 (45 in v1).

**hydrogen2/autoswing (no license)** - daily loss halt 3%, sticky drawdown kill at 15% cleared only by an explicit `--i-am-sure` reset; tightening the stop cap to 5% collapsed the edge.

**andrewkng/robinhood-agent** - PreToolUse guard is an allowlist + denylist (reads allowed; all `place_*`, `cancel_*`, `exercise_option` denied in read-only mode). Historicals: omit `interval` for ~2,500 bars; explicit-interval range ≤ 5,000 bars; 1-minute interval is `minute`; skip `interpolated: true`. Fresh UUID `ref_id` per logical order, reused on retries. With approvals ON, a review returns `customer_approval_required: true` and `place_*` queues it for in-app approval.

**Robinhood historicals shape - VERIFIED with one read-only call (SPY daily)**: `{"data":{"results":[{"symbol","interval","bounds","bars":[{"begins_at","open_price","close_price","high_price","low_price","volume","session"}]}]},"guide":"..."}`. Prices are strings, volume an integer, `begins_at` is UTC; the guide notes the latest bar's close is not the official settled close (use `get_equity_quotes`).

**LangAlpha PR #630** - `place_advanced_order(account_number, symbol, side, quantity, take_profit_limit_price, stop_loss_stop_price, time_in_force, market_hours, ref_id)`; OCO pair: take-profit **limit** leg + stop-loss **stop-market** leg; either fill cancels the other. With approvals ON, `place_*` returns an `approval_id` tracked via `get_trade_approvals(approval_ids=[...])`. Response shapes are assumed (Robinhood publishes input schemas only).

**OpenAlice** - commit hash = `sha256(JSON{message, operations, timestamp, parentHash})[:8]`; push/reject require the expected pending hash (a stale UI cannot approve different operations); one pending commit at a time.

**Claude app capabilities** - the built-in GitHub integration is read-only; the GitHub MCP connector can write but has known 403 failures (fixes: grant the repo in the GitHub App installation, revoke and reconnect, or use a fine-grained token). Skills upload as a ZIP and run Python with code execution on; skill scripts cannot call connectors (Claude makes the MCP calls and passes results to Python). The user confirmed on 2026-11-19 that the GitHub connector works in their Claude app.

**Design decisions taken from this verification**
1. Exits: fixed 2R target + breakeven at +1R; **no chandelier** in v1 (a 2R take-profit closes trades before a +2R trail could act).
2. Indicators: Wilder RSI/ATR, ≥ 250 bars warm-up; time stop counts NYSE trading days with a holiday table.
3. Breaker semantics copied from tradermonty (realized P&L, ET calendar, breakeven resets streak, fail closed); plus a sticky −15% peak lock cleared only by `CLEAR HALT <code>`.
4. Gate adds R:R ≥ 1.5 at the live price, a 24 h revenge window, and an ATR% 1-8% liquidity band.
5. Approval codes follow OpenAlice: chained 8-char hash, one pending card, stale codes rejected.
6. All code in this repo is original; ideas from unlicensed repos are credited, not copied.

## Sources
- https://robinhood.com/us/en/support/articles/trading-with-your-agent/
- https://robinhood.com/us/en/support/articles/robinhood-agents-overview/
- https://www.robinhood.com/us/en/support/articles/order-types
- https://robinhood.com/us/en/agentic-trading
- https://robinhood.com/newsroom/robinhood-is-now-open-to-agents
- https://www.wallstreetsurvivor.com/robinhood-agentic-trading/
- https://finks.ai/api/mcp/robinhood
- https://medium.com/p/33d3725a23e0 (no paper trading; {data, guide} wrapper)
- https://www.nasdaq.com/articles/robinhood-markets-bets-agentic-ai-trading-assets-climb-350-billion
- https://github.com/andrewkng/robinhood-agent
- https://github.com/ginlix-ai/LangAlpha/pull/630
- https://github.com/evanrc27/swing-agent
- https://github.com/kevmyung/swing-trading-agent
- https://github.com/tradermonty/claude-trading-skills
- https://github.com/tradermonty/claude-trading-skills/blob/main/skills/breakout-trade-planner/SKILL.md
- https://github.com/tradermonty/claude-trading-skills/blob/main/workflows/README.md
- https://tradermonty.github.io/claude-trading-skills/en/skills/vcp-screener/
- https://tradermonty.github.io/claude-trading-skills/en/skill-catalog/
- https://tessl.io/registry/skills/github/tradermonty/claude-trading-skills/uptrend-analyzer
- https://github.com/irsyadfptr/mercury/pull/1
- https://skillstore.io/skills/tradermonty-pre-trade-discipline-gate
- https://www.skills.sh/tradermonty/claude-trading-skills/drawdown-circuit-breaker
- https://github.com/LLMQuant/awesome-trading-agents
- https://www.openalice.ai/docs/core-concepts/trading-as-git
- https://www.openalice.ai/docs/trading/accounts-and-brokers
- https://www.researchgate.net/publication/397322519_LiveTradeBench_Seeking_Real-World_Alpha_with_Large_Language_Models
- https://arxiv.org/pdf/2510.11695
- https://arxiv.org/pdf/2602.18481
- https://arxiv.org/pdf/2609.33470
- https://arxiv.org/pdf/2605.05580
- https://github.com/LuckyOne7777/LLM-Trading-Lab/blob/main/Experiments/chatgpt_micro-cap/evaluation/evaluation_report.md
- https://www.finra.org/compliance-tools/weekly-archive/04152026
- https://therighttrader.com/learn/trading-basics/pattern-day-trader-rule
- https://www.cmelitegroup.com/knowledge-hub/pdt-rule-2026/
- https://carry.com/learn/what-is-a-good-faith-violation
- https://github.com/wanweileee/swingtrade
- https://github.com/hydrogen2/autoswing
- https://github.com/Vipuld14/LIVE-swing-trading-agent
- https://claude.com/docs/third-party/claude-desktop/connectors-github.md
- https://github.com/apps/claude-github-mcp-connector
- https://github.com/tradermonty/claude-trading-skills/blob/main/skills/drawdown-circuit-breaker/scripts/check_circuit_breaker.py (§11)
- https://github.com/kevmyung/swing-trading-agent/blob/main/config/settings.py (§11)
- https://github.com/TraderAlice/OpenAlice (§11)
- https://support.claude.com/en/articles/10167454-using-the-github-integration (§11)
- https://support.claude.com/en/articles/12512180-use-skills-in-claude (§11)
- https://github.com/github/github-mcp-server/issues/1610 (§11)
