# Response to the independent review (2026-10-22)

The review (`EXTERNAL_REVIEW_chatgpt_sol.md`) was checked claim by claim
against the code and the ledger. Verdict: it is right on every reproduction
point and on all but one engineering point. The brief it reviewed contained
three errors of mine, listed first.

## Errors in the brief, now corrected in `REVIEW_BRIEF.md`

1. **Win definition.** The brief said a signal "win" is `f15 ≥ +0.05%`. The
   code (`main.py`, outcome scoring) labels a win when the *best* favorable
   move within 30 minutes, net of 0.05%, exceeds +0.10%; flat within ±0.10%;
   loss below. The reviewer's fixed-15 recount is the honest one for a
   15-minute hold: MSTR call 25/44 = 56.8% (Wilson .42), not 71%. Every
   "win rate" in the leaderboard is the 30-minute-best label.
2. **Headline table.** It was built from a scratch merge whose de-duplication
   key lacked `strategy` and dropped six rows. The exact 7/24–10/21 cohort is
   1,123 trades, −$10,604; purgatory calls +$2,892 on 382 (−$122 on the 343
   that are not AAPL); puts −$7,475 on 411. The handoff CSV tables were
   already correct (they use the 7/23 boundary); only the brief's prose was
   off.
3. **Stop slippage.** "−24.7% realized on a 15% rule, ~$40 per stop" pooled
   127 stops taken under the 30% rule (before 10/03) with 190 under 15%.
   Under the current rule: mean −18.2%, ≈ $15 per stop beyond the line.
   The stop is not the dominant drain; puts and the two widened strategies
   are.

## Engineering findings: confirmed and fixed (PR #59, live 2026-10-22)

- **$2,880 / $4,380 paper debits (TSLA put, ORCL put, 10/14).** Cause found:
  the entry quote failed, sizing fell back to the contract's prior close
  ($0.33), computed 15 lots, and the market order filled at $1.92 / $2.92.
  Fix: size only against a live quote mid; unknown premium → exactly one
  contract; new `PAPER_MAX_TRADE_USD` (default $750) skips an entry whose
  single contract exceeds the cap (this also stops the $1,200–$1,460
  one-lot MSFT/TSLA entries).
- **Holding times of 9–13 minutes on MSTR forward trades.** Cause: a second
  entry in the same contract while the first was open; close-by-symbol sold
  both when the first timer fired (identical exit prices in the ledger
  confirm it). Fix: exits now close the entry's own quantity
  (`DELETE /v2/positions/{sym}?qty=N`), with close-all as fallback if the
  partial close is rejected. The 22-minute hold on 10/15 is the scanner
  outage that day (3-minute scans).
- **Exit fill before entry fill (two 10/15 rows).** Same outage: the
  scanner was down 13:15 ET 10/15 → 10:50 ET 10/16; those entries' fills
  were reconciled after recovery. Not a logic defect, but the timestamps are
  "when we learned", not broker time. Noted as a ledger limitation.
- **236 exit fills timestamped before exit submission.** Median gap 0.07 s:
  `exit_submitted_at` is written after the close call returns. Cosmetic;
  the brief now says so.
- **`pnl_live.json` carried `paper: true`.** Bug; now reports the account
  requested. The 21 all-time live trades are real: TSLA call traded live
  8/18–9/21 (18 trades, +$1,136), then AAPL call 3 trades −$184.
- **Coverage note said ~4-minute sampling.** Stale text from before the
  10/16 async scan; cadence is ~1 minute. Fixed.
- **No-stop row is not uniformly mid-to-mid.** Correct. Held trades exit at
  their real fill; stopped trades exit at the recorded hold-time mid. The
  note now states this. A uniform mid basis would use `pnl_at_mid` for held
  trades; not changed yet, because it would make the realized and replay
  rows differ on the same trade.

## Points taken, not yet acted on

- **Pre-registration is underspecified.** Agreed: the MSTR gate now reads
  once, at the close of the first session where n ≥ 15 honest forward
  signals, on the fixed-15 endpoint (`f15 ≥ +0.05`), with a missing `f15`
  counted as a non-win, and no re-reads if it fails (analysis/README).
- **The proposed quote-ledger experiment** (1-second quotes, strict
  contract rule, debit cap, session bootstrap) is the right next test. It is
  a build of roughly a day on this stack, and 1-second quoting for 15
  minutes per trade is heavier than the free tier has run so far; a
  10-second cadence would keep the protocol's decision rule intact. This is
  the owner's call.
- **Multiplicity.** The leaderboard shows ~250 pairs; the promotion gate's
  win-count component passes ~15 of them by chance. Agreed that a fresh
  prospective block for a frozen candidate set is the only honest fix.
- **Puts.** The August put cohort was +$519 on 67; the 90-day aggregate is
  −$7,475. `TRADING_DIRECTIONS=call` removes put *orders* only; puts stay
  scored, so the research observation continues.
- **Watchlist.** 17 names, not ~24. Brief corrected.

## One point disputed

"Legitimate shadow quotes after a stop are necessary for a no-stop
counterfactual; deleting all post-close quotes would introduce another
censoring problem." Agreed in principle, and that is what the fix does: the
path is capped at the *hold deadline*, not at the exit. Shadow quotes
between a stop and the deadline are kept; only quotes after the deadline
(where no policy under test could still be in the trade) are dropped.
