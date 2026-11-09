# Stop slippage decomposition (Task 3a, read 2026-11-08)

**Question.** Stops realize ~−19 to −21% on a 15% rule. How much of the
overshoot is our once-per-scan check (fixable with faster or native stops),
how much is the spread (irreducible with a market exit), and how much is the
fill itself?

**Data.** All 289 stop exits 10/05–11/06 (15%-stop era, 25 sessions, paper,
`stop_basis=option_quote` for every one), from `GET /purgatory/orders?date=`.
Per stop, with `line = entry_fill × 0.85`, `mid/bid` = the quote the sweep
used when it fired, `xf` = exit fill, all in % of the entry premium:

| component | meaning | mean | median | $ (289 stops) |
|---|---|---|---|---|
| total beyond the line | (line − xf) / fill | +4.2 | +3.8 | 5,728 |
| (i) overshoot at the check | (line − mid) / fill | +3.1 | +2.5 | 4,147 |
| (ii) half-spread | (mid − bid) / fill | +2.1 | +1.5 | 2,829 |
| (iii) fill residual | (bid − xf) / fill | −1.0 | −0.8 | −1,249 |

37 of 289 stops filled above the line. Overshoot p75 +5.4, p90 +8.9, max +28.8;
126 of 289 were ≤ 2 points. By premium: sub-$1 contracts have the worst of
everything (overshoot +4.6, half-spread +3.4, median spread 5.6%).

**Natural experiment on cadence.** The scan ran every ~4 min until 10/15 and
every ~1 min since 10/16 (coverage note on `/purgatory/stop-study`). If the
overshoot were our delay, the 1-min era should overshoot less. It overshoots
MORE, including within strategy and premium bucket:

| purgatory stops | n | overshoot mean | median | $/stop |
|---|---|---|---|---|
| 4-min era 10/05–15 | 51 | +1.6 | +1.7 | 9 |
| 1-min era 10/16–11/06 | 117 | +4.4 | +2.7 | 20 |
| ↳ premium $0–1 | 19 → 29 | +3.1 → +7.6 | +1.7 → +5.8 | |
| ↳ premium $1–2 | 21 → 37 | +0.5 → +4.0 | +1.7 → +2.7 | |
| ↳ premium $2+ | 11 → 51 | +1.0 → +2.8 | +1.1 → +2.1 | |

In the 1-min era 36 of 117 purgatory stops (31%) overshot by more than
5 points — the contract fell >20% inside one minute — and those 36 carry
$1,759 of the $2,343 overshoot. That is price discontinuity in a selloff
(late Oct–Nov), not our clock. A 15-second check, or an Alpaca server-side
stop, triggers inside the same air pocket and then sells at the same bid.

**Alpaca native stops.** The API reference (`/reference/postorder`) lists
market, limit, stop, stop_limit for single-leg options; the options overview
says market and limit only; the trigger price for options is not documented
(equities elect on the consolidated print, and option prints are sparse).
Even if accepted, a native stop fixes only component (i), which the cadence
experiment says is not a latency problem.

**Paper flatters.** Fill residual is −1.0: paper market sells fill ~1 point
better than the bid we saw. Live fills will not. Expect live stops ≈ 1 point
worse than paper on the same rule.

## Decision (Task 3b): NO-GO
Do not build faster or native stops. Expected recovery is bounded by the
cadence-sensitive part of (i), which the 4-min → 1-min change shows is
small (medians 1.7 vs 2.7 moved the wrong way). The irreducible half-spread
(ii) is $2,829 / 289 = ~$10 per stop and applies to every market exit,
including the 58 hold exits a week — a limit-at-mid exit for HOLD exits
(not stops) is the natural extension of Task 2 if its entry A/B passes.

The measured cost of the stop rule is therefore structural: ~4 points past
the line of which ~2 is the spread, plus the 15 points of the rule. The
remaining levers on stops are fewer entries that stop (signal/filters) or
not buying contracts under ~$1, where every component is worst.

Reproduce: `python3` snippet in this directory's git history (fetch
`/purgatory/orders?date=` for the sessions, decompose on `exit_quote`);
raw per-stop rows in `stop_decomp_2026-10-05_to_11-06.json`.
