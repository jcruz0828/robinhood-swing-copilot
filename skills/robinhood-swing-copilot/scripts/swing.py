#!/usr/bin/env python3
"""swing.py - the deterministic engine behind the robinhood-swing-copilot skill.

The LLM never does trading math. Every number shown on a trade card comes
from this file. It uses only the Python standard library (3.9+) so it runs
unchanged in Claude Code, in the Claude app's code-execution sandbox, and in CI.

Usage (every command reads JSON and writes JSON to stdout):

    python3 swing.py <command> [--input FILE|-] [--rules FILE] [--out FILE]

Commands
    unwrap       Robinhood {data, guide} historicals payload -> {SYMBOL: [bars]}
    indicators   latest SMA/RSI/ATR/Bollinger snapshot per symbol (+ cross-check)
    corr         pairwise 60-day return correlation
    regime       SPY regime: GREEN / YELLOW / RED (+ volatility override)
    signal       trend-pullback entry check per symbol -> trigger and limit
    size         position size, stop, 2R target from equity and risk %
    breaker      circuit breaker -> TRADING_ALLOWED / COOLDOWN / HALTED
    clear-halt   clear a sticky drawdown lock with "CLEAR HALT <code>"
    gate         pre-trade gate -> GO / REVIEW_REQUIRED / NO_GO per candidate
    card         build a trade card + 8-char approval code (stages it as pending)
    approve      validate a typed "APPROVE <code>" against the pending card
    reject       discard the pending card with "REJECT <code>"
    paper        paper account: init / place / step (step catches up missed days)
    review       win rate, average R, expectancy, profit factor, graduation check
    reconcile    match approved cards to Robinhood orders; flag UNPROTECTED
    calendar     NYSE trading-day helper (is_trading_day / next / between)
    selftest     built-in smoke test; exits 1 on failure

Exit codes: 0 ok, 1 selftest failure, 2 bad input / refused action.
Not financial advice. You are responsible for every order your agent places.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone

VERSION = "1.0.0"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RULES = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "config", "rules.json"))


class SwingError(Exception):
    """Bad input or a refused action. The CLI maps it to exit code 2."""


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

def load_rules(path: str | None = None) -> dict:
    with open(path or DEFAULT_RULES, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# Time and the NYSE calendar (all times are naive US/Eastern)
# --------------------------------------------------------------------------

try:  # zoneinfo needs tzdata; fall back to a fixed EST offset if missing.
    from zoneinfo import ZoneInfo

    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - depends on host
    _ET = None

NYSE_HOLIDAYS = {
    # 2025
    date(2025, 1, 1), date(2025, 1, 9), date(2025, 1, 20), date(2025, 2, 17),
    date(2025, 4, 18), date(2025, 5, 26), date(2025, 6, 19), date(2025, 7, 4),
    date(2025, 9, 1), date(2025, 11, 27), date(2025, 12, 25),
    # 2026
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
    # 2027
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26),
    date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6),
    date(2027, 11, 25), date(2027, 12, 24),
}
CALENDAR_YEARS = (2025, 2027)


def to_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def parse_dt(value, default_time: time = time(16, 0)) -> datetime:
    """Parse an ISO date/datetime into naive US/Eastern.

    Date-only strings get `default_time` (16:00, the close). Aware datetimes
    (e.g. Robinhood's UTC "Z" timestamps) are converted to Eastern.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, default_time)
    else:
        s = str(value).strip()
        if len(s) == 10:
            dt = datetime.combine(date.fromisoformat(s), default_time)
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(_ET or timezone(timedelta(hours=-5))).replace(tzinfo=None)
    return dt


def is_trading_day(d) -> bool:
    d = to_date(d)
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS


def calendar_covered(d) -> bool:
    return CALENDAR_YEARS[0] <= to_date(d).year <= CALENDAR_YEARS[1]


def next_trading_day(d) -> date:
    d = to_date(d) + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def prev_trading_day(d) -> date:
    d = to_date(d) - timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def trading_days_between(a, b) -> int:
    """Number of trading days in (a, b]. Negative when b is before a."""
    a, b = to_date(a), to_date(b)
    if a == b:
        return 0
    sign = 1
    if b < a:
        a, b, sign = b, a, -1
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if is_trading_day(d):
            n += 1
    return n * sign


def trading_dates(start, count: int) -> list:
    d = to_date(start)
    while not is_trading_day(d):
        d += timedelta(days=1)
    out = [d]
    while len(out) < count:
        d = next_trading_day(d)
        out.append(d)
    return out


# --------------------------------------------------------------------------
# Robinhood payloads
# --------------------------------------------------------------------------

_BAR_ALIASES = {
    "date": ("begins_at", "date", "timestamp", "time", "t"),
    "open": ("open_price", "open", "o"),
    "high": ("high_price", "high", "h"),
    "low": ("low_price", "low", "l"),
    "close": ("close_price", "close", "c"),
    "volume": ("volume", "v"),
}


def unwrap_data(payload):
    """Strip Robinhood's {data, guide} envelope. `guide` is advisory text only."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    if isinstance(payload, dict) and "data" in payload and set(payload) <= {"data", "guide", "meta"}:
        return payload["data"]
    return payload


def _pick(d: dict, names):
    for n in names:
        if n in d and d[n] not in (None, ""):
            return d[n]
    return None


def normalize_bar(raw: dict):
    vals = {k: _pick(raw, names) for k, names in _BAR_ALIASES.items()}
    if any(vals[k] is None for k in ("date", "open", "high", "low", "close")):
        return None
    try:
        bar = {
            "date": str(vals["date"])[:10],
            "open": float(vals["open"]),
            "high": float(vals["high"]),
            "low": float(vals["low"]),
            "close": float(vals["close"]),
            "volume": float(vals["volume"]) if vals["volume"] is not None else 0.0,
        }
    except (TypeError, ValueError):
        return None
    return bar


def unwrap(payload) -> dict:
    """Return {SYMBOL: [bars sorted by date]} from any supported shape.

    Supported: Robinhood {"data": {"results": [{"symbol", "bars": [...]}]}, "guide": ...},
    a bare {"results": [...]}, a single {"symbol", "bars"}, {SYMBOL: [bars]}, or [bars].
    Bars flagged `interpolated: true` are dropped; duplicate dates keep the last.
    """
    data = unwrap_data(payload)
    results = None
    if isinstance(data, dict):
        if "results" in data:
            results = data["results"]
        elif "bars" in data:
            results = [data]
        elif data and all(isinstance(v, list) for v in data.values()):
            results = [{"symbol": k, "bars": v} for k, v in data.items()]
    elif isinstance(data, list):
        if data and isinstance(data[0], dict) and "bars" in data[0]:
            results = data
        else:
            results = [{"symbol": "UNKNOWN", "bars": data}]
    if results is None:
        raise SwingError("unrecognized historicals payload: expected data.results[].bars[]")
    out = {}
    for r in results:
        sym = str(r.get("symbol") or "UNKNOWN").upper()
        by_date = {}
        for raw in r.get("bars") or r.get("historicals") or []:
            if raw.get("interpolated"):
                continue
            bar = normalize_bar(raw)
            if bar:
                by_date[bar["date"]] = bar
        out[sym] = [by_date[k] for k in sorted(by_date)]
    return out


def _bars_from_input(obj) -> dict:
    """Accept either ready {SYMBOL: [bars]} or any raw Robinhood payload."""
    if isinstance(obj, dict) and obj and all(
        isinstance(v, list) and (not v or {"date", "close"} <= set(v[0])) for v in obj.values()
    ):
        return {k.upper(): v for k, v in obj.items()}
    return unwrap(obj)


# --------------------------------------------------------------------------
# Indicators (Wilder smoothing, matches TradingView / Robinhood after warm-up)
# --------------------------------------------------------------------------

def sma(values, n: int) -> list:
    out = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def _rsi_from(ag: float, al: float) -> float:
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def rsi(closes, n: int = 14) -> list:
    """Wilder RSI. First value at index n (seeded with simple averages)."""
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    ag, al = gains / n, losses / n
    out[n] = _rsi_from(ag, al)
    for i in range(n + 1, len(closes)):
        ch = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(ch, 0.0)) / n
        al = (al * (n - 1) + max(-ch, 0.0)) / n
        out[i] = _rsi_from(ag, al)
    return out


def true_ranges(highs, lows, closes) -> list:
    tr = []
    for i in range(len(closes)):
        if i == 0:
            tr.append(highs[0] - lows[0])
        else:
            pc = closes[i - 1]
            tr.append(max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc)))
    return tr


def atr(highs, lows, closes, n: int = 14) -> list:
    """Wilder ATR. First value at index n (mean of TR[1..n])."""
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    tr = true_ranges(highs, lows, closes)
    a = sum(tr[1:n + 1]) / n
    out[n] = a
    for i in range(n + 1, len(closes)):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


def bollinger(closes, n: int = 20, k: float = 2.0) -> list:
    out = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        w = closes[i - n + 1:i + 1]
        m = sum(w) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
        out[i] = {"mid": m, "upper": m + k * sd, "lower": m - k * sd}
    return out


def returns_by_date(bars) -> dict:
    out = {}
    for i in range(1, len(bars)):
        pc = bars[i - 1]["close"]
        if pc:
            out[bars[i]["date"]] = bars[i]["close"] / pc - 1.0
    return out


def correlation(bars_a, bars_b, lookback: int = 60):
    ra, rb = returns_by_date(bars_a), returns_by_date(bars_b)
    common = sorted(set(ra) & set(rb))[-lookback:]
    if len(common) < max(20, lookback // 2):
        return None
    xs = [ra[d] for d in common]
    ys = [rb[d] for d in common]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def snapshot(bars, rules: dict | None = None, idx: int | None = None) -> dict:
    """Latest (or bar `idx`) indicator values used by regime/signal/size."""
    rules = rules or load_rules()
    if not bars:
        raise SwingError("no bars")
    i = len(bars) - 1 if idx is None else idx
    closes = [b["close"] for b in bars[: i + 1]]
    highs = [b["high"] for b in bars[: i + 1]]
    lows = [b["low"] for b in bars[: i + 1]]
    vols = [b.get("volume", 0.0) for b in bars[: i + 1]]
    rp = rules["entry"]["rsi_period"]
    ap = rules["sizing"]["atr_period"]
    lb = rules["entry"]["pullback_lookback"]
    slope = rules["regime"]["slope_lookback"]
    s20, s50, s200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    r = rsi(closes, rp)
    a = atr(highs, lows, closes, ap)
    bb = bollinger(closes, 20, 2.0)
    v50 = sma(vols, 50)
    recent_rsi = [x for x in r[-lb:] if x is not None]
    swing_n = rules["sizing"]["swing_low_lookback"]
    last = bars[i]
    snap = {
        "date": last["date"],
        "bars": i + 1,
        "open": last["open"],
        "high": last["high"],
        "low": last["low"],
        "close": last["close"],
        "prev_high": bars[i - 1]["high"] if i >= 1 else None,
        "prev_close": bars[i - 1]["close"] if i >= 1 else None,
        "sma20": s20[-1],
        "sma50": s50[-1],
        "sma200": s200[-1],
        "sma50_prev": s50[-1 - slope] if len(s50) > slope else None,
        "rsi": r[-1],
        "rsi_prev": r[-2] if len(r) >= 2 else None,
        "rsi_min_recent": min(recent_rsi) if recent_rsi else None,
        "atr": a[-1],
        "atr_pct": (a[-1] / last["close"] * 100.0) if a[-1] and last["close"] else None,
        "bollinger": bb[-1],
        "avg_volume_50": v50[-1],
        "low_recent": min(lows[-swing_n:]),
        "day_change_pct": ((last["close"] / bars[i - 1]["close"] - 1.0) * 100.0) if i >= 1 else None,
    }
    return snap


def cross_check(ours: dict, theirs: dict, rules: dict) -> list:
    """Compare our values with Robinhood's get_equity_technical_indicators output."""
    tol = rules["indicator_tolerance"]
    issues = []

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    for key, (kind, limit) in {
        "rsi": ("abs", tol["rsi_abs"]),
        "sma20": ("pct", tol["sma_pct"]),
        "sma50": ("pct", tol["sma_pct"]),
        "sma200": ("pct", tol["sma_pct"]),
        "atr": ("pct", tol["atr_pct"]),
    }.items():
        a, b = ours.get(key), num(theirs.get(key))
        if a is None or b is None:
            continue
        diff = abs(a - b) if kind == "abs" else abs(a - b) / abs(b) * 100.0 if b else 0.0
        if diff > limit:
            issues.append({"field": key, "ours": round(a, 4), "robinhood": b,
                           "diff": round(diff, 3), "tolerance": limit, "unit": kind})
    return issues


# --------------------------------------------------------------------------
# Regime, signal, sizing
# --------------------------------------------------------------------------

_LEVELS = ["GREEN", "YELLOW", "RED"]


def regime(bars, rules: dict) -> dict:
    cfg = rules["regime"]
    need = cfg["sma_slow"] + cfg["slope_lookback"] + 1
    if len(bars) < need:
        state, reasons, snap = "RED", [f"insufficient data: {len(bars)} bars < {need} (fail closed)"], None
    else:
        snap = snapshot(bars, rules)
        c, f, s, fp = snap["close"], snap["sma50"], snap["sma200"], snap["sma50_prev"]
        rising = f > fp
        reasons = [
            f"close {c:.2f} {'>' if c > s else '<='} SMA200 {s:.2f}",
            f"SMA50 {f:.2f} {'>' if f > s else '<='} SMA200",
            f"SMA50 {'rising' if rising else 'flat/falling'} vs {cfg['slope_lookback']} bars ago ({fp:.2f})",
            f"close {'>' if c > f else '<='} SMA50 {f:.2f}",
        ]
        if c <= s:
            state = "RED"
        elif f > s and rising and c > f:
            state = "GREEN"
        else:
            state = "YELLOW"
        override = []
        if snap["atr_pct"] is not None and snap["atr_pct"] > cfg["vol_override_atr_pct"]:
            override.append(f"ATR/close {snap['atr_pct']:.2f}% > {cfg['vol_override_atr_pct']}%")
        if snap["day_change_pct"] is not None and snap["day_change_pct"] <= -cfg["vol_override_day_drop_pct"]:
            override.append(f"day change {snap['day_change_pct']:.2f}% <= -{cfg['vol_override_day_drop_pct']}%")
        if override and state != "RED":
            state = _LEVELS[_LEVELS.index(state) + 1]
            reasons.append("volatility override (one level down): " + "; ".join(override))
    limits = dict(cfg["states"][state])
    out = {"symbol": cfg["symbol"], "state": state, "reasons": reasons, "limits": limits,
           "action": "NEW_ENTRY_ALLOWED" if limits["new_entries"] else "REDUCE_ONLY"}
    if snap:
        out["snapshot"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in snap.items()
                           if k not in ("bollinger",)}
    return out


def signal(symbol: str, bars, rules: dict, meta: dict | None = None) -> dict:
    """Trend template + RSI pullback entry. All checks must pass for setup=True."""
    meta = meta or {}
    sc, en = rules["screen"], rules["entry"]
    checks = {}
    if len(bars) < sc["min_bars"]:
        checks["history"] = {"pass": False, "value": len(bars), "rule": f">= {sc['min_bars']} bars"}
        return {"symbol": symbol, "setup": False, "checks": checks, "failed": ["history"]}
    s = snapshot(bars, rules)

    def chk(name, ok, value, rule):
        checks[name] = {"pass": bool(ok), "value": value, "rule": rule}

    chk("history", True, len(bars), f">= {sc['min_bars']} bars")
    chk("price", s["close"] >= sc["min_price"], round(s["close"], 2), f">= {sc['min_price']}")
    chk("avg_volume_50", (s["avg_volume_50"] or 0) >= sc["min_avg_volume_50"],
        round(s["avg_volume_50"] or 0), f">= {sc['min_avg_volume_50']}")
    mc = meta.get("market_cap")
    chk("market_cap", mc is not None and float(mc) >= sc["min_market_cap"], mc,
        f">= {sc['min_market_cap']} (missing = fail)")
    chk("atr_pct", s["atr_pct"] is not None and sc["atr_pct_min"] <= s["atr_pct"] <= sc["atr_pct_max"],
        round(s["atr_pct"], 3) if s["atr_pct"] else None, f"{sc['atr_pct_min']}..{sc['atr_pct_max']}%")
    chk("tradable", meta.get("tradable", True) is True, meta.get("tradable", True), "tradable")
    lev = bool(meta.get("leveraged_etf", False))
    chk("not_leveraged_etf", not (sc["exclude_leveraged_etfs"] and lev), lev, "no leveraged/inverse ETFs")
    chk("sma50_above_sma200", s["sma50"] > s["sma200"], [round(s["sma50"], 2), round(s["sma200"], 2)], "SMA50 > SMA200")
    chk("close_above_sma200", s["close"] > s["sma200"], [round(s["close"], 2), round(s["sma200"], 2)], "close > SMA200")
    chk("sma50_rising", s["sma50"] > s["sma50_prev"], [round(s["sma50"], 2), round(s["sma50_prev"], 2)],
        f"SMA50 > SMA50 {rules['regime']['slope_lookback']} bars ago")
    chk("rsi_pullback", s["rsi_min_recent"] is not None and s["rsi_min_recent"] <= en["rsi_pullback_max"],
        round(s["rsi_min_recent"], 2) if s["rsi_min_recent"] is not None else None,
        f"min RSI({en['rsi_period']}) over last {en['pullback_lookback']} sessions <= {en['rsi_pullback_max']}")
    chk("rsi_turning_up", s["rsi"] is not None and s["rsi_prev"] is not None and s["rsi"] > s["rsi_prev"],
        [round(s["rsi"], 2), round(s["rsi_prev"], 2)], "RSI today > RSI yesterday")
    chk("close_above_prior_high", s["close"] > s["prev_high"], [round(s["close"], 2), round(s["prev_high"], 2)],
        "close > prior high")
    failed = [k for k, v in checks.items() if not v["pass"]]
    trigger = round(s["high"] + en["trigger_offset"], 2)
    limit = round(trigger + en["limit_offset_atr"] * s["atr"], 2)
    return {
        "symbol": symbol,
        "date": s["date"],
        "setup": not failed,
        "failed": failed,
        "checks": checks,
        "trigger": trigger,
        "limit": limit,
        "atr": round(s["atr"], 4),
        "low_recent": round(s["low_recent"], 4),
        "close": round(s["close"], 4),
        "order": {"type": "buy_stop_limit", "stop_price": trigger, "limit_price": limit,
                  "time_in_force": "gfd", "session": str(next_trading_day(s["date"]))},
    }


def _floor(x: float) -> int:
    return int(math.floor(x + 1e-9))


def size(entry: float, atr_value: float, low_recent: float, equity: float, settled_cash: float,
         rules: dict, risk_pct: float | None = None, risk_mult: float = 1.0,
         cash_price: float | None = None) -> dict:
    """Shares from risk; stop = entry - max(2xATR, entry - 5-day low x 0.99)."""
    sz, ex = rules["sizing"], rules["exits"]
    if entry <= 0 or atr_value <= 0 or equity <= 0:
        raise SwingError("entry, atr and equity must be positive")
    risk_pct = sz["risk_pct_default"] if risk_pct is None else risk_pct
    allowed = equity * risk_pct / 100.0 * risk_mult
    dist = max(sz["stop_atr_mult"] * atr_value, entry - low_recent * sz["swing_low_buffer"])
    stop = round(entry - dist, 2)
    if stop <= 0:
        raise SwingError("stop would be <= 0")
    dist = entry - stop
    target = round(entry + ex["target_r"] * dist, 2)
    px = cash_price or entry
    caps = {
        "risk": _floor(allowed / dist),
        "max_position": _floor(equity * sz["max_position_pct"] / 100.0 / px),
        "settled_cash": _floor(max(settled_cash, 0.0) / px),
    }
    shares = max(0, min(caps.values()))
    binding = min(caps, key=caps.get)
    return {
        "entry": round(entry, 2),
        "stop": stop,
        "target": target,
        "stop_distance": round(dist, 4),
        "shares": shares,
        "binding_cap": binding,
        "caps": caps,
        "risk_dollars": round(shares * dist, 2),
        "risk_allowed_dollars": round(allowed, 2),
        "risk_pct_of_equity": round(shares * dist / equity * 100.0, 3),
        "position_value": round(shares * px, 2),
        "position_pct": round(shares * px / equity * 100.0, 2),
        "reward_risk": ex["target_r"],
        "breakeven_trigger": round(entry + ex["breakeven_at_r"] * dist, 2),
        "note": "whole shares only" if sz["whole_shares_only"] else "",
    }


# --------------------------------------------------------------------------
# Circuit breaker
# --------------------------------------------------------------------------

_BREAKER_RANK = {"TRADING_ALLOWED": 0, "COOLDOWN": 1, "HALTED": 2}


def _clear_code(since: str) -> str:
    return hashlib.sha256(("CLEAR HALT|" + since).encode()).hexdigest()[:8]


def breaker(inp: dict, rules: dict) -> dict:
    """Realized-P&L breakers + losing streak + sticky peak-drawdown lock + HALT file.

    Input keys: as_of, account_size (or equity), equity, peak_equity, closed_trades
    [{exit_time, pnl, symbol}], halt_file (bool), peak_lock (bool), peak_lock_since.
    Missing or malformed state fails closed as HALTED.
    """
    cfg = rules["breakers"]
    triggered = []
    missing = [k for k in ("as_of", "equity", "peak_equity", "closed_trades") if inp.get(k) is None]
    if missing:
        return {"recommendation": "HALTED", "risk_mult": 0.0,
                "triggered_rules": [{"rule": "incomplete_state_data", "detail": f"missing {missing}",
                                     "severity": "HALTED"}],
                "data_quality": "incomplete", "new_state": {}}
    try:
        now = parse_dt(inp["as_of"])
        equity = float(inp["equity"])
        acct = float(inp.get("account_size") or equity)
        peak = max(float(inp["peak_equity"]), equity)
        trades = sorted(
            ({"exit": parse_dt(t["exit_time"]), "pnl": float(t["pnl"]), "symbol": t.get("symbol")}
             for t in inp["closed_trades"]),
            key=lambda t: t["exit"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"recommendation": "HALTED", "risk_mult": 0.0,
                "triggered_rules": [{"rule": "incomplete_state_data", "detail": str(exc), "severity": "HALTED"}],
                "data_quality": "malformed", "new_state": {}}

    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    day_pnl = sum(t["pnl"] for t in trades if t["exit"].date() == today)
    week_pnl = sum(t["pnl"] for t in trades if week_start <= t["exit"].date() <= today)
    month_pnl = sum(t["pnl"] for t in trades if month_start <= t["exit"].date() <= today)

    def pct(x):
        return x / acct * 100.0 if acct else 0.0

    def open_at(d):
        return datetime.combine(d, time(9, 30)).isoformat()

    if inp.get("halt_file"):
        triggered.append({"rule": "halt_file", "detail": "HALT file present; delete it to resume",
                          "severity": "HALTED", "active_until": "manual"})
    if pct(day_pnl) <= -cfg["daily_loss_pct"]:
        triggered.append({"rule": "daily_loss", "threshold": -cfg["daily_loss_pct"], "observed": round(pct(day_pnl), 3),
                          "severity": "HALTED", "active_until": open_at(next_trading_day(today))})
    if pct(week_pnl) <= -cfg["weekly_loss_pct"]:
        nxt = week_start + timedelta(days=7)
        nxt = nxt if is_trading_day(nxt) else next_trading_day(nxt)
        triggered.append({"rule": "weekly_loss", "threshold": -cfg["weekly_loss_pct"],
                          "observed": round(pct(week_pnl), 3), "severity": "HALTED", "active_until": open_at(nxt)})
    if pct(month_pnl) <= -cfg["monthly_loss_pct"]:
        nm = (month_start + timedelta(days=32)).replace(day=1)
        nm = nm if is_trading_day(nm) else next_trading_day(nm)
        triggered.append({"rule": "monthly_loss", "threshold": -cfg["monthly_loss_pct"],
                          "observed": round(pct(month_pnl), 3), "severity": "HALTED", "active_until": open_at(nm)})

    dd = (peak - equity) / peak * 100.0 if peak else 0.0
    lock = bool(inp.get("peak_lock"))
    since = inp.get("peak_lock_since")
    if dd >= cfg["peak_drawdown_lock_pct"] and not lock:
        lock, since = True, now.isoformat()
    if lock:
        since = since or now.isoformat()
        triggered.append({"rule": "peak_drawdown_lock", "threshold": cfg["peak_drawdown_lock_pct"],
                          "observed": round(dd, 3), "severity": "HALTED", "active_until": "manual",
                          "detail": f"read-only until the user types: CLEAR HALT {_clear_code(since)}"})

    streak = 0
    for t in reversed(trades):
        if t["pnl"] < 0:
            streak += 1
        else:
            break  # breakeven or a win resets the streak
    risk_mult = 1.0
    if streak >= cfg["losing_streak"]:
        risk_mult = cfg["post_streak_risk_mult"]
        until = trades[-1]["exit"] + timedelta(hours=cfg["cooldown_hours"])
        if now < until:
            triggered.append({"rule": "losing_streak", "threshold": cfg["losing_streak"], "observed": streak,
                              "severity": "COOLDOWN", "active_until": until.isoformat()})

    rec = "TRADING_ALLOWED"
    for t in triggered:
        if _BREAKER_RANK[t["severity"]] > _BREAKER_RANK[rec]:
            rec = t["severity"]
    if rec != "TRADING_ALLOWED":
        risk_mult = 0.0
    return {
        "recommendation": rec,
        "risk_mult": risk_mult,
        "triggered_rules": triggered,
        "metrics": {"day_pnl": round(day_pnl, 2), "week_pnl": round(week_pnl, 2), "month_pnl": round(month_pnl, 2),
                    "day_pct": round(pct(day_pnl), 3), "week_pct": round(pct(week_pnl), 3),
                    "month_pct": round(pct(month_pnl), 3), "drawdown_from_peak_pct": round(dd, 3),
                    "consecutive_losses": streak},
        "data_quality": "ok",
        "new_state": {"peak_equity": round(peak, 2), "peak_lock": lock, "peak_lock_since": since if lock else None,
                      "consecutive_losses": streak, "breaker": rec},
    }


def clear_halt(inp: dict) -> dict:
    state = inp.get("state") or {}
    text = (inp.get("text") or "").strip()
    if not state.get("peak_lock"):
        return {"cleared": False, "reason": "no drawdown lock is active"}
    code = _clear_code(state.get("peak_lock_since") or "")
    if text != f"CLEAR HALT {code}":
        return {"cleared": False, "reason": f"type exactly: CLEAR HALT {code}"}
    equity = inp.get("equity")
    if equity is None:
        raise SwingError("clear-halt needs current equity to reset the peak")
    new_state = dict(state)
    new_state.update({"peak_lock": False, "peak_lock_since": None, "peak_equity": float(equity)})
    return {"cleared": True, "new_state": new_state,
            "note": "peak equity reset to current equity; consider halving risk for the next 5 trades"}


# --------------------------------------------------------------------------
# Pre-trade gate
# --------------------------------------------------------------------------

_GATE_RANK = {"GO": 0, "REVIEW_REQUIRED": 1, "NO_GO": 2}


def _risk_of(pos: dict) -> float:
    entry, stop, sh = pos.get("entry"), pos.get("stop"), pos.get("shares", 0)
    if entry is None or stop is None:
        return float("inf")  # unknown stop = unprotected = unbounded risk
    return max(0.0, (float(entry) - float(stop)) * float(sh))


def gate(inp: dict, rules: dict) -> dict:
    """Every rule from rules.json, applied per candidate. Worst decision wins.

    A missing upstream input is never permission to trade: it yields NO_GO.
    """
    pf, ev, en = rules["portfolio"], rules["events"], rules["entry"]
    general = []
    for key in ("as_of", "mode", "breaker", "regime", "portfolio", "settings"):
        if inp.get(key) is None:
            general.append(("NO_GO", f"missing input: {key}"))
    if general:
        return {"overall_decision": "NO_GO", "general_reasons": [r for _, r in general], "candidate_results": []}

    now = parse_dt(inp["as_of"])
    mode = inp["mode"]
    settings = inp["settings"]
    brk = inp["breaker"]
    reg = inp["regime"]
    port = inp["portfolio"]
    equity = float(port.get("equity") or 0)
    if equity <= 0:
        general.append(("NO_GO", "equity missing or <= 0"))
    if inp.get("halt_file"):
        general.append(("NO_GO", "HALT file present"))
    if mode == "live":
        appr = inp.get("approvals_setting")
        if appr is None:
            general.append(("NO_GO", "trade approval setting not checked this session"))
        elif str(appr).lower() not in ("on", "true", "enabled") and not inp.get("chat_only_consent"):
            general.append(("NO_GO", "Robinhood trade approvals are OFF and chat-only consent was not accepted"))
    if brk.get("recommendation") != "TRADING_ALLOWED":
        general.append(("NO_GO", f"breaker is {brk.get('recommendation')}"))
    limits = reg.get("limits") or rules["regime"]["states"].get(reg.get("state", "RED"), {})
    if not limits.get("new_entries", False):
        general.append(("NO_GO", f"regime {reg.get('state')} is REDUCE_ONLY"))
    if ev["block_macro_event_days"] and inp.get("macro_event_today"):
        general.append(("NO_GO", f"macro event today ({inp.get('macro_event_today')})"))
    minutes = inp.get("minutes_since_open")
    if minutes is not None and 0 <= minutes < en["no_entry_first_minutes"]:
        general.append(("NO_GO", f"no new entries in the first {en['no_entry_first_minutes']} minutes"))

    positions = port.get("positions") or []
    pending = int(port.get("pending_entries") or 0)
    max_pos = min(int(limits.get("max_positions", 0)), int(settings.get("max_positions", 99)))
    risk_pct = float(settings.get("risk_pct", rules["sizing"]["risk_pct_default"]))
    allowed_risk = equity * risk_pct / 100.0 * float(limits.get("risk_mult", 0)) * float(brk.get("risk_mult", 1.0))
    open_risk = sum(_risk_of(p) for p in positions)
    gross = sum(float(p.get("market_value") or 0) for p in positions)
    losses = inp.get("recent_losses") or []

    results = []
    accepted_risk = accepted_value = 0.0
    accepted = []
    for c in inp.get("candidates") or []:
        reasons = []

        def add(level, msg):
            reasons.append((level, msg))

        sym = str(c.get("symbol", "?")).upper()
        entry, stop, target = c.get("entry"), c.get("stop"), c.get("target")
        shares = int(c.get("shares") or 0)
        if entry is None or stop is None or target is None:
            add("NO_GO", "entry/stop/target missing")
            entry = stop = target = 0.0
        entry, stop, target = float(entry), float(stop), float(target)
        if stop >= entry:
            add("NO_GO", "stop must be below entry")
        if shares < 1:
            add("NO_GO", "size is zero shares (risk budget, cash or cap too small)")
        if c.get("in_written_plan") is False:
            add("NO_GO", "not in today's written plan")
        if c.get("signal_setup") is False:
            add("NO_GO", "entry signal not confirmed by swing.py signal")
        if c.get("tradable") is False:
            add("NO_GO", "not tradable")
        for v in c.get("veto_reasons") or []:  # web/news checks can only block, never add
            add("NO_GO", f"veto: {v}")
        risk = max(0.0, (entry - stop) * shares)
        if risk > allowed_risk * 1.01 + 0.01:
            add("NO_GO", f"risk ${risk:.2f} > allowed ${allowed_risk:.2f}")
        if c.get("planned_risk_dollars") is not None and risk > float(c["planned_risk_dollars"]) * 1.01 + 0.01:
            add("NO_GO", "actual risk exceeds planned risk")
        value = shares * float(c.get("cash_price") or entry)
        if equity > 0:
            if value / equity * 100.0 > rules["sizing"]["max_position_pct"] + 1e-6:
                add("NO_GO", f"position {value / equity * 100:.1f}% > {rules['sizing']['max_position_pct']}%")
            heat = (open_risk + accepted_risk + risk) / equity * 100.0
            if heat > float(limits.get("max_heat_pct", 0)) + 1e-6:
                add("NO_GO", f"portfolio heat {heat:.2f}% > {limits.get('max_heat_pct')}%")
            g = (gross + accepted_value + value) / equity * 100.0
            if g > pf["max_gross_pct"] + 1e-6:
                add("NO_GO", f"gross exposure {g:.1f}% > {pf['max_gross_pct']}%")
        if len(positions) + pending + len(accepted) + 1 > max_pos:
            add("NO_GO", f"position count would exceed {max_pos}")
        if any(str(p.get("symbol", "")).upper() == sym for p in positions):
            add("NO_GO", "already holding (no averaging down / pyramiding)")
        sector = c.get("sector")
        if not sector:
            add("REVIEW_REQUIRED", "sector unknown")
        else:
            same = [p for p in positions + accepted if p.get("sector") == sector]
            if len(same) >= pf["max_names_per_sector"]:
                add("NO_GO", f"already {len(same)} names in {sector}")
            sv = sum(float(p.get("market_value") or 0) for p in same) + value
            if equity > 0 and sv / equity * 100.0 > pf["max_sector_pct"] + 1e-6:
                add("NO_GO", f"sector {sector} {sv / equity * 100:.1f}% > {pf['max_sector_pct']}%")
        corr = c.get("max_correlation")
        if corr is None:
            if positions:
                add("REVIEW_REQUIRED", "correlation vs holdings not computed")
        elif float(corr) > pf["max_correlation"]:
            add("NO_GO", f"correlation {float(corr):.2f} > {pf['max_correlation']} with a holding")
        # earnings
        if "earnings_date" not in c or c.get("earnings_date") in (None, "", "unknown"):
            if ev["block_unknown_earnings"]:
                add("NO_GO", "next earnings date unknown")
        else:
            ed = to_date(c["earnings_date"])
            if ed >= now.date():
                td = trading_days_between(now.date(), ed)
                if td <= ev["earnings_buffer_trading_days"]:
                    add("NO_GO", f"earnings {ed} is {td} trading day(s) away (buffer {ev['earnings_buffer_trading_days']})")
        # cooldowns
        for loss in losses:
            lt = parse_dt(loss["exit_time"])
            if str(loss.get("symbol", "")).upper() == sym and \
                    trading_days_between(lt.date(), now.date()) < pf["reentry_cooldown_trading_days"]:
                add("NO_GO", f"re-entry cooldown: loss on {sym} on {lt.date()}")
            if now - lt < timedelta(hours=pf["revenge_window_hours"]):
                add("NO_GO", f"revenge window: a loss closed at {lt.isoformat()}")
        # live price checks (pre-market / open)
        live = c.get("live_price")
        trig = c.get("trigger", entry)
        atr_v = c.get("atr")
        if live is not None:
            live = float(live)
            if live <= stop:
                add("NO_GO", "live price at or below stop")
            else:
                rr = (target - live) / (live - stop)
                if rr < en["min_rr_at_live_price"]:
                    add("NO_GO", f"reward/risk {rr:.2f} at live price < {en['min_rr_at_live_price']}")
            gap = live - float(trig)
            if gap / float(trig) * 100.0 > en["max_gap_above_trigger_pct"] or \
                    (atr_v and gap > en["max_gap_above_trigger_atr"] * float(atr_v)):
                add("NO_GO", "gapped too far above trigger: do not chase")
        level = "GO"
        for lv, _ in reasons:
            if _GATE_RANK[lv] > _GATE_RANK[level]:
                level = lv
        for lv, _ in general:
            if _GATE_RANK[lv] > _GATE_RANK[level]:
                level = lv
        if level == "GO":
            accepted_risk += risk
            accepted_value += value
            accepted.append({"symbol": sym, "sector": sector, "market_value": value})
        results.append({"symbol": sym, "decision": level, "risk_dollars": round(risk, 2),
                        "reasons": [r for _, r in general] + [r for _, r in reasons]})

    overall = "GO" if results else ("NO_GO" if general else "NO_ACTIONABLE_ORDERS")
    for r in results:
        if _GATE_RANK[r["decision"]] > _GATE_RANK.get(overall, 0):
            overall = r["decision"]
    return {
        "overall_decision": overall,
        "general_reasons": [r for _, r in general],
        "limits": {"max_positions": max_pos, "allowed_risk_dollars": round(allowed_risk, 2),
                   "max_heat_pct": limits.get("max_heat_pct"), "open_risk_dollars": round(open_risk, 2)},
        "candidate_results": results,
    }


# --------------------------------------------------------------------------
# Trade cards and approval codes (stage -> commit -> push)
# --------------------------------------------------------------------------

CARD_KINDS = ("ENTRY", "PROTECT", "MOVE_STOP", "EXIT", "CANCEL")


def _end_of_day(dt: datetime) -> datetime:
    return datetime.combine(dt.date(), time(23, 59, 59))


def make_code(card_core: dict, created_at: str, parent: str | None) -> str:
    blob = json.dumps(card_core, sort_keys=True, separators=(",", ":")) + "|" + created_at + "|" + (parent or "")
    return hashlib.sha256(blob.encode()).hexdigest()[:8]


def card(inp: dict, rules: dict) -> dict:
    """Stage a trade card. Refuses if another unexpired card is pending."""
    state = dict(inp.get("state") or {})
    c = dict(inp.get("card") or {})
    kind = c.get("kind")
    if kind not in CARD_KINDS:
        raise SwingError(f"card.kind must be one of {CARD_KINDS}")
    for req in ("symbol", "account_mask", "mode", "action"):
        if not c.get(req):
            raise SwingError(f"card.{req} is required")
    if kind == "MOVE_STOP":
        old, new = c.get("old_stop"), c.get("new_stop")
        if old is None or new is None:
            raise SwingError("MOVE_STOP needs old_stop and new_stop")
        if float(new) < float(old):
            raise SwingError("refused: stops only move up")
    created = parse_dt(inp.get("now") or datetime.now().isoformat(timespec="seconds"))
    pending = state.get("pending_card")
    if pending and parse_dt(pending["expires_at"]) >= created:
        raise SwingError(f"card {pending['code']} is still pending: approve or reject it first (one card at a time)")
    c.setdefault("ref_id", str(uuid.uuid4()))
    core = {k: v for k, v in c.items() if k not in ("ref_id",)}
    created_s = created.isoformat(timespec="seconds")
    code = make_code(core, created_s, state.get("last_code"))
    staged = {"code": code, "kind": kind, "created_at": created_s,
              "expires_at": _end_of_day(created).isoformat(timespec="seconds"),
              "parent": state.get("last_code"), "card": c}
    state["pending_card"] = staged
    return {"code": code, "staged": staged, "new_state": state, "markdown": render_card(staged)}


def _fmt(v, money=False):
    if v is None or v == "":
        return "n/a"
    if isinstance(v, float):
        return f"${v:,.2f}" if money else f"{v:,.2f}"
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v) if v else "none"
    if isinstance(v, dict):
        return ", ".join(f"{k}: {x}" for k, x in v.items())
    return str(v)


def render_card(staged: dict) -> str:
    c = staged["card"]
    warn = c.get("review_warnings") or []
    lines = [
        f"### TRADE CARD {staged['code']} - {staged['kind']} {c.get('symbol')}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Account | {_fmt(c.get('account_mask'))} ({_fmt(c.get('mode')).upper()}) |",
        f"| Robinhood trade approvals | {_fmt(c.get('approvals'))} |",
        f"| Regime | {_fmt(c.get('regime'))} |",
        f"| Breaker | {_fmt(c.get('breaker'))} |",
        f"| Action | {_fmt(c.get('action'))} |",
        f"| Order | {_fmt(c.get('order'))} |",
        f"| Thesis | {_fmt(c.get('thesis'))} |",
        f"| Stop / Target | {_fmt(c.get('stop'), True)} / {_fmt(c.get('target'), True)} |",
        f"| Shares | {_fmt(c.get('shares'))} |",
        f"| Risk | {_fmt(c.get('risk_dollars'), True)} ({_fmt(c.get('risk_pct'))}% of equity) |",
        f"| Portfolio after | {_fmt(c.get('portfolio_after'))} |",
        f"| Events | {_fmt(c.get('events'))} |",
        f"| Exit plan | {_fmt(c.get('exit_plan'))} |",
        f"| ref_id | `{c.get('ref_id')}` |",
        f"| Expires | {staged['expires_at']} ET |",
        "",
        "**Robinhood review warnings (verbatim):**",
    ]
    lines += [f"> {w}" for w in warn] if warn else ["> none returned"]
    lines += ["", f"To approve this one card, type exactly: `APPROVE {staged['code']}`",
              f"To discard it: `REJECT {staged['code']}`. Batch approvals are not accepted."]
    return "\n".join(lines)


def approve(inp: dict, rules: dict) -> dict:
    """Validate the user's typed approval against the single pending card."""
    state = dict(inp.get("state") or {})
    text = (inp.get("text") or "").strip()
    pending = state.get("pending_card")
    now = parse_dt(inp.get("now") or datetime.now().isoformat(timespec="seconds"))
    phrase = rules["consent"]["approve_phrase"]

    def refuse(reason):
        return {"approved": False, "reason": reason, "new_state": state}

    parts = text.split()
    if len(parts) != 2 or parts[0] != phrase:
        return refuse(f"only an exact '{phrase} <code>' for one card counts (got: {text!r})")
    code = parts[1]
    if not pending:
        return refuse("no card is pending")
    if code != pending["code"]:
        return refuse(f"code {code} does not match the pending card {pending['code']} (stale or mistyped)")
    if now > parse_dt(pending["expires_at"]):
        state["pending_card"] = None
        return {"approved": False, "reason": "card expired; build a new card", "new_state": state}
    price, atr_v = inp.get("current_price"), pending["card"].get("atr")
    ref_px = pending["card"].get("price_at_card")
    if price is not None and atr_v and ref_px is not None:
        moved = abs(float(price) - float(ref_px))
        if moved > rules["consent"]["reprice_atr"] * float(atr_v):
            state["pending_card"] = None
            return {"approved": False, "new_state": state,
                    "reason": f"price moved {moved:.2f} > {rules['consent']['reprice_atr']}xATR since the card; build a new card"}
    log = list(state.get("approvals") or [])
    log.append({"code": code, "kind": pending["kind"], "symbol": pending["card"].get("symbol"),
                "ref_id": pending["card"].get("ref_id"), "approved_at": now.isoformat(timespec="seconds")})
    state.update({"pending_card": None, "last_code": code, "approvals": log[-200:]})
    return {"approved": True, "code": code, "card": pending["card"], "new_state": state,
            "next": "place exactly this order with this ref_id; reuse the same ref_id on retries"}


def reject(inp: dict, rules: dict) -> dict:
    state = dict(inp.get("state") or {})
    text = (inp.get("text") or "").strip()
    pending = state.get("pending_card")
    if not pending:
        return {"rejected": False, "reason": "no card is pending", "new_state": state}
    if text != f"{rules['consent']['reject_phrase']} {pending['code']}":
        return {"rejected": False, "reason": f"type exactly: REJECT {pending['code']}", "new_state": state}
    state["pending_card"] = None
    return {"rejected": True, "code": pending["code"], "new_state": state}


# --------------------------------------------------------------------------
# Paper trading simulator (Robinhood has no paper environment)
# --------------------------------------------------------------------------

def paper_init(equity: float, as_of: str) -> dict:
    return {
        "schema": "paper-account/1",
        "created": as_of,
        "last_stepped": as_of,
        "starting_equity": round(float(equity), 2),
        "cash": round(float(equity), 2),
        "equity": round(float(equity), 2),
        "positions": [],
        "orders": [],
        "history": [],
        "equity_curve": [{"date": as_of, "equity": round(float(equity), 2)}],
        "events": [],
    }


def paper_place(account: dict, order: dict) -> dict:
    acct = json.loads(json.dumps(account))
    req = ("symbol", "shares", "stop_price", "limit_price", "stop_loss", "target", "created")
    miss = [k for k in req if order.get(k) is None]
    if miss:
        raise SwingError(f"paper order missing {miss}")
    shares = int(order["shares"])
    sp, lp, sl, tg = (float(order[k]) for k in ("stop_price", "limit_price", "stop_loss", "target"))
    if shares < 1 or not (lp >= sp > sl) or tg <= sp:
        raise SwingError("invalid paper order: need shares>=1 and limit >= stop > stop_loss, target > stop")
    if any(o["symbol"] == order["symbol"].upper() for o in acct["orders"]) or \
            any(p["symbol"] == order["symbol"].upper() for p in acct["positions"]):
        raise SwingError("already have an order or position in this symbol")
    session = order.get("session") or str(next_trading_day(order["created"]))
    o = {"id": order.get("card_code") or uuid.uuid4().hex[:8], "symbol": order["symbol"].upper(),
         "type": "buy_stop_limit", "shares": shares, "stop_price": sp, "limit_price": lp,
         "stop_loss": sl, "target": tg, "session": session, "created": order["created"],
         "card_code": order.get("card_code"), "sector": order.get("sector")}
    acct["orders"].append(o)
    return acct


def _slip(px: float, side: str, pct: float) -> float:
    return round(px * (1 + pct / 100.0) if side == "buy" else px * (1 - pct / 100.0), 4)


def paper_step(account: dict, bars_by_sym: dict, rules: dict, through: str | None = None) -> dict:
    """Advance the paper account one trading day at a time up to `through`.

    Catches up every missed trading day since last_stepped. Fill rules:
      buy stop-limit: open > limit -> no fill; stop <= open <= limit -> fill at open;
                      high >= stop -> fill at stop; else expires (day order).
      protective stop: open <= stop -> fill at open (gap); low <= stop -> fill at stop.
      target: open >= target -> fill at open; high >= target -> fill at target.
      same bar stop and target -> stop first (conservative). Slippage on every fill.
      close < SMA20 (held >= 2 days) or 15 trading days without +1R -> exit next open.
      high >= entry + 1R -> stop moves to breakeven for the next bar.
    """
    acct = json.loads(json.dumps(account))
    ex, slip = rules["exits"], rules["paper"]["slippage_pct"]
    bars_by_sym = {k.upper(): v for k, v in bars_by_sym.items()}
    idx = {s: {b["date"]: i for i, b in enumerate(bs)} for s, bs in bars_by_sym.items()}
    closes = {s: [b["close"] for b in bs] for s, bs in bars_by_sym.items()}
    s20 = {s: sma(c, ex["sma_exit"]) for s, c in closes.items()}
    last = to_date(acct["last_stepped"])
    all_dates = sorted({b["date"] for bs in bars_by_sym.values() for b in bs})
    end = to_date(through) if through else (to_date(all_dates[-1]) if all_dates else last)
    days = []
    d = last
    while True:
        d = next_trading_day(d)
        if d > end:
            break
        days.append(d)
    events = []
    last_close = {p["symbol"]: p.get("last_close", p["entry_price"]) for p in acct["positions"]}

    def close_position(p, px, reason, day):
        exit_px = _slip(px, "sell", slip)
        acct["cash"] = round(acct["cash"] + exit_px * p["shares"], 4)
        pnl = (exit_px - p["entry_price"]) * p["shares"]
        r_mult = (exit_px - p["entry_price"]) / p["r_dist"] if p["r_dist"] else 0.0
        trade = {"symbol": p["symbol"], "entry_date": p["entry_date"], "exit_date": str(day),
                 "entry": p["entry_price"], "exit": exit_px, "shares": p["shares"], "pnl": round(pnl, 2),
                 "r_multiple": round(r_mult, 3), "reason": reason, "card_code": p.get("card_code"),
                 "sector": p.get("sector"), "mfe_r": round(p.get("mfe_r", 0.0), 3),
                 "mae_r": round(p.get("mae_r", 0.0), 3), "rule_adherent": True}
        acct["history"].append(trade)
        events.append({"date": str(day), "event": "exit", **trade})

    for day in days:
        ds = str(day)
        still_open = []
        for p in acct["positions"]:
            i = idx.get(p["symbol"], {}).get(ds)
            if i is None:
                events.append({"date": ds, "event": "data_gap", "symbol": p["symbol"]})
                still_open.append(p)
                continue
            b = bars_by_sym[p["symbol"]][i]
            if p.get("exit_next_open"):
                close_position(p, b["open"], p["exit_next_open"], day)
                continue
            stop, target = p["stop"], p["target"]
            if b["open"] <= stop:
                close_position(p, b["open"], "stop_gap", day)
                continue
            if b["low"] <= stop:
                close_position(p, stop, "stop" if stop < p["entry_price"] else "breakeven_stop", day)
                continue
            if b["open"] >= target:
                close_position(p, b["open"], "target_gap", day)
                continue
            if b["high"] >= target:
                close_position(p, target, "target", day)
                continue
            still_open.append(p)
        acct["positions"] = still_open

        remaining = []
        for o in acct["orders"]:
            if to_date(o["session"]) > day:
                remaining.append(o)
                continue
            if to_date(o["session"]) < day:
                events.append({"date": ds, "event": "order_expired", "symbol": o["symbol"], "reason": "missed session"})
                continue
            i = idx.get(o["symbol"], {}).get(ds)
            if i is None:
                events.append({"date": ds, "event": "order_expired", "symbol": o["symbol"], "reason": "no bar for session"})
                continue
            b = bars_by_sym[o["symbol"]][i]
            if b["open"] > o["limit_price"]:
                events.append({"date": ds, "event": "order_expired", "symbol": o["symbol"],
                               "reason": f"gapped over limit (open {b['open']} > {o['limit_price']})"})
                continue
            if b["open"] >= o["stop_price"]:
                px = b["open"]
            elif b["high"] >= o["stop_price"]:
                px = o["stop_price"]
            else:
                events.append({"date": ds, "event": "order_expired", "symbol": o["symbol"], "reason": "trigger not reached"})
                continue
            fill = _slip(px, "buy", slip)
            cost = fill * o["shares"]
            if cost > acct["cash"] + 1e-6:
                events.append({"date": ds, "event": "order_rejected", "symbol": o["symbol"], "reason": "insufficient cash"})
                continue
            acct["cash"] = round(acct["cash"] - cost, 4)
            p = {"symbol": o["symbol"], "shares": o["shares"], "entry_price": fill, "entry_date": ds,
                 "stop": o["stop_loss"], "initial_stop": o["stop_loss"], "target": o["target"],
                 "r_dist": round(fill - o["stop_loss"], 4), "card_code": o.get("card_code"),
                 "sector": o.get("sector"), "max_high": b["high"], "mfe_r": 0.0, "mae_r": 0.0}
            events.append({"date": ds, "event": "fill", "symbol": o["symbol"], "price": fill, "shares": o["shares"]})
            if b["low"] <= p["stop"]:  # conservative: assume the stop was hit after the fill
                close_position(p, p["stop"], "stop_same_day", day)
                continue
            acct["positions"].append(p)
        acct["orders"] = remaining

        for p in acct["positions"]:
            i = idx.get(p["symbol"], {}).get(ds)
            if i is None:
                continue
            b = bars_by_sym[p["symbol"]][i]
            last_close[p["symbol"]] = b["close"]
            p["last_close"] = b["close"]
            p["max_high"] = max(p.get("max_high", b["high"]), b["high"])
            if p["r_dist"]:
                p["mfe_r"] = max(p.get("mfe_r", 0.0), (b["high"] - p["entry_price"]) / p["r_dist"])
                p["mae_r"] = min(p.get("mae_r", 0.0), (b["low"] - p["entry_price"]) / p["r_dist"])
            be = p["entry_price"] + ex["breakeven_at_r"] * p["r_dist"]
            if b["high"] >= be and p["stop"] < p["entry_price"]:
                p["stop"] = round(p["entry_price"], 2)
                events.append({"date": ds, "event": "stop_to_breakeven", "symbol": p["symbol"], "stop": p["stop"]})
            held = trading_days_between(p["entry_date"], day)
            sm = s20[p["symbol"]][i]
            if sm is not None and b["close"] < sm and held >= ex["sma_exit_min_days"]:
                p["exit_next_open"] = "sma20_close"
            elif held >= ex["time_stop_days"] and p["max_high"] < p["entry_price"] + ex["time_stop_min_r"] * p["r_dist"]:
                p["exit_next_open"] = "time_stop"

        mv = sum(p["shares"] * last_close.get(p["symbol"], p["entry_price"]) for p in acct["positions"])
        acct["equity"] = round(acct["cash"] + mv, 2)
        acct["equity_curve"].append({"date": ds, "equity": acct["equity"]})
        acct["last_stepped"] = ds

    if not calendar_covered(end):
        events.append({"date": str(end), "event": "warning",
                       "detail": "date outside the built-in NYSE holiday table; extend NYSE_HOLIDAYS"})
    acct["events"] = (acct.get("events") or []) + events
    acct["events"] = acct["events"][-500:]
    return {"account": acct, "days_processed": [str(x) for x in days], "events": events}


# --------------------------------------------------------------------------
# Review and reconcile
# --------------------------------------------------------------------------

def review(inp: dict, rules: dict) -> dict:
    trades = inp.get("trades") or []
    g = rules["graduation"]
    rs = [float(t["r_multiple"]) for t in trades if t.get("r_multiple") is not None]
    pnls = [float(t.get("pnl", 0)) for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)
    streak = worst = 0
    for t in trades:
        if float(t.get("pnl", 0)) < 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    adh = [t["rule_adherent"] for t in trades if "rule_adherent" in t]
    adherence = (sum(1 for a in adh if a) / len(adh) * 100.0) if adh else None
    expectancy = (sum(rs) / len(rs)) if rs else None
    weeks = None
    if inp.get("start_date") and inp.get("as_of"):
        weeks = (to_date(inp["as_of"]) - to_date(inp["start_date"])).days / 7.0
    criteria = {
        "weeks": {"value": None if weeks is None else round(weeks, 1), "need": f">= {g['min_weeks']}",
                  "pass": weeks is not None and weeks >= g["min_weeks"]},
        "closed_trades": {"value": len(trades), "need": f">= {g['min_closed_trades']}",
                          "pass": len(trades) >= g["min_closed_trades"]},
        "expectancy_r": {"value": None if expectancy is None else round(expectancy, 3),
                         "need": f"> {g['min_expectancy_r']}",
                         "pass": expectancy is not None and expectancy > g["min_expectancy_r"]},
        "adherence_pct": {"value": None if adherence is None else round(adherence, 1),
                          "need": f">= {g['min_adherence_pct']}",
                          "pass": adherence is not None and adherence >= g["min_adherence_pct"]},
    }
    return {
        "closed_trades": len(trades),
        "win_rate_pct": round(len(wins) / len(rs) * 100.0, 1) if rs else None,
        "avg_r": round(expectancy, 3) if expectancy is not None else None,
        "expectancy_r": round(expectancy, 3) if expectancy is not None else None,
        "avg_win_r": round(sum(wins) / len(wins), 3) if wins else None,
        "avg_loss_r": round(sum(losses) / len(losses), 3) if losses else None,
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else (None if not gross_win else "inf"),
        "net_pnl": round(sum(pnls), 2),
        "max_consecutive_losses": worst,
        "adherence_pct": None if adherence is None else round(adherence, 1),
        "graduation": {"eligible": all(c["pass"] for c in criteria.values()), "criteria": criteria},
        "note": "small samples are noise; do not change rules on fewer than 20 trades",
    }


def _get(d: dict, *names):
    for n in names:
        if isinstance(d, dict) and d.get(n) not in (None, ""):
            return d[n]
    return None


def _as_list(x, *keys):
    x = unwrap_data(x) if x is not None else []
    if isinstance(x, dict):
        for k in keys:
            if isinstance(x.get(k), list):
                return x[k]
        return []
    return x or []


def reconcile(inp: dict) -> dict:
    """Facts (Robinhood) vs intent (journal cards)."""
    cards = inp.get("cards") or []
    orders = _as_list(inp.get("orders"), "results", "orders")
    adv = _as_list(inp.get("advanced_orders"), "advanced_orders", "results")
    positions = _as_list(inp.get("positions"), "results", "positions")
    findings, matched = [], set()
    for c in cards:
        m = None
        for i, o in enumerate(orders):
            if i in matched:
                continue
            if c.get("ref_id") and _get(o, "ref_id") == c.get("ref_id"):
                m = i
                break
        if m is None:
            for i, o in enumerate(orders):
                if i in matched:
                    continue
                if str(_get(o, "symbol") or "").upper() == str(c.get("symbol", "")).upper() and \
                        str(_get(o, "side") or "").lower() == str(c.get("side", "")).lower() and \
                        float(_get(o, "quantity") or 0) == float(c.get("shares") or 0):
                    m = i
                    break
        if m is None:
            findings.append({"type": "NOT_FOUND_AT_BROKER", "code": c.get("code"), "symbol": c.get("symbol"),
                             "hint": "may still be waiting in Robinhood trade approvals; check get_trade_approvals"})
        else:
            matched.add(m)
            findings.append({"type": "MATCHED", "code": c.get("code"), "symbol": c.get("symbol"),
                             "state": _get(orders[m], "state", "status")})
    for i, o in enumerate(orders):
        if i not in matched:
            findings.append({"type": "UNTRACKED_ORDER", "symbol": _get(o, "symbol"), "side": _get(o, "side"),
                             "state": _get(o, "state", "status"),
                             "hint": "placed outside the copilot; journal it or ask the user"})
    active = {"queued", "confirmed", "partially_filled", "unconfirmed", "active", "pending", "open", "new"}
    protected = set()
    for a in adv:
        st = str(_get(a, "state", "status") or "active").lower()
        sym = _get(a, "symbol") or _get((a.get("legs") or [{}])[0], "symbol")
        if sym and st in active:
            protected.add(str(sym).upper())
    for o in orders:
        st = str(_get(o, "state", "status") or "").lower()
        if str(_get(o, "side") or "").lower() == "sell" and _get(o, "stop_price") and st in active:
            protected.add(str(_get(o, "symbol")).upper())
    for p in positions:
        qty = float(_get(p, "quantity", "shares") or 0)
        sym = str(_get(p, "symbol") or "").upper()
        if qty > 0 and sym not in protected:
            findings.append({"type": "UNPROTECTED", "symbol": sym, "quantity": qty,
                             "hint": "first card of the session: PROTECT with review_advanced_order"})
    return {"findings": findings,
            "unprotected": [f["symbol"] for f in findings if f["type"] == "UNPROTECTED"],
            "ok": not any(f["type"] in ("UNPROTECTED", "UNTRACKED_ORDER") for f in findings)}


# --------------------------------------------------------------------------
# Synthetic data (shared by selftest and the unit tests)
# --------------------------------------------------------------------------

def synthetic_bars(pattern: str = "uptrend_pullback", n: int = 300, start: str = "2025-08-01",
                   base: float = 100.0, volume: float = 2_000_000) -> list:
    """Deterministic bars. Patterns: uptrend_pullback, uptrend, downtrend, flat."""
    dates = trading_dates(start, n)
    closes, p = [], base
    for i in range(n):
        if pattern == "uptrend_pullback":
            if i < n - 7:
                step = 0.012 if i % 2 == 0 else -0.006
            elif i < n - 1:
                step = -0.02
            else:
                step = 0.03
        elif pattern == "uptrend":
            step = 0.012 if i % 2 == 0 else -0.006
        elif pattern == "downtrend":
            step = -0.012 if i % 2 == 0 else 0.006
        else:
            step = 0.004 if i % 2 == 0 else -0.004
        p *= 1 + step
        closes.append(p)
    bars, prev = [], base
    for d, c in zip(dates, closes):
        o = prev
        bars.append({"date": str(d), "open": round(o, 4), "high": round(max(o, c) * 1.004, 4),
                     "low": round(min(o, c) * 0.996, 4), "close": round(c, 4), "volume": volume})
        prev = c
    return bars


# --------------------------------------------------------------------------
# Selftest
# --------------------------------------------------------------------------

def selftest(rules: dict) -> dict:
    results = []

    def check(name, cond, detail=""):
        results.append({"check": name, "pass": bool(cond), "detail": detail})

    # indicators
    check("sma", sma([1, 2, 3, 4, 5], 3)[-1] == 4.0)
    up = [float(i) for i in range(1, 30)]
    check("rsi_all_gains_is_100", rsi(up, 14)[-1] == 100.0)
    flat_h, flat_l, flat_c = [11.0] * 20, [9.0] * 20, [10.0] * 20
    check("atr_constant_range", abs(atr(flat_h, flat_l, flat_c, 14)[-1] - 2.0) < 1e-9)
    # calendar
    check("thanksgiving_closed", not is_trading_day("2026-11-26"))
    check("trading_days_between", trading_days_between("2026-11-25", "2026-11-30") == 2)
    # unwrap
    raw = {"data": {"results": [{"symbol": "spy", "bars": [
        {"begins_at": "2026-11-17T05:00:00Z", "open_price": "1.0", "high_price": "2", "low_price": "0.5",
         "close_price": "1.5", "volume": 10, "session": "reg"},
        {"begins_at": "2026-11-18T05:00:00Z", "open_price": "1.5", "high_price": "2", "low_price": "1",
         "close_price": "1.8", "volume": 10, "interpolated": True}]}]}, "guide": "advisory"}
    u = unwrap(raw)
    check("unwrap_drops_interpolated", list(u) == ["SPY"] and len(u["SPY"]) == 1 and u["SPY"][0]["close"] == 1.5)
    # regime + signal
    bars = synthetic_bars("uptrend_pullback")
    check("regime_green_on_uptrend", regime(synthetic_bars("uptrend"), rules)["state"] == "GREEN")
    check("regime_red_on_downtrend", regime(synthetic_bars("downtrend"), rules)["state"] == "RED")
    sig = signal("TEST", bars, rules, {"market_cap": 5e9})
    check("signal_fires_on_pullback", sig["setup"], f"failed={sig['failed']}")
    check("signal_blocks_downtrend", not signal("DN", synthetic_bars("downtrend"), rules, {"market_cap": 5e9})["setup"])
    # size
    s = size(100.0, 2.0, 97.0, 10000.0, 10000.0, rules)
    check("size_whole_shares", s["shares"] == 10 and s["stop"] == 96.0 and s["target"] == 108.0, s)
    # breaker
    b = breaker({"as_of": "2026-11-19T17:00:00", "equity": 9700, "peak_equity": 10000, "account_size": 10000,
                 "closed_trades": [{"exit_time": "2026-11-19T11:00:00", "pnl": -250}]}, rules)
    check("breaker_daily_halt", b["recommendation"] == "HALTED")
    check("breaker_missing_state_fails_closed", breaker({}, rules)["recommendation"] == "HALTED")
    # card + approve
    st = {"pending_card": None, "last_code": None}
    cd = card({"state": st, "now": "2026-11-19T17:00:00",
               "card": {"kind": "ENTRY", "symbol": "TEST", "account_mask": "••1234", "mode": "paper",
                        "action": "buy stop-limit", "atr": 2.0, "price_at_card": 100.0}}, rules)
    bad = approve({"state": cd["new_state"], "text": "approve all", "now": "2026-11-19T17:05:00"}, rules)
    good = approve({"state": cd["new_state"], "text": f"APPROVE {cd['code']}", "now": "2026-11-19T17:05:00",
                    "current_price": 100.5}, rules)
    check("approve_rejects_batch", not bad["approved"])
    check("approve_exact_code", good["approved"] and good["new_state"]["last_code"] == cd["code"])
    # paper
    acct = paper_init(10000, "2026-11-18")
    acct = paper_place(acct, {"symbol": "X", "shares": 10, "stop_price": 101, "limit_price": 102, "stop_loss": 97,
                              "target": 109, "created": "2026-11-18"})
    px = {"X": [{"date": "2026-11-19", "open": 100, "high": 101.5, "low": 99.5, "close": 101.2, "volume": 1}]}
    stepped = paper_step(acct, px, rules, "2026-11-19")["account"]
    check("paper_fills_at_stop_price", stepped["positions"] and stepped["positions"][0]["entry_price"] == _slip(101, "buy", 0.05))
    ok = all(r["pass"] for r in results)
    return {"ok": ok, "passed": sum(r["pass"] for r in results), "total": len(results),
            "failures": [r for r in results if not r["pass"]], "version": VERSION}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _read_input(path):
    if path in (None, "-"):
        data = sys.stdin.read()
    else:
        with open(path, "r", encoding="utf-8") as fh:
            data = fh.read()
    return json.loads(data) if data.strip() else {}


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="swing.py", description=__doc__.split("\n")[0])
    ap.add_argument("command")
    ap.add_argument("subcommand", nargs="?")
    ap.add_argument("--input", "-i", default=None, help="JSON input file or - for stdin")
    ap.add_argument("--rules", default=None, help="path to rules.json")
    ap.add_argument("--out", "-o", default=None, help="write JSON output here as well")
    ap.add_argument("--equity", type=float, default=None)
    ap.add_argument("--date", default=None)
    args = ap.parse_args(argv)
    rules = load_rules(args.rules)
    cmd = args.command

    def need_input():
        return _read_input(args.input if args.input is not None else "-")

    try:
        if cmd == "selftest":
            out = selftest(rules)
        elif cmd == "unwrap":
            out = unwrap(need_input())
        elif cmd == "indicators":
            inp = need_input()
            bars = _bars_from_input(inp.get("bars", inp) if isinstance(inp, dict) else inp)
            theirs = inp.get("robinhood_indicators", {}) if isinstance(inp, dict) else {}
            out = {}
            for sym, bs in bars.items():
                snap = snapshot(bs, rules)
                snap["cross_check"] = cross_check(snap, theirs.get(sym, {}), rules) if theirs else []
                out[sym] = snap
        elif cmd == "corr":
            inp = need_input()
            bars = _bars_from_input(inp.get("bars", inp))
            lb = inp.get("lookback", rules["portfolio"]["correlation_lookback"])
            syms = sorted(bars)
            out = {a: {b: (None if a == b else correlation(bars[a], bars[b], lb)) for b in syms} for a in syms}
        elif cmd == "regime":
            inp = need_input()
            bars = _bars_from_input(inp.get("bars", inp))
            sym = rules["regime"]["symbol"]
            out = regime(bars.get(sym) or next(iter(bars.values())), rules)
        elif cmd == "signal":
            inp = need_input()
            bars = _bars_from_input(inp.get("bars", inp))
            meta = inp.get("meta", {}) if isinstance(inp, dict) else {}
            out = {s: signal(s, bs, rules, meta.get(s, {})) for s, bs in bars.items()}
        elif cmd == "size":
            i = need_input()
            out = size(float(i["entry"]), float(i["atr"]), float(i["low_recent"]), float(i["equity"]),
                       float(i.get("settled_cash", i["equity"])), rules, i.get("risk_pct"),
                       float(i.get("risk_mult", 1.0)), i.get("cash_price"))
        elif cmd == "breaker":
            out = breaker(need_input(), rules)
        elif cmd == "clear-halt":
            out = clear_halt(need_input())
        elif cmd == "gate":
            out = gate(need_input(), rules)
        elif cmd == "card":
            out = card(need_input(), rules)
        elif cmd == "approve":
            out = approve(need_input(), rules)
        elif cmd == "reject":
            out = reject(need_input(), rules)
        elif cmd == "paper":
            sub = args.subcommand
            if sub == "init":
                out = paper_init(args.equity or 10000.0, args.date or str(date.today()))
            elif sub == "place":
                i = need_input()
                out = paper_place(i["account"], i["order"])
            elif sub == "step":
                i = need_input()
                out = paper_step(i["account"], _bars_from_input(i["bars"]), rules, i.get("through"))
            else:
                raise SwingError("paper needs a subcommand: init | place | step")
        elif cmd == "review":
            out = review(need_input(), rules)
        elif cmd == "reconcile":
            out = reconcile(need_input())
        elif cmd == "calendar":
            d = args.date or str(date.today())
            out = {"date": d, "is_trading_day": is_trading_day(d), "next_trading_day": str(next_trading_day(d)),
                   "prev_trading_day": str(prev_trading_day(d)), "calendar_covered": calendar_covered(d)}
        else:
            raise SwingError(f"unknown command {cmd!r}; see --help")
    except SwingError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stdout)
        return 2
    except KeyError as exc:
        print(json.dumps({"error": f"missing input field: {exc.args[0]}"}), file=sys.stdout)
        return 2
    except (TypeError, ValueError) as exc:  # includes json.JSONDecodeError
        print(json.dumps({"error": f"bad input: {exc}"}), file=sys.stdout)
        return 2
    text = json.dumps(out, indent=2, default=str)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    if cmd == "selftest" and not out["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
