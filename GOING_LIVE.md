# Going live: purgatory TSLA calls only

Mechanics for pointing the auto-trader at a real-money Alpaca account with
the blast radius limited to a single pair. Every activation step is yours —
the code ships inert and nothing changes until you edit Render env vars.

**Read first:** the TSLA-call record is 15/16 (93.8%) but n=16, one month,
one market regime, measured on paper fills. The 95% lower bound is ~72%.
Real 0DTE fills add slippage and spread the paper account never charged.
Nothing here is investment advice — it's the plumbing, documented.

## 1. Alpaca live account (one-time, on alpaca.markets)

1. Complete the **live brokerage application** (identity + funding details).
   Your paper account's settings do not carry over.
2. Request **options trading approval** on the live account — Level 2 is
   enough (long calls/puts only; the bot never sells short or spreads).
3. Choose the account type deliberately:
   - **Cash account** — no Pattern Day Trader rule, but option proceeds
     settle **T+1**: cash used today is reusable the day after tomorrow.
     At ~3 TSLA-call trades/week and $500 notional each, roughly $1,500–
     $2,000 keeps the rotation unconstrained.
   - **Margin account** — instant reuse of funds, but 15-minute round
     trips are day trades: more than 3 in any 5 business days flags PDT,
     which requires a $25,000 minimum equity. The observed TSLA-call rate
     (~3/week) sits right at that line.
4. Fund it, then generate **live API keys** (Account → API Keys). Live and
   paper keys are separate pairs; live keys also work for market data.

## 2. Render env changes (the actual switch)

| Var | Value | Note |
| --- | --- | --- |
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` | your **live** keys | data feed keeps working (IEX) |
| `ALPACA_PAPER` | `0` | flips order routing to api.alpaca.markets |
| `TRADING_PAIRS_ALLOWLIST` | `purgatory:TSLA:call` | THE scalpel — only this pair places orders |
| `ALPACA_TRADING_ENABLED` | `1` | already set |
| `ALPACA_TRADING_NOTIONAL_USD` | `500` (or your choice) | per-trade sizing |

Leave `ALPACA_TRADING_HOLD_MINUTES=15` and `ALPACA_TRADING_STOP_LOSS_PCT=30`
as-is — the TSLA record was earned under exactly these settings; changing
them invalidates the evidence you're acting on.

What does NOT change: every other strategy and pair keeps alerting and
being honest-scored (scoring uses market data, not orders). The only
casualty is paper P&L accrual for non-TSLA purgatory signals — they become
signals-only while the deployment points at the live account.

## 3. Verify before the first trade

- `https://tickertracker.dev/purgatory/status` → `trading_paper: false`,
  `trading_pairs_allowlist: [purgatory TSLA call]`.
- Alpaca's live dashboard shows the app's orders in real time; the EOD
  Slack retro and the Trading tab keep reporting per-trade P&L as before
  (rows are tagged `paper: false`).

## 4. Tripwires — decide them before the first trade, not after

- **Stand-down switch:** set `ALPACA_PAPER=1` + restore paper keys.
  One redeploy and you're back to rehearsal.
- Review after every 10 live trades: if the live win rate is tracking
  materially under the paper record (e.g. under ~60% at n=10), stand down
  and compare live fills vs. scored entry prices — slippage is measurable
  in the `entry_slippage_pct` column.
- The stop-loss's option-quote basis works better live than on paper
  (real quotes exist), but the underlying-estimate fallback stays in
  place regardless.
- Keep Friday in mind: purgatory's Friday record is 49.1% (n=55) vs 71.7%
  on Thursdays. The system doesn't skip Fridays today; if early live
  results are Friday-heavy losers, that's the first lever to consider.
