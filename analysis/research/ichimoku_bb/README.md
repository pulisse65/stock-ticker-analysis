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
