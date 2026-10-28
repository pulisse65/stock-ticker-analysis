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

## Does the weekly regime predict intraday direction? No. (2026-10-27)

`regime_join.py` tags every honest signal (4,210) and paper fill (1,189)
with the ticker's weekly-cloud regime as of the prior week's close
(above / inside / below; no look-ahead) and splits by direction.

| purgatory, fixed-15 endpoint | n | win | net f15 |
|---|---|---|---|
| with the regime (above+call, below+put) | 400 | 41.2% | −0.07 |
| against the regime | 470 | 41.9% | −0.04 |

Paper fills tell the same story once direction is held fixed: purgatory
calls were positive in both regimes (+$2,761 above, +$1,731 below) and
puts negative in both (−$4,154, −$2,959). The only cell with a real
tilt is calls in a *below* regime, 56% on 170 signals (Wilson .48): buying
dips in downtrending names, which is the opposite of what the cloud is
supposed to say. Not pre-registering a forward test; the retrospective is
unambiguous. The join script stays here so it can be rerun on new signals.

## What a month looks like, weekly cloud rule E, long only, no costs

Six years, equal-weight baskets, `monthly_profile.py`:

| | CAGR | positive months | median month | worst month | worst quarter | max drawdown |
|---|---|---|---|---|---|---|
| watchlist basket, cloud | 12.9% | 44% | 0.0% | −8.2% | −14.6% | −21.5% |
| watchlist basket, buy & hold | 32.1% | 62% | +2.4% | −17.1% | −20.2% | −37.2% |
| QQQ, cloud | 12.8% | 38% | 0.0% | −7.6% | −9.6% | −21.3% |
| QQQ, buy & hold | 18.5% | 62% | +1.8% | −12.9% | −17.9% | −35.1% |
| MSTR, cloud | 42.8% | 24% | 0.0% | −24.8% | −28.5% | −34.1% |
| MSTR, buy & hold | 42.8% | 53% | +2.7% | −48.3% | −56.5% | −86.3% |

The typical month is zero because the rule is out of the market more than
half the time. It is a drawdown-control overlay for someone who wants to
hold volatile names without the 2022 experience, not a return generator.
Last 13 months on the watchlist basket: cloud +15% cumulative vs buy and
hold +15% — equal, with the cloud catching half the up months and half the
down months.
