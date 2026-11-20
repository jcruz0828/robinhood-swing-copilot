<!-- Template for a trade card. swing.py card renders this layout automatically
     (field "markdown"); this file documents what every field means.
     Never fill a card by hand: every number must come from swing.py output. -->
### TRADE CARD {code} - {kind} {symbol}

| Field | Value | Where it comes from |
|---|---|---|
| Account | ••1234 (LIVE or PAPER) | get_accounts, masked to the last 4 digits |
| Robinhood trade approvals | ON / OFF + chat-only consent | get_trade_approval_setting, fetched this session |
| Regime | GREEN / YELLOW / RED + reason | swing.py regime |
| Breaker | TRADING_ALLOWED / COOLDOWN / HALTED | swing.py breaker |
| Action | e.g. BUY 4 AAA buy stop-limit 219.73 / 222.24, day order | swing.py signal + size |
| Order | the exact tool arguments that will be sent | built from the approved fields |
| Thesis | one sentence: trend + pullback + trigger | signal checks |
| Stop / Target | 209.51 / 240.17 (2R) | swing.py size |
| Shares | 4 (whole shares) | swing.py size |
| Risk | $40.88 (0.41% of equity) | swing.py size |
| Portfolio after | positions, open risk %, gross %, sector % | swing.py gate |
| Events | next earnings date, macro events | get_earnings_results, settings.macro_event_dates |
| Exit plan | PROTECT after fill; breakeven at +1R; SMA20 close; 15-day time stop | rules.json exits |
| ref_id | UUID reused on retries | swing.py card |
| Expires | end of today, ET | swing.py card |

**Robinhood review warnings (verbatim):** paste every alert from review_equity_order /
review_advanced_order exactly as returned. Never summarize or drop one.

To approve this one card, type exactly: `APPROVE {code}`
To discard it: `REJECT {code}`. Batch approvals are not accepted.
