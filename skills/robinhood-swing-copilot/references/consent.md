# Consent: nothing executes without the user

The copilot is **propose-only**. It computes, checks and presents trades. A
human approves every single order. Consent is enforced in three stacked layers,
so a failure in one layer is caught by the next.

## The three layers

| # | Layer | Where | Who enforces it | How to verify |
|---|---|---|---|---|
| 1 | **Robinhood trade approvals ON** | Robinhood app → MCP account → Agent Settings → Safety Controls | Robinhood: `place_*` returns an `approval_id` and the order waits for the user's tap in the app | `get_trade_approval_setting` at every preflight |
| 2 | **Tool permission "always ask"** | Claude app: Settings → Connectors → Robinhood → set every `place_*`, `cancel_*` and `decline_*` tool to "Ask". Claude Code: `.claude/settings.json` `ask` list plus the `order_guard.py` hook | The Claude client pops a confirmation before the tool runs | The user sees a permission prompt |
| 3 | **Typed approval code** | In chat | `swing.py approve`: only an exact `APPROVE <code>` matching the single pending card | The card shows the code |

- **Approvals OFF by default for MCP accounts.** Robinhood turns approvals ON
  by default for its built-in agents but OFF for external (MCP) agent
  accounts, so preflight must check every time.
- **If approvals are OFF**, the user must either switch them ON or type exactly
  `I ACCEPT CHAT-ONLY CONSENT`. That covers this session only; record it in
  the daily plan. Never treat "ok", "yes", "sure", or silence as consent.

## Trade cards (stage → commit → push)

The model is OpenAlice's "trading as git":
- **Stage:** call `review_equity_order` / `review_advanced_order` and copy
  Robinhood's warnings **verbatim** into the card.
- **Commit:** `swing.py card` builds the card and an **8-character code**:
  `sha256(card + created_at + previous code)[:8]`. It marks the card as the
  single `pending_card` in `state.json`.
- **Push:** the user types `APPROVE <code>`. `swing.py approve` validates it,
  and only then does the agent call `place_*` with the card's exact arguments
  and `ref_id`.

**Card kinds**
- `ENTRY`: a new buy stop-limit.
- `PROTECT`: the exit pair after a fill (take-profit limit plus stop-loss stop).
- `MOVE_STOP`: cancel/replace the exit pair with a higher stop.
- `EXIT`: sell now, for an SMA20 close, time stop, or user request.
- `CANCEL`: cancel a working order, or decline a stale Robinhood approval.

**Every card shows:**
- the account (masked), approvals state, regime and breaker
- the action and the exact order arguments
- the thesis
- stop, target, shares, risk in dollars and percent
- the portfolio after the trade
- events (earnings, macro)
- Robinhood's review warnings, verbatim
- the exit plan, `ref_id`, and expiry

**Approval rules (enforced by swing.py)**
- Only an exact `APPROVE <code>` counts. It is case-sensitive, takes one
  code, and nothing else.
- **No batch approvals.** "approve all", "APPROVE a b", "yes" and "go" are all
  refused.
- **One pending card at a time.** A new card cannot be staged until the
  pending one is approved, rejected (`REJECT <code>`), or expired.
- **Codes expire** at 23:59:59 ET on the day they are created.
- **Reprice rule:** if the price moved more than 0.5×ATR since the card was
  built, the approval is refused; build a new card.
- **Stale codes are rejected.** Each code chains to the previous one, so an
  old code cannot approve a different card.
- **After approval,** place **exactly** what the card says. If anything must
  change (price, size, type), build a new card.
- **Retries** after a transport error reuse the **same** `ref_id`. Robinhood
  de-duplicates on it, so a retry never creates a second order.

## Never automated (refuse, explain, offer the safe alternative)

- Raising `risk_pct` or `max_positions`, or changing any rule outside the
  monthly review.
- Clearing a HALT, the peak-drawdown lock, or a breaker.
- Market orders outside regular hours.
- Options, crypto, short selling, margin.
- **Moving a stop down**, or removing a protective order without replacing it.
- Averaging down or adding to a position.
- Trading in any account other than the one with `agentic_allowed: true`.
- Turning Robinhood trade approvals OFF, or asking the user to.
- Changing rules mid-week because of recent results.

## Kill switch

Any one of these stops new entries:
1. The user types **KILL** or **HALT** in chat. The agent immediately creates
   a `HALT` file in the journal with the reason and timestamp, commits it, and
   from then on only proposes protective actions.
2. A `HALT` file exists in the journal repo. The user can add it from the
   GitHub app on their phone.
3. The connector is disconnected in Robinhood (Agent Settings), which cuts
   access entirely.
4. The automatic peak-drawdown lock (−15%).

Only the user deletes `HALT`. The agent never does.

## Scheduled runs

Unattended runs default to **read-only** (`scheduled_runs: "strict"`). The
optional `broker_queue` mode allows only ENTRY and PROTECT placements, and only
after approvals are verified ON in that same run, so every order still waits for
a tap in the Robinhood app. Never disable the client's "always ask" setting for
scheduled tasks.
