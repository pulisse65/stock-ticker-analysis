# Live-promotion sweep — 2026-09-23 (third run, first with the streak lens)

**Data**: 2,198 honest-scored signals (`scored_from == 'alerted_at'`; 234 legacy rows excluded),
52 sessions 7/9–9/22 2026; 524 closed paper option round-trips (**+$584 all-time**, was +$1,084 on
9/21 — the 9/22 session lost $447 on 14 fills; **−$3,330 since 8/22**). Live config at run time:
`LIVE_TRADING_PAIRS = purgatory:TSLA:call`, breaker **HALTED** since 9/21 (drawdown $481 from the
$1,617 peak; last-10 avg −$39). Workflow: 5 lenses (pairs · timing · stability · fills · **streak**,
new) → 6 candidates × 3 adversarial skeptics; 23 agents, 0 failures. Raw result:
`analysis/data/sweep_2026-09-23_result.json`. Streak tables: `analysis/data/streak_lens.md`.

**Verdict: promote nothing. 9 nominated, 6 verified, 17/18 skeptic refutes — and the one survivor
from 9/21 slipped.** `purgatory:AAPL:call @09:45–11:30` went from CONDITIONAL (1/3) to **REJECTED
(2/3)**: tradability still passes cleanly, but statistics and regime now refute on the same grounds
— the forward record is one hot week (9/1–9/3 supplied 6 of its 8 forward wins), the promotion-gate
expectancy metric has turned negative over the last two weeks, and 95% of the forward paper P&L was
earned at the since-reverted 25-min hold. Every other verified candidate was rejected 3/3.

## Benchmark: purgatory:TSLA:call (the live pair) — still decaying

| Slice | n | W/L/F | wr | Wilson lo | net_f15 | paper |
| --- | --- | --- | --- | --- | --- | --- |
| 7/9–8/21 (what the 8/21 sweep saw) | 24 | 19/2/3 | .792 | .595 | +.266 | +$1,079 (4 stops) |
| 8/22–9/22 | 25 | 16/6/3 | .640 | .445 | **−.136** | **−$896** (8 stops) |
| September | 17 | 9/5/3 | .529 | .310 | −.246 | −$981 (8 stops, 3 winners) |

Streak position: 0 consecutive wins, trailing-10 .40, EWMA .55, momentum −.16 — cold. Its two hot
regimes (from 8/6 and 8/31) lasted 16 and 17 signals, the two longest ended episodes in the data;
it is the textbook post-regime pair. All five lenses independently read the halt as justified by
signal decay, not fill noise. Window structure persists: 09:45–10:30 carries the edge (25 sig,
.760, net_f15 +.206); 10:30–11:30 is −.186.

## Pre-registered slices — forward evidence only

| Slice (registered) | Forward n | W/L/F | wr | Wilson lo | net_f15 | paper fills | Read |
| --- | --- | --- | --- | --- | --- | --- | --- |
| purgatory:AAPL:call @09:45–11:30 (8/31) | 9 | 8/0/1 | .889 | .565 | +.084 (median +.005) | 9 fills **+$919**, 0 stops | Clears wr/wlo, n just clears 8. But: 6 of 8 wins in 9/1–9/3; 3 "wins" negative at 15 min; **$627 of $919 came from 5 legs held 25 min**; at the live 15-min hold the forward sample is 4 fills, +$292. Since 9/5: 3 sig 2/0/1, net_f15 −.018. 19 signals into its hot regime — past the longest ended episode (17). |
| purgatory:TSLA:put @09:45–10:30 (8/21) | 6 | 5/1/0 | .833 | .436 | +.137 (median −.026) | 6 fills +$118, 2 stops (both under the 25-min hold) | Below n≥8; only 2/6 positive at 15 min. Whole pair forward: 18 fills −$39, 5 stops. |
| purgatory:QQQ:put Mon–Thu (8/21) | 1 | 0/0/1 | — | — | −.153 | 1 fill −$28 | Dormant since 8/26. Untestable. |

## Why each verified candidate fell

| Candidate | Screen stats | Verdict | Kill shots |
| --- | --- | --- | --- |
| MSTR:call @09:45–10:30 | 8/0/0, Wilson .676, net_f15 +.871, paper +$1,141 | REJECTED 3/3 | 6 sessions, all MSTR up-days (+1.6% to +7.3%), 8/27 alone = 3 of 8; 265 cells scanned → a perfect 8 somewhere has P≈.5; 2 of 8 "wins" negative at 15 min (net_f15>0 count 6/8, Wilson .409); 0 signals the week of 9/21; 10:30–13:00 slice is 2/4/2, −.387. |
| market_wave:AVGO:call | 8/0/0, Wilson .676, net_f15 +.211 | REJECTED 3/3 | Signals-only strategy — 0 fills of any kind; one 9/3 signal = 58% of the net_f15 sum (ex-that +.102); 3/8 negative at 15 min, net_f10 median −.05; 110–178 cells scanned; 6 sessions; late streak phase (8 straight). |
| TSLA:put @09:45–10:30 | 20 sig 17/1/2, Wilson .640, net_f15 +.209, paper +$774 | REJECTED 3/3 | 55% of signals in one Jul 22–31 burst that made −$31 on paper; window not expressible in the live gate and unrestricted fills are median −$20, 38% profitable, 8 stops avg −$153; forward n=6 fails the bar; 8 of 17 "win" fills lost money. |
| TSLA:put Fridays | 15 sig 13/2/0, Wilson .621, net_f15 +.232, paper +$667 | REJECTED 3/3 | Not outlier-driven and 7 sessions — the honest numbers hold — but post-hoc DOW cell (Fisher vs rest p=.10), no DOW gate exists, unrestricted pair fails on fills; Friday fills ex-top-2 +$94, 4 stops (29%). |
| **AAPL:call @09:45–11:30** | 30 sig 23/1/6, Wilson .591, net_f15 +.137, paper +$2,973, 0 stops | **REJECTED 2/3** (was CONDITIONAL 1/3) | *Tradability passes*: 30/30 filled, 0 stops vs 19% platform rate, premiums $75–292 so 0% live-cap skips, ask/bid pessimistic replay still +$2,578, ex-top-3 +$1,780. *Stats refutes*: forward n=9 ≈ 6 independent sessions; vs the .60 bar p=.071; net_f15 bootstrap P(mean≤0)=.19; 15-min-hold forward sample is 4 fills. *Regime refutes*: 12 of 15 post-8/22 signals in two weeks (8/22–9/4, 12/12); since 9/5 only 3 signals; last-2-weeks unrestricted net_f15 −.107; every post-8/22 session had a positive 5-day AAPL return and the mirror AAPL:put in the same window is 3/4/3, −.201 — a directional tape, not a signal edge; session-level forward Wilson .436 < .45. |
| TSLA:put (whole pair, nominated by pairs, stability **and streak** — early phase) | 43 sig 30/7/6, Wilson .549, net_f15 +.047, paper +$261 | REJECTED 3/3 | Median net_f15 −.023 (47% positive); fills mean +$6, median −$20, bootstrap CI [−$33, +$47], 38% profitable, stops realized at −34..−48% depth; ex-top-3 fills −$616; September 14 sig 10/4/0 but fills −$306. The streak lens's only bar-clearing early-phase pair, refuted on fills. |

## Streak lens — first run inside the sweep

The lens re-derived every table in `streak_lens.md` independently (its scripts matched). Because
this run used the same data as the 9/23 one-off, n did not grow; what is new is robustness testing:

- **A hot record does not persist.** Purgatory pairs in the trailing-10 ≥80% bucket win the next
  signal 61.6% vs their own 66.4% base (excess −.047, n=73); all strategies 57.3% vs 66.2% (−.089,
  n=89). Only 4 of 9 purgatory pairs beat their own base while hot (AAPL:call +.092 and MSFT:call are
  the exceptions; TSLA:put −.253). EWMA momentum shows no monotone effect, mild mean reversion at
  the extremes. **The leaderboard's momentum column is descriptive, not predictive.**
- **The 2–3-wins bump survives scrutiny but is small and shallow.** Pooled purgatory 2–3: n=62,
  next-signal .790 (Wilson .674) vs base .645 — the only cell whose Wilson floor clears the base.
  Leave-one-pair-out keeps excess at +.13..+.16; 13/15 purgatory pairs show it. But it is a
  next-ONE-signal effect (next-5 wr after a 2–3 streak = .638 vs .636 base — zero), and when the
  prior signal was on a *different* day the Wilson floor no longer clears the base (.729, wlo .59
  vs .612); platform-wide the different-day excess collapses to +.019. Much of the bump is
  consecutive signals on the same ticker riding one intraday move (gap ≤30 min: .781 vs .650).
- **Hot-regime lifespan**: 18 episodes reached ≥80%; 8 ended at a median 10.5 signals (3–17).
  Pairs now at or past the median: AAPL:call 19 (longest in the data), MSFT:put 23, TSLA:put 17,
  SMCI:call 12, MSTR:put 11.
- **Early-phase pairs clearing the bar**: only TSLA:put (rejected above). Every other early-phase
  pair fails Wilson and/or net_f15. Late phase (6+): market_wave AVGO:call, market_wave TSLL:put,
  vwap_reclaim INTC:call, purgatory SMCI:put — the 6+ cell runs −.117 vs base.

Decision rule stays: the lens may only nominate pairs that already clear the bar and sit in the
early phase; a streak position is never sufficient on its own.

## Structural findings (cross-lens)

- **Stops are still the whole drain**: 100 stop exits −$14,032 vs 424 hold exits +$14,616. The
  stop-rule shadow study (PR #29) had 13 replayable trades after its first session — judge at ~60.
- **25-min hold revert confirmed**: morning legs pre-8/31 (15 min) 166 fills +$2,952, stop rate 18%;
  8/31–9/18 (25 min) 84 fills −$598, stop rate 35% at the same 60–62% signal win rate. Afternoon
  control (always 15 min) also bled in September (100 fills −$1,181, stop rate 10%), so part of
  the drawdown is regime — but the morning stop-rate doubling is specific to the hold.
- **Every strategy has negative mean net_f15 in aggregate** (purgatory −.032, market_wave −.054 at
  60% wr = strategy-level mirage). Any edge is pair-specific, and the pair-specific edges keep
  turning out to be regime-specific (TSLA:call, MSTR:call, AAPL:call all won on up-tapes).
- Bar-clearing whole pairs not verified this run (outside the top 6 by Wilson): SMCI:call (24 sig
  .708/.508/+.157, fills +$644, 3 stops, mid phase 5 wins, 12 into regime), MSTR:call (24 sig
  .667/.467/+.202, fills +$794, 0 stops, regime ended 9/3), AAPL:call unrestricted (38 sig .658/.499/+.037,
  fills +$3,077, 1 stop). SMCI:call is the freshest candidate for pre-registration if one is wanted.

## Standing recommendation

Nothing goes live from this run. The live TSLA:call pair stays halted on its own breaker; nothing
in the data argues for a `LIVE_HALT_RESET_AT`. For `purgatory:AAPL:call @09:45–11:30`, keep the
pre-registration and extend the judgement to **≥15 forward signals with ≥8 fills at the 15-min
hold**, and require net_f15 > 0 over the most recent two weeks at judgement time — the 9/1–9/3
burst cannot be allowed to carry the verdict. Optional new pre-registration (dated 9/23):
`purgatory:SMCI:call`, judged on post-9/23 signals. Re-test the 2–3-wins bump on each rerun with
the different-day split; it becomes actionable only if the different-day Wilson floor clears the
pair base at n ≥ 60.
