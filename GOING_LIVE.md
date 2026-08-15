# Going live: dual-account model (paper + real money)

The platform runs TWO Alpaca trading clients side by side:

- **Paper account** (existing keys) — keeps trading *every* purgatory
  signal, exactly as before, purely for data collection.
- **Live account** (new, separate keys) — additionally places real orders,
  but ONLY for pairs promoted via `LIVE_TRADING_PAIRS`.

One signal on a promoted pair produces two independent positions — a paper
leg and a live leg — each opened, stopped, closed, reconciled, and P&L'd
against its own account. They never cross. Every activation step is yours:
the code ships inert and nothing goes live until the env vars below exist.

**Read first:** the TSLA-call record is 15/16 (93.8%) but n=16, one month,
one regime, on paper fills; the 95% lower bound is ~72%. Real 0DTE fills
add slippage the paper account never charged. Nothing here is investment
advice — it's the plumbing, documented.

## 1. Alpaca live account (done ✅ 8/15 — kept for reference)

1. Complete the live brokerage application; fund it.
2. Options approval Level 2 (long calls/puts — the bot never sells short).
3. Account type trade-offs at ~3 day-trades/week:
   - **Cash**: no PDT rule; option proceeds settle T+1 (cash used today is
     reusable the day after tomorrow).
   - **Margin**: instant reuse, but >3 day trades per 5 business days flags
     PDT → $25k minimum equity.
4. Generate **live API keys** (separate pair from paper keys).

## 2. Render env changes (the actual switch)

| Var | Value | Note |
| --- | --- | --- |
| `ALPACA_LIVE_API_KEY` / `ALPACA_LIVE_API_SECRET` | live keys | never paste in chat — straight into Render |
| `LIVE_TRADING_PAIRS` | `purgatory:TSLA:call` | the ONLY pair that trades real money |
| `ALPACA_LIVE_NOTIONAL_USD` | your per-trade size | live sizing is its own knob; think in % of bankroll |
| `ALPACA_LIVE_MAX_TRADE_USD` | optional, default 1.5× notional | hard cap per live trade — a pricier contract skips the live leg (Slack note); paper still trades it |
| `SLACK_SIGNAL_SCOPE` | `live` (optional) | quiets paper/signals-only alerts; live entries/stops/exits still ping |

Do NOT touch: `ALPACA_API_KEY`/`SECRET` (paper + market data),
`ALPACA_PAPER` (stays `1` — the paper client), `ALPACA_TRADING_ENABLED`
(stays `1`), hold/stop/notional for paper. The TSLA record was earned
under hold=15min, stop=30%; those settings govern both accounts — changing
them invalidates the evidence you're acting on.

`SLACK_SIGNAL_SCOPE` options: `all` (default — today's behavior),
`trading` (only signals from trading strategies), `live` (only signals
matching `LIVE_TRADING_PAIRS`). Daily/weekly retros always post, now with
a `💵 Live / 📋 Paper` split line, and live order events (entry, hold
exit, stop-loss) always post individually.

## 3. Verify before the first trade

- `https://tickertracker.dev/purgatory/status` → `live_trading.keys_configured:
  true`, `live_trading.active: true`, `pairs: [purgatory TSLA call]`.
- Trading tab → Mode pill reads `paper + 💵 LIVE (TSLA calls)`; the account
  dropdown filters P&L and trades to `💵 Live only`.
- Alpaca's live dashboard mirrors the app's orders in real time.

## 4. Tripwires — decide them before the first trade

- **Stand-down:** delete `LIVE_TRADING_PAIRS` (or the live keys) and
  redeploy. Paper trading and all scoring continue untouched.
- Review after every 10 live trades: live win rate materially under the
  paper record (under ~60% at n=10) → stand down and compare live fills vs
  paper fills on the same signals — the dual-leg design makes slippage
  directly measurable per trade.
- Friday caution: purgatory runs 49.1% on Fridays (n=55) vs 71.7% on
  Thursdays. If early live losers cluster on Fridays, that's the first
  lever.
