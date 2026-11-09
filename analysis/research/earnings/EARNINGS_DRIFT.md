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

## Result (read 2026-11-08, `PEAD_RESULTS.md`, `pead_backtest.py`)

Coverage: yfinance earnings history reaches April 2016 (2016 partial); prices
for 105/106 tickers (BK none); S&P 100 set 4,154 events, median 42 per
ticker; watchlist 499 events (SPCX too short for sigma60). 27% of events have
z ≥ 2 — earnings days are routinely 2 normal-day sigmas, so the primary
signal means "clearly positive reaction", not "extreme".

Primary cell — S&P 100, z ≥ 2, hold 10 sessions, net of 10 bps:

| | value | bar | |
|---|---|---|---|
| n | 1,104 | | |
| mean net return / trade | +1.03% (median +0.93%) | > 0 | ✓ |
| random same-ticker baseline | +0.65% → paired t = 2.22 | t ≥ 2.0 | ✓ |
| SPY same windows | +0.54% → paired t = 3.27 | (reported) | |
| hit rate | 58.5%, Wilson lower 55.6% | > 50% | ✓ |
| years positive (n ≥ 10) | 11 of 11 | ≥ 60% | ✓ |
| excluding best ticker (TSLA) | +0.96%, t vs random 1.89 | > 0 | ✓ |
| watchlist subset | n 144, +2.45%, t vs random 2.45 | > 0 | ✓ |

Secondary (not judged): hold 5 +0.48% (t 1.91), hold 20 +1.70% (t 1.67) —
the excess over random is largest at 10. Top-quintile raw reaction: +1.18%,
t 2.49. Mirror z ≤ −2 long: +0.45% vs random +0.64% (t −1.03) — weak
negative drift on the downside, i.e. the effect is roughly symmetric and
not just "stocks go up".

**Verdict on the frozen rule: PASS (5 of 5).**

What the pass does and does not say:
- The signal-attributable edge is the paired excess over owning the same
  names at random times: **≈ +0.38% per 10-session trade**, t 2.2, on one
  pre-registered test. Real but small. The headline +1.03% is mostly the
  names' own drift (survivorship: current constituents), which the random
  baseline shares.
- Scale: ~105 qualifying S&P 100 events a year. At $2,000 per trade and
  10-session holds that is ≈ $2,100/yr gross on ~$4k average deployed, of
  which ≈ $800/yr is attributable to the timing signal. It does not
  transform a $10k book; it is a positive-expectancy process with costs
  that do not eat it, which the intraday option book has never been.
- Not modelled: slippage beyond 10 bps (negligible at this size), overlapping
  positions / capital constraints, taxes, the 2016 partial year.
- The ticker table is top-heavy in recent momentum names (TSLA, PLTR, INTC,
  QCOM); the ex-TSLA condition passes but t falls to 1.9.

Next (Task 6, owner's "go"): a SWING_BOOK-style paper book — S&P 100 + the
watchlist, z ≥ 2 at the reaction close, buy next open, sell at the 10th
close, equal $ slots with a concurrency cap, pre-registered 13-week read
against the random-entry baseline computed the same way. Stock only, paper
only, nothing live.
