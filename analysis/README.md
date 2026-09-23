# Live-promotion sweep — rerunnable analysis

Answers: *which (strategy, ticker, direction) pairs are statistically strong enough to
promote to live trading — in total, or inside specific time-of-day / day-of-week slices?*

First run: 2026-08-21 → verdict in [results/2026-08-21-live-promotion-sweep.md](results/2026-08-21-live-promotion-sweep.md)
(short version: nothing cleared the bar; 10 nominated, 6 adversarially verified, 18/18 skeptic refutes).

Second run: 2026-09-21 → [results/2026-09-21-live-promotion-sweep.md](results/2026-09-21-live-promotion-sweep.md)
(51 sessions; 9 nominated, 6 verified, 17/18 refutes; `purgatory:AAPL:call @09:45–11:30` CONDITIONAL
and confirmed by forward evidence; live TSLA:call decay confirmed — net_f15 +.266 → −.134, paper −$806
since 8/22; the 8/31 paper 25-min morning hold doubled stop-outs → revert; stops = −$13.8k of drain).

Third run: 2026-09-23 → [results/2026-09-23-live-promotion-sweep.md](results/2026-09-23-live-promotion-sweep.md)
(52 sessions, first run with the streak lens; 9 nominated, 6 verified, 17/18 refutes; AAPL:call morning
slipped CONDITIONAL → REJECTED 2/3 — forward record is one hot week and 95% of forward paper P&L came from
the reverted 25-min hold; hot records do not persist platform-wide; only the 2–3-wins bump survives, shallow).

## How to rerun (ask Claude to "rerun the live-promotion sweep")

1. **Pull fresh data** (any python with pandas; writes to `analysis/data/`):

   ```bash
   python analysis/pull_signals.py && python analysis/pull_orders.py && python analysis/streak_lens.py
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
- **Five parallel lenses**: whole-pair conviction · time-of-day & day-of-week slices ·
  stability/recency (half-splits, week-by-week, cumulative curves) · realized fills
  (P&L, stop-outs, execution drag, outlier concentration) · streak position / momentum
  persistence (`streak_lens.py`, added 2026-09-23 — see below).
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

**9/23 update:** AAPL:call forward 9 sig 8W/0L/1F, 9 fills +$919, 0 stops — but 6 of 8 wins in 9/1–9/3 and
$627 of the P&L from 25-min legs; judgement extended to ≥15 forward signals with ≥8 fills at the 15-min hold
and net_f15 > 0 over the trailing two weeks. Optional new pre-registration 9/23: `purgatory:SMCI:call` (24 sig
.708/.508/+.157, fills +$644), judged on post-9/23 signals.

**9/21 update:** AAPL:call forward 8 sig 7W/0L/1F, 8 fills +$771, 0 stops — passes the bar on forward
evidence alone (n=8 exactly; revisit at ~15). TSLA:put morning forward 6 sig 5/1/0 but fills +$118
with ex-top-2 −$273 — not confirming. QQQ:put has fired once since 8/21 — untestable.

**Paper morning-hold experiment (started 2026-08-31):** hold-horizon curves showed morning
signals keep developing past the 15-min exit (TSLA calls before 10:30 ET: net favorable
+0.384% @15m → +0.542% @30m, n=17; pooled purgatory morning improves; midday decays).
Paper legs entered before 10:30 ET held 25 min (`PAPER_MORNING_HOLD_MINUTES`) from 8/31 to
9/21; live kept 15 everywhere. **Reverted to 15 on 2026-09-21** — the 9/21 sweep found the extra
10 minutes added no underlying edge (net_f15 +.049 vs net_f25 +.042) and doubled the morning
stop-out rate (18% → 35%). Any retest should make the stop hold-aware first. Decision rule: after ~15–20 paired morning TSLA-call trades, compare
the paper-25m legs vs live-15m legs (and vs each leg's own f15/f25) — hold duration is
derivable from `entry_filled_at` → `exit_filled_at`. Only then consider changing the live hold.

## Streak lens (added 2026-09-23)

Question: *can you catch a pair as its hot streak starts and ride it before it turns?*
`analysis/streak_lens.py` answers it deterministically from `signals.csv` (+ `orders.csv`) and
writes `data/streak_lens.md`, `data/streak_persistence.csv`, `data/streak_pairs.csv`, which the
sweep's fifth lens and the regime skeptic read. Method: for every signal of every pair with ≥15
honest signals, measure the pair's state *before* the signal (trailing-10 win rate, consecutive
wins, EWMA half-life 8) and compare with that signal's outcome and the next five. A momentum effect
must beat the pair's **own** base rate (`excess_vs_base`), not the platform's. Wilson lower bounds
sit next to every cell.

**First read (632 signal-states, 52 pairs, data through 9/22):**

| state before the signal | purgatory next-signal wr | vs own base | all strategies | vs own base |
|---|---|---|---|---|
| trailing-10 ≥ 80 % ("hot") | 62 % (n=73) | −0.05 | 57 % (n=89) | −0.09 |
| EWMA momentum > +.15 | 53 % (n=74) | −0.02 | 47 % (n=148) | −0.06 |
| 2 consecutive wins | 82 % (n=33, Wilson 0.66) | +0.18 | 72 % (n=71, Wilson 0.60) | +0.12 |
| 3 consecutive wins | 76 % (n=29, Wilson 0.58) | +0.10 | 72 % (n=53, Wilson 0.58) | +0.10 |
| 6+ consecutive wins | 55 % (n=20, Wilson 0.34) | −0.12 | 50 % (n=26, Wilson 0.32) | −0.16 |

Hot regimes (trailing-10 ≥ 80 %) that have ended lasted a median 10.5 signals before falling below
60 % (8 ended / 18). Reading: a hot *record* and the leaderboard's EWMA momentum do not persist —
they are descriptions of the past. The one bump is *early* in a streak (2–3 wins), fading by 6+;
cells are thin, so this is a **pre-registered hypothesis to re-test on each rerun**, not a rule.
Decision rule: the lens may only nominate pairs that already clear the candidate bar on their own
and sit in the early phase; the regime skeptic treats "late" (6+) or past-median-lifespan as
grounds to refute. `purgatory:AAPL:call` on 9/23: 19 signals into its regime, phase none (1 win) —
its stronger structure is time-of-day (30 morning signals, 23W/0L/7F; all 3 losses outside
09:45–11:30), tracked by the pre-registration above.

## Bullseye daily-prediction track (started 2026-09-06)

Separate from the intraday sweep: a friend's daily BUY/HOLD/SELL classifier (bullseye,
gradient-boosted over 40 daily bars, 5-session horizon) is measured on the platform before
any paper equity book is built on it. Setup, quirks, and run modes: `BULLSEYE_SETUP.md`.
Live view: the **Bullseye** tab, or `GET /purgatory/external-predictions?days=90` — the
`summary` block carries accuracy, direction hit, always-HOLD and majority-class baselines,
per-call precision, confusion matrix, per-ticker accuracy.

**Baseline read (backfill of 2026-07-09 → 2026-08-28, 384 scored rows, 11 tickers, all
`backfilled=true`):**

| metric | value |
|---|---|
| accuracy (label match) | 49.5% |
| always-HOLD baseline | 25.3% |
| majority-class baseline | 37.5% |
| direction hit | 58.3% |
| BUY precision / median move | 47.8% / +1.34% (n=226) |
| SELL precision / median move | 52.1% / −1.14% (n=94) |
| HOLD precision | 51.6% (n=64) |

Per ticker (n=37 each): AAPL 65%, SMCI 59%, MSFT 54%, IWM/MSTR/TSLA 51%, AVGO 49%,
AMZN 41%, QQQ 35%, INTC 32%.

Read with care: every row is backfilled and the model's training cut-off is unknown, so
some dates may sit inside its training set; the early 200-row read (acc 51.5%, SELL 63%)
softened as the sample grew; and the low always-HOLD baseline says this window had large
moves, which flatters a model that leans BUY/SELL. Verdict: beats both naive baselines,
roughly half the calls are wrong — *worth watching, not worth trading yet.*

**Decision rule for Stage 2 (paper equity swing book):** judge only on forward rows
(daemon output, `backfilled=false`, use the tab's forward-only toggle) after ≥ 3 weeks
(~150 rows). Proceed if forward accuracy clears the always-HOLD and majority baselines by a
margin that survives a Wilson 95% lower bound, and BUY/SELL median realized moves keep their
sign. Otherwise leave it as a measurement feed.

**Rerun / extend:**
- Backfill more history (insert-once, safe to repeat):
  `~/Downloads/bullseye-main/.venv/bin/python bullseye_runner.py backfill --days 120`
- Scoring is automatic (scan loop, 30-min throttle, 200 rows/pass, completed sessions
  only). Off-hours, `curl -X POST https://tickertracker.dev/purgatory/scan` forces a pass.
- Runner output was verified identical to `app.py -p TICKER DATE -j` on the same DB, so the
  platform scores the model exactly as shipped (incl. its `return_1d ≡ 0` and yield-curve
  ≡ 0 inference quirks — see `BULLSEYE_SETUP.md`).

## Stop-rule study (started 2026-09-22)

The 9/21 sweep's biggest structural finding: 98 stop exits = −$13.8k vs 412 hold exits = +$14.9k.
Fills alone can't say what a different stop would have done (a stopped option's later price is never
observed), so the platform now records the option quote path on every open paper position (every
scan already quotes it for the stop check → `purgatory_orders.raw.quote_path`) and, after a stop,
keeps quoting the contract until the original hold deadline (`raw.shadow`, with `hold_mid`).

`GET /purgatory/stop-study?days=30` replays thresholds 10/15/20/25/30/40/50% and *no stop* over the
real paths; the Trading tab shows it as "Stop-rule study". Trading behaviour is unchanged (the live
and paper stop is still `ALPACA_TRADING_STOP_LOSS_PCT` = 30 — one knob for both accounts, which is
why the study is shadow-tracked rather than an A/B on the paper account).

Read with care: paths are one sample per scan (~4 min), so thresholds tighter than 30% are evaluated
on a coarse grid (a 15% stop that would have fired between samples is missed); a "no stop" total
ignores the tail risk a stop exists to cap — look at the *Worst* column, not just the total.
Decision rule: at least ~60 replayable trades (≈3 weeks) before comparing rules; prefer the rule with
the best total that does not materially worsen the worst trade; retest the 25-min morning hold only
once the stop rule is settled.
