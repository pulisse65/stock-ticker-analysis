# Ticker Tracker — independent review brief (data as of 2026-10-21, after close)

This folder is a complete, self-contained snapshot for an outside reviewer.
Nothing here is advice to trade. The owner wants a second, skeptical read of
the statistics and the engineering decisions before any more real money goes in.

## 1. What the system is

- **Ticker Tracker** (tickertracker.dev): a FastAPI + vanilla JS app that scans
  17 watchlist tickers on 1-minute bars every minute during US market hours, fires
  directional signals ("call" / "put") from ten rule-based detectors, scores
  each signal on the underlying 5–30 minutes later, and auto-trades a subset
  as short-dated options through Alpaca.
- **Signal scoring.** `f5..f30` are the signed favorable underlying moves
  (%) at 5–30 minutes after the signal bar. The stored `outcome` label is
  *win* when the **best** of those moves, net of a 0.05% spread stand-in,
  exceeds +0.10% (flat within ±0.10%, loss below). That is a 30-minute-best
  label, not a fixed 15-minute hit rate; for a 15-minute hold use
  `f15 ≥ +0.05` directly (`net_f15 = f15 − 0.05`). Both are reported in
  `REVIEW_RESPONSE.md`. (Corrected 2026-10-22; the first version of this
  brief described the label wrongly.)
  Only rows with `scored_from == 'alerted_at'` are honest (scored forward
  from the moment the alert fired); the rest were back-filled and are
  excluded from every number below.
- **Paper book.** Every signal from the strategies in `STRATEGIES_TRADING`
  becomes a paper options trade: ATM-ish nearest-expiry contract, $500
  notional (qty = notional / premium, min 1), exit at a 15-minute hold timer
  or a 15% stop on the option's mid price, checked once per scan. Entry and
  exit are market orders; realized P&L includes bid/ask drag.
- **Live book.** Currently one pair: `purgatory:AAPL:call`, 09:45–11:30 ET
  window, since 2026-10-06: three fills, −$184; the account-level breaker
  halted it on 2026-10-21 (cumulative loss ≤ −$150). Before that the live
  account traded `purgatory:TSLA:call` 2026-08-18 → 09-21 (18 trades,
  +$1,136), so the live ledger holds 21 trades, +$952 all time.
- **Strategies.** `purgatory` (the original breakout/pullback detector), plus
  `vwap_reclaim`, `market_wave`, `orb_ntz`, `pd_level`, `bb_squeeze`,
  `ema_pullback`, `vwap_reversion` (signals only unless named in
  `STRATEGIES_TRADING`). Between 2026-10-09 and 10-21 `vwap_reclaim` and
  `market_wave` were also paper-traded; that was reverted on 10-21.
- **Promotion discipline.** Pairs (strategy:ticker:direction) are promoted
  to live only after a pre-registered forward test: ≥15 honest signals after
  the registration date with Wilson lower bound ≥ .45, net_f15 mean AND
  median > 0, ≥8 paper fills positive at the 15-minute hold with the largest
  fill < 50% of the total, and trailing-2-week net_f15 > 0. Pairs are also
  auto-muted when their trailing-30-day record drops to ≤30% win rate (min
  10 signals) and un-mute themselves if it recovers.

## 2. Files

| file | what it is |
|---|---|
| `signals.csv` | every persisted signal (4,444 rows; 4,210 honest). Columns: strategy, ticker, direction, bar_time (UTC), alerted_at, price, scored_from, outcome (win/loss/flat), f5…f30 (signed favorable % move), ET time columns. |
| `orders.csv` | every paper round-trip (1,189 rows, 2026-07-09 → 10-21). Columns: strategy, account, ticker, direction, bar_time, qty, entry, exit (fill prices), pnl ($), exit_reason (hold / stop_loss), entry/exit timestamps, et_time, dow. |
| `pairs_90d.csv`, `pairs_30d.csv` | paper P&L by pair: n, pnl, avg, win_rate, stops, stop_avg, hold_avg. |
| `strategy_90d.csv`, `strategy_direction_90d.csv`, `exit_reason_90d.csv`, `hour_et_90d.csv`, `weekly_alltime.csv`, `monthly_alltime.csv`, `direction_by_month_purgatory.csv` | the same aggregation on other keys. |
| `signal_pairs_alltime.csv`, `signal_pairs_30d.csv`, `signal_strategy_alltime.csv` | signal-level records with Wilson lower bounds and net_f15 mean/median. |
| `mstr_call_forward_since_1007.csv` | the pre-registered forward sample for purgatory:MSTR:call. |
| `raw/status.json` | live config: pairs, windows, breaker state, auto-muted pairs, strategy roster, knobs. |
| `raw/pnl_paper.json`, `raw/pnl_live.json` | per-day realized P&L series with rollups. |
| `raw/leaderboard_30d.json`, `raw/leaderboard_90d.json` | per-pair signal records (all / window / momentum / paper fills). |
| `raw/stop_study_*.json` | the stop-rule replay (see §4) platform-wide and per slice. `*_detail_*.json` carry one audit row per replayed trade. |
| `raw/hold_study_*.json` | the hold-length replay (15/20/25/30-minute exits on real option quote paths, 15% stop applied; exit mid = nearest sample within ±5 min of each horizon, so not exact-minute executions). |
| `EXTERNAL_REVIEW_chatgpt_sol.md`, `REVIEW_RESPONSE.md` | the independent review received 2026-10-22 and the point-by-point response. |
| `raw/bullseye_external_predictions.json` | a friend's daily ML forecasts (buy/hold/sell per ticker) and their scored accuracy; a side track, not used for trading. |

All money figures are USD on a $500-notional paper book. Times in raw JSON
are UTC; `et_time` columns are America/New_York.

## 3. Headline numbers the owner has already seen

Paper, `orders.csv`, `account == paper`, 2026-07-24 ≤ date ≤ 10-21:
1,123 round-trips, −$10,604 (corrected 2026-10-22; the first version of
this table was built from a merge that dropped six rows). Win = pnl > 0.

| slice | n | P&L | win rate | stops |
|---|---|---|---|---|
| hold exits | 806 | +$23,744 | 47.4% | — |
| stop exits | 317 | −$34,348 | 0.3% | 317 |
| purgatory calls | 382 | +$2,892 | 41.9% | 91 |
| purgatory calls excluding AAPL | 343 | −$122 | 39.9% | 85 |
| purgatory puts | 411 | −$7,475 | 32.8% | 105 |
| vwap_reclaim (10/12–10/21 only) | 197 | −$3,690 | 27.4% | 73 |
| market_wave (10/12–10/21 only) | 133 | −$2,331 | 25.6% | 48 |

- Stops by rule era (the stop was 30% until 2026-10-03, 15% since): 127
  stops at mean −34.4% of debit under the 30% rule; 190 at mean −18.2%
  (median −18.4%) under the 15% rule, ≈ $15 per stop beyond the line.
- AAPL call (the live pair): Aug +$1,278 (10/12), Sep +$2,179 (11/15), Oct
  −$379 (1/8, 4 stops). Live: 3 fills, 2 stops, −$184.
- MSTR call: 43 fills +$1,178, 22/43 profitable, 1 stop in 90 days. Signal
  record, 45 honest rows: stored label 32/45 = 71% (Wilson .57); fixed-15
  endpoint 25/44 = 56.8% (Wilson .42). Forward sample since 10-07: 13
  signals of the 15 required, 10W/2L/1F on the stored label; 12 observed
  `f15` (one missing), 10/12 ≥ +0.05, net mean +.46 / median +.26; 12
  fills +$607, largest 36% of total; four of those fills held 9–22 minutes
  rather than 15 (cause and fix in `REVIEW_RESPONSE.md`).
- Hold study (309 usable trades, mid-to-mid): 15-min −$3,534, 20 −$4,406,
  25 −$3,704, 30 −$4,921. Longer holds add stops and lose more.

## 4. Stop-rule replay (counterfactual) — read the caveats

Since 2026-09-22 every open position's option mid is recorded once per scan
(`raw.quote_path`), and stopped positions keep being quoted to their hold
deadline. The replay applies each threshold (10–50%, none) to those paths.
Pricing basis: stopped trades exit at the triggering sample's mid (or the
recorded hold-time mid when the replay lets them run); held trades exit at
their real fill. No spread cost on the mid legs. It covers only trades with a path
(~4 weeks), and on 2026-10-21 two defects were found and fixed the same
day: samples at/after the hold deadline and quotes recorded after the
position had already closed (some of them garbage, e.g. MSTR 4.60 → 0.73)
were triggering replay stops that never happened. The numbers in
`raw/stop_study_*.json` are post-fix; `REPLAY_RESULTS.md` has the table.

## 5. What the owner changed on 2026-10-21

- `STRATEGIES_TRADING` back to `purgatory` only.
- New `TRADING_DIRECTIONS` switch (default call,put) so puts can be turned
  off for order placement while still being scored. Not yet set.
- Per-pair filters and a per-trade audit on the stop study; the replay
  path capped at the hold deadline.
- Live stays halted. MSTR call forward read scheduled for Fri 2026-10-23.

## 6. Questions for the reviewer

1. Is "hold exits are profitable" anything other than survivorship? Is the
   no-stop row the right counterfactual, and what is it missing (spread,
   slippage on the hold exit, path-dependence of the stop check cadence)?
2. The stop realizes ~25% on a 15% rule. Is the fix tighter cadence, a
   limit exit, a wider stop with smaller size, or no stop on calls?
3. Puts lose under every configuration across 90 days and 409 trades.
   Is there any reading of the data under which puts should keep trading?
4. AAPL call: Aug–Sep 83%/71% then Oct 12%. Regime, mean reversion of a
   lucky sample, or something structural (AAPL went live the week it went
   cold)? What would a fair prior be for the next 20 trades?
5. MSTR call clears every pre-registered criterion at n=13 of 15. Is the
   pre-registration itself sound? What are the ways a 45-signal, 71%
   record on one ticker is fooling us (expiry choice, premium size, qty=1
   sizing, time of day, BTC beta)?
6. Sizing: $500 notional / premium gives 10–16 lots on cheap contracts and
   1 lot on MSTR. Is that creating the stop-loss skew by itself?
7. Multiple comparisons: ~250 pairs × several windows. What false-discovery
   control should the promotion rule carry?
8. What single experiment, run for two weeks on paper, would most change
   the decision about real money?

## 7. Constraints the reviewer should respect

- Do not provide personalized financial advice or tell the owner to buy or
  sell anything. Statistics, methodology and engineering only.
- Treat every number here as paper or small live samples; do not
  extrapolate to annualized returns.
- Credentials and account identifiers are deliberately absent from this
  package; do not ask for them.
