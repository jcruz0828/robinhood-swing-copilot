<!-- One file per trade: trades/YYYY-MM-DD-SYMBOL.md, created when the ENTRY card
     is approved and completed when the trade closes. -->
# {SYMBOL} - {entry date}

- Card codes: ENTRY {code} | PROTECT {code} | MOVE_STOP {codes} | EXIT {code}
- ref_ids: {uuid(s)}
- Mode: {paper|live}

## Plan (from the approved card)
- Thesis:
- Entry trigger / limit:
- Stop / Target / Shares / Risk $:
- Regime and breaker at entry:

## Execution (facts from Robinhood or the paper sim)
| Date | Event | Price | Shares | Notes |
|---|---|---|---|---|

## Result
- Exit reason: {stop | stop_gap | breakeven_stop | target | sma20_close | time_stop | manual}
- P&L $: | R multiple: | MFE R: | MAE R:
- rule_adherent: {true|false}: if false, which rule and why

## Lesson (one line, written at close)
-
