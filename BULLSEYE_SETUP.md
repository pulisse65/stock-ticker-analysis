# Bullseye runner setup (Mac)

Bullseye is a friend's daily stock model: a scikit-learn
`HistGradientBoostingClassifier` over 40 daily bars that calls BUY / HOLD /
SELL for the return 5 sessions ahead. It is **not** an intraday option signal,
so it doesn't go through the strategy registry, Slack, the kill gate, or the
trader. The runner posts its calls to `/purgatory/external-predictions`; the
server scores each one against the realized 5-session close move using the
same cut-offs the model was trained on (BUY > +1.65 %, SELL < −1.05 %). The
**Bullseye** tab shows the hit rate against always-HOLD and majority-class
baselines.

The bullseye checkout is third-party code. It runs in its own venv, needs no
Alpaca keys, and talks only to yfinance and the app.

## 1. One-time setup

```bash
# The checkout lives wherever you cloned it; default is ~/Downloads/bullseye-main
export BULLSEYE_REPO=~/Downloads/bullseye-main

# Its own venv. scikit-learn MUST be 1.7.2 — the committed .dmp classifiers
# were pickled with it and newer versions fail to unpickle.
~/.local/bin/python3.11 -m venv "$BULLSEYE_REPO/.venv"
"$BULLSEYE_REPO/.venv/bin/pip" install "scikit-learn==1.7.2" peewee pandas numpy ta \
  python-dateutil joblib yfinance requests
```

The runner creates `stocks.db` inside the checkout on first run and fills it
from yfinance (3 years of daily bars per ticker, then technicals). No
treasury / yield-curve feed is needed: bullseye's production inference
passes the raw `YieldCurve` list where a dict is expected, so that feature
is always 0 at prediction time — the runner reproduces that exactly.

## 2. Secrets

The runner reuses the Kronos shared secret — the same box, the same trust
domain. If you already run Kronos, nothing new to generate.

```bash
export EXTERNAL_SIGNAL_TOKEN="<same value as Render's EXTERNAL_SIGNAL_TOKEN>"
```

Run `supabase_daily_predictions.sql` once in the Supabase SQL editor before
the first post.

## 3. Run it

```bash
cd "~/Documents/Stock Ticker Analysis"
V="$BULLSEYE_REPO/.venv/bin/python"

# Backfill the last 60 calendar days (rows are flagged `backfilled`)
$V bullseye_runner.py backfill --days 60

# One pass for the last completed session (safe to re-run: rows are insert-once)
$V bullseye_runner.py run

# Keep it running: predicts every weekday at 17:00 ET
$V bullseye_runner.py daemon
```

`--tickers AAPL TSLA` overrides the app watchlist; `--dry-run` prints the
batch instead of posting.

## Env vars

| var | default | meaning |
|---|---|---|
| `BULLSEYE_REPO` | `~/Downloads/bullseye-main` | the checkout (holds `stocks.db`, `models/`) |
| `BULLSEYE_MODEL` | `models/small-classifier-nb.dmp` | repo-relative classifier path |
| `BULLSEYE_HISTORY_PERIOD` | `3y` | yfinance depth on first load of a ticker |
| `BULLSEYE_RUN_AT_ET` | `17:00` | daemon run time (after yfinance has the settle) |
| `TICKER_APP_URL` | `https://tickertracker.dev` | the app |
| `EXTERNAL_SIGNAL_TOKEN` | — | shared secret (same as Kronos) |

Server-side knobs (Render env): `DAILY_PRED_BUY_PCT` (1.65),
`DAILY_PRED_SELL_PCT` (−1.05), `DAILY_PRED_HORIZON_BDAYS` (5).

## Reading the numbers

- **Accuracy** = share of scored rows whose realized label matches the call.
  Compare to **always-HOLD** (what you get by never acting) and
  **majority class** — a model below either isn't adding information.
- **Direction hit** = BUY rows that went up / SELL rows that went down (HOLD
  counts as a hit only when the move stayed inside the band). Looser than
  accuracy; useful for Stage 2 (equity book) sizing later.
- **Backfilled** rows were posted after their as_of session. They're honest
  about features (the model only sees bars up to as_of) but the classifier
  may have been *trained* on those dates, so prefer the forward-only toggle
  for anything that matters.

## Known model quirks (relay to the author)

1. `utils.predict()` computes `return_1d` from `history[-1]` against itself,
   so it is always 0 at inference (training used the real 1-day return).
2. `predict()` receives the `YieldCurve` rows as a list but looks them up as
   a dict, so the yield-curve feature is always 0 at inference.
3. The sector feature is an insertion-order index over the local `Stock`
   table — it means different things in different databases.

None of these are fixed here (the model is the author's); they're why the
platform measures the model as shipped rather than as intended.
