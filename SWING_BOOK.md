# Swing book — pre-registered 2026-10-27

A paper **stock** book that runs beside the intraday options book and never
touches it. It exists to answer the question the 90-day read left open:
every dollar the project has made came from being long strong names during
up weeks, so test *that* directly, with the rule frozen before the data.

## The rule (frozen)

- **Universe:** the watchlist as of 2026-10-27 (17 names, `/purgatory/status`
  → `watchlist`). Override only via `SWING_UNIVERSE`; any change is a new
  registration.
- **Bars:** weekly, weeks ending Friday, built from daily closes. Only
  completed weeks count: a Monday read sees last Friday and nothing newer.
- **Eligible:** last weekly close above the weekly Ichimoku cloud (9/26/52,
  both spans) **and** above the close 26 weeks earlier (lagging span).
- **Rank:** eligible names by 12-week return, best first.
- **Book:** top 5, equal weight, `SWING_NOTIONAL_USD` (default $10,000) / 5
  per slot, whole shares, paper market orders. A name already held stays
  while it is still eligible and ranked ≤ 8 (buffer 3); otherwise it is
  sold and the slot refilled best-first.
- **Cadence:** once per trading week, the first scan at or after 09:35 ET on
  Monday (or the first session if Monday is a holiday). Sells first, then
  buys. One `rebalance` marker row per week in `swing_trades` guards against
  double runs.
- **Benchmarks:** equal-weight universe and SPY, total return from the first
  rebalance date, same closes.

## What the six-year backtest said (why these numbers)

`analysis/research/ichimoku_bb/swing_momentum.py`, Oct-2020 → Oct-2026,
weekly, no costs, long only. On the 16-name watchlist: top-5 / 12-week /
cloud-required 27.8% CAGR vs 31.6% buy-and-hold, max drawdown −37% vs −36%,
2022: +5% vs −34%. On a 36-name universe that includes names picked with
hindsight (NVDA, PLTR, COIN…) it looked better (33.6% vs 33.7%, −32% vs
−40%), which is exactly why the live universe is frozen to the watchlist.
Over rolling 52-week windows it beat SPY 85% of the time; over 13-week
windows only 57%. Expect a typical month near zero and a bad quarter near
−15%.

## Pre-registered read

**Date:** the first Monday after 13 completed weeks (≈ 2027-01-25). One read.

**Pass to a second quarter** if both hold, measured from the first rebalance:
1. Max drawdown of the book ≤ max drawdown of the equal-weight universe.
2. Total return ≥ 0.5 × equal-weight universe return when that return is
   positive; or total return > equal-weight universe return when it is ≤ 0.

**Fail** otherwise: the book is closed and the result recorded. No
re-reads, no parameter changes, no universe changes mid-test. Real money is
a separate decision that needs two consecutive passing quarters and is the
owner's alone.

## Running it

1. Run `supabase_swing_trades.sql` once in the Supabase SQL editor.
2. Set on Render: `SWING_ENABLED=1` (and optionally `SWING_NOTIONAL_USD`,
   `SWING_TOP_N`, `SWING_BUFFER`, `SWING_UNIVERSE`).
3. Dry run anytime, token-gated:

```bash
curl -s -X POST -H "X-Signal-Token: $EXTERNAL_SIGNAL_TOKEN" "https://tickertracker.dev/purgatory/swing/rebalance?dry_run=1"
```

4. `GET /purgatory/swing` shows the ranked table, the target book, paper
   holdings, book value vs benchmarks, and the order log. The Trading tab
   has a card for it.

Paper only. The live account is never used by this module.
