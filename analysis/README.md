# Live-promotion sweep — rerunnable analysis

Answers: *which (strategy, ticker, direction) pairs are statistically strong enough to
promote to live trading — in total, or inside specific time-of-day / day-of-week slices?*

First run: 2026-08-21 → verdict in [results/2026-08-21-live-promotion-sweep.md](results/2026-08-21-live-promotion-sweep.md)
(short version: nothing cleared the bar; 10 nominated, 6 adversarially verified, 18/18 skeptic refutes).

## How to rerun (ask Claude to "rerun the live-promotion sweep")

1. **Pull fresh data** (any python with pandas; writes to `analysis/data/`):

   ```bash
   python analysis/pull_signals.py && python analysis/pull_orders.py
   ```

2. **Refresh the PLATFORM FACTS block** in `promotion_sweep.workflow.js` — live pairs,
   disabled pairs, skip windows, muted strategies, and plan-scored strategies drift.
   Check `https://tickertracker.dev/purgatory/status` and `LIVE_TRADING_PAIRS` /
   `PURGATORY_DISABLED_PAIRS` / `_STRATEGY_SKIP_WINDOWS` in main.py.

3. **Launch the workflow** (Claude Code Workflow tool):

   ```
   Workflow({scriptPath: "analysis/promotion_sweep.workflow.js",
             args: {dataDir: "<abs path to analysis/data>",
                    python: "<abs path to a python with pandas>",
                    dates: "<e.g. 7/9–9/15 2026, 48 sessions>"}})
   ```

4. Compare the new verdicts against the previous file in `results/`, then write a new
   dated results file there.

## Design (why the answer can be trusted)

- **Data**: every persisted signal (honest filter: `scored_from == 'alerted_at'` only) plus
  every closed paper option round-trip (real fills, realized $).
- **Four parallel lenses**: whole-pair conviction · time-of-day & day-of-week slices ·
  stability/recency (half-splits, week-by-week, cumulative curves) · realized fills
  (P&L, stop-outs, execution drag, outlier concentration).
- **Candidate bar**: n ≥ 8 honest signals in the slice, win rate ≥ 60 %, Wilson 95 %
  lower bound ≥ 0.45, avg net_f15 > 0.
- **Adversarial verification**: each top candidate faces three independent skeptics told
  to refute — statistics (multiple comparisons, outlier sensitivity), tradability
  (fills, drag, premium vs live caps, whether the gate can even express the slice),
  regime (hot-week concentration, session clustering, recency). Majority refute = dead.
- **Known traps it checks for**: scalper-metric mirage (high win rate, negative net_f15 —
  e.g. MSFT:put), window/dow slices that `LIVE_TRADING_PAIRS` cannot express, paper P&L
  carried by 1–2 outlier trades, edges concentrated in one hot week, pre-8/13 bb_squeeze
  signals in now-skipped windows, orb_ntz generic metrics (plan-scored strategy).

## Standing recommendation from the first run

Promote nothing retroactively. Instead **pre-register** promising slices and judge them on
signals that fire *after* the registration date — forward evidence is immune to the
multiple-comparisons objection. Pre-registered on 2026-08-21:

- `purgatory:TSLA:put` restricted to 09:45–10:30 ET
- `purgatory:QQQ:put` restricted to Mon–Thu
- *(added 2026-08-31)* `purgatory:AAPL:call` in the morning (09:45–11:30 ET): flagged by three
  independent lenses — best fill book (+$1,151, zero stop-outs, not outlier-dominated), and
  80–82% positive-net hit rates at 15m/25m holds in both morning windows across 8–9 sessions
  (n=10–11 each) despite a mediocre generic win rate (its moves are consistently positive but
  small, so the +0.10%-in-30min threshold underrates it). Judge on post-8/31 signals.

Revisit either after ~10–15 forward signals with positive paper fills.

**Paper morning-hold experiment (started 2026-08-31):** hold-horizon curves showed morning
signals keep developing past the 15-min exit (TSLA calls before 10:30 ET: net favorable
+0.384% @15m → +0.542% @30m, n=17; pooled purgatory morning improves; midday decays).
Paper legs entered before 10:30 ET now hold 25 min (`PAPER_MORNING_HOLD_MINUTES`); live
keeps 15 everywhere. Decision rule: after ~15–20 paired morning TSLA-call trades, compare
the paper-25m legs vs live-15m legs (and vs each leg's own f15/f25) — hold duration is
derivable from `entry_filled_at` → `exit_filled_at`. Only then consider changing the live hold.
