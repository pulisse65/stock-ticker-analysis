# Independent review of Ticker Tracker

Review of the supplied October 21, 2026 snapshot. Scope: statistics, methodology, and engineering. No trading instructions or annualized projections.

All performance calculations below use the supplied files. The sole external product reference concerns the limits of Alpaca's paper simulator. Source files were read without modification. Dollar amounts are rounded to cents or whole dollars for display; calculations retain the source precision.

**1. One-page verdict**

The package supports a negative overall paper result, a particularly weak historical put book, and a promising but unvalidated MSTR call sample. It does **not** establish a deployable options edge, demonstrate that stops cause the losses, or establish that MSTR has passed its stated promotion requirements.

For the brief's explicit July 24–October 21 interval, `orders.csv`, filtered to `account == 'paper'` and those inclusive dates, contains **1,123 trades and −$10,604**, rather than 1,117 and −$9,869. Purgatory calls produce **+$2,892 on 382 trades**; puts produce **−$7,475 on 411**. The two newer strategies reproduce their stated losses. The positive call total is concentrated: AAPL contributes **+$3,014 on 39 trades**, leaving **−$122 on the other 343 purgatory calls**. This is evidence against treating “calls” as an established broad edge.

Three problems dominate the interpretation:

1. **The outcome being counted is not the outcome described.** The brief calls a win a favorable move of at least 0.05% at 15 minutes. Both leaderboard JSON snapshots describe the stored label as the best favorable move within 30 minutes, above a different net threshold. In `signals.csv`, 821 of the 4,202 honest rows with an observed `f15` disagree between `outcome == 'win'` and `f15 >= 0.05`. MSTR's advertised 71.1% is 32 stored wins among 45 honest signals. Its observed fixed-15-minute success rate is **25/44 = 56.8%**. These are different endpoints.
2. **Selection and dependence make the apparent confirmation much weaker than its row count.** Hold exits are selected by what happened after entry. The replay includes only usable paths. The MSTR forward sample has 13 alerts across seven sessions, only 12 observed `f15` values, and overlapping trades. Its trailing-two-week sample is the same 13 alerts, not independent confirmation. Hundreds of pairs, multiple windows, and repeated promotion checks compound this problem.
3. **The execution ledger and replay do not yet support their advertised precision.** A nominal $500 book includes $2,880 and $4,380 positions. Two order records close before their recorded entry fill. Four of MSTR's 12 forward paper trades have holding times outside 14–16 minutes. The stop replay's no-stop totals reproduce using a mixture of realized fill P&L and fill-to-shadow-mid P&L, rather than uniformly mid-to-mid pricing.

The pooled “15% stop loses about 25%” claim also needs correction. Using the October 3 rule change documented in `REPLAY_RESULTS.md`, the 317 stops in the headline interval split into **127 under the former 30% rule, averaging −34.4% of entry cost**, and **190 under the current 15% rule, averaging −18.2%**. The current-period average shortfall beyond 15% is approximately **$15 per stop**, not $40. Attribution anomalies prevent interpreting all of that difference as execution slippage.

MSTR's forward **+$607 on 12 paper trades** is worth further measurement. It is not a completed registration: 13 is below 15, one 15-minute score is missing, and the actual holding times do not consistently implement the promised policy. The next experiment should establish whether this pair survives a prospectively frozen, auditable implementation of its intended economics.

**2. Answers to the eight questions**

**Q1. Are profitable hold exits anything other than survivorship? Is no-stop the right counterfactual?**

The hold/stop comparison cannot identify the effect of a stop. In the headline `orders.csv` cohort, hold exits return +$23,744 on 806 trades and stop exits −$34,348 on 317. Exit type is determined after entry. A path that falls sufficiently is assigned to the stop group; removing that group after observing the path produces a selected sample. The hold group's median P&L is actually −$2 despite its positive aggregate.

A no-stop policy evaluated on the **same entries, contracts, quantities, and final deadlines** is the appropriate trade-level counterfactual. In `raw/stop_study_detail_purgatory_calls.json`, all 110 audit rows sum to +$2,113.50 at 15%, versus +$1,613.50 for the reconstructed no-stop policy: **+$500 in favor of the stop, or $4.55 per trade**. The same rows' actual realized P&L is +$2,265. Comparing this replay with +$3,656 from 323 trades in the API's broader realized population is not a matched comparison.

An exploratory session bootstrap of the 110 paired differences across 17 sessions gives a 95% percentile interval of approximately **−$10.09 to +$25.74 per trade**. I resampled whole sessions 50,000 times, seed 20261021, retaining all rows within a sampled session and dividing its aggregate difference by its aggregate trade count. This does not establish superiority, equivalence, or a confidence statement robust to regime change or the earlier search across thresholds.

There is also a pricing-definition problem. The exported no-stop numbers reproduce exactly using:

`100 × qty × (hold_mid − fill)` when `hold_mid` is present; otherwise `actual_pnl`.

That reconstruction matches all four detail exports: 110 calls, 162 puts, 11 AAPL calls, and 15 MSTR calls. For MSTR, all 15 `hold_mid` values are missing and no-stop equals realized P&L, +$335; the corresponding orders' `pnl_at_mid` sum is +$451. This is strong evidence that the exported comparison is not a uniform mid-to-mid experiment. The source implementation and original quote paths are not included, so I can establish the numerical identity, not prove its code path.

The corrected replay still lacks reliable executable bid/ask prices at every counterfactual exit, quote ages, quote size, latency, costs, and a complete audit of excluded paths. At portfolio level, exits can also affect capital availability, overlapping signals, position limits, and later entries. Holding entries fixed estimates a trade-level effect, not a full portfolio-policy effect. Legitimate shadow quotes after a stop are necessary for a no-stop counterfactual; deleting all post-close quotes would introduce another censoring problem. The fix must preserve valid quotes for the exact contract while rejecting misattributed or stale ones.

**Q2. Should the stop be fixed through cadence, limit exits, wider stops, or no stop?**

First correct the historical comparison. In `orders.csv`, headline-window stops have these arithmetic mean returns, calculated separately for each trade as `pnl / (100 × qty × entry)`:

| Rule period, using the change date in `REPLAY_RESULTS.md` | Stops | Mean return | Median return | Mean dollar loss | Mean loss beyond that period's nominal threshold |
|---|---:|---:|---:|---:|---:|
| Before October 3; reported 30% rule | 127 | −34.44% | −34.51% | −$143.91 | $18.57 |
| October 3 onward; reported 15% rule | 190 | −18.17% | −18.44% | −$84.58 | $15.12 |

The pooled mean is −24.69%, median −22.47%. Its loss is −21.67% when expressed against a constant $500 denominator instead. “Percent of notional” must specify which denominator is meant. Comparing every historical stop to 15% produces the quoted $41.61 excess, but that comparison assigns the wrong rule to 127 trades.

For the 185 current-period stopped trades with an `execution_drag` value, its mean is −$9.21. That is a measured quote-versus-fill diagnostic, not a complete causal decomposition. Twenty-six of the 190 rows have `exit_attributed == True`; those average only −9.04% and include a +$27 “stop.” The remaining 164 average −19.62%. Shared position exits, attribution, and threshold basis therefore matter to the apparent stop skew.

My engineering priority is: verify lot attribution and trigger basis, then measure threshold-crossing time, detection time, order submission, and fill time on valid quotes. Only then compare cadence. The JSON coverage note says roughly four-minute sampling; the brief says one minute. The package does not contain the full timestamps needed to settle the actual cadence distribution.

A faster check can reduce detection delay but cannot guarantee a 15% realized loss. A limit exit constrains acceptable execution price and introduces non-fill risk; its unfilled outcomes must remain in the experiment. Wider stops with smaller size change both exposure and the path rule and require their own comparison. No-stop is not justified by the current call replay. The choice among these policies is not identified by this sample.

**Q3. Is there a defensible reason for puts to keep trading?**

There is a defensible **research** role for paper puts as a control or as a newly registered conditional hypothesis. These files do not establish positive standalone expectancy for the current aggregate put policy.

`orders.csv`, purgatory puts in the headline interval: **411 trades, −$7,475, 135 wins, 105 stops**. An exploratory bootstrap of 56 sessions using the same method as Q1 gives a mean P&L interval of approximately **−$34.21 to −$1.81 per trade**. This is descriptive evidence of weakness, not a correction for all the selection and policy changes.

`raw/stop_study_purgatory_puts.json` has **162 usable trades**. Every supplied threshold is negative, including **−$2,412 at 15%** and **−$3,837.40 with no stop**. This makes “the stop alone caused the put losses” an inadequate explanation. It does not prove every possible put strategy is bad. In fact, the August purgatory-put cohort in `orders.csv` is **+$519 on 67 trades**.

Any argument for a portfolio diversification benefit needs simultaneous, capital-consistent portfolio data and a prespecified risk objective. An aggregate negative P&L series is not evidence of such a benefit by itself. Continuing shadow scoring preserves research observations without making a profitability claim.

**Q4. AAPL: regime change, lucky sample, or structural problem? What prior for the next 20 trades?**

The files cannot distinguish those explanations causally. The paper decline shows that becoming live is not necessary to produce the October deterioration. There was also a reported system-wide stop-rule change just before the live launch. Contract selection, option exposure, underlying regime, and operational changes are confounded.

From `orders.csv`, `strategy == 'purgatory'`, `ticker == 'AAPL'`, `direction == 'call'`, grouped by calendar month:

| Month | Trades | Profitable trades | Paper P&L |
|---|---:|---:|---:|
| August | 12 | 10 / 12 = 83.3% | +$1,278 |
| September | 15 | 11 / 15 = 73.3% | +$2,179 |
| October through the 21st | 8 | 1 / 8 = 12.5% | −$379 |

October's eight trades span only five sessions. Its ordinary 95% Wilson interval is about **2.2%–47.1%**, assuming independent Bernoulli observations. Intraday dependence weakens that interpretation. The all-day paper population also differs from the live window. Applying `09:45 <= et_time <= 11:30` to October AAPL calls gives **five paper trades, zero wins, −$321**; this is still not a one-for-one live match.

A fair prior should shrink the selected winner toward its broader strategy, rather than treat 83% or 71% as a persistent parameter. As an explicit sensitivity example, use **Beta(4,6)**: a 40% mean with only ten pseudo-observations. Its mean is motivated by the other purgatory calls in the headline cohort, **137 wins among 343 trades = 39.9%**; its strength is an assumption, not an estimated fact. Updating with October's 1/8 produces Beta(5,13), an expected **5.56 profitable trades out of the next 20**, with a beta-binomial 95% predictive interval of **1–12**. A neutral Beta(1,1) prior updated with October gives an expected **4/20**, interval **0–11**.

These are transparent illustrative models, not reliable forecasts under regime change. Neither predicts dollars: hit rate and payoff magnitude are separate quantities. A rolling, partially pooled model of net returns and session-level effects is a more appropriate eventual forecasting target.

**Q5. Has MSTR cleared the registration? How can its record fool us?**

**No.** At 13 signals it has not met a requirement of at least 15. With the ordinary two-sided 95% Wilson formula, 10 wins in 15 yields a lower bound of **0.417**; 11/15 yields **0.480**. At the first 15-observation checkpoint, the next two outcomes still matter.

The honest forward filter in `signals.csv` is purgatory:MSTR:call, `scored_from == 'alerted_at'`, alert time on or after October 7 ET, through October 21. It yields **13 rows on seven sessions: 10W/2L/1F**, lower bound **0.4974**. However, the October 15 12:49 ET alert has `f5` but no `f15`. Therefore **mean +0.4576% and median +0.2563% use 12 rows**, not 13. On those 12 observed endpoints, ten are favorable by the brief's fixed-horizon threshold. A missing endpoint cannot silently become a completed endpoint or disappear from a promotion gate.

The matching forward paper date/pair filter yields **12 trades, +$607, eight positive, three negative, one zero**. The largest gain is **$220 = 36.2% of net total**, and the total excluding it remains +$387. Those concentration checks reproduce. But holding times include **13.05, 11.32, 9.16, and 22.07 minutes**. The remaining eight trades within 14–16 minutes contain five positive trades. “Exit reason = hold” does not establish a fixed 15-minute test.

The main ways this record can mislead are:

- **Selection:** 45 honest rows are one selected pair from 254 observed honest pairs, after unknown prior searches. The ordinary Wilson interval does not account for this.
- **Shared events:** four of the 13 forward alerts occurred October 8. Three pairs of forward entries share exit timestamps. Rows are not independent opportunities.
- **Repeated evidence:** the trailing October 8–21 record is exactly the same 13-row forward sample. All-time statistics include it too.
- **Contract and sizing mix:** among 43 MSTR paper trades, 32 one-contract trades earn only **+$77**; seven two-contract trades earn **+$908**; three three-contract trades +$153; one ten-contract trade +$40. The ten-contract trade had a $0.45 premium. The “MSTR is one expensive contract” explanation does not describe the whole sample.
- **Exposures not supplied:** strike, expiry, contract identifier, delta, implied volatility, and contemporaneous BTC controls are absent from these CSVs. Expiry, time-of-day and BTC-beta explanations are hypotheses, not findings that can be verified here.
- **Endpoint economics:** `net_f15` is an adjusted underlying return. A universal 0.05-percentage-point subtraction cannot measure option spread, volatility and time-value changes across different contracts.

The discipline of using a prospective test is sound. This specific registration is underspecified: the exact immutable registration, code version, endpoint, missing-data policy, fixed stopping time, timezone, position-overlap rule, and search family are not supplied. “At least 15, then check until the bounds pass” is optional stopping, not a fixed-sample test. Use one locked endpoint and decision date, with a rule for incomplete data and independent future validation. Do not retroactively replace a failed or ambiguous registration with a more favorable definition.

**Q6. Does contract count itself create the stop-loss skew?**

No. For a standard 100-multiplier long option, with equal per-contract entry and exit prices,

`P&L = 100 × qty × (exit − entry)`

and `P&L / entry_cost = (exit − entry) / entry`. Quantity cancels from the percentage return. The dollar P&L identity reproduces all **1,189 orders**, to floating-point precision. More contracts can still change fees, available depth and fill quality; a cheap premium also makes a given cent spread larger as a percentage. These mechanisms are different from quantity alone.

The more immediate issue is that actual debit is not consistently $500. In the **1,123-row headline cohort**, **126** entries exceed $500, **24** exceed $750, and **19** exceed $1,000. Forty-eight of the entries above $500 are single-contract positions, consistent with the stated minimum-one rule overriding the target. But that cannot explain these two October 14 purgatory puts:

| Ticker and signal time UTC | Qty | Entry premium | Actual debit | P&L |
|---|---:|---:|---:|---:|
| TSLA, 14:00 | 15 | $1.92 | $2,880 | −$690 |
| ORCL, 14:12 | 15 | $2.92 | $4,380 | −$450 |

These require a sizing or attribution explanation. The exports do not determine which. Neither has an entry quote in the CSV. A hard debit-cap invariant and explicit per-lot allocations should be audited before attributing performance differences to ticker quality or contract count.

The premium-bin comparison is descriptive, not causal: among the headline cohort's 98 trades with entry premium below $0.50, 43 stop; among 474 trades with premium $2–$5, 84 stop. Those groups also differ in ticker, date, direction, expiry and market state. Compare normalized return and dollar risk while controlling for those fields, using session-level inference.

**Q7. What multiple-comparison control should promotion carry?**

Count the full research family. `signals.csv` contains **255 raw pairs and 254 with honest records**. A leaderboard that displays only pairs above a minimum count is not the full family. Candidate windows, direction switches, expiry filters, stop thresholds and repeated read dates are additional choices.

A useful calibration: at n=15, Wilson lower bound ≥0.45 requires at least 11 wins. Under an illustrative independent fair-coin null, `P[Binomial(15,0.5) >= 11] = 0.05923`. Across 250 such tests, about **14.8** would pass that **win-count component** on average. This does not estimate the false-promotion rate of all the combined filters. It demonstrates that this component is not strong multiplicity protection, and 50% wins is not necessarily the economic break-even threshold.

For exploration, define one net-return endpoint and one end date per hypothesis, and generate valid p-values accounting for the session dependence. Apply Benjamini–Yekutieli at q=0.05 if arbitrary dependence across hypotheses must be allowed: sort p-values and find the largest k with `p_(k) <= k*q/(m*H_m)`, where `H_m = sum(1/j, j=1..m)`. Benjamini–Hochberg is less conservative when its independence or positive-dependence conditions are justified. Neither method repairs invalid individual p-values or optional stopping. [Official SAS documentation of the procedures](https://support.sas.com/documentation/cdl/en/statug/66859/HTML/default/statug_multtest_details11.htm).

For promotion, prefer a fresh, untouched prospective block for a small frozen candidate set. If multiple candidates are tested together, use a prespecified family-wise rule such as Holm at 0.05 on valid one-sided economic-endpoint tests. FDR controls the expected fraction of false discoveries in a selected set; it does not give each individual promoted pair a 95% probability of being sound. Repeated future batches need a declared error budget or valid sequential method. Do not recalculate the same fixed-sample Wilson gate daily until it passes.

**Q8. What two-week experiment would most change the assessment?**

Run a prospectively frozen **MSTR call replication with an independent quote-based ledger**, specified in section 4. The critical question is whether its positive result survives the intended holding period, a real debit cap, consistent option pricing, and unambiguous event accounting. Another optimization over eight stop thresholds would leave those uncertainties unresolved. Two weeks may produce too few independent sessions or trades; “inconclusive” must be a permitted outcome, rather than an invitation to keep sampling until success.

**3. Reproduction check**

**Filters and definitions.** All dates below refer to the supplied snapshot through October 21. For the headline table I use `orders.csv`, `account == 'paper'`, `2026-07-24 <= date <= 2026-10-21`. Repeating the filter on New York dates derived from bar, submission, entry-fill, and exit-fill timestamps gives the same headline population. Paper win means strictly `pnl > 0`; zero P&L stays in the denominator. Stops mean `exit_reason == 'stop_loss'`. I do not filter orders on signal labels. A join on strategy, ticker, direction and bar time matches 1,188 of all 1,189 orders to honest signal records, with one unmatched order; the headline reproduction retains the supplied order population.

For signals, retain **only `scored_from == 'alerted_at'`**. There are **4,210 honest rows out of 4,444**, matching the brief. All stored-label Wilson calculations below use z=1.9599639845, with losses and flats both counted as non-wins. Fixed-horizon success is separately computed from observed `f15 >= 0.05`. Means and medians of `f15 − 0.05` exclude missing values and show their denominator.

**The section 3 paper table does not reproduce in four of its six rows.**

| Slice | Brief n | Recomputed n | Brief P&L | Recomputed P&L | Recomputed win rate | Brief stops → recomputed |
|---|---:|---:|---:|---:|---:|---:|
| Hold exits | 800 | **806** | +$24,497 | **+$23,744.00** | 382/806 = **47.4%** | 0 → 0 |
| Stop exits | 317 | **317** | −$34,366 | **−$34,348.00** | 1/317 = **0.3%** | 317 → 317 |
| Purgatory calls | 378 | **382** | +$3,445 | **+$2,892.00** | 160/382 = **41.9%** | 92 → **91** |
| Purgatory puts | 409 | **411** | −$7,293 | **−$7,475.00** | 135/411 = **32.8%** | 104 → **105** |
| VWAP reclaim | 197 | **197** | −$3,690 | **−$3,690.00** | 54/197 = **27.4%** | 73 → 73 |
| Market wave | 133 | **133** | −$2,331 | **−$2,331.00** | 34/133 = **25.6%** | 48 → 48 |

The first two rows partition the same population as the last four rows; they must not be summed together. Totals are **1,123 trades and −$10,604**, versus the brief's **1,117 and −$9,869**: six additional rows and $735 lower P&L. The VWAP-reclaim and market-wave rows reproduce, including their October 12 first trade dates. The one profitable “stop” is market_wave:INTC:call, October 15 18:16 UTC signal, +$27, with exit attribution flagged.

The supplied `*_90d.csv` paper summaries use a different start boundary. **Including July 23 yields 1,133 trades and −$10,769.** That cohort reproduces the counts, P&L and rounded win rates in `strategy_90d.csv`, `strategy_direction_90d.csv`, `exit_reason_90d.csv`, `hour_et_90d.csv`, and `pairs_90d.csv`. Thus those summary files are internally consistent with `orders.csv`, but not with the brief's explicit dates or headline figures. The July 23 boundary explains the summary-file difference; it does not reconcile the brief's 1,117 rows.

`pairs_30d.csv` similarly reproduces with September 21 onward: **694 orders**. Monthly and weekly all-time paper tables reproduce from **all 1,189 orders**; the purgatory month/direction table reproduces from **859 purgatory orders**. Counts match exactly. Dollar differences from their rounded totals are at most $0.0001; win-rate differences are consistent with three-decimal rounding.

**Honest MSTR/AAPL signal records.** “All time” means all honest rows in the supplied file. “30-day export” means September 21 onward. “Forward” means alert time on or after October 7 ET.

| Pair / interval | Honest rows | Stored W/L/F | Stored win rate | Wilson lower | Observed f15 rows | Fixed-15 successes | Net f15 mean / median, percentage points |
|---|---:|---:|---:|---:|---:|---:|---:|
| MSTR call, all time | 45 | 32 / 9 / 4 | 71.11% | 0.5663 | **44** | **25/44 = 56.82%** | +0.1922595 / +0.1502618 |
| AAPL call, all time | 51 | 29 / 6 / 16 | 56.86% | 0.4327 | 51 | 27/51 = 52.94% | +0.0092575 / +0.0074765 |
| MSTR call, 30-day export | 24 | 17 / 5 / 2 | 70.83% | 0.5083 | **23** | 13/23 = 56.52% | +0.1462629 / +0.0252634 |
| AAPL call, 30-day export | 14 | 5 / 2 / 7 | 35.71% | 0.1634 | 14 | 4/14 = 28.57% | −0.0669954 / −0.0733003 |
| MSTR call, forward | 13 | 10 / 2 / 1 | 76.92% | 0.4974 | **12** | 10/12 = 83.33% | +0.4575728 / +0.2562680 |

These stored-label and net-return summaries reproduce `signal_pairs_alltime.csv`, `signal_pairs_30d.csv`, and the forward export within published rounding. Their interpretation does not reproduce the brief's win definition. For example, the fixed-15 MSTR all-time Wilson lower bound is **0.4222**, rather than 0.5663 for stored labels. The forward record is better, but incomplete.

Across all honest signals, the stored-label total is **2,163 wins / 4,210**. There are **1,773 fixed-15 successes / 4,202 observed endpoints**. Eight endpoints are missing. Of the 4,202 observed rows, **821 disagree** about success. This is a material label-definition discrepancy, not rounding. It does not by itself prove look-ahead in signal entry generation; it does invalidate using the label's win rate as the fixed-exit hit rate.

**Remaining headline checks and discrepancies:**

- **AAPL months:** August and October reproduce; September is +$2,179 and 11/15 wins, rather than +$2,031 and 71%. See Q4 for the exact monthly cohort sizes.
- **MSTR paper:** 43 trades, +$1,178, 22/43 profitable, one stop reproduce. Forward 12 trades and +$607 reproduce. Those fill counts do not establish a clean fixed-15-minute implementation.
- **Stop percentages:** −24.69% mean / −22.47% median reproduce using actual entry debit. The interpretation as current 15% execution loss does not; see the 127/190 regime split in Q2.
- **Hold replay:** `raw/hold_study_30d.json` reports 309 usable rows out of 702 covered trades, with 15/20/25/30-minute P&Ls **−$3,534.20 / −$4,405.85 / −$3,703.90 / −$4,920.70**, matching the brief. Only 44.0% of covered trades are usable. The export says it selects a quote within ±5 minutes of each requested horizon. These are not necessarily exact 15/20/25/30-minute executions. Individual full paths are absent, so I cannot independently rebuild these four counterfactual totals.
- **Stop replay aggregates:** the dollar totals in `REPLAY_RESULTS.md` match the supplied JSON to rounding, and the four detail exports reproduce their 15% sums. All-strategy replay has 526 usable trades; its broader realized denominator is 989. That denominator does not match either CSV 90-day cohort. The JSON's broader realized scope should not be substituted for the CSV cohort without its query and inclusion rules.
- **Replay disagreement note:** among the 110 call audit rows, 10 disagree with the recorded exit type, but **one is after October 3**: the acknowledged AAPL October 13 case. Among 162 put rows, 23 disagree, with **one after October 3**: ORCL October 14 14:16 UTC. Thus the statement that all remaining disagreements are pre-change is not exact.
- **Known AAPL shadow quote:** removing only the acknowledged suspect AAPL row changes its 15% total from +$433 to **+$721 on 10 rows**, and no-stop from +$467.50 to **+$755.50 on the same 10**. The paired difference stays −$34.50 because the bad value enters both policies. It must not be “repaired” by inventing a replacement price. Its influence on other thresholds cannot be independently rebuilt without the path.
- **Live scope:** `raw/status.json` confirms a halted post-reset cohort of **three trades, zero wins, −$184**, with reset timestamp October 7 02:38:30 UTC. `raw/pnl_live.json` also totals −$184 for October, but contains **21 historical trades and +$952 all time**, and even carries `paper: true`. The current cohort can be reconciled; “three live trades ever” cannot. No live per-trade CSV is supplied, so the claimed two live stops cannot be independently counted here.
- **Paper API scope:** `raw/pnl_paper.json` reports **1,235 trades and −$7,999** all time, beginning July 2. `orders.csv` has **1,189 and −$8,923**, beginning July 9. These are different populations. Do not silently mix their rollups.

**4. One experiment, specified before the observations**

**Question:** Does purgatory:MSTR:call retain positive paper option economics when the contract, debit, timing, and exit accounting are defined prospectively and independently of the existing replay?

This protocol defines one candidate and one policy. It is a measurement and forward-validation experiment, not another search over thresholds. It is written here for registration before data collection; this review does not deploy or schedule it.

**Calendar:** October 22–November 4, 2026, ten scheduled weekday sessions, America/New_York. Freeze the implementation and this protocol before October 22 at 09:30 ET. If readiness misses that deadline, choose a new ten-session interval before seeing its results; do not retrospectively include sessions. Evaluate only after the final session and all outcomes mature. No early promotion and no extension until a threshold passes.

**Population:** Every new honest purgatory:MSTR:call alert in 09:45–15:30 ET, under a frozen detector version. Log all alerts and exclusion reasons. Allow only one pending/open MSTR position in the experimental ledger. Later alerts while it is open are recorded but do not create new experimental trades. Do not add pairs, widen the time window, or change eligibility after viewing results. Muting or unrelated production changes must not selectively suppress the experiment's observation log.

**Contract and entry rule:** At one second after the alert, use the first valid contemporaneous quote snapshot. Select the nearest unexpired listed call expiry that remains tradable through the full holding period, then the strike closest to the contemporaneous underlying midpoint; break a strike-distance tie toward the lower strike. Resolve that contract once, before examining future quotes. Require positive bid, ask at least bid, quote age no more than two seconds, relative spread `(ask−bid)/mid <= 10%`, and displayed ask size sufficient for the proposed quantity. Set `qty = floor(500 / (100 × ask))`. If qty is zero or the entry conditions fail, log a skip; do not force one contract or search for a cheaper alternative strike. A qualifying virtual paper entry fills at that ask. This strict definition is a new validation policy; success would apply to it, not automatically to every historical MSTR fill.

**Exit rule:** Record validated quotes at least once per second through the 15-minute deadline even after an early stop. Check a 15% loss from the entry premium at exactly 60, 120, …, 840 seconds after the virtual entry, using the most recent valid midpoint no older than two seconds. On the first qualifying check, schedule an exit one second later and use the first valid bid at or after that time. Otherwise schedule the hold exit at 900 seconds, with the same one-second execution delay. At the hold deadline, hold takes precedence; no later observation can retroactively cause a stop. Require displayed bid size sufficient for the quantity. A scheduled check or exit without the required valid quote is an observable data failure, not an omitted losing trade. No choosing the nearest earlier/later favorable quote.

This deliberately defines one-minute stop checks and a one-second modeled execution delay. It does not claim these assumptions reproduce live execution. Use isolated virtual lots, immutable IDs, and a journal linking alert → contract → entry → checks → exit. Record exchange quote time and receipt time separately, along with contract identifier, strike, expiry, multiplier, quantity, bid/ask and size. Any broker-paper orders collected alongside this experiment must have their own lot and order IDs; report their execution differences separately.

**Primary endpoint:** For each accepted entry, calculate

`Y_i = 100 × qty_i × (exit_bid_i − entry_ask_i) − 2 × qty_i`.

The final term reserves $1 per contract per side for fees and unmodeled friction. This is a chosen experimental reserve, not an assertion about the broker's fees. The primary estimate is mean `Y_i` over all accepted entries. Report the median, total, per-session totals and all skips as well. Fixed-15 underlying returns and stored outcome labels are secondary diagnostics, never substitutes for this option endpoint.

**Data gate:** Every accepted entry must have a complete auditable outcome. Require no contract mismatches, no debit above $500, no negative holding times, and no unexplained allocation or quote-validity failures. Any unresolved accepted-entry failure makes the experiment inconclusive. Keep the failed records and their counts; do not drop them to make the quality gate pass. A feed outage is a failure of measurement, not a zero return.

**Sample gate:** At least **15 completed non-overlapping experimental trades across eight distinct sessions**. If that is not reached within the ten scheduled sessions, the result is **inconclusive**. Given the existing 13 alerts across seven sessions before overlap exclusions, failure to reach this gate is plausible. Do not call two calendar weeks a sufficient sample merely because two weeks elapsed.

**Exact decision rule:** A result is “eligible for a longer, locked paper validation” only if both gates above pass and **all** of the following hold:

1. Mean and median `Y_i` are strictly positive.
2. The one-sided 95% session-bootstrap lower bound for mean `Y_i` is strictly positive. Resample all ten scheduled sessions, including zero-entry sessions, as blocks with replacement 50,000 times, seed 20261022. For each draw, divide summed P&L by summed trade count; omit only draws with zero total trade count. Use the empirical fifth percentile with linear interpolation. Preserve all within-session rows.
3. Removing the single session with the largest total `Y` leaves aggregate `Y` strictly positive.
4. The largest positive individual `Y_i` is less than 50% of aggregate `Y`.
5. Aggregate stressed P&L remains strictly positive after additionally deducting **2% of each trade's entry debit**.

If the data and sample gates pass but total `Y <= 0`, the positive-profitability hypothesis fails this validation screen. If the gates fail, or if total is positive but any other success criterion fails, the result is inconclusive. Report the actual failed conditions. Do not replace them with a different ticker, threshold, confidence level, or window.

The bootstrap is a prespecified research screen, not a finite-sample Type I error guarantee with eight to ten sessions. Cross-session dependence and regime changes remain limitations. Even a pass supports a longer independent test of this precise policy; it does not establish live execution quality or automatically authorize promotion. A failed or incomplete measurement gate would be especially informative here, because the historical package already contains failures in those exact fields.

**5. Other matters that change the interpretation**

**The call aggregate is fragile.** In the 382 headline purgatory calls, the mean is +$7.57 and the median −$15. The exploratory bootstrap across 56 sessions gives a 95% interval of approximately **−$10.22 to +$26.02 per trade**, using the Q1 method. AAPL's +$3,014 exceeds the entire +$2,892 call total. This does not prove there is no call edge; it prevents presenting the aggregate sign as robust evidence of one.

**The ledger needs explicit chronology and allocation invariants.** Across all 1,189 orders, **236 exit-fill timestamps precede their recorded exit-submission timestamps**. Some could reflect local logging order or reused position events; the files cannot determine the cause. More seriously, two `hold` rows close before their entry fill:

- purgatory:ORCL:call, October 15 16:56 UTC signal: entry fill 18:10:44 UTC, exit fill 17:17:51 UTC, P&L −$22.
- market_wave:TSLL:call, the same signal time: entry fill 18:10:50 UTC, exit fill 17:36:44 UTC, P&L −$12.

These cannot represent the claimed round-trip chronology as recorded. Reconcile fills by immutable broker order/fill IDs and contract ID, allocate exits to individual lots, and enforce quantity conservation. Separate broker timestamps from the time a local process learned about an event. The current CSV does not include those identifiers, so this is an engineering finding, not a diagnosis of a particular code defect.

**“Honest” is a useful filter, not an independent proof of causality.** Of the 4,210 honest signals, **37 alerts occur outside 09:30–16:00 ET** under a timestamp-only regular-hours check. This check does not use an exchange holiday calendar. Observed alert-minus-bar delay has a median of 65.3 seconds and a maximum of 4,489.7 seconds. Audit the price used as the forward-return baseline, horizon timestamps, session boundary behavior, and data availability at the alert. Preserve data vintage and scoring-code versions. A stored `scored_from` flag alone cannot verify those facts.

**Paper performance includes simulated execution assumptions.** Alpaca states that its simulator omits market impact, latency slippage, regulatory fees, and queue position, and does not check order quantity against displayed NBBO quantity. These limitations are directly relevant to the cheap-contract and oversized-position observations. A paper fill price or a positive quote-based experiment does not validate live fillability. [Alpaca paper-trading documentation](https://docs.alpaca.markets/us/docs/paper-trading).

**Freeze the observation universe separately from the trading policy.** The status snapshot lists **17 watchlist names**, compared with approximately 24 in the brief. It also has manual and automatic exclusions. Preserve watchlist membership, enabled strategies, per-pair gates, and reasons for rejected orders as dated data. A rule that mutes a pair and later allows it to recover needs continued shadow observation; otherwise both the sample and the un-muting logic become ambiguous. Historical eligibility cannot be reconstructed from current status alone.

**The external forecast sidetrack also needs a prospective-only view.** In `raw/bullseye_external_predictions.json`, selecting rows with non-null `correct` yields **726 scored forecasts, 312 correct = 42.98%**, matching the summary. Of these, **339 are marked backfilled**. Restricting further to `backfilled == false` leaves **387 rows on 26 forecast dates: 144 correct = 37.21%**. In that same subset, the largest actual class is “sell,” **184/387 = 47.55%**. That majority-class figure is a retrospective diagnostic, not a trained forward baseline, but it demonstrates why the pooled 42.98% cannot be cited as established prospective skill. Five-day overlapping targets and shared market dates further reduce independence. Do not use it as confirmation of the options system.

**Make the next handoff an auditable snapshot.** Include exact query bounds, row identifiers, code/config hashes, inclusion and exclusion reasons, option contract identifiers, original quote paths and quote timestamps, and a manifest linking the signal, order, and API populations. Keep rule-era labels per trade. Show separate denominators for total alerts, completed fixed-horizon scores, eligible entries, actual fills, and usable replays. Publish the scoring definition next to every win rate. The supplied summary tables largely calculate what their inputs say; the main problem is that several of those inputs and populations do not measure what the narrative claims.

Reproduction arithmetic was independently cross-checked using both pandas and Python's CSV/Decimal reader for the headline counts and P&L. Source hashes, intermediate computations and audit scripts were retained locally with this review. No source data, application settings, trading switches, or live account state were changed.
