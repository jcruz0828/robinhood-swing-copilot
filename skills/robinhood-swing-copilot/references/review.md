# Reviews: weekly (observe) and monthly (decide)

**Weekly reviews observe; monthly reviews decide.** Rules and risk change
only at a monthly review, and only with evidence from at least 20 trades.

## Weekly review (Friday after the close, about 30 minutes)

1. **Gather trades.**
   - Paper: closed trades from `paper/account.json` history.
   - Live: `get_pnl_trade_history`, matched to `trades/*.md` for card codes and
     `rule_adherent`.
2. **Compute metrics.** Run `swing.py review` with
   `{"trades": [...], "start_date": settings.paper_start_date, "as_of": today}`.
   It reports:
   - closed trades and win rate
   - average R (= expectancy) and profit factor
   - max consecutive losses
   - adherence %
3. **Rule adherence.** Go through the week's `plans/*.md`. Any trade that broke
   a rule gets `rule_adherent: false` in its trade file, with the reason. A
   broken rule is any of:
   - a discretionary exit
   - a card placed with changed arguments
   - an approval given without a card
   - a missed PROTECT
4. **Write the review.** Fill `templates/weekly-review.md` as
   `reviews/YYYY-Www.md` and commit.
5. **Change nothing.** Put ideas in the "Ideas for the monthly review" section.

With 1-2 trades a week, weekly numbers are noise. Use the weekly review to
check that the process was followed, not to judge the strategy.

## Monthly review (first weekend of the month, about 90 minutes)

1. Run `swing.py review` twice: once for the month and once since the start.
2. **Postmortem every closed trade.** Record R, MFE R, MAE R and the exit
   reason, and ask: did the rule do its job?
3. **Exit mix.**
   - Mostly time stops: entries may be early.
   - Mostly gap stops: size or the earnings buffer may need attention.
   - Mostly SMA20 exits: fine in choppy markets.
4. **Graduation check** (`review.graduation`):
   - **Paper → live:** only if eligible and the user wants it.
   - **0.5% → 1% risk and 3 → 6 positions:** requires eligibility on **live**
     trades after at least 10 weeks live.
5. **Tax lots and wash sales (live).** Call `get_equity_tax_lots`.
   - A loss re-bought within 30 days is a wash sale. Note it.
   - The 10-day re-entry cooldown reduces but does not prevent wash sales.
6. **Decide.** Any rule or setting change needs:
   - the reason
   - the evidence (at least 20 trades)
   - the exact old → new value
   - an effective date of next Monday

   Edit `config/rules.json` through a PR on the public repo (rules) or
   `settings.json` in the journal (settings). Bump `rules_version`.
7. Fill `templates/monthly-review.md` as `reviews/YYYY-MM.md` and commit.

## Anti-patterns to call out

- Changing rules after 2-3 losses ("it's broken").
- Loosening filters because there were no setups this week.
- Raising risk after a winning streak.
- Re-entering a symbol that just stopped out (blocked for 10 trading days
  anyway).
- Skipping PROTECT because "I'll watch it".
