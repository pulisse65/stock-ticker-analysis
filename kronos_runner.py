#!/usr/bin/env python3
"""Kronos signal runner — off-box ML forecaster for Ticker Tracker.

Runs on a machine with enough RAM for PyTorch (i.e. NOT the Render free
tier — typically the user's Mac). Every KRONOS_INTERVAL_SEC during regular
trading hours it:

  1. pulls the watchlist from the Ticker Tracker app,
  2. fetches 5-minute IEX bars from Alpaca for each ticker,
  3. runs the open-source Kronos model (https://github.com/shiyu-coder/Kronos)
     to forecast the next 30 minutes,
  4. POSTs a signal to {app}/purgatory/external-signal when the forecast
     clears KRONOS_MIN_MOVE_PCT within 15 minutes and the 30-minute path
     agrees.

The server treats these signals exactly like its own detectors: same skip
windows, cooldowns, honest scoring, kill gate, and promotion criteria.

Setup (see KRONOS_SETUP.md for the full walkthrough):
    git clone https://github.com/shiyu-coder/Kronos.git ~/Kronos
    python3 -m venv ~/Kronos/.venv
    ~/Kronos/.venv/bin/pip install -r ~/Kronos/requirements.txt requests
    export ALPACA_API_KEY=...  ALPACA_API_SECRET=...  EXTERNAL_SIGNAL_TOKEN=...
    ~/Kronos/.venv/bin/python kronos_runner.py

Env vars:
    TICKER_APP_URL          app base URL       (default https://tickertracker.dev)
    EXTERNAL_SIGNAL_TOKEN   shared secret — must match the Render env var (required)
    ALPACA_API_KEY / ALPACA_API_SECRET        market-data keys (required)
    KRONOS_REPO             path to the cloned Kronos repo (default ~/Kronos)
    KRONOS_MODEL            HF model id       (default NeoQuasar/Kronos-small)
    KRONOS_TOKENIZER        HF tokenizer id   (default NeoQuasar/Kronos-Tokenizer-base)
    KRONOS_DEVICE           mps | cpu         (default: mps if available)
    KRONOS_INTERVAL_SEC     scan cadence      (default 300)
    KRONOS_MIN_MOVE_PCT     15-min forecast threshold, pct (default 0.25)
    KRONOS_SAMPLE_COUNT     forecast paths to average (default 8)
    KRONOS_LOOKBACK_BARS    context bars fed to the model (default 400, max 510)
    KRONOS_TICKERS          csv override — skip the watchlist fetch
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kronos-runner")

ET = ZoneInfo("America/New_York")

APP_URL = os.environ.get("TICKER_APP_URL", "https://tickertracker.dev").rstrip("/")
SIGNAL_TOKEN = os.environ.get("EXTERNAL_SIGNAL_TOKEN", "").strip()
ALPACA_KEY = os.environ.get("ALPACA_API_KEY", "").strip()
ALPACA_SECRET = os.environ.get("ALPACA_API_SECRET", "").strip()
KRONOS_REPO = os.path.expanduser(os.environ.get("KRONOS_REPO", "~/Kronos"))
MODEL_NAME = os.environ.get("KRONOS_MODEL", "NeoQuasar/Kronos-small")
TOKENIZER_NAME = os.environ.get("KRONOS_TOKENIZER", "NeoQuasar/Kronos-Tokenizer-base")
INTERVAL_SEC = int(os.environ.get("KRONOS_INTERVAL_SEC", "300"))
MIN_MOVE_PCT = float(os.environ.get("KRONOS_MIN_MOVE_PCT", "0.25"))
SAMPLE_COUNT = int(os.environ.get("KRONOS_SAMPLE_COUNT", "8"))
LOOKBACK_BARS = min(int(os.environ.get("KRONOS_LOOKBACK_BARS", "400")), 510)
PRED_BARS = 6            # 6 x 5 min = 30-minute forecast horizon
MIN_CONTEXT_BARS = 200   # skip a ticker with less usable history than this
COOLDOWN_MIN = 30        # local re-post throttle; the server enforces its own

_last_posted: dict[tuple[str, str], float] = {}


def _fail_fast_config() -> None:
    missing = [name for name, val in [
        ("EXTERNAL_SIGNAL_TOKEN", SIGNAL_TOKEN),
        ("ALPACA_API_KEY", ALPACA_KEY),
        ("ALPACA_API_SECRET", ALPACA_SECRET),
    ] if not val]
    if missing:
        log.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)
    if not os.path.isdir(KRONOS_REPO):
        log.error("KRONOS_REPO %s not found. Clone it first:\n"
                  "  git clone https://github.com/shiyu-coder/Kronos.git %s",
                  KRONOS_REPO, KRONOS_REPO)
        sys.exit(1)


def _load_predictor():
    """Import the Kronos package from the cloned repo and build a predictor.
    Heavy (downloads weights on first run) — called once at startup."""
    sys.path.insert(0, KRONOS_REPO)
    import torch  # noqa: PLC0415 — deliberate late import, torch is heavy
    from model import Kronos, KronosPredictor, KronosTokenizer  # noqa: PLC0415

    device = os.environ.get("KRONOS_DEVICE", "").strip() or (
        "mps" if torch.backends.mps.is_available() else "cpu")
    log.info("Loading %s + %s on %s ...", MODEL_NAME, TOKENIZER_NAME, device)
    tokenizer = KronosTokenizer.from_pretrained(TOKENIZER_NAME)
    model = Kronos.from_pretrained(MODEL_NAME)
    try:
        predictor = KronosPredictor(model, tokenizer, device=device, max_context=512)
    except TypeError:
        # older Kronos versions have no device kwarg
        predictor = KronosPredictor(model, tokenizer, max_context=512)
    log.info("Model ready.")
    return predictor


def _fetch_watchlist() -> list[str]:
    override = os.environ.get("KRONOS_TICKERS", "").strip()
    if override:
        return sorted({t.strip().upper() for t in override.split(",") if t.strip()})
    try:
        res = requests.get(f"{APP_URL}/purgatory/status", timeout=20)
        res.raise_for_status()
        data = res.json()
        wl = data.get("watchlist") or data.get("tickers") or []
        tickers = [w["ticker"] if isinstance(w, dict) else str(w) for w in wl]
        return sorted({t.strip().upper() for t in tickers if t and t.strip()})
    except Exception as exc:  # noqa: BLE001
        log.warning("Watchlist fetch failed: %s", exc)
        return []


def _fetch_5min_bars(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Alpaca v2 multi-symbol 5-min IEX bars for the last 10 calendar days,
    filtered to regular trading hours, completed bars only."""
    start = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET}
    raw: dict[str, list[dict]] = {t: [] for t in tickers}
    page_token = None
    for _ in range(20):  # page cap
        params = {"symbols": ",".join(tickers), "timeframe": "5Min",
                  "start": start, "feed": "iex", "limit": 10000, "adjustment": "raw"}
        if page_token:
            params["page_token"] = page_token
        res = requests.get("https://data.alpaca.markets/v2/stocks/bars",
                           params=params, headers=headers, timeout=30)
        res.raise_for_status()
        data = res.json()
        for sym, bars in (data.get("bars") or {}).items():
            raw.setdefault(sym, []).extend(bars or [])
        page_token = data.get("next_page_token")
        if not page_token:
            break

    now_utc = pd.Timestamp.now(tz="UTC")
    out: dict[str, pd.DataFrame] = {}
    for sym, bars in raw.items():
        if not bars:
            continue
        df = pd.DataFrame(bars)
        df["t"] = pd.to_datetime(df["t"], utc=True)
        df = df.sort_values("t").reset_index(drop=True)
        # completed bars only: a 5-min bar starting at t covers [t, t+5m)
        df = df[df["t"] + pd.Timedelta(minutes=5) <= now_utc]
        # regular hours only (bar STARTS 9:30-15:55 ET)
        et = df["t"].dt.tz_convert(ET)
        mins = et.dt.hour * 60 + et.dt.minute
        df = df[(mins >= 570) & (mins <= 955) & (et.dt.weekday < 5)]
        if len(df) >= MIN_CONTEXT_BARS:
            out[sym] = df.reset_index(drop=True)
    return out


def _forecast_moves(predictor, df: pd.DataFrame) -> tuple[float, float, float, str]:
    """Return (move15_pct, move30_pct, last_close, bar_time_iso) for one
    ticker. Timestamps are fed to the model naive-ET (exchange-local, like
    its training data); bar_time reported to the app is the UTC close time
    of the last completed bar."""
    ctx = df.tail(LOOKBACK_BARS).reset_index(drop=True)
    x_df = pd.DataFrame({
        "open":   ctx["o"].astype(float),
        "high":   ctx["h"].astype(float),
        "low":    ctx["l"].astype(float),
        "close":  ctx["c"].astype(float),
        "volume": ctx["v"].astype(float),
        "amount": ctx["c"].astype(float) * ctx["v"].astype(float),
    })
    ts_et = ctx["t"].dt.tz_convert(ET).dt.tz_localize(None)
    x_timestamp = pd.Series(ts_et)
    last_start = ctx["t"].iloc[-1]
    y_timestamp = pd.Series(
        [(last_start + pd.Timedelta(minutes=5 * (i + 1))).tz_convert(ET).tz_localize(None)
         for i in range(PRED_BARS)])

    pred_df = predictor.predict(
        df=x_df, x_timestamp=x_timestamp, y_timestamp=y_timestamp,
        pred_len=PRED_BARS, T=1.0, top_p=0.9, sample_count=SAMPLE_COUNT,
        verbose=False,
    )
    last_close = float(ctx["c"].iloc[-1])
    closes = pred_df["close"].astype(float).tolist()
    move15 = (closes[2] - last_close) / last_close * 100.0
    move30 = (closes[5] - last_close) / last_close * 100.0
    bar_time_iso = (last_start + pd.Timedelta(minutes=5)).isoformat()
    return move15, move30, last_close, bar_time_iso


def _decide(move15: float, move30: float) -> str | None:
    """Fire when the 15-min forecast clears the threshold and the 30-min
    path agrees (holds at least half the move — no forecast reversals)."""
    if move15 >= MIN_MOVE_PCT and move30 >= 0.5 * move15:
        return "call"
    if move15 <= -MIN_MOVE_PCT and move30 <= 0.5 * move15:
        return "put"
    return None


def _post_signal(ticker: str, direction: str, price: float, bar_time: str,
                 move15: float, move30: float) -> None:
    key = (ticker, direction)
    last = _last_posted.get(key)
    if last is not None and time.time() - last < COOLDOWN_MIN * 60:
        log.info("%s %s: local cooldown, not re-posting", ticker, direction)
        return
    body = {
        "strategy": "kronos",
        "ticker":   ticker,
        "signal":   direction,
        "price":    price,
        "bar_time": bar_time,
        "meta": {
            "pred_move_15m_pct": round(move15, 3),
            "pred_move_30m_pct": round(move30, 3),
            "sample_count":      SAMPLE_COUNT,
            "model":             MODEL_NAME.split("/")[-1],
        },
    }
    try:
        res = requests.post(f"{APP_URL}/purgatory/external-signal", json=body,
                            headers={"X-Signal-Token": SIGNAL_TOKEN}, timeout=30)
        if res.status_code >= 400:
            log.error("%s %s: server rejected (%s): %s",
                      ticker, direction, res.status_code, res.text[:300])
            return
        data = res.json()
        if data.get("accepted"):
            _last_posted[key] = time.time()
            log.info("%s %s ACCEPTED (pred %+.2f%%/15m, %+.2f%%/30m) slack=%s",
                     ticker, direction, move15, move30, data.get("slack_sent"))
        else:
            _last_posted[key] = time.time()   # server said no — don't hammer it
            log.info("%s %s filtered by server: %s", ticker, direction, data.get("reason"))
    except Exception as exc:  # noqa: BLE001
        log.warning("%s %s: post failed: %s", ticker, direction, exc)


def _market_open_now() -> bool:
    now = datetime.now(ET)
    mins = now.hour * 60 + now.minute
    return now.weekday() < 5 and 570 <= mins < 960


def _seconds_until_next_open() -> float:
    now = datetime.now(ET)
    candidate = now.replace(hour=9, minute=30, second=0, microsecond=0)
    while candidate <= now or candidate.weekday() >= 5:
        candidate += timedelta(days=1)
        candidate = candidate.replace(hour=9, minute=30, second=0, microsecond=0)
    return (candidate - now).total_seconds()


def main() -> None:
    _fail_fast_config()
    predictor = _load_predictor()
    log.info("Runner up: app=%s cadence=%ss threshold=±%.2f%%/15m samples=%d lookback=%d bars",
             APP_URL, INTERVAL_SEC, MIN_MOVE_PCT, SAMPLE_COUNT, LOOKBACK_BARS)

    while True:
        if not _market_open_now():
            wait = min(_seconds_until_next_open(), 3600)
            log.info("Market closed — sleeping %.0f min", wait / 60)
            time.sleep(wait)
            continue

        cycle_start = time.time()
        try:
            tickers = _fetch_watchlist()
            if not tickers:
                log.warning("Empty watchlist — nothing to scan")
            else:
                bars = _fetch_5min_bars(tickers)
                skipped = sorted(set(tickers) - set(bars))
                if skipped:
                    log.info("Skipped (insufficient bars): %s", ", ".join(skipped))
                for sym in sorted(bars):
                    try:
                        move15, move30, price, bar_time = _forecast_moves(predictor, bars[sym])
                        direction = _decide(move15, move30)
                        log.info("%s: pred %+.2f%%/15m %+.2f%%/30m @ %.2f -> %s",
                                 sym, move15, move30, price, direction or "no signal")
                        if direction:
                            _post_signal(sym, direction, price, bar_time, move15, move30)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("%s: forecast failed: %s", sym, exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("Cycle failed: %s", exc)

        elapsed = time.time() - cycle_start
        time.sleep(max(30.0, INTERVAL_SEC - elapsed))


if __name__ == "__main__":
    main()
