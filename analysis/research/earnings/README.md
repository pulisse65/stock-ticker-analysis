# Earnings join (Task 4, read 2026-11-08)

Tables in `JOIN_RESULTS.md`; script `earnings_join.py` (re-runnable from the
cached `/purgatory/orders` + `/purgatory/signals` pulls; earnings dates from
yfinance `get_earnings_dates`). Window 2026-08-10 → 11-06, 63 sessions, 26
earnings events on 14 watchlist names (IWM/QQQ/TSLL are ETFs, no events).

## Raw result (purgatory paper fills)

| bucket (sessions to reaction day) | n | P&L | per trade | win | stops |
|---|---|---|---|---|---|
| pre (−5…−1) | 65 | −$2,002 | −$31 | 20% (Wilson lo 12%) | 35% |
| reaction (0) | 15 | −$518 | −$35 | 13% | 53% |
| post1 (+1) | 6 | +$100 | +$17 | 50% | 33% |
| post2–5 | 75 | −$881 | −$12 | 41% | 33% |
| other (baseline) | 774 | −$4,342 | −$6 | 36% | 28% |

Pre-earnings and reaction-day trades are 8.6% of fills and 33% of the loss.

## The confound, and the controlled read

48 of the 65 pre-earnings fills (−$1,823 of the −$2,002) sit in 10/22–11/06:
the Q3 big-tech reporting fortnight is also the market selloff and the
book's worst two weeks. So compare pre-earnings fills with OTHER tickers'
fills on the same sessions (14 sessions have both):

| session-matched | per trade | stops | win |
|---|---|---|---|
| pre-earnings (55 fills) | −$25.8 | 33% | 12%* |
| other, same sessions (146) | −$13.9 | 42% | 28%* |

(*win rates from the 10/22+ window). Pre did worse on 8 of 14 sessions,
one-sided sign test p = 0.40. Reaction day: −$34.5 vs −$8.6 matched, worse
on 5 of 7 sessions (n = 15 fills). Post 2–5: no difference (−$13.1 vs −$15.8).
Signal labels barely move (fixed-15 win 37% pre vs 42% other).

Pattern worth noting: pre-earnings trades stop LESS often but win less —
they bleed on hold exits rather than blowing up. Consistent with elevated
pre-report implied vol damping the option's response to a 15-minute
underlying move, but this data cannot establish the mechanism.

## Read
Directionally, trading into a report and on reaction day is worse than the
rest of the book. With 14 matched sessions overlapping the worst regime of
the year it is not separable from that regime (p ≈ 0.4). The matched
estimate of what a "skip pre/reaction" filter would have saved is about
(25.8 − 13.9) × 55 + (34.5 − 8.6) × 15 ≈ $1,000 over 90 days, not the raw
$2,500. No filter is installed on this evidence.

Re-run this join after the Q4 season (reports late Jan–mid Feb 2027), when
pre-earnings sessions will not coincide with one market regime; if the
matched gap holds at p < 0.05 on ≥ 30 matched sessions, pre-register a
pre/reaction skip for the paper book. This join says nothing about
multi-day post-earnings drift (Task 5), which is a different horizon and
instrument and proceeds on daily bars.

Data notes: yfinance report times of 06:00 (ASST) and 01:00 (NOK) are
treated as before-open; events before 08/10 have no rows; SPY fills/signals
are not on the watchlist and sit in `other`.
