# Kronos runner setup (Mac)

The KRONOS strategy is an off-box ML forecaster: the open-source
[Kronos](https://github.com/shiyu-coder/Kronos) model (a transformer
pretrained on ~12B candles) runs on your Mac — the Render free tier can't
fit PyTorch — and POSTs signals to the app's `/purgatory/external-signal`
endpoint. Server-side it's just another signals-only strategy: same skip
windows, cooldowns, honest scoring, kill gate, and promotion criteria.

## 1. One-time setup

```bash
# Clone the Kronos repo (model code + requirements)
git clone https://github.com/shiyu-coder/Kronos.git ~/Kronos

# Its own venv — torch is heavy and does not belong in the app's venv
python3 -m venv ~/Kronos/.venv
~/Kronos/.venv/bin/pip install -r ~/Kronos/requirements.txt requests
```

First run downloads the model weights (~100MB for Kronos-small) from
Hugging Face automatically.

## 2. Secrets

Generate a shared secret (don't paste it in chat — straight to the env):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

- **Render**: add `EXTERNAL_SIGNAL_TOKEN=<that value>` to the app's env vars
  and redeploy. Without it the endpoint answers 503 to everyone.
- **Mac**: export the same value, plus your Alpaca market-data keys (the
  same ones the app uses):

```bash
export EXTERNAL_SIGNAL_TOKEN="<same value>"
export ALPACA_API_KEY="<key>"
export ALPACA_API_SECRET="<secret>"
```

## 3. Run it

```bash
cd "~/Documents/Stock Ticker Analysis"
~/Kronos/.venv/bin/python kronos_runner.py
```

It sleeps outside regular trading hours, scans every 5 minutes during
them, logs one forecast line per ticker per cycle, and posts a signal only
when the averaged forecast path moves ≥0.25% within 15 minutes with the
30-minute path agreeing. The server may still filter a post (cooldown,
kill gate, skip window) — the runner logs the reason; that's normal.

## Tuning (env vars, all optional)

| Var | Default | Meaning |
| --- | --- | --- |
| `KRONOS_MIN_MOVE_PCT` | `0.25` | 15-min forecast threshold (%) |
| `KRONOS_SAMPLE_COUNT` | `8` | forecast paths averaged per prediction |
| `KRONOS_INTERVAL_SEC` | `300` | scan cadence |
| `KRONOS_LOOKBACK_BARS` | `400` | 5-min context bars fed to the model (max 510) |
| `KRONOS_MODEL` | `NeoQuasar/Kronos-small` | try `NeoQuasar/Kronos-base` if the Mac keeps up |
| `KRONOS_DEVICE` | auto | `mps` on Apple Silicon, else `cpu` |
| `KRONOS_TICKERS` | — | csv override; otherwise the app's watchlist is used |
| `TICKER_APP_URL` | `https://tickertracker.dev` | point at localhost for testing |

## What to expect

Signals show up in the Alerts tab with a KRONOS badge, get scored by the
same honest scorer (entry = first 1-min close after the alert, net of
spread), and count toward the same promotion gate (≥30 scored, ≥50% win
rate, net > +0.05% @15m). If its trailing record breaches the kill gate,
the server benches it automatically — the runner keeps running, its posts
just get filtered with a "benched by the kill gate" reason.

The model has no demonstrated live edge — this rig exists to measure it
honestly at zero capital risk. Expect it to be muted or unremarkable;
promotion to auto-trading is a deliberate env-var change, never automatic.
