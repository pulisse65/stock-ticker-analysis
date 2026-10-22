# Stop-rule replay, corrected (fetched 2026-10-21 23:30 ET, after PRs #57/#58)

Replay = every stop threshold applied to the real option mid-price path of
each paper trade, sampled once per scan, path capped at the hold deadline.
Mid-to-mid, no spread cost. Only trades with a recorded path count
(recording began 2026-09-22, so this is ~4 weeks even on the 90-day call).
"Realized" is what the book actually did over the same window, all trades.
Current live rule: 15% (was 30% until 2026-10-03, which is why some
pre-10/03 trades "disagree": they dipped 15–30% and really did hold).

| slice | replayable | realized (all trades) | 10% | **15% (current)** | 20% | 30% | no stop | worst (no stop) |
|---|---|---|---|---|---|---|---|---|
| all strategies | 526 | −$9,317 on 989 | −$4,167 | **−$3,086** | −$6,734 | −$6,795 | −$5,393 | −$1,928 |
| purgatory, all | 272 | −$3,756 on 684 | −$1,426 | **−$298** | −$3,190 | −$3,270 | −$2,224 | −$1,928 |
| purgatory calls | 110 | +$3,656 on 323 | +$1,929 | **+$2,114** | +$1,211 | +$1,222 | +$1,614 | −$426 |
| purgatory puts | 162 | −$7,412 on 361 | −$3,354 | **−$2,412** | −$4,401 | −$4,493 | −$3,837 | −$1,928 |
| purgatory AAPL call | 11 | +$2,883 on 35 | +$751 | **+$433** | +$416 | +$348 | +$468 | −$288 |
| purgatory MSTR call | 15 | +$1,203 on 37 | +$59 | **+$304** | +$322 | +$335 | +$335 | −$48 |

Stops fired in replay at 15%: all 174/526, purgatory calls 32/110, puts
63/162, AAPL 4/11, MSTR 3/15.

## What changed versus the numbers quoted earlier on 2026-10-21

Before the fix the replay said purgatory calls were +$1,252 with no stop and
−$1,360 at 15%, and that MSTR would have stopped 5 of 16 times with a worst
of −$387. Both were artifacts: (a) the quote sample taken at the hold
deadline was being counted as a stop, and (b) quotes recorded after the
position had already closed, some of them garbage (MSTR 4.60 → 0.73, AAPL
1.675 → 0.035), were triggering replay stops. With the path capped at the
deadline, **the 15% rule is the best or within noise of the best on every
slice.** The no-stop row is not better. The earlier statement that "the
stop costs money on calls" is withdrawn.

## What still holds

- Puts lose under every threshold and with no stop at all.
- Calls are positive under every threshold in the replay window and
  realized +$3,656 over 90 days.
- Realized stop exits lose more than the replay's mid-based stops
  (realized stop avg ≈ −$109; the rule implies ≈ −$70 on $460 notional).
  That gap is execution: market sell at the bid after a once-per-scan
  check. Second-order next to the put/call split.
- MSTR call is insensitive to the stop rule: the contract is ~$3–5 and the
  position is 1–2 lots, so a 15% move on the premium is rare inside 15
  minutes.

## Known bad data still in the set

- AAPL call 2026-10-13 14:20 UTC: really stopped at −$75, but its recorded
  shadow `hold_mid` is 0.415 on a 1.855 fill (−78% in 15 minutes, not
  credible). It is the −$288 "worst" in the AAPL and purgatory-calls rows.
- The 10 remaining purgatory-call "disagree" rows and 23 put rows are
  pre-2026-10-03 trades evaluated against today's 15% rule (the live rule
  was 30% then). They are correct counterfactuals, not errors.

Per-trade audit rows: `raw/stop_study_detail_*.json` (`disagree: true`
marks trades where the replay and the realized exit type differ).
