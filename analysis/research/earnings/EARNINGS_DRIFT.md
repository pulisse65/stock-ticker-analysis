# Post-earnings drift backtest — rules frozen 2026-11-08, BEFORE running

Task 5 of `analysis/plan_2026-11-08.md`. Hypothesis: after a large positive
earnings-day price reaction, the stock keeps drifting up for days to weeks
(post-earnings-announcement drift). This is the one "external factor" with a
long replication record, and it lives at a horizon (sessions, not minutes)
and instrument (stock, not options) where this book's measured costs are
negligible.

## Frozen rules
- **Universe.** (a) Watchlist stocks with earnings (AAPL AMZN ASST AVGO INTC
  META MSFT MSTR NOK ORCL QCOM SMCI SPCX TSLA); (b) current S&P 100 members,
  reported separately. Both lists are CURRENT constituents → survivorship
  bias toward names that did well; stated, not corrected.
- **Data.** yfinance daily bars, auto-adjusted, 2016-01-01 → 2026-11-06, plus
  SPY. Earnings timestamps from yfinance `get_earnings_dates`; events with
  a report time before 09:30 ET react that session, otherwise the next
  session. Events after 2026-10-15 are dropped (hold windows incomplete).
- **Signal.** Reaction return `r = close(reaction session) / close(prior
  session) − 1`, standardized by the ticker's trailing 60-session daily
  close-to-close standard deviation measured up to the prior session:
  `z = r / sigma60`. **Primary: z ≥ +2.** Secondary (reported, not judged):
  pooled top quintile of raw `r`. Mirror (reported): z ≤ −2.
- **Trade.** Buy at the OPEN of the session after the reaction session.
  **Primary hold: 10 sessions** (sell at the close of the 10th session after
  entry). Also report 5 and 20. Cost 5 bps per side (10 bps round trip).
  Equal weight per trade; returns per trade, no leverage.
- **Baselines.** (1) Random: for each trade, the same ticker and hold,
  entered at 20 random non-event sessions (≥ 10 sessions from any event),
  averaged — the ticker's unconditional drift. (2) SPY over the identical
  windows. (3) The mirror set (z ≤ −2) long, to see whether drift is
  symmetric.
- **Statistics.** n, mean and median net return per trade, hit rate with
  Wilson 95% lower bound, paired t-statistic of (trade − random baseline),
  by year, by ticker, and excluding the single best ticker.

## Decision rule (primary = z ≥ 2, hold 10, S&P 100 set)
PASS requires all of:
1. mean net return per trade > 0 and paired t vs the random baseline ≥ 2.0;
2. hit-rate Wilson 95% lower bound > 50%;
3. positive mean in ≥ 60% of calendar years that have ≥ 10 trades;
4. mean still > 0 excluding the best single ticker;
5. the watchlist subset's mean net return > 0 (no t requirement, small n).
FAIL on any miss. A PASS leads to a SWING_BOOK-style paper pre-registration
(Task 6); a FAIL is recorded and the idea is dropped unless a different,
newly pre-registered variant is proposed. No rule is changed after reading
the results; variants seen in the secondary tables are not promoted.

## Result
(filled in after the run — see below)
