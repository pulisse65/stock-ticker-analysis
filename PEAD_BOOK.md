# PEAD book — pre-registered 2026-11-08

A paper STOCK book that trades the post-earnings drift rule which passed its
frozen backtest the same day (`analysis/research/earnings/EARNINGS_DRIFT.md`:
S&P 100, z ≥ 2, buy next open, sell 10th close; +1.03%/trade net, +0.38%
over same-ticker random entries, t 2.2, 11/11 years positive).

## Rule (frozen)
- Universe: current S&P 100 **minus the swing universe** (the watchlist).
  Both books share the paper account and the swing rebalance treats any
  position in its universe as its own, so the two may never hold the same
  symbol. This drops the watchlist half of the backtest's primary set; the
  S&P 100 cell is the one that was judged.
- Signal: on the first scan ≥ 09:35 ET, for every universe stock with an
  earnings report in the last 4 calendar days (FMP calendar, yfinance
  fallback) whose reaction session (report before 09:30 ET → that session,
  else the next) is the last completed session: z = reaction return /
  std of the 60 prior sessions' daily returns (≥ 40 required). z ≥ 2.0 qualifies.
- Entry: market buy, qty = floor($2,000 / reaction close), highest z first,
  at most 5 open positions ($10,000 / $2,000), never a symbol already held.
- Exit: first scan ≥ 15:50 ET on the 10th weekday after entry (a holiday
  pushes it to the next session), market sell of the logged qty.
- Fail closed: unreadable ledger, unavailable events, or Alpaca errors → no
  orders this pass; one Slack warning per day. Slack otherwise only on orders.
- Env: `PEAD_ENABLED=1`, `PEAD_NOTIONAL_USD=10000`, `PEAD_SLOT_USD=2000`,
  `PEAD_HOLD_SESSIONS=10`, `PEAD_Z_MIN=2.0`. Table `pead_trades`
  (`supabase_pead_trades.sql`). Read: `GET /purgatory/pead`,
  `GET /purgatory/pead/candidates`, token-gated `POST /purgatory/pead/run`.

## Decision rule
Read once, at the first of: 50 closed trades, or 2027-05-08 (26 weeks — one
13-week season gives only ~25 S&P 100 events, too few). PASS = mean net
return per closed trade > 0, hit rate > 50%, and mean per trade ≥ the
same-ticker random-entry baseline computed the backtest's way over the same
dates (script in analysis/research/earnings/). Pass → keep running and
decide separately whether anything moves beyond paper. Fail → stop the book,
record why. No rule changes in flight.

Statistics and engineering only. Nothing here is live money or advice.
