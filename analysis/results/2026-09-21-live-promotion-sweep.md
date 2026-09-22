# Live-promotion sweep — 2026-09-21 (second run)

**Data**: 2,080 honest-scored signals (`scored_from == 'alerted_at'`; 234 legacy rows excluded),
51 sessions 7/9–9/21 2026; 510 closed paper option round-trips (+$1,084 all-time, **−$2,830 since
8/22**). Live config at run time: `LIVE_TRADING_PAIRS = purgatory:TSLA:call`, **breaker HALTED
9/21** (drawdown $481 from the $1,617 peak). Same workflow as 8/21 (4 lenses → 6 candidates × 3
adversarial skeptics), platform facts refreshed. Raw result: `analysis/data/sweep_2026-09-21_result.json`.

**Verdict: promote nothing today. One candidate survives conditionally.** 9 nominated, 6 verified:
**17/18 skeptic refutes**. Five candidates rejected 3/3. `purgatory:AAPL:call @09:45–11:30` is
CONDITIONAL (1/3 refute — statistics only) and is the only pair confirmed by pre-registered forward
evidence. It also needs no time gate to trade: the whole pair's fill book is the best on the platform.

## Benchmark: purgatory:TSLA:call (the live pair) — the decay is real

| Slice | n | W/L/F | wr | Wilson lo | net_f15 | paper |
| --- | --- | --- | --- | --- | --- | --- |
| 7/9–8/21 (what the 8/21 sweep saw) | 24 | 19/2/3 | .792 | .595 | +.266 | +$1,079 |
| 8/22–9/21 | 23 | 15/5/3 | .652 | .449 | **−.134** | **−$806** (23 fills, 8 stops) |
| since 9/8 | 13 | 6/4/3 | .462 | .232 | −.339 | |

Win rate held near 65% while **move size collapsed**: wins got shallower (+0.1–0.5%) and losses
deeper (−1.0% on 9/9 ×2, 9/15, 9/17), which the 30% option stop converts into −$112 average
stop-outs. "Signal win but option lost" rate for this pair: 38% (13 of 34). Live: 18 trades,
+$1,136 all-time, the first four trades (8/18–8/21) made +$1,517 and the next 14 made −$381.
Every lens independently concludes the halt is justified by the data.

## Pre-registered slices — forward evidence only (post-registration signals)

| Slice (registered) | Forward n | W/L/F | wr | Wilson lo | net_f15 | paper fills | Read |
| --- | --- | --- | --- | --- | --- | --- | --- |
| purgatory:AAPL:call @09:45–11:30 (8/31) | 8 | 7/0/1 | .875 | .529 | +.093 | 8 fills **+$771**, 0 stops | **Passes the bar on forward evidence alone** (n=8 exactly). Whole pair since 9/1: 11 sig 9/1/1, 10 fills +$969. |
| purgatory:TSLA:put @09:45–10:30 (8/21) | 6 | 5/1/0 | .833 | .436 | +.137 | 6 fills +$118, 2 stops; ex-top-2 −$273 | Signals fine, fills not confirming; n too small. Whole pair forward: 18 fills −$39. |
| purgatory:QQQ:put Mon–Thu (8/21) | 1 | 0/0/1 | — | — | −.153 | 1 fill −$28 | Pair stopped firing (last signal 8/26). Untestable. |

## Why each verified candidate fell

| Candidate | Screen stats | Verdict | Kill shots |
| --- | --- | --- | --- |
| MSTR:call @09:45–10:30 | 8/0/0, Wilson .676, net_f15 +.871, paper +$1,141 | REJECTED 3/3 | 6 sessions, 3 signals in 21 min on 8/27; a perfect 8-streak somewhere among 34 windowed cells has P≈0.53 by chance; **$1,041 of the $1,141 came from 4 post-8/31 25-min paper legs** — the 3 fills that held 15 min (what live does) made +$100; outside the window the pair is 8/6/2 net −.133, fills −$347. |
| TSLA:put @09:45–10:30 | 17/1/2, Wilson .640, net_f15 +.209, paper +$774 | REJECTED 3/3 | 7 of 17 "wins" had net_f15 ≤ 0; median fill −$16.50, 11/20 fills negative, top-3 fills = 110% of P&L; 8/12 session = 71% of P&L; net_f30 decays +.707 (Jul) → +.236 (Aug) → +.010 (Sep); unrestricted pair: 42 fills +$261, 38% profitable, ex-top-2 −$346; window not expressible in the live gate. |
| **AAPL:call @09:45–11:30** | 22/1/6, Wilson .579, net_f15 +.141, paper +$2,825 | **CONDITIONAL 1/3** | *Stats skeptic (refute, medium):* selection pressure — binomial p .0041 × ~100 cells; registration on 8/31 came right after a 6/6 run; as of 8/21 the cell was 9/1/5 Wilson .357. *Tradability (survive):* 34 fills +$2,929, 25W/9L, **1 stop-out in 34** (2.9% vs 19% platform), worst trade −$144, max drawdown −$144 on a +$3,003 peak, avg premium $1.77, 0 fills over the $750 cap, window fills bootstrap 95% CI [+$47, +$157]/trade, every window signal filled. *Regime (survive):* 20 sessions across 11 weeks, best session 3/22 wins, Jul .455 → Aug 10/0/0 → Sep 7/0/1, positive net_f15 every month; last 14 days 3W/1L/1F net −.13 — watch. |
| TSLA:put whole pair | 30/7/6, Wilson .549, net_f15 +.047, paper +$261 | REJECTED 3/3 | Fails the .55 Wilson haircut; simulating 165 no-edge cells produces a max Wilson ≥ .549 in 81% of runs; median net_f15 −.023; fills 38% profitable, median −$20, ex-top-2 −$346, ex-top-5 −$1,068, 20 fills underwater to −$657 before recovering; net_f15 by month +.012 / +.179 / +.013 — August only. |
| MSTR:call @09:45–11:30 | 10/2/1, Wilson .497, net_f15 +.432, paper +$952 | REJECTED 3/3 | Needs n≈38 at this win rate to clear a corrected threshold; 3 wins with negative net_f15; same 25-min-hold artifact (4 legs +$1,041 vs 8 fifteen-minute legs −$89); entry spreads 5.5–6.6% (13/23 fills ≥ 6%); last 7 signals 4/2/1 with net_f30 down 89%. |
| SMCI:call whole pair | 16/4/3, Wilson .491, net_f15 +.150, paper +$604 | REJECTED 3/3 | Three signals (9/11 ×2, 9/17) = 136% of summed net_f15 — the other 20 net negative; ex-top-1 fill −$164, ex-top-2 −$639; underwater fills 1–12 (−$455 trough); 15-min legs 14 fills −$619 vs 25-min legs 5 fills +$1,223; both hot sessions were >5% gap-up mornings. |

## Structural findings (cross-lens)

- **Stop-losses are the single largest drain.** 98 stop exits = **−$13,799** (avg −$141) vs 412 hold
  exits = +$14,883 (avg +$36). Median trade −$17; fill win rate 42.9%. The 30% stop on a 15-minute
  option hold fires at noise level on wide-spread names.
- **The 8/31 paper hold change (morning legs 15→25 min) doubled stop exposure.** Morning legs
  pre-8/31: n=166, +$2,952, stop rate 18%. Post-8/31: n=84, −$598, stop rate **35%**. Controlled to
  legacy tickers: avg +$23 → −$21, stop rate 17% → 42%. Underlying check: purgatory morning signals
  post-8/31 net_f15 +.049 vs net_f25 +.042 — the extra 10 minutes adds nothing on average.
  **Recommendation: revert the paper morning hold to 15 min** (also restores paper/live
  comparability), or make the stop hold-aware. Every 25-min "success" in this sweep (MSTR, SMCI)
  was an artifact of this rule.
- **Cheap contracts win.** Entry premium ≤ $100: +$975 over 97 trades; $100–200: +$509/141;
  $200–400: +$304/212; $400–800: −$49/46; > $800: −$655/14. AAPL calls average $1.77.
- **Spreads by name**: QQQ/SPY 1.2–1.4%, TSLA 2.1–2.4%, AAPL 2.3–2.8%, MSFT 4.8–5.0%, MSTR 5.1–5.6%,
  SMCI 5.2%, NOK 5.4–6.4%, QCOM 7.2–8.5%. The late-August expansion tickers (NOK, INTC, ORCL, QCOM,
  TSLL) bleed: INTC put −$570, NOK put −$554, ORCL put −$424, INTC call −$463.
- **Scalper mirage confirmed again**: `market_wave` runs 61% platform-wide with **negative**
  net_f15 (−.052); `vwap_reclaim:INTC:put` 78% / net −.108; `purgatory:MSFT:put` 68% / paper −$482.
  Every strategy has negative aggregate net_f15 — edge exists only in specific pairs.
- **Time of day**: pooled 09:45–10:30 wr .580 → 13:00–14:30 .374; purgatory's only net30-positive
  window is 09:45–10:30 (paper +$2,404 on 246 fills) and 10:30–11:30 is where it bleeds (−$1,286).
- **Day of week**: Monday weakest everywhere (purgatory paper −$1,257 on 25 fills); Friday is where
  the tails live (TSLA:put Fri +$667 vs Mon–Thu −$406; AMZN:call Fri −$1,276).
- **Decayed pairs**: MSFT:call 83% → 28% by halves; AMZN:call 71% → 33%; QQQ:put dormant since 8/26.

## Standing recommendation

1. Keep the live breaker halted. The pair that was promoted decayed exactly the way the skeptics
   warned; nothing has replaced it on evidence.
2. Revert the paper morning hold to 15 minutes before judging anything else — the 25-minute legs
   contaminate every morning slice and doubled stop-outs.
3. Test the stop rule on paper (wider stop, or no stop with the hold as the only exit) — it is the
   largest single lever in the fill book.
4. `purgatory:AAPL:call` stays pre-registered. It is the only candidate with (a) positive forward
   evidence, (b) the cleanest fill book, and (c) no new gating code needed. Revisit at ~15 forward
   window signals (~3 more weeks). If it still clears the bar and the whole-pair fills stay positive,
   it is the promotion candidate; even then the stats skeptic's point stands — start at minimum size.
5. Momentum, not static win rate: watch the leaderboard's EWMA / last-10 columns. TSLA:call's EWMA
   hit its series minimum in September while its all-time win rate still read 72%.
