#!/usr/bin/env python3
"""PreToolUse guard for Robinhood MCP tools (Claude Code only).

Claude Code pipes the pending tool call as JSON on stdin. This script prints a
permission decision and never calls Robinhood itself.

Policy, from most to least restrictive:
  1. Options, crypto and option exercise are always DENIED. The copilot is
     equities-only.
  2. A HALT file means new BUY entries are DENIED. Protective sells, exit
     pairs and cancels still go through the normal ask flow.
  3. Unattended runs are read-only. A run counts as unattended when
     SWING_COPILOT_HEADLESS=1 or permission_mode is bypassPermissions/dontAsk.
     Every order write is DENIED, unless SWING_COPILOT_SCHEDULED_MODE=broker_queue,
     which lets place_equity_order / place_advanced_order fall through to
     Robinhood's own approval queue. The skill must verify approvals are ON in
     that same run.
  4. Interactive order writes (place_*, cancel_*, decline_trade_approval) always
     get "ask", even if a broader allow rule exists. This is consent layer 2.
  5. Reads (get_*, search, run_scan, preview_*, review_*) and other non-order
     calls pass through untouched.

If stdin is malformed, the script exits with code 2, which blocks the call (fail
closed). Modelled on the read-only guard in andrewkng/robinhood-agent; this code
is original.
"""
from __future__ import annotations

import json
import os
import sys

PREFIXES = ("mcp__robinhood-trading__", "mcp__claude_ai_Robinhood__", "mcp__robinhood__")
READ_PREFIXES = ("get_", "search", "run_scan", "preview_", "review_")
NEVER = {"place_option_order", "place_crypto_order", "exercise_option"}
QUEUEABLE = {"place_equity_order", "place_advanced_order"}


def is_robinhood(tool: str) -> bool:
    return tool.startswith(PREFIXES) or (tool.startswith("mcp__") and "robinhood" in tool.lower())


def halt_present(env: dict, cwd: str | None) -> bool:
    candidates = []
    if env.get("SWING_JOURNAL_DIR"):
        candidates.append(os.path.join(env["SWING_JOURNAL_DIR"], "HALT"))
    base = cwd or os.getcwd()
    candidates += [os.path.join(base, "HALT"),
                   os.path.join(base, "..", "robinhood-swing-journal", "HALT")]
    return any(os.path.exists(p) for p in candidates)


def decide(event: dict, env: dict | None = None):
    """Return None (no opinion) or (decision, reason) with decision in {deny, ask}."""
    env = os.environ if env is None else env
    tool = str(event.get("tool_name") or "")
    if not is_robinhood(tool):
        return None
    op = tool.split("__")[-1]
    if op.startswith(READ_PREFIXES):
        return None
    if op in NEVER:
        return ("deny", f"{op}: options, crypto and exercises are never automated by the swing copilot")
    args = event.get("tool_input") or {}
    side = str(args.get("side") or "").lower()
    is_entry = op == "place_equity_order" and side != "sell"
    is_order_write = op.startswith("place_") or op.startswith("cancel_") or op == "decline_trade_approval"
    headless = env.get("SWING_COPILOT_HEADLESS") == "1" or \
        event.get("permission_mode") in ("bypassPermissions", "dontAsk")

    if is_entry and halt_present(env, event.get("cwd")):
        return ("deny", "HALT file present: new entries are blocked. Delete HALT in the journal to resume.")
    if headless and is_order_write:
        if env.get("SWING_COPILOT_SCHEDULED_MODE") == "broker_queue" and op in QUEUEABLE:
            return None
        return ("deny", "unattended run: scheduled_runs is strict (read-only). Run interactively to trade.")
    if is_order_write:
        return ("ask", "Robinhood order action. Confirm it matches the trade card you approved "
                       "(same symbol, side, quantity, prices and ref_id).")
    return None


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
        if not isinstance(event, dict):
            raise ValueError("event is not an object")
    except Exception as exc:  # fail closed
        print(f"order_guard: unreadable hook input ({exc}); blocking", file=sys.stderr)
        return 2
    result = decide(event)
    if result is None:
        return 0
    decision, reason = result
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": decision,
                                             "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
