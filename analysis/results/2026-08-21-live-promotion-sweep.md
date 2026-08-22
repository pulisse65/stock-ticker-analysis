# Live-promotion sweep — 2026-08-21

**Data**: 707 honest-scored signals (`scored_from == 'alerted_at'`), 32 sessions 7/9–8/21 2026;
239 closed paper option round-trips (+$3,914 total). Live config at run time:
`LIVE_TRADING_PAIRS = purgatory:TSLA:call`, notional $500, per-trade cap $750.

**Verdict: promote nothing.** 10 slices passed the numeric screen
(n≥8, wr≥60%, Wilson lo ≥0.45, net_f15>0); the top 6 were each adversarially verified by
3 independent skeptics (statistics / tradability / regime) → **18/18 refuted**. The
remaining 4 fail on the same cross-lens evidence.

## Benchmark (already live): purgatory:TSLA:call

n=24 honest signals, 19W/2L/3F, wr 79.2%, Wilson lo 0.595, net_f15 +0.266, net_f30 +0.328,
14 sessions, paper +$1,079/23 fills. Live record at run time: 4 trades, 4 wins, +$1,517
(8/18 +$30, 8/19 +$886, 8/21 +$601). Watch item: since 8/13 its threshold win rate fell to
50% (4W/1L/3F) while expectancy improved (+0.411 net_f15, +$1,179 paper) — wins got bigger.

## Why each top candidate fell

| Candidate | Screen stats | Kill shots |
| --- | --- | --- |
| TSLA:put @09:45–10:30 | 12W/0L/2F, Wilson 0.601, net_f15 +0.241 | 84% of paper P&L from one session (8/12); July fills −$31 despite 9/11 signal wins; ~3 signals in all of August; fails multiple-comparison haircut vs 61% window base rate; window gating not expressible in LIVE_TRADING_PAIRS |
| TSLA:put whole pair | n=24, 70.8%, Wilson 0.508, net_f15 +0.064 | fills: 8/24 positive, median −$17.50; ex-8/12 session = −$252/22 fills; all 3 stop-outs outside the morning window |
| MSFT:call whole pair | n=27, 70.4%, Wilson 0.515, net_f15 +0.038 | decayed: halves 92.3%→50.0%, Aug net −0.146; drag −$23/fill ate 67% of mid P&L; 17% of fills over the $750 live cap |
| MSFT:call @10:30–11:30 / @10:30–12:00 | 8W/1L, Wilson 0.565, net_f15 +0.179 | 6 of 8 wins from 7/9–7/16; 3 signals in the 26 sessions since; Aug n=2 |
| MSFT:call Thursdays | 7W/0L/1F, net_f15 +0.519 | mean carried by one +3.18% pre-open outlier (ex: +0.139); dow gating not expressible |
| AMZN:call Mon–Thu | 12W/1L/3F, Wilson 0.505, net_f15 +0.244, paper +$707 | Fridays −$808 (sharpest day effect found) but Aug Mon–Thu is 2/5 net −0.044 — decayed; whole pair Wilson 0.407, paper −$101 |
| QQQ:put (whole / Mon–Thu) | 70.6% / 76.9% | whole-pair net_f15 +0.003, net_f30 negative (move fades past 15 min); 13 Mon–Thu signals in 6 sessions with same-minute bursts; fills ex-top2 −$294 |

## Structural findings

- **Scalper-metric mirage confirmed**: MSFT:put wr 72.2% (Wilson 0.491) yet net_f15 −0.106
  and paper **−$514/17 fills** — wins tap +0.10% momentarily and retrace before the 15-min
  exit. Inverse anomaly: AAPL:call wr only 50% but the cleanest fill book (+$1,151, zero
  stop-outs) — the underlying-move scorer underrates it; recheck as n grows.
- **Scorer validated at the fill level**: fills on win-scored signals +$10,174 (n=141);
  loss-scored −$3,684 (0/33 positive); flat-scored −$2,576.
- **Edge is front-loaded**: 09:45–10:30 is the only pooled window with Wilson lo > 0.5
  (57.3% wr); win rate decays monotonically to ~30% by early afternoon. Monday is the worst
  day (34.1%); Wed/Thu best (purgatory Wed 62.1%, Thu 61.9% net_f15 +0.121).
- **Stop-losses drain**: 41 stop exits = −$5,646 vs 198 hold exits = +$9,560.
- **Defensive candidates (paper book)**: AAPL:put is the worst pair — −$923, 9 stop-outs,
  its 09:45–10:30 slice alone 3W/7L −$730 → disable-list candidate alongside AVGO.
  purgatory:AVGO:put data (42.9% wr, net −0.051) supports the existing disable.
- **Non-purgatory strategies**: nothing promotable. bb_squeeze:TSLA:call's 80% wr is 70%
  built on windows now skip-gated (effective n=3 under current config). ema_pullback fails
  every slice. vwap_reclaim dead (kill-gate). orb_ntz not evaluable until plan verdicts
  reach n≥30.

## Pre-registered forward candidates (as of 2026-08-21)

Judge only on signals fired after this date; revisit at ~10–15 forward signals each:

1. `purgatory:TSLA:put` @ 09:45–10:30 ET
2. `purgatory:QQQ:put` Mon–Thu

Both would need a time/day-scoped live gate (new feature) if they ever pass.
