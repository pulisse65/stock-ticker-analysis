# Ichimoku Cloud + Bollinger Bands — screen (2026-10-24)

Source: a friend's email pointing at fmz.com/strategy/436778 (a Coinrule
template: BTC/USDT 10-minute bars, one-week backtest 2023-12-19..26, no
metrics, no exit rule). Rules as stated: long when the conversion line
crosses above the base line, price is above the cloud, the lagging span is
above price 26 bars back, and price breaks above the upper Bollinger band;
short is the mirror. Ichimoku 9/26/52, Bollinger 20/2.

Screen: yfinance 1-minute bars, the 17 watchlist tickers, 2026-09-28 →
10-23 (20 sessions), RTH 09:45–15:30, scored exactly like the app's fixed
15-minute endpoint (`f15 − 0.05 ≥ 0` = win). `pull_bars.py` then
`evaluate.py` (run with the project venv).

| variant, 1-minute bars | n | win | Wilson lo | net f15 mean / median |
|---|---|---|---|---|
| A article rules, calls | 220 | 34.1% | .281 | −0.070 / −0.079 |
| A article rules, puts | 238 | 45.4% | .392 | +0.032 / −0.024 |
| B without Bollinger | 1,603 | 42.4% | .400 | −0.031 / −0.046 |
| C Bollinger as "inside bands" filter | 1,144 | 43.4% | .405 | −0.036 / −0.042 |
| D cloud + band break, no cross | 8,146 | 40.0% | .390 | −0.033 / −0.057 |
| baseline, every RTH bar, long / short | 117k | 39.4% / 43.2% | | |

10-minute bars (the template's timeframe), 30-minute horizon: variant A
fires 23 times in 20 sessions, 65% win, Wilson .449, net +0.21 — too few
to mean anything and it is the only cell above baseline. 5-minute bars:
A 38.6% on 88.

Verdict: on this watchlist and horizon the combination does not beat
picking a random bar. Purgatory's honest fixed-15 rate is 42% platform-wide
and MSTR call 57%. Not added as a detector.

## Swing timeframe (daily / weekly bars), added 2026-10-27

Paul asked whether the cloud works on a weekly cadence. `swing_backtest.py`
and `swing_periods.py`: yfinance daily bars Oct-2020 → Oct-2026, the 17
watchlist names plus 20 liquid controls, long only, enter at the next close
after the signal, exit when price closes back below the cloud (or below the
base line), max hold 60 days / 26 weeks. No costs. Rules: **A** = the
article (TK cross + above cloud + lagging span + upper-band break);
**B** = A without the Bollinger condition; **E** = first close above the
cloud with the lagging span confirming (plain cloud breakout).

Pooled, median ticker, compounded return of the rule vs buy-and-hold:

| | trades | win | 2022 bear: rule / B&H | 2023–26: rule / B&H | full-period drawdown: rule / B&H |
|---|---|---|---|---|---|
| A daily, article | 53 | 32% | | | |
| B daily | 144 | 40% | −6% / −33% | +29% / +178% | −33% / −60% |
| B weekly | 36 | 47% | 0% / −29% | +13% / +170% | −32% / −59% |
| **E weekly** | 96 | 56% | **0% / −29%** | +58% / +170% | **−37% / −59%** |
| random daily entries, 5–40 day holds | 7,200 | 55% | | | |

Findings. The article's combination (A) is the worst variant on every
timeframe: 32% wins, below random entry timing. The Bollinger "break above
the upper band" condition is what hurts, since it buys 2-sigma spikes. The
plain weekly cloud breakout (E) is a different animal: it was flat through
all of 2022 while every ticker fell, and it roughly halves the full-period
drawdown. The price is upside: it captured about a third of buy-and-hold in
the bull years, and beat buy-and-hold on only 19% of tickers. On MSTR
specifically, weekly E matched buy-and-hold (+748% vs +737%) with a −34%
drawdown instead of −86%, which is the honest version of the friend's
result: any long rule on MSTR made money; the cloud's contribution was
staying out of 2022.

What this is not: an edge on entry timing. What it might be: a regime
filter (weekly close above the cloud = allowed to be long) that could gate
which direction the intraday book trades. Untested; see the proposal in
the 10/27 notes.
