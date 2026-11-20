<!-- reviews/YYYY-MM.md. First weekend of the month, about 90 minutes.
     The ONLY place rules.json or settings.json risk numbers may change. -->
# Monthly review - {YYYY-MM}

## Scoreboard (swing.py review)
| Metric | Month | Since start |
|---|---|---|

## Graduation check (paper -> live, or 0.5% -> 1% risk)
| Criterion | Need | Value | Pass |
|---|---|---|---|
| Weeks | >= 4 | | |
| Closed trades | >= 20 | | |
| Expectancy R | > 0 | | |
| Adherence | >= 95% | | |

## Trade postmortems
| Trade | R | MFE R | MAE R | Exit reason | What the rules did right/wrong |
|---|---|---|---|---|---|

## Parameter drift check
- Did any exit type dominate (e.g. many time stops = entries too early)?
- Did gaps make losses worse than 1R? How often?

## Tax and wash sales (live only)
- Losses re-bought within 30 days (wash-sale risk): check get_equity_tax_lots

## Decisions
- Rule changes (with reason and evidence, or "none"):
- Settings changes:
- Effective date (next Monday):
