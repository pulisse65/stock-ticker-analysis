from __future__ import annotations

import base64
import concurrent.futures
import json
import logging
import math
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

log = logging.getLogger("uvicorn.error")

app = FastAPI(title="Stock Ticker Analysis")

# dropdown value -> (yfinance period, interval)
PERIOD_MAP: dict[str, tuple[str, str]] = {
    "1wk": ("5d", "1h"),
    "1mo": ("1mo", "1d"),
    "3mo": ("3mo", "1d"),
    "6mo": ("6mo", "1d"),
    "1yr": ("1y", "1d"),
}

PERIOD_LABEL: dict[str, str] = {
    "1wk": "1 week",
    "1mo": "1 month",
    "3mo": "3 months",
    "6mo": "6 months",
    "1yr": "1 year",
}


class AnalyzeRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    period: str


# ----------------------------- Search history -----------------------------
#
# Two backends selected by env:
#   - Supabase (Postgres) when SUPABASE_URL + SUPABASE_KEY are set — the
#     production path on Render, since Render free-tier disks are ephemeral.
#   - Local JSON file otherwise — keeps `./run.sh` working with no env setup.
#
# The Postgres table is expected to look like:
#   create table search_history (
#     ticker text primary key,
#     count integer not null default 0,
#     last_period text,
#     last_searched timestamptz not null default now(),
#     first_searched timestamptz not null default now()
#   );

HISTORY_FILE = Path(__file__).parent / "history.json"
HISTORY_TABLE = "search_history"
_history_lock = threading.Lock()

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
_SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
_supabase_client: Any = None

if _SUPABASE_URL and _SUPABASE_KEY:
    try:
        from supabase import create_client  # type: ignore

        _supabase_client = create_client(_SUPABASE_URL, _SUPABASE_KEY)
        log.info("Search history: using Supabase backend.")
    except Exception as exc:  # noqa: BLE001
        log.warning("Supabase client init failed (%s); falling back to JSON file.", exc)
        _supabase_client = None
else:
    log.info("Search history: using local JSON file (no SUPABASE_URL/SUPABASE_KEY set).")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- JSON-file backend ---

def _load_history_json() -> dict[str, dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return {}
    try:
        data = json.loads(HISTORY_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_history_json(data: dict[str, dict[str, Any]]) -> None:
    tmp = HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(HISTORY_FILE)


def _record_search_json(ticker: str, period: str) -> None:
    with _history_lock:
        h = _load_history_json()
        entry = h.get(ticker) or {"count": 0, "last_period": None, "last_searched": None}
        now = _now_iso()
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last_period"] = period
        entry["last_searched"] = now
        if not entry.get("first_searched"):
            entry["first_searched"] = now
        h[ticker] = entry
        _save_history_json(h)


def _list_history_json() -> list[dict[str, Any]]:
    h = _load_history_json()
    items = [{"ticker": t, **entry} for t, entry in h.items()]
    items.sort(key=lambda x: (x.get("count", 0), x.get("last_searched") or ""), reverse=True)
    return items


def _clear_history_json() -> None:
    with _history_lock:
        if HISTORY_FILE.exists():
            HISTORY_FILE.unlink()


# --- Supabase backend ---

def _record_search_supabase(ticker: str, period: str) -> None:
    assert _supabase_client is not None
    now = _now_iso()
    existing = (
        _supabase_client.table(HISTORY_TABLE)
        .select("count, first_searched")
        .eq("ticker", ticker)
        .limit(1)
        .execute()
    )
    if existing.data:
        new_count = int(existing.data[0].get("count", 0)) + 1
        first_searched = existing.data[0].get("first_searched") or now
    else:
        new_count = 1
        first_searched = now

    _supabase_client.table(HISTORY_TABLE).upsert(
        {
            "ticker": ticker,
            "count": new_count,
            "last_period": period,
            "last_searched": now,
            "first_searched": first_searched,
        },
        on_conflict="ticker",
    ).execute()


def _list_history_supabase() -> list[dict[str, Any]]:
    assert _supabase_client is not None
    res = (
        _supabase_client.table(HISTORY_TABLE)
        .select("ticker, count, last_period, last_searched, first_searched")
        .order("count", desc=True)
        .order("last_searched", desc=True)
        .execute()
    )
    return list(res.data or [])


def _clear_history_supabase() -> None:
    assert _supabase_client is not None
    # Supabase requires a filter on delete; this matches every row.
    _supabase_client.table(HISTORY_TABLE).delete().gte("count", 0).execute()


# --- Public dispatch ---

def _record_search(ticker: str, period: str) -> None:
    if _supabase_client is not None:
        try:
            _record_search_supabase(ticker, period)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("Supabase record_search failed (%s); falling back to JSON.", exc)
    _record_search_json(ticker, period)


def _list_history() -> list[dict[str, Any]]:
    if _supabase_client is not None:
        try:
            return _list_history_supabase()
        except Exception as exc:  # noqa: BLE001
            log.warning("Supabase list_history failed (%s); falling back to JSON.", exc)
    return _list_history_json()


def _clear_history_all() -> None:
    if _supabase_client is not None:
        try:
            _clear_history_supabase()
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("Supabase clear_history failed (%s); falling back to JSON.", exc)
    _clear_history_json()


def _clean(series: pd.Series) -> list[float | None]:
    """Convert a pandas series to a JSON-safe list, replacing NaN with None."""
    return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v) for v in series]


def _last_valid(series: pd.Series) -> float | None:
    s = series.dropna()
    return float(s.iloc[-1]) if not s.empty else None


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder's smoothing via EMA with alpha = 1/length
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal
    return macd_line, signal, hist


def _bollinger(close: pd.Series, length: int = 20, k: float = 2.0):
    mid = close.rolling(length).mean()
    std = close.rolling(length).std(ddof=0)
    return mid + k * std, mid, mid - k * std


def _slope_pct(series: pd.Series) -> float | None:
    """Linear-regression slope normalized as % change per bar over the mean."""
    s = series.dropna()
    if len(s) < 5:
        return None
    x = np.arange(len(s), dtype=float)
    y = s.to_numpy(dtype=float)
    slope = np.polyfit(x, y, 1)[0]
    mean = float(np.mean(y))
    if mean == 0:
        return None
    return float(slope / mean * 100.0)


def _verdict_from_score(score: int) -> str:
    """Map an aggregate signal score to a verdict label."""
    if score >= 3:
        return "bullish"
    if score >= 1:
        return "lean-bullish"
    if score <= -3:
        return "bearish"
    if score <= -1:
        return "lean-bearish"
    return "neutral"


def _quick_verdict_from_close(close: pd.Series) -> dict[str, Any]:
    """Compute a verdict + change% from a daily close series.

    Used by /watchlist and /sectors to score many tickers cheaply.
    Mirrors the same signals as /analyze (price vs SMAs, RSI, MACD, BB)
    but skips bullet-text generation.
    """
    close = close.dropna()
    if len(close) < 2:
        return {"verdict": "neutral", "score": 0, "price": None, "prev_close": None,
                "change_pct": None, "change_abs": None, "indicators": {}}

    last_price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])
    change_abs = last_price - prev_close
    change_pct = (change_abs / prev_close * 100.0) if prev_close else None

    n = len(close)

    def _change_pct_back(bars: int) -> float | None:
        """% change vs the close `bars` trading days ago."""
        if n <= bars:
            return None
        ref = float(close.iloc[-bars - 1])
        return ((last_price / ref) - 1) * 100.0 if ref else None

    change_pct_1w  = _change_pct_back(5)   # ~1 week (5 trading days)
    change_pct_1mo = _change_pct_back(21)  # ~1 month (21 trading days)

    def _safe_float(v: Any) -> float | None:
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return None if math.isnan(f) else f

    sma20 = _safe_float(close.rolling(20).mean().iloc[-1]) if n >= 20 else None
    sma50 = _safe_float(close.rolling(50).mean().iloc[-1]) if n >= 50 else None
    sma200 = _safe_float(close.rolling(200).mean().iloc[-1]) if n >= 200 else None

    rsi_series = _rsi(close, 14)
    rsi = _safe_float(rsi_series.iloc[-1]) if not rsi_series.dropna().empty else None

    macd_line, macd_signal, _ = _macd(close)
    macd_v = _safe_float(macd_line.iloc[-1])
    macd_sig_v = _safe_float(macd_signal.iloc[-1])
    macd_v_prev = _safe_float(macd_line.iloc[-2]) if len(macd_line) >= 2 else None
    macd_sig_v_prev = _safe_float(macd_signal.iloc[-2]) if len(macd_signal) >= 2 else None

    # Detect a fresh MACD cross on the last bar
    macd_cross: str | None = None
    if all(x is not None for x in [macd_v, macd_sig_v, macd_v_prev, macd_sig_v_prev]):
        if macd_v_prev <= macd_sig_v_prev and macd_v > macd_sig_v:
            macd_cross = "up"
        elif macd_v_prev >= macd_sig_v_prev and macd_v < macd_sig_v:
            macd_cross = "down"

    # Detect a fresh golden/death cross (SMA50 vs SMA200) on the last bar
    ma_cross: str | None = None
    if n >= 201:
        sma50_now = _safe_float(close.rolling(50).mean().iloc[-1])
        sma200_now = _safe_float(close.rolling(200).mean().iloc[-1])
        sma50_prev = _safe_float(close.rolling(50).mean().iloc[-2])
        sma200_prev = _safe_float(close.rolling(200).mean().iloc[-2])
        if all(x is not None for x in [sma50_now, sma200_now, sma50_prev, sma200_prev]):
            if sma50_prev <= sma200_prev and sma50_now > sma200_now:
                ma_cross = "golden"
            elif sma50_prev >= sma200_prev and sma50_now < sma200_now:
                ma_cross = "death"

    bb_upper, bb_mid, bb_lower = _bollinger(close, 20, 2.0)
    bbu = _safe_float(bb_upper.iloc[-1]) if n >= 20 else None
    bbl = _safe_float(bb_lower.iloc[-1]) if n >= 20 else None

    score = 0
    if sma20 is not None:
        score += 1 if last_price > sma20 else -1
    if sma20 is not None and sma50 is not None:
        score += 1 if sma20 > sma50 else -1
    if sma200 is not None:
        score += 1 if last_price > sma200 else -1
    if rsi is not None:
        if rsi >= 70:
            score -= 1
        elif rsi <= 30:
            score += 1
    if macd_v is not None and macd_sig_v is not None:
        score += 1 if macd_v > macd_sig_v else -1
    if bbu is not None and bbl is not None and (bbu - bbl) > 0:
        pos = (last_price - bbl) / (bbu - bbl)
        if pos >= 0.95:
            score -= 1
        elif pos <= 0.05:
            score += 1

    return {
        "verdict": _verdict_from_score(score),
        "score": score,
        "price": last_price,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "change_abs": change_abs,
        "change_pct_1w": change_pct_1w,
        "change_pct_1mo": change_pct_1mo,
        "indicators": {
            "SMA20": sma20, "SMA50": sma50, "SMA200": sma200,
            "RSI": rsi, "MACD": macd_v, "MACD_signal": macd_sig_v,
            "BB_upper": bbu, "BB_lower": bbl,
        },
        "macd_cross": macd_cross,
        "ma_cross":   ma_cross,
    }


def _build_summary(ind: dict[str, Any], price: float, period_label: str, ticker: str) -> tuple[str, list[dict[str, str]], str]:
    """Return (paragraph_summary, bullet_signals, overall_verdict)."""
    bullets: list[dict[str, str]] = []
    score = 0  # bullish positive, bearish negative

    # --- Trend (SMAs) ---
    sma20, sma50, sma200 = ind["SMA20"], ind["SMA50"], ind["SMA200"]
    slope = ind["SMA20_slope_pct"]

    if sma20 is not None:
        if price > sma20:
            score += 1
            bullets.append({
                "tone": "bullish",
                "label": "Price above 20-day SMA",
                "text": f"Price ({price:.2f}) is above its short-term average ({sma20:.2f}), which is typically a near-term bullish sign.",
            })
        else:
            score -= 1
            bullets.append({
                "tone": "bearish",
                "label": "Price below 20-day SMA",
                "text": f"Price ({price:.2f}) is below its short-term average ({sma20:.2f}), suggesting near-term weakness.",
            })

    if sma50 is not None and sma20 is not None:
        if sma20 > sma50:
            score += 1
            bullets.append({
                "tone": "bullish",
                "label": "Short-term SMA above mid-term SMA",
                "text": f"The 20-day average ({sma20:.2f}) is above the 50-day average ({sma50:.2f}), a sign the medium-term trend is up.",
            })
        else:
            score -= 1
            bullets.append({
                "tone": "bearish",
                "label": "Short-term SMA below mid-term SMA",
                "text": f"The 20-day average ({sma20:.2f}) is below the 50-day average ({sma50:.2f}), suggesting a softer medium-term trend.",
            })

    if sma200 is not None:
        if price > sma200:
            score += 1
            bullets.append({
                "tone": "bullish",
                "label": "Price above 200-day SMA",
                "text": f"Price is above the 200-day average ({sma200:.2f}) — the long-term trend is up.",
            })
        else:
            score -= 1
            bullets.append({
                "tone": "bearish",
                "label": "Price below 200-day SMA",
                "text": f"Price is below the 200-day average ({sma200:.2f}) — the long-term trend is down.",
            })

    if slope is not None:
        if slope > 0.05:
            bullets.append({
                "tone": "bullish",
                "label": "20-day SMA sloping up",
                "text": f"The 20-day average is rising (~{slope:+.2f}% per bar), confirming momentum is to the upside.",
            })
        elif slope < -0.05:
            bullets.append({
                "tone": "bearish",
                "label": "20-day SMA sloping down",
                "text": f"The 20-day average is falling (~{slope:+.2f}% per bar), confirming momentum is to the downside.",
            })
        else:
            bullets.append({
                "tone": "neutral",
                "label": "20-day SMA roughly flat",
                "text": "The 20-day average is essentially flat, suggesting the stock is consolidating rather than trending.",
            })

    # --- RSI ---
    rsi = ind["RSI"]
    if rsi is not None:
        if rsi >= 70:
            score -= 1
            bullets.append({
                "tone": "bearish",
                "label": f"RSI overbought ({rsi:.1f})",
                "text": f"RSI is {rsi:.1f}, above the 70 overbought threshold. The stock has run hot and may be due for a pullback.",
            })
        elif rsi <= 30:
            score += 1
            bullets.append({
                "tone": "bullish",
                "label": f"RSI oversold ({rsi:.1f})",
                "text": f"RSI is {rsi:.1f}, below the 30 oversold threshold. The stock looks washed out and could see a bounce.",
            })
        elif rsi >= 55:
            bullets.append({
                "tone": "bullish",
                "label": f"RSI bullish-neutral ({rsi:.1f})",
                "text": f"RSI is {rsi:.1f} — momentum is leaning bullish but not yet stretched.",
            })
        elif rsi <= 45:
            bullets.append({
                "tone": "bearish",
                "label": f"RSI bearish-neutral ({rsi:.1f})",
                "text": f"RSI is {rsi:.1f} — momentum is leaning bearish but not yet washed out.",
            })
        else:
            bullets.append({
                "tone": "neutral",
                "label": f"RSI neutral ({rsi:.1f})",
                "text": f"RSI is {rsi:.1f}, right in the middle of the range — no momentum extreme.",
            })

    # --- MACD ---
    macd_line = ind["MACD"]
    macd_signal = ind["MACD_signal"]
    macd_hist = ind["MACD_hist"]
    macd_hist_prev = ind["MACD_hist_prev"]
    if macd_line is not None and macd_signal is not None:
        if macd_line > macd_signal:
            score += 1
            tone = "bullish"
            cross_note = "MACD is above its signal line"
        else:
            score -= 1
            tone = "bearish"
            cross_note = "MACD is below its signal line"

        hist_txt = ""
        if macd_hist is not None and macd_hist_prev is not None:
            if macd_hist > 0 and macd_hist > macd_hist_prev:
                hist_txt = " and the histogram is expanding upward, suggesting strengthening upside momentum"
            elif macd_hist > 0 and macd_hist < macd_hist_prev:
                hist_txt = " though the histogram is shrinking, hinting upside momentum is fading"
            elif macd_hist < 0 and macd_hist < macd_hist_prev:
                hist_txt = " and the histogram is expanding downward, suggesting strengthening downside momentum"
            elif macd_hist < 0 and macd_hist > macd_hist_prev:
                hist_txt = " though the histogram is shrinking, hinting downside momentum is fading"

        bullets.append({
            "tone": tone,
            "label": "MACD " + ("bullish" if tone == "bullish" else "bearish"),
            "text": f"{cross_note} ({macd_line:.3f} vs {macd_signal:.3f}){hist_txt}.",
        })

    # --- Bollinger Bands ---
    bb_upper = ind["BB_upper"]
    bb_lower = ind["BB_lower"]
    bb_mid = ind["BB_mid"]
    if bb_upper is not None and bb_lower is not None and bb_mid is not None:
        rng = bb_upper - bb_lower
        pos = (price - bb_lower) / rng if rng > 0 else 0.5
        if pos >= 0.95:
            score -= 1
            bullets.append({
                "tone": "bearish",
                "label": "Pinned to upper Bollinger Band",
                "text": f"Price is at or above the upper band ({bb_upper:.2f}). The move is stretched relative to recent volatility.",
            })
        elif pos <= 0.05:
            score += 1
            bullets.append({
                "tone": "bullish",
                "label": "Pinned to lower Bollinger Band",
                "text": f"Price is at or below the lower band ({bb_lower:.2f}). The selloff is stretched relative to recent volatility.",
            })
        else:
            bullets.append({
                "tone": "neutral",
                "label": "Bollinger position normal",
                "text": f"Price is {int(pos * 100)}% of the way between the lower ({bb_lower:.2f}) and upper ({bb_upper:.2f}) bands — no volatility extreme.",
            })

    # --- Volume ---
    vol = ind["volume_last"]
    vol_avg = ind["volume_avg20"]
    if vol is not None and vol_avg is not None and vol_avg > 0:
        ratio = vol / vol_avg
        if ratio >= 1.5:
            bullets.append({
                "tone": "neutral",
                "label": f"Volume {ratio:.1f}× the 20-bar average",
                "text": f"Recent volume ({vol:,.0f}) is well above its 20-bar average ({vol_avg:,.0f}), so today's move carries conviction.",
            })
        elif ratio <= 0.6:
            bullets.append({
                "tone": "neutral",
                "label": f"Volume {ratio:.1f}× the 20-bar average",
                "text": f"Recent volume ({vol:,.0f}) is well below its 20-bar average ({vol_avg:,.0f}) — moves on light volume are less reliable.",
            })
        else:
            bullets.append({
                "tone": "neutral",
                "label": f"Volume {ratio:.1f}× the 20-bar average",
                "text": "Volume is roughly in line with its recent average.",
            })

    # --- Support / Resistance ---
    high = ind["resistance"]
    low = ind["support"]
    if high is not None and low is not None:
        bullets.append({
            "tone": "neutral",
            "label": "Key levels",
            "text": (
                f"Over the last {period_label}, the swing high was {high:.2f} (resistance) and the swing low was "
                f"{low:.2f} (support). Watch these as the next levels where the trend could stall or reverse."
            ),
        })

    # --- Verdict ---
    verdict = _verdict_from_score(score)
    verdict_text = {
        "bullish": "an overall bullish setup",
        "lean-bullish": "a slight bullish lean",
        "bearish": "an overall bearish setup",
        "lean-bearish": "a slight bearish lean",
        "neutral": "a mixed/neutral picture",
    }[verdict]

    paragraph = (
        f"Over the past {period_label}, {ticker.upper()} is showing {verdict_text}. "
        f"It is currently trading at {price:.2f}"
    )
    if sma20 is not None:
        paragraph += f", {'above' if price > sma20 else 'below'} its 20-bar moving average"
    if rsi is not None:
        paragraph += f", with RSI at {rsi:.1f}"
    if macd_line is not None and macd_signal is not None:
        paragraph += f" and MACD {'bullishly' if macd_line > macd_signal else 'bearishly'} crossed against its signal line"
    paragraph += "."

    paragraph += (
        " Note: this is a quick read of the technicals, not investment advice. Indicators can stay stretched or "
        "fail to confirm; always pair this with fundamentals and risk management."
    )

    return paragraph, bullets, verdict


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    if req.period not in PERIOD_MAP:
        raise HTTPException(status_code=400, detail=f"Invalid period. Must be one of {list(PERIOD_MAP)}.")

    yf_period, interval = PERIOD_MAP[req.period]
    ticker = req.ticker.strip().upper()

    try:
        df = yf.Ticker(ticker).history(period=yf_period, interval=interval, auto_adjust=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to fetch data: {exc}") from exc

    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"No data returned for ticker '{ticker}'.")

    df = df.dropna(subset=["Close"])
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No usable price data for '{ticker}'.")

    close = df["Close"].astype(float)
    volume = df["Volume"].astype(float)
    n = len(df)

    # --- Compute indicators ---
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean() if n >= 50 else pd.Series([np.nan] * n, index=close.index)
    sma200 = close.rolling(200).mean() if n >= 200 else pd.Series([np.nan] * n, index=close.index)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()

    rsi = _rsi(close, 14)
    macd_line, macd_signal, macd_hist = _macd(close)
    bb_upper, bb_mid, bb_lower = _bollinger(close, 20, 2.0)
    vol_avg20 = volume.rolling(20).mean()

    # support/resistance: rolling-window swing highs/lows over the period
    resistance = float(df["High"].max())
    support = float(df["Low"].min())

    sma20_slope = _slope_pct(sma20)

    last_close = float(close.iloc[-1])

    indicators_scalar: dict[str, Any] = {
        "price": last_close,
        "SMA20": _last_valid(sma20),
        "SMA50": _last_valid(sma50) if n >= 50 else None,
        "SMA200": _last_valid(sma200) if n >= 200 else None,
        "EMA12": _last_valid(ema12),
        "EMA26": _last_valid(ema26),
        "RSI": _last_valid(rsi),
        "MACD": _last_valid(macd_line),
        "MACD_signal": _last_valid(macd_signal),
        "MACD_hist": _last_valid(macd_hist),
        "MACD_hist_prev": float(macd_hist.dropna().iloc[-2]) if macd_hist.dropna().size >= 2 else None,
        "BB_upper": _last_valid(bb_upper),
        "BB_mid": _last_valid(bb_mid),
        "BB_lower": _last_valid(bb_lower),
        "volume_last": float(volume.iloc[-1]) if not volume.empty else None,
        "volume_avg20": _last_valid(vol_avg20),
        "support": support,
        "resistance": resistance,
        "SMA20_slope_pct": sma20_slope,
    }

    # --- Build summary ---
    paragraph, bullets, verdict = _build_summary(
        indicators_scalar, last_close, PERIOD_LABEL[req.period], ticker
    )

    # --- Record in search history (only on successful analysis) ---
    _record_search(ticker, req.period)

    # --- Series for chart ---
    labels = [ts.isoformat() for ts in df.index]
    series = {
        "labels": labels,
        "close": _clean(close),
        "SMA20": _clean(sma20),
        "SMA50": _clean(sma50),
        "SMA200": _clean(sma200),
        "EMA12": _clean(ema12),
        "EMA26": _clean(ema26),
        "BB_upper": _clean(bb_upper),
        "BB_mid": _clean(bb_mid),
        "BB_lower": _clean(bb_lower),
        "RSI": _clean(rsi),
        "MACD": _clean(macd_line),
        "MACD_signal": _clean(macd_signal),
        "MACD_hist": _clean(macd_hist),
        "volume": _clean(volume),
    }

    return {
        "ticker": ticker,
        "period": req.period,
        "period_label": PERIOD_LABEL[req.period],
        "interval": interval,
        "bars": n,
        "indicators": indicators_scalar,
        "series": series,
        "summary": {
            "verdict": verdict,
            "paragraph": paragraph,
            "bullets": bullets,
        },
    }


@app.get("/history")
def get_history():
    items = _list_history()
    total = sum(int(item.get("count", 0)) for item in items)
    return {
        "items": items,
        "unique": len(items),
        "total": total,
        "backend": "supabase" if _supabase_client is not None else "json",
    }


@app.delete("/history")
def clear_history():
    _clear_history_all()
    return {"ok": True}


# ----------------------------- Sentiment analysis -----------------------------
#
# VADER (Valence Aware Dictionary and sEntiment Reasoner) — lightweight,
# no API key, ~4MB lexicon. Designed for short social-media-style text,
# which is what news headlines and Reddit titles are. The base lexicon
# misses finance jargon (it scores "bullish" and "bearish" as 0), so we
# extend it with a curated finance vocabulary below.

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # noqa: E402

_VADER = SentimentIntensityAnalyzer()
_VADER.lexicon.update({
    # Direction
    "bullish": 2.5, "bearish": -2.5,
    # Big moves up
    "moon": 3.0, "mooning": 3.0, "rally": 2.0, "rallies": 2.0,
    "surge": 2.0, "surges": 2.0, "soar": 2.5, "soars": 2.5,
    "skyrocket": 3.0, "rip": 2.0, "ripping": 2.0, "rips": 2.0,
    "pump": 1.5, "pumping": 1.5, "pumps": 1.5,
    "spike": 1.5, "spikes": 1.5, "breakout": 2.0, "breakouts": 2.0,
    # Big moves down
    "crash": -3.0, "crashes": -3.0, "crashing": -3.0,
    "tank": -2.5, "tanking": -2.5, "tanks": -2.5,
    "plunge": -2.5, "plunges": -2.5, "plummet": -3.0, "plummets": -3.0,
    "dump": -2.0, "dumping": -2.0, "dumps": -2.0,
    "selloff": -2.0, "bloodbath": -3.5, "rout": -2.5,
    # Earnings / fundamentals
    "beat": 2.0, "beats": 2.0, "exceeded": 2.0, "outperformed": 2.0,
    "miss": -2.0, "misses": -2.0, "missed": -2.0,
    "disappoint": -2.0, "disappointed": -2.0, "disappointing": -2.0,
    "buyback": 1.5, "buybacks": 1.5,
    # Analyst actions
    "upgrade": 2.0, "upgrades": 2.0, "upgraded": 2.0,
    "downgrade": -2.0, "downgrades": -2.0, "downgraded": -2.0,
    # Reddit / WSB jargon
    "yolo": 1.0, "hodl": 1.5, "moonshot": 2.5,
    "bagholder": -2.5, "bagholders": -2.5,
    "tendies": 2.5, "rugpull": -3.0,
    # Trouble
    "lawsuit": -2.0, "fined": -1.5, "investigation": -2.0,
    "subpoena": -2.5, "halt": -2.0, "halted": -2.0,
    "bankrupt": -3.5, "bankruptcy": -3.5, "delisted": -3.0, "fraud": -3.5,
    # Soften words that VADER over-weights in business-news context
    # ("chip war", "price war", "battle for market share" aren't really
    # negative sentiment — they're competitive framing).
    "war": -0.5, "battle": -0.3, "fight": -0.3,
    "weapon": -0.5, "weapons": -0.5,
})


def _strip_news_source(title: str) -> str:
    """Strip Google News' ' - Publisher' suffix before sentiment scoring.
    The publisher name carries no headline sentiment and frequently injects
    irrelevant words into the score."""
    if " - " not in title:
        return title
    # Only strip if what comes after " - " is short (looks like a publisher
    # name) — don't lop off content from headlines that legitimately use
    # dashes mid-sentence.
    head, _, tail = title.rpartition(" - ")
    if len(tail) < 40 and len(head) > 15:
        return head.strip()
    return title


def _score_sentiment(text: str) -> dict[str, Any] | None:
    """Score a single piece of short text. Returns None for empty input."""
    if not text or not text.strip():
        return None
    s = _VADER.polarity_scores(text)
    compound = float(s.get("compound", 0.0))
    return {
        "compound": compound,
        "pos":      float(s.get("pos", 0.0)),
        "neg":      float(s.get("neg", 0.0)),
        "neu":      float(s.get("neu", 0.0)),
        "label":    _sentiment_label(compound),
    }


def _sentiment_label(compound: float) -> str:
    """VADER convention: compound >= 0.05 positive, <= -0.05 negative."""
    if compound >= 0.05:
        return "positive"
    if compound <= -0.05:
        return "negative"
    return "neutral"


def _aggregate_sentiment(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Compute mean compound + label tallies across a list of items each
    carrying a `sentiment` dict from _score_sentiment."""
    scored = [it["sentiment"] for it in items if isinstance(it.get("sentiment"), dict)]
    if not scored:
        return None
    mean_compound = sum(s["compound"] for s in scored) / len(scored)
    labels = [s["label"] for s in scored]
    return {
        "mean_compound": mean_compound,
        "label":         _sentiment_label(mean_compound),
        "positive":      labels.count("positive"),
        "negative":      labels.count("negative"),
        "neutral":       labels.count("neutral"),
        "total":         len(scored),
    }


# ----------------------------- Dashboard widgets -----------------------------
#
# Server-fed widget endpoints. The TradingView mini-chart is fully client-side
# and doesn't need a backend.
#
# Some endpoints prefer Financial Modeling Prep (FMP) when FMP_API_KEY is
# set, falling back to yfinance / public APIs otherwise. FMP gives cleaner
# structured data than yfinance .info, but the free tier is 250 req/day and
# many endpoints are gated to paid plans — so we cache aggressively (hours,
# not minutes) and degrade gracefully on 401/403/429.
#
# All endpoints are wrapped in a tiny in-memory TTL cache.

FMP_API_KEY = os.environ.get("FMP_API_KEY", "").strip()
FMP_BASE = "https://financialmodelingprep.com/api/v3"


class FMPError(Exception):
    """FMP returned an error we should surface or fall back from."""


def _fmp_enabled() -> bool:
    return bool(FMP_API_KEY)


def _fmp_get(endpoint: str, params: dict[str, Any] | None = None, timeout: int = 10) -> Any:
    """Hit an FMP endpoint. Raises FMPError on auth/plan/rate problems so
    callers can decide whether to fall back."""
    if not _fmp_enabled():
        raise FMPError("FMP_API_KEY not configured")
    p = dict(params or {})
    p["apikey"] = FMP_API_KEY
    r = requests.get(f"{FMP_BASE}{endpoint}", params=p, timeout=timeout)
    if r.status_code in (401, 403):
        raise FMPError(f"FMP auth/plan rejected ({r.status_code}) — endpoint may require paid tier")
    if r.status_code == 429:
        raise FMPError("FMP rate limit reached (free tier = 250 req/day)")
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError as exc:
        raise FMPError(f"FMP returned non-JSON: {exc}") from exc
    # FMP returns {"Error Message": "..."} for some plan-restricted endpoints with HTTP 200
    if isinstance(data, dict) and "Error Message" in data:
        raise FMPError(f"FMP error: {data['Error Message']}")
    return data


_WIDGET_CACHE: dict[tuple, tuple[float, Any]] = {}


def _cache_get(key: tuple) -> Any | None:
    entry = _WIDGET_CACHE.get(key)
    if entry is None:
        return None
    expiry, value = entry
    if time.time() > expiry:
        _WIDGET_CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: tuple, value: Any, ttl: int) -> None:
    _WIDGET_CACHE[key] = (time.time() + ttl, value)


def _with_timeout(fn: Callable[[], Any], timeout: float, default: Any = None) -> Any:
    """Run a sync callable with a hard wall-clock timeout. Useful for yfinance
    calls which can hang for tens of seconds when Yahoo throttles datacenter
    IPs — we'd rather return empty data than spin the widget forever.

    NOTE: we can't actually kill the thread in Python — it keeps running in
    the background until it finishes naturally. But we stop *waiting* for it,
    so the request returns promptly. shutdown(wait=False) is critical: the
    default `with ThreadPoolExecutor()` block blocks on exit until the thread
    completes, which would defeat the timeout."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(fn)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return default
        except Exception:  # noqa: BLE001
            return default
    finally:
        pool.shutdown(wait=False)


def _safe(call: Callable[[], Any], default: Any = None) -> Any:
    try:
        return call()
    except Exception:  # noqa: BLE001
        return default


def _ts_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            return None
    if isinstance(value, (int, float)) and not math.isnan(value):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    return str(value)


REDDIT_USER_AGENT = os.environ.get(
    "REDDIT_USER_AGENT",
    "web:ticker-tracker:v1.0 (by /u/anonymous)",
)


def _get_reddit_token() -> str | None:
    """Get a Reddit OAuth client-credentials token, cached ~23h.

    Returns None when REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET aren't set or
    when Reddit refuses the auth — caller should surface a 503 in that case.
    Reddit started blocking unauthenticated server-side hits to
    www.reddit.com in 2023; OAuth + oauth.reddit.com is the supported path.
    """
    cid = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    cs = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    if not cid or not cs:
        return None

    cache_key = ("reddit_token",)
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        auth = base64.b64encode(f"{cid}:{cs}".encode()).decode()
        r = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {auth}",
                "User-Agent": REDDIT_USER_AGENT,
            },
            timeout=10,
        )
        r.raise_for_status()
        token = (r.json() or {}).get("access_token")
        if not token:
            log.warning("Reddit token response missing access_token")
            return None
        # Tokens last 24h; cache for 23h so we refresh before expiry.
        _cache_set(cache_key, token, ttl=23 * 3600)
        return token
    except Exception as exc:  # noqa: BLE001
        log.warning("Reddit OAuth token fetch failed: %s", exc)
        return None


@app.get("/widgets/reddit")
def widget_reddit(ticker: str):
    ticker = ticker.strip().upper()
    if not ticker:
        raise HTTPException(400, "Missing ticker.")

    cache_key = ("reddit", ticker)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    token = _get_reddit_token()
    if not token:
        raise HTTPException(
            503,
            "Reddit widget requires REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET "
            "env vars (Reddit blocked unauthenticated access in 2023). "
            "Register a free app at https://www.reddit.com/prefs/apps.",
        )

    subs = "wallstreetbets+stocks+investing+StockMarket"

    # Two-pronged query so we cover both conventions:
    #   "$TICKER"     — the cashtag, used on r/wallstreetbets etc.
    #   title:TICKER  — posts that mention the ticker in the title, even
    #                   without a $ prefix (common on r/stocks, r/investing)
    # We over-fetch and post-filter so that posts which only mention the
    # ticker incidentally (e.g. listed in a portfolio screenshot) get dropped.
    params = {
        "q": f'"${ticker}" OR title:{ticker}',
        "restrict_sr": "on",
        "sort": "relevance",
        "limit": "30",
        "t": "month",
    }
    url = f"https://oauth.reddit.com/r/{subs}/search.json?{urlencode(params)}"
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": REDDIT_USER_AGENT,
    }

    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Reddit fetch failed: {exc}") from exc

    cashtag_re = re.compile(rf"\${re.escape(ticker)}\b", re.IGNORECASE)
    word_re = re.compile(rf"\b{re.escape(ticker)}\b", re.IGNORECASE)
    # Single- and two-letter tickers (F, T, M, GE, BP, ...) collide with
    # English words too easily. Require the explicit cashtag for those.
    cashtag_only = len(ticker) <= 2

    candidates: list[dict[str, Any]] = []
    for child in (data.get("data") or {}).get("children", []):
        d = child.get("data") or {}
        title = d.get("title") or ""
        selftext = d.get("selftext") or ""

        # Match strength:
        #   2 = cashtag in title or body (strongest signal)
        #   1 = ticker as a whole word in the title (skipped for short tickers)
        #   0 = no real match (drop it)
        if cashtag_re.search(title) or cashtag_re.search(selftext):
            strength = 2
        elif not cashtag_only and word_re.search(title):
            strength = 1
        else:
            continue

        candidates.append({
            "title": title,
            "subreddit": d.get("subreddit"),
            "score": int(d.get("score") or 0),
            "num_comments": int(d.get("num_comments") or 0),
            "created_utc": d.get("created_utc"),
            "permalink": f"https://www.reddit.com{d.get('permalink', '')}",
            "author": d.get("author"),
            "flair": d.get("link_flair_text"),
            "_strength": strength,
        })

    # Re-rank: stronger matches first, then by Reddit upvotes
    candidates.sort(key=lambda x: (x["_strength"], x.get("score", 0)), reverse=True)

    posts = []
    for c in candidates[:15]:
        c.pop("_strength", None)
        c["sentiment"] = _score_sentiment(c.get("title") or "")
        posts.append(c)

    result = {
        "ticker": ticker,
        "posts": posts,
        "sentiment": _aggregate_sentiment(posts),
    }
    _cache_set(cache_key, result, ttl=300)  # 5 min
    return result


@app.get("/widgets/news")
def widget_news(ticker: str):
    ticker = ticker.strip().upper()
    if not ticker:
        raise HTTPException(400, "Missing ticker.")

    cache_key = ("news", ticker)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = (
        f"https://news.google.com/rss/search?q={ticker}+stock"
        f"&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"News fetch failed: {exc}") from exc

    items = []
    for it in root.findall(".//item")[:20]:
        title = (it.findtext("title") or "").strip()
        items.append({
            "title":     title,
            "link":      (it.findtext("link") or "").strip(),
            "pub_date":  (it.findtext("pubDate") or "").strip(),
            "source":    (it.findtext("source") or "").strip(),
            "sentiment": _score_sentiment(_strip_news_source(title)),
        })

    result = {
        "ticker": ticker,
        "items": items,
        "sentiment": _aggregate_sentiment(items),
    }
    _cache_set(cache_key, result, ttl=300)  # 5 min
    return result


@app.get("/widgets/fundamentals")
def widget_fundamentals(ticker: str):
    ticker = ticker.strip().upper()
    if not ticker:
        raise HTTPException(400, "Missing ticker.")

    cache_key = ("fundamentals", ticker)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Prefer FMP — cleaner structured data than yfinance .info
    if _fmp_enabled():
        try:
            profile_arr = _fmp_get(f"/profile/{ticker}")
            quote_arr = _fmp_get(f"/quote/{ticker}")
            profile = (profile_arr[0] if profile_arr else {}) or {}
            quote = (quote_arr[0] if quote_arr else {}) or {}

            if profile or quote:
                price = quote.get("price")
                last_div = profile.get("lastDiv")
                data = {
                    "longName":   profile.get("companyName") or quote.get("name"),
                    "shortName":  quote.get("name"),
                    "sector":     profile.get("sector"),
                    "industry":   profile.get("industry"),
                    "country":    profile.get("country"),
                    "currency":   profile.get("currency"),
                    "exchange":   profile.get("exchangeShortName") or quote.get("exchange"),
                    "marketCap":  profile.get("mktCap") or quote.get("marketCap"),
                    "trailingPE": quote.get("pe"),
                    "trailingEps": quote.get("eps"),
                    "beta":       profile.get("beta"),
                    "fiftyTwoWeekLow":  quote.get("yearLow"),
                    "fiftyTwoWeekHigh": quote.get("yearHigh"),
                    "fiftyDayAverage":  quote.get("priceAvg50"),
                    "twoHundredDayAverage": quote.get("priceAvg200"),
                    "currentPrice":     price,
                    "regularMarketPrice": price,
                    "previousClose":    quote.get("previousClose"),
                    "regularMarketChange":        quote.get("change"),
                    "regularMarketChangePercent": quote.get("changesPercentage"),
                    "volume":         quote.get("volume"),
                    "averageVolume":  quote.get("avgVolume"),
                    "sharesOutstanding": quote.get("sharesOutstanding"),
                    "dividendRate":   last_div,
                    "dividendYield":  (last_div / price * 100) if (last_div and price) else None,
                }
                # Normalize NaN floats
                for k, v in list(data.items()):
                    if isinstance(v, float) and math.isnan(v):
                        data[k] = None

                result = {"ticker": ticker, "data": data, "source": "fmp"}
                _cache_set(cache_key, result, ttl=21600)  # 6 hours
                return result
        except FMPError as exc:
            log.warning("FMP fundamentals failed for %s: %s; falling back to yfinance", ticker, exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("FMP fundamentals errored for %s: %s; falling back to yfinance", ticker, exc)

    # Fallback 1: yfinance .info (works from residential IPs, often blocked
    # on datacenter IPs like Render)
    info = _safe(lambda: yf.Ticker(ticker).info, default={}) or {}
    fields = [
        "longName", "shortName", "sector", "industry", "country", "currency", "exchange",
        "marketCap", "enterpriseValue",
        "trailingPE", "forwardPE", "priceToBook", "pegRatio",
        "trailingEps", "forwardEps",
        "profitMargins", "operatingMargins", "returnOnEquity",
        "dividendYield", "dividendRate", "payoutRatio",
        "beta",
        "fiftyTwoWeekLow", "fiftyTwoWeekHigh",
        "fiftyDayAverage", "twoHundredDayAverage",
        "currentPrice", "regularMarketPrice", "previousClose",
        "regularMarketChange", "regularMarketChangePercent",
        "volume", "averageVolume", "averageVolume10days",
        "sharesOutstanding", "floatShares",
    ]
    if info:
        data: dict[str, Any] = {}
        for k in fields:
            v = info.get(k)
            if isinstance(v, float) and math.isnan(v):
                v = None
            data[k] = v
        result = {"ticker": ticker, "data": data, "source": "yfinance"}
        _cache_set(cache_key, result, ttl=600)
        return result

    # Fallback 2: yfinance .fast_info — uses Yahoo's chart API instead of
    # the .info scrape, so it works from Render's datacenter IPs. Fewer
    # fields available (no PE/EPS/dividend yield/sector via this path) so
    # we backfill sector from our SECTORS mapping and accept the rest as —.
    fi = _safe(lambda: yf.Ticker(ticker).fast_info)
    if fi is None:
        raise HTTPException(404, f"No fundamentals available for '{ticker}'.")

    def _fi(name: str) -> Any:
        try:
            v = getattr(fi, name)
        except Exception:  # noqa: BLE001
            return None
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        return v

    last_price = _fi("last_price")
    prev_close = _fi("previous_close")
    change_abs = (last_price - prev_close) if (last_price is not None and prev_close is not None) else None
    change_pct = (change_abs / prev_close * 100) if (change_abs is not None and prev_close) else None

    # Backfill sector from our hardcoded SECTORS map (covers ~165 large caps)
    sector = next((sec["name"] for sec in SECTORS if ticker in sec["components"] or ticker == sec["etf"]), None)

    data = {k: None for k in fields}
    data.update({
        "currentPrice":           last_price,
        "regularMarketPrice":     last_price,
        "previousClose":          prev_close,
        "regularMarketChange":    change_abs,
        "regularMarketChangePercent": change_pct,
        "marketCap":              _fi("market_cap"),
        "fiftyTwoWeekHigh":       _fi("year_high"),
        "fiftyTwoWeekLow":        _fi("year_low"),
        "fiftyDayAverage":        _fi("fifty_day_average"),
        "twoHundredDayAverage":   _fi("two_hundred_day_average"),
        "currency":               _fi("currency"),
        "exchange":               _fi("exchange"),
        "volume":                 _fi("last_volume"),
        "averageVolume":          _fi("three_month_average_volume"),
        "sharesOutstanding":      _fi("shares"),
        "longName":               ticker,  # we don't have the company name on this path
        "sector":                 sector,
    })

    # If we don't even have a last price, fail honestly rather than render an empty widget.
    if data["currentPrice"] is None and data["marketCap"] is None:
        raise HTTPException(404, f"No fundamentals available for '{ticker}'.")

    result = {"ticker": ticker, "data": data, "source": "yfinance-fast"}
    _cache_set(cache_key, result, ttl=600)
    return result


@app.get("/widgets/earnings")
def widget_earnings(ticker: str):
    """Per-ticker earnings — next date, estimate range, and recent history
    with surprise %. Prefers FMP's per-ticker earning_calendar (clean shape,
    works from datacenter IPs); falls back to yfinance with a hard timeout
    so the widget can never spin forever."""
    ticker = ticker.strip().upper()
    if not ticker:
        raise HTTPException(400, "Missing ticker.")

    cache_key = ("earnings", ticker)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    calendar: dict[str, Any] = {}
    earnings_dates: list[dict[str, Any]] = []
    source = "empty"

    # --- FMP: /v3/historical/earning_calendar/{symbol} returns mixed past +
    # upcoming earnings in a single call. eps/revenue are populated for past
    # entries; epsEstimated/revenueEstimated for upcoming.
    if _fmp_enabled():
        try:
            rows = _fmp_get(f"/historical/earning_calendar/{ticker}", {"limit": 40}) or []
            if isinstance(rows, list) and rows:
                today = datetime.now(timezone.utc).date().isoformat()
                # Sort ascending by date
                rows.sort(key=lambda r: (r.get("date") or ""))
                upcoming = [r for r in rows if (r.get("date") or "") >= today]
                past = [r for r in rows if (r.get("date") or "") < today]

                # Build the calendar shape the frontend expects from the
                # nearest upcoming entry.
                if upcoming:
                    nxt = upcoming[0]
                    calendar = {
                        "Earnings Date":      nxt.get("date"),
                        "Earnings Average":   nxt.get("epsEstimated"),
                        "Earnings High":      nxt.get("epsEstimated"),
                        "Earnings Low":       nxt.get("epsEstimated"),
                        "Revenue Average":    nxt.get("revenueEstimated"),
                        "Revenue High":       nxt.get("revenueEstimated"),
                        "Revenue Low":        nxt.get("revenueEstimated"),
                    }

                # Past earnings, newest first, with surprise %
                for r in reversed(past[-8:]):
                    eps_actual = r.get("eps")
                    eps_est = r.get("epsEstimated")
                    surprise = None
                    if isinstance(eps_actual, (int, float)) and isinstance(eps_est, (int, float)) and eps_est:
                        surprise = (eps_actual - eps_est) / abs(eps_est) * 100
                    earnings_dates.append({
                        "date":         r.get("date"),
                        "eps_estimate": eps_est,
                        "eps_actual":   eps_actual,
                        "surprise_pct": surprise,
                    })
                source = "fmp"
        except FMPError as exc:
            log.info("FMP earnings unavailable for %s (%s); falling back to yfinance", ticker, exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("FMP earnings errored for %s: %s; falling back to yfinance", ticker, exc)

    # --- Fallback: yfinance. Wrapped in a hard timeout because .calendar and
    # .earnings_dates can hang for 30s+ from Render's datacenter IP.
    if source == "empty":
        t = yf.Ticker(ticker)

        raw_cal = _with_timeout(lambda: t.calendar, timeout=6.0)
        if isinstance(raw_cal, dict):
            for k, v in raw_cal.items():
                if isinstance(v, list):
                    calendar[k] = [_ts_to_iso(x) for x in v]
                else:
                    calendar[k] = _ts_to_iso(v) if hasattr(v, "isoformat") else v
        elif isinstance(raw_cal, pd.DataFrame) and not raw_cal.empty:
            for col in raw_cal.columns:
                v = raw_cal[col].iloc[0]
                calendar[col] = _ts_to_iso(v) if hasattr(v, "isoformat") else (None if pd.isna(v) else v)

        raw_ed = _with_timeout(lambda: t.earnings_dates, timeout=6.0)
        if isinstance(raw_ed, pd.DataFrame) and not raw_ed.empty:
            ed = raw_ed.head(8).reset_index()
            date_col = "Earnings Date" if "Earnings Date" in ed.columns else ed.columns[0]
            for _, row in ed.iterrows():
                def _f(col: str) -> float | None:
                    v = row.get(col)
                    if v is None or (isinstance(v, float) and math.isnan(v)):
                        return None
                    return float(v) if isinstance(v, (int, float, np.integer, np.floating)) else None

                earnings_dates.append({
                    "date":         _ts_to_iso(row.get(date_col)),
                    "eps_estimate": _f("EPS Estimate"),
                    "eps_actual":   _f("Reported EPS"),
                    "surprise_pct": _f("Surprise(%)"),
                })
        if calendar or earnings_dates:
            source = "yfinance"

    result = {
        "ticker": ticker,
        "calendar": calendar,
        "earnings_dates": earnings_dates,
        "source": source,
    }
    _cache_set(cache_key, result, ttl=900)  # 15 min
    return result


@app.get("/widgets/analysts")
def widget_analysts(ticker: str):
    ticker = ticker.strip().upper()
    if not ticker:
        raise HTTPException(400, "Missing ticker.")

    cache_key = ("analysts", ticker)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Prefer FMP — daily-updated price targets and clean rating breakdown.
    # Some of these endpoints require a paid plan; we degrade to yfinance.
    if _fmp_enabled():
        try:
            tgt_arr = _fmp_get("/price-target-consensus", {"symbol": ticker})
            rec_arr = _fmp_get("/upgrades-downgrades-consensus", {"symbol": ticker})
            quote_arr = _fmp_get(f"/quote/{ticker}")
            tgt = (tgt_arr[0] if tgt_arr else {}) or {}
            rec = (rec_arr[0] if rec_arr else {}) or {}
            quote = (quote_arr[0] if quote_arr else {}) or {}

            ratings = None
            if rec:
                try:
                    ratings = {
                        "strong_buy":  int(rec.get("strongBuy", 0) or 0),
                        "buy":         int(rec.get("buy", 0) or 0),
                        "hold":        int(rec.get("hold", 0) or 0),
                        "sell":        int(rec.get("sell", 0) or 0),
                        "strong_sell": int(rec.get("strongSell", 0) or 0),
                    }
                except (TypeError, ValueError):
                    ratings = None

            num_analysts = sum(ratings.values()) if ratings else None

            if tgt or rec:
                result = {
                    "ticker":              ticker,
                    "current_price":       quote.get("price"),
                    "target_mean":         tgt.get("targetConsensus"),
                    "target_high":         tgt.get("targetHigh"),
                    "target_low":          tgt.get("targetLow"),
                    "target_median":       tgt.get("targetMedian"),
                    "recommendation_mean": None,  # FMP gives a string consensus, not a 1-5
                    "recommendation_key":  (rec.get("consensus") or "").lower() or None,
                    "num_analysts":        num_analysts,
                    "ratings":             ratings,
                    "source":              "fmp",
                }
                _cache_set(cache_key, result, ttl=21600)  # 6 hours
                return result
        except FMPError as exc:
            log.warning("FMP analysts failed for %s: %s; falling back to yfinance", ticker, exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("FMP analysts errored for %s: %s; falling back to yfinance", ticker, exc)

    # Fallback: yfinance
    t = yf.Ticker(ticker)
    info = _safe(lambda: t.info, default={}) or {}

    ratings: dict[str, int] | None = None
    raw_recs = _safe(lambda: t.recommendations)
    if isinstance(raw_recs, pd.DataFrame) and not raw_recs.empty:
        latest = raw_recs.iloc[0]
        try:
            ratings = {
                "strong_buy":  int(latest.get("strongBuy", 0) or 0),
                "buy":         int(latest.get("buy", 0) or 0),
                "hold":        int(latest.get("hold", 0) or 0),
                "sell":        int(latest.get("sell", 0) or 0),
                "strong_sell": int(latest.get("strongSell", 0) or 0),
            }
        except Exception:  # noqa: BLE001
            ratings = None

    def _num(key: str) -> float | None:
        v = info.get(key)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    result = {
        "ticker": ticker,
        "current_price": _num("currentPrice") or _num("regularMarketPrice"),
        "target_mean":  _num("targetMeanPrice"),
        "target_high":  _num("targetHighPrice"),
        "target_low":   _num("targetLowPrice"),
        "target_median": _num("targetMedianPrice"),
        "recommendation_mean": _num("recommendationMean"),
        "recommendation_key":  info.get("recommendationKey"),
        "num_analysts": int(info["numberOfAnalystOpinions"]) if isinstance(info.get("numberOfAnalystOpinions"), (int, float)) else None,
        "ratings": ratings,
        "source":  "yfinance",
    }
    _cache_set(cache_key, result, ttl=900)  # 15 min
    return result


# ----------------------------- Watchlist + Sectors -----------------------------
#
# Both endpoints reuse `_quick_verdict_from_close` to score many tickers from
# a single batched yf.download() call instead of one HTTP round-trip per ticker.

# 11 SPDR sector ETFs + their top large-cap components (US-listed, by market
# cap; not strictly NYSE-only since most tech / communication-services giants
# trade on NASDAQ — strict NYSE filtering would gut the most useful sectors).
SECTORS: list[dict[str, Any]] = [
    {"name": "Technology", "etf": "XLK",
     "components": ["AAPL","MSFT","NVDA","AVGO","ORCL","CRM","ADBE","AMD","CSCO","INTC","TXN","QCOM","IBM","NOW","INTU"]},
    {"name": "Financials", "etf": "XLF",
     "components": ["JPM","BAC","WFC","GS","MS","BLK","AXP","C","SCHW","BX","KKR","USB","PNC","COF","MMC"]},
    {"name": "Health Care", "etf": "XLV",
     "components": ["LLY","UNH","JNJ","MRK","ABBV","TMO","PFE","ABT","DHR","ISRG","AMGN","GILD","BMY","CI","MDT"]},
    {"name": "Consumer Discretionary", "etf": "XLY",
     "components": ["AMZN","TSLA","HD","MCD","NKE","LOW","BKNG","TJX","SBUX","CMG","MAR","ABNB","F","GM","ORLY"]},
    {"name": "Consumer Staples", "etf": "XLP",
     "components": ["WMT","COST","PG","KO","PEP","PM","MO","MDLZ","CL","TGT","KHC","MNST","GIS","KMB","KR"]},
    {"name": "Energy", "etf": "XLE",
     "components": ["XOM","CVX","COP","EOG","SLB","MPC","OXY","PSX","VLO","WMB","KMI","OKE","BKR","HAL","FANG"]},
    {"name": "Industrials", "etf": "XLI",
     "components": ["CAT","GE","RTX","HON","UPS","BA","UNP","ETN","DE","LMT","ADP","NOC","TT","GD","EMR"]},
    {"name": "Materials", "etf": "XLB",
     "components": ["LIN","SHW","ECL","APD","FCX","NEM","DOW","DD","CTVA","NUE","MLM","VMC","IFF","PPG","IP"]},
    {"name": "Utilities", "etf": "XLU",
     "components": ["NEE","SO","DUK","AEP","SRE","CEG","D","EXC","XEL","EIX","WEC","PCG","PEG","ED","ETR"]},
    {"name": "Real Estate", "etf": "XLRE",
     "components": ["PLD","AMT","EQIX","WELL","SPG","CCI","PSA","O","DLR","EXR","AVB","EQR","INVH","ARE","VICI"]},
    {"name": "Communication Services", "etf": "XLC",
     "components": ["META","GOOGL","GOOG","NFLX","TMUS","DIS","CMCSA","T","VZ","CHTR","EA","WBD","TTWO","OMC","IPG"]},
]


def _safe_str(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return str(v)


def _score_tickers_bulk(tickers: list[str], period: str = "3mo") -> dict[str, dict[str, Any]]:
    """Batch-fetch closes for many tickers and run _quick_verdict on each.

    Returns {ticker: {price, change_pct, verdict, ...}} or {error} per ticker.
    """
    if not tickers:
        return {}

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for t in tickers:
        u = t.strip().upper()
        if u and u not in seen:
            seen.add(u)
            unique.append(u)

    out: dict[str, dict[str, Any]] = {}
    try:
        df = yf.download(
            tickers=unique,
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Bulk yf.download failed: %s", exc)
        return {t: {"error": f"download failed: {exc}"} for t in unique}

    for t in unique:
        try:
            if len(unique) == 1:
                close = df["Close"] if "Close" in df.columns else None
            else:
                close = df[t]["Close"] if (t in df.columns.get_level_values(0)) else None

            if close is None or close.dropna().empty:
                out[t] = {"error": "no data"}
                continue

            v = _quick_verdict_from_close(close.astype(float))
            out[t] = v
        except Exception as exc:  # noqa: BLE001
            out[t] = {"error": f"compute failed: {exc}"}

    return out


_INSIDER_BUY_TOKENS  = ("buy", "purchase", "acquisition", "acquired")
_INSIDER_SELL_TOKENS = ("sale", "sell", "disposition", "disposed")


def _classify_insider_txn(text: str) -> str | None:
    t = (text or "").lower()
    if any(tok in t for tok in _INSIDER_BUY_TOKENS):
        return "buy"
    if any(tok in t for tok in _INSIDER_SELL_TOKENS):
        return "sell"
    return None


@app.get("/widgets/insider")
def widget_insider(ticker: str):
    """Recent insider transactions for a ticker. Tries FMP first (cleaner
    structured data, but gated to paid plans); falls back to yfinance which
    scrapes Yahoo's insider-transactions table — works without auth."""
    ticker = ticker.strip().upper()
    if not ticker:
        raise HTTPException(400, "Missing ticker.")

    cache_key = ("insider", ticker)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Prefer FMP when available
    if _fmp_enabled():
        try:
            rows = _fmp_get("/insider-trading", {"symbol": ticker, "limit": 25}) or []
            items: list[dict[str, Any]] = []
            for row in rows[:25]:
                if not isinstance(row, dict):
                    continue
                ttype = (row.get("transactionType") or "").strip()
                side = row.get("acquistionOrDisposition") or row.get("acquisitionOrDisposition")
                items.append({
                    "filing_date":      row.get("filingDate"),
                    "transaction_date": row.get("transactionDate"),
                    "name":             row.get("reportingName"),
                    "title":            row.get("typeOfOwner"),
                    "transaction_type": ttype,
                    "side":             "buy" if side == "A" else ("sell" if side == "D" else None),
                    "shares":           row.get("securitiesTransacted"),
                    "price":            row.get("price"),
                    "value":            (row.get("securitiesTransacted") or 0) * (row.get("price") or 0) if isinstance(row.get("securitiesTransacted"), (int, float)) and isinstance(row.get("price"), (int, float)) else None,
                    "shares_owned_after": row.get("securitiesOwned"),
                    "form_type":        row.get("formType"),
                    "link":             row.get("link"),
                })
            result = {"ticker": ticker, "items": items, "source": "fmp"}
            _cache_set(cache_key, result, ttl=43200)
            return result
        except FMPError as exc:
            log.info("FMP insider unavailable for %s (%s); falling back to yfinance", ticker, exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("FMP insider errored for %s: %s; falling back to yfinance", ticker, exc)

    # Fallback: yfinance .insider_transactions
    df = _safe(lambda: yf.Ticker(ticker).insider_transactions)
    items = []
    if isinstance(df, pd.DataFrame) and not df.empty:
        for _, row in df.head(25).iterrows():
            ttype = str(row.get("Transaction") or row.get("Text") or "").strip()
            shares = row.get("Shares")
            value = row.get("Value")
            shares_f = float(shares) if shares is not None and not pd.isna(shares) else None
            value_f = float(value) if value is not None and not pd.isna(value) else None
            price_f = (value_f / shares_f) if (value_f and shares_f) else None
            items.append({
                "filing_date":      _ts_to_iso(row.get("Start Date")),
                "transaction_date": _ts_to_iso(row.get("Start Date")),
                "name":             row.get("Insider"),
                "title":            row.get("Position"),
                "transaction_type": ttype,
                "side":             _classify_insider_txn(ttype),
                "shares":           shares_f,
                "price":            price_f,
                "value":            value_f,
                "shares_owned_after": None,
                "form_type":        None,
                "link":             row.get("URL"),
            })

    result = {"ticker": ticker, "items": items, "source": "yfinance"}
    _cache_set(cache_key, result, ttl=43200)
    return result


# ----- Economic calendar (no free API exists, so we generate it) -----
#
# FOMC dates are hardcoded from the Fed's published schedule. Recurring BLS
# releases (NFP, Jobless Claims, ISM) follow deterministic monthly patterns
# and are computed algorithmically. CPI/PPI/Retail Sales dates aren't
# strictly periodic so they're omitted (better to omit than mislead with a
# date that's a few days off).
#
# Update FOMC_MEETINGS once a year — the Fed publishes the next year's
# schedule around September.

FOMC_MEETINGS = [
    # 2026 — published by the Fed
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
]


def _first_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """First date in (year, month) with the given weekday (0=Mon..6=Sun)."""
    d = date(year, month, 1)
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def _nth_business_day(year: int, month: int, n: int) -> date:
    """Nth business day of the month (n>=1, M-F only, no holiday calendar)."""
    d = date(year, month, 1)
    count = 0
    while True:
        if d.weekday() < 5:
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)


def _generate_economic_events(start: date, days: int = 30) -> list[dict[str, Any]]:
    """US economic-event calendar built from hardcoded FOMC dates + algorithmic
    rules for recurring BLS releases. All times ET → expressed in UTC assuming
    EDT (UTC-4); off by one hour during EST. Good enough for "what day".
    """
    end = start + timedelta(days=days)
    events: list[dict[str, Any]] = []

    def add(d: date, time_utc: str, name: str, impact: str) -> None:
        if start <= d <= end:
            events.append({
                "event":    name,
                "date":     f"{d.isoformat()} {time_utc}",
                "country":  "US",
                "impact":   impact,
                "actual":   None,
                "previous": None,
                "estimate": None,
                "currency": "USD",
            })

    # FOMC meetings — rate decision 2 PM ET (= 18:00 UTC during EDT)
    for ds in FOMC_MEETINGS:
        d = date.fromisoformat(ds)
        add(d, "18:00:00", "FOMC Meeting + Rate Decision", "high")
        # Meeting Minutes released exactly 3 weeks later, also 2 PM ET
        add(d + timedelta(days=21), "18:00:00", "FOMC Meeting Minutes", "medium")

    # Walk every month that overlaps [start, end] and add monthly recurring events
    cur_month = date(start.year, start.month, 1)
    while cur_month <= end:
        y, m = cur_month.year, cur_month.month
        # Employment Situation (NFP) — first Friday at 8:30 AM ET (= 12:30 UTC EDT)
        add(_first_weekday_of_month(y, m, 4), "12:30:00", "Employment Situation (NFP)", "high")
        # ISM Manufacturing PMI — first business day at 10:00 AM ET (= 14:00 UTC)
        add(_nth_business_day(y, m, 1), "14:00:00", "ISM Manufacturing PMI", "medium")
        # ISM Services PMI — third business day at 10:00 AM ET
        add(_nth_business_day(y, m, 3), "14:00:00", "ISM Services PMI", "medium")
        # Next month
        cur_month = (date(y, 12, 1) + timedelta(days=32)).replace(day=1) if m == 12 else date(y, m + 1, 1)

    # Initial Jobless Claims — every Thursday at 8:30 AM ET
    cur = start + timedelta(days=(3 - start.weekday()) % 7)
    while cur <= end:
        add(cur, "12:30:00", "Initial Jobless Claims", "medium")
        cur += timedelta(days=7)

    events.sort(key=lambda x: x["date"])
    return events


@app.get("/widgets/economic")
def widget_economic():
    """Generated US economic calendar for the next 30 days. No upstream API
    needed — FMP gates the real /economic_calendar to paid plans."""
    cache_key = ("economic-static", "us-30d")
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    today = datetime.now(timezone.utc).date()
    items = _generate_economic_events(today, days=30)
    result = {"items": items, "as_of": _now_iso(), "source": "static"}
    _cache_set(cache_key, result, ttl=86400)  # 24 hours
    return result


# Performance horizons in (key, label, trading-days-back) tuples
_PERFORMANCE_HORIZONS: list[tuple[str, str, int]] = [
    ("1d",  "1 day",    1),
    ("1w",  "1 week",   5),
    ("1mo", "1 month",  21),
    ("3mo", "3 months", 63),
    ("6mo", "6 months", 126),
    ("1y",  "1 year",   252),
]


@app.get("/widgets/performance")
def widget_performance(ticker: str):
    """% change at 1d / 1w / 1mo / 3mo / 6mo / 1y in a single response, so the
    user can compare horizons without re-pulling /analyze five times."""
    ticker = ticker.strip().upper()
    if not ticker:
        raise HTTPException(400, "Missing ticker.")

    cache_key = ("performance", ticker)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Pull 2y of bars so the 1-year horizon (252 trading days) is always
    # safely reachable; "1y" period gives ~250 bars which sometimes falls short.
    try:
        df = yf.Ticker(ticker).history(period="2y", interval="1d", auto_adjust=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Failed to fetch data: {exc}") from exc
    if df is None or df.empty:
        raise HTTPException(404, f"No data for '{ticker}'.")

    close = df["Close"].dropna().astype(float)
    if len(close) < 2:
        raise HTTPException(404, f"Insufficient data for '{ticker}'.")

    last_price = float(close.iloc[-1])

    periods: list[dict[str, Any]] = []
    for key, label, bars in _PERFORMANCE_HORIZONS:
        if len(close) <= bars:
            periods.append({"key": key, "label": label, "change_pct": None,
                            "change_abs": None, "from_price": None})
            continue
        from_price = float(close.iloc[-bars - 1])
        change_abs = last_price - from_price
        change_pct = (change_abs / from_price * 100) if from_price else None
        periods.append({
            "key": key,
            "label": label,
            "change_pct": change_pct,
            "change_abs": change_abs,
            "from_price": from_price,
        })

    result = {
        "ticker": ticker,
        "price": last_price,
        "periods": periods,
        "as_of": _now_iso(),
    }
    _cache_set(cache_key, result, ttl=300)  # 5 min
    return result


@app.get("/search")
def search(q: str, limit: int = 8):
    """Company-name / ticker search. FMP-powered; degrades to empty results
    + a message if FMP isn't configured or rejects the query."""
    q = (q or "").strip()
    if not q:
        return {"results": [], "source": "none"}
    limit = max(1, min(int(limit), 20))

    cache_key = ("search", q.lower(), limit)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if not _fmp_enabled():
        return {"results": [], "source": "none", "message": "Search requires FMP_API_KEY"}

    try:
        rows = _fmp_get("/search", {"query": q, "limit": limit}) or []
    except FMPError as exc:
        return {"results": [], "source": "none", "message": str(exc)}

    results: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        results.append({
            "symbol":   row.get("symbol"),
            "name":     row.get("name"),
            "exchange": row.get("exchangeShortName") or row.get("stockExchange"),
            "currency": row.get("currency"),
        })

    result = {"results": results, "source": "fmp"}
    _cache_set(cache_key, result, ttl=1800)  # 30 min
    return result


@app.get("/movers")
def movers():
    """Market overview: today's gainers / losers / most active, technical
    signals scanned across our sector universe, and upcoming earnings."""
    cache_key = ("movers",)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # 1) Today's movers from FMP
    gainers: list[dict[str, Any]] = []
    losers: list[dict[str, Any]] = []
    actives: list[dict[str, Any]] = []

    if _fmp_enabled():
        for target, endpoint in [(gainers, "/stock_market/gainers"),
                                  (losers,  "/stock_market/losers"),
                                  (actives, "/stock_market/actives")]:
            try:
                rows = _fmp_get(endpoint) or []
                for row in rows[:10]:
                    if not isinstance(row, dict):
                        continue
                    target.append({
                        "symbol":     row.get("symbol"),
                        "name":       row.get("name"),
                        "price":      row.get("price"),
                        "change_pct": row.get("changesPercentage"),
                        "change_abs": row.get("change"),
                    })
            except Exception as exc:  # noqa: BLE001
                log.warning("FMP %s failed: %s", endpoint, exc)

    # 2) Technical signals scan across our sector universe (~165 stocks)
    universe = sorted({c for sec in SECTORS for c in sec["components"]})
    scored = _score_tickers_bulk(universe, period="1y")

    signals: dict[str, list[dict[str, Any]]] = {
        "oversold":        [],
        "overbought":      [],
        "macd_cross_up":   [],
        "macd_cross_down": [],
        "golden_cross":    [],
        "death_cross":     [],
    }

    for t, v in scored.items():
        if "error" in v:
            continue
        ind = v.get("indicators", {}) or {}
        rsi = ind.get("RSI")
        common = {
            "symbol":     t,
            "price":      v.get("price"),
            "change_pct": v.get("change_pct"),
            "rsi":        rsi,
            "verdict":    v.get("verdict"),
        }
        if rsi is not None:
            if rsi <= 30:
                signals["oversold"].append(common)
            elif rsi >= 70:
                signals["overbought"].append(common)
        mc = v.get("macd_cross")
        if mc == "up":
            signals["macd_cross_up"].append(common)
        elif mc == "down":
            signals["macd_cross_down"].append(common)
        mac = v.get("ma_cross")
        if mac == "golden":
            signals["golden_cross"].append(common)
        elif mac == "death":
            signals["death_cross"].append(common)

    # Sort signals by extremity / score
    signals["oversold"].sort(key=lambda x: (x.get("rsi") or 100))
    signals["overbought"].sort(key=lambda x: -(x.get("rsi") or 0))
    for k in ("macd_cross_up", "macd_cross_down", "golden_cross", "death_cross"):
        signals[k].sort(key=lambda x: (x.get("change_pct") or 0), reverse=(k.endswith("_up") or k == "golden_cross"))

    # 3) Upcoming earnings within the next 7 days for our universe
    earnings: list[dict[str, Any]] = []
    if _fmp_enabled():
        today = datetime.now(timezone.utc).date()
        next_week = today + timedelta(days=7)
        try:
            rows = _fmp_get("/earning_calendar", {
                "from": today.isoformat(),
                "to":   next_week.isoformat(),
            }) or []
            uni_set = set(universe) | {sec["etf"] for sec in SECTORS}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                sym = row.get("symbol")
                if sym not in uni_set:
                    continue
                earnings.append({
                    "symbol":           sym,
                    "date":             row.get("date"),
                    "time":             row.get("time"),
                    "eps_estimate":     row.get("epsEstimated"),
                    "revenue_estimate": row.get("revenueEstimated"),
                })
            earnings.sort(key=lambda x: (x.get("date") or "", x.get("symbol") or ""))
        except FMPError as exc:
            log.info("FMP /earning_calendar unavailable: %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("FMP earnings calendar errored: %s", exc)

    result = {
        "gainers":  gainers,
        "losers":   losers,
        "actives":  actives,
        "signals":  signals,
        "earnings": earnings,
        "universe_size": len(universe),
        "as_of": _now_iso(),
    }
    _cache_set(cache_key, result, ttl=600)  # 10 min
    return result


@app.get("/watchlist")
def watchlist(tickers: str):
    """Score a list of tickers cheaply for the Watchlist tab.

    Query param: tickers=AAPL,MSFT,NVDA  (max 50)
    Returns: { items: [ {ticker, name, price, change_pct, verdict, ...}, ... ], as_of }
    """
    raw = [t.strip().upper() for t in (tickers or "").split(",") if t.strip()]
    if not raw:
        raise HTTPException(400, "Provide at least one ticker.")
    if len(raw) > 50:
        raise HTTPException(400, "Max 50 tickers per request.")

    cache_key = ("watchlist", tuple(sorted(raw)))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    scored = _score_tickers_bulk(raw, period="3mo")

    # Best-effort name + sector enrichment — yfinance caches .info per
    # Ticker instance, so we only pay the network round-trip once per
    # ticker. Don't fail the whole request if one lookup blows up.
    def _info_pair(tk: str) -> tuple[str | None, str | None]:
        info = yf.Ticker(tk).info or {}
        return (
            info.get("shortName") or info.get("longName"),
            info.get("sector"),
        )

    items: list[dict[str, Any]] = []
    for t in raw:
        v = scored.get(t, {})
        if "error" in v:
            items.append({"ticker": t, "error": v["error"]})
            continue
        name, sector = _safe(lambda t=t: _info_pair(t), default=(None, None))
        items.append({
            "ticker": t,
            "name": name,
            "sector": sector,
            "price": v.get("price"),
            "prev_close": v.get("prev_close"),
            "change_pct": v.get("change_pct"),
            "change_abs": v.get("change_abs"),
            "change_pct_1w": v.get("change_pct_1w"),
            "change_pct_1mo": v.get("change_pct_1mo"),
            "verdict": v.get("verdict"),
            "score": v.get("score"),
        })

    result = {"items": items, "as_of": _now_iso()}
    _cache_set(cache_key, result, ttl=120)  # 2 min — markets move
    return result


@app.get("/sectors")
def sectors():
    """Sector overview: 11 sector ETFs as headlines + top components per sector.

    Heavy: ~225 tickers per cache miss; aggressively cached for 15 min.
    """
    cache_key = ("sectors",)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    all_tickers: list[str] = []
    for sec in SECTORS:
        all_tickers.append(sec["etf"])
        all_tickers.extend(sec["components"])

    scored = _score_tickers_bulk(all_tickers, period="3mo")

    # Optional: overlay FMP's authoritative live intraday sector % on the
    # ETF headlines. Our yfinance bars give yesterday-close-vs-day-before,
    # not today's intraday move. FMP /sectors-performance is one cheap call.
    fmp_sector_pct: dict[str, float] = {}
    if _fmp_enabled():
        try:
            rows = _fmp_get("/sectors-performance") or []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = (row.get("sector") or "").strip()
                pct_str = (row.get("changesPercentage") or "").strip().rstrip("%")
                try:
                    fmp_sector_pct[name] = float(pct_str)
                except (TypeError, ValueError):
                    pass
        except Exception as exc:  # noqa: BLE001
            log.warning("FMP /sectors-performance failed: %s", exc)

    sectors_out: list[dict[str, Any]] = []
    for sec in SECTORS:
        etf_v = scored.get(sec["etf"], {})
        components_out: list[dict[str, Any]] = []
        for c in sec["components"]:
            cv = scored.get(c, {})
            if "error" in cv:
                continue
            components_out.append({
                "ticker": c,
                "price": cv.get("price"),
                "change_pct": cv.get("change_pct"),
                "verdict": cv.get("verdict"),
                "score": cv.get("score"),
            })

        # Sector tally — how the components break down
        tally = {"bullish": 0, "lean-bullish": 0, "neutral": 0, "lean-bearish": 0, "bearish": 0}
        for c in components_out:
            v = c.get("verdict")
            if v in tally:
                tally[v] += 1

        # Prefer FMP's live intraday sector % when available (more current than
        # our daily-bar computed change). Yfinance number stays as fallback.
        live_pct = fmp_sector_pct.get(sec["name"])

        sectors_out.append({
            "name": sec["name"],
            "etf": {
                "ticker": sec["etf"],
                "price": etf_v.get("price"),
                "change_pct": live_pct if live_pct is not None else etf_v.get("change_pct"),
                "change_pct_source": "fmp-live" if live_pct is not None else "yfinance-eod",
                "verdict": etf_v.get("verdict"),
            } if "error" not in etf_v else {"ticker": sec["etf"], "error": etf_v.get("error")},
            "components": components_out,
            "tally": tally,
        })

    result = {"sectors": sectors_out, "as_of": _now_iso()}
    _cache_set(cache_key, result, ttl=900)  # 15 min
    return result


# ----------------------------- AI chat (OpenRouter) -----------------------------
#
# Lightweight proxy to openrouter.ai chat completions API with SSE streaming.
# Builds a system prompt that grounds the LLM in everything we know about the
# active ticker (technicals + fundamentals + news/reddit sentiment).

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
DEFAULT_AI_MODEL = "anthropic/claude-sonnet-4"
ALLOWED_AI_MODELS = {
    "anthropic/claude-sonnet-4",
    "anthropic/claude-3.5-sonnet",
    "anthropic/claude-haiku-4",
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "google/gemini-2.0-flash-001",
    "meta-llama/llama-3.3-70b-instruct:free",
    "x-ai/grok-2-1212",
}


def _openrouter_enabled() -> bool:
    return bool(OPENROUTER_API_KEY)


def _build_ai_context_for_ticker(ticker: str) -> str:
    """Build a markdown-style context block summarizing everything we know
    about a ticker. Best-effort — each section degrades independently so a
    failure in (say) Reddit doesn't blank out the rest of the context."""
    ticker = ticker.strip().upper()
    if not ticker:
        return ""

    lines: list[str] = [f"# Stock data: {ticker}\n"]

    # Technical analysis (verdict + paragraph + bullets + key indicators)
    try:
        result = analyze(AnalyzeRequest(ticker=ticker, period="3mo"))
        s = result["summary"]
        ind = result["indicators"]
        lines.append("## Technical analysis (3-month read)")
        lines.append(f"- Verdict: **{s['verdict']}**")
        lines.append(f"- Summary: {s['paragraph']}")
        lines.append("- Indicators:")
        ind_keys = [
            ("price", "Price", "{:.2f}"),
            ("SMA20", "SMA20", "{:.2f}"),
            ("SMA50", "SMA50", "{:.2f}"),
            ("SMA200", "SMA200", "{:.2f}"),
            ("RSI", "RSI(14)", "{:.1f}"),
            ("MACD", "MACD", "{:.3f}"),
            ("MACD_signal", "MACD signal", "{:.3f}"),
            ("BB_upper", "BB upper", "{:.2f}"),
            ("BB_lower", "BB lower", "{:.2f}"),
            ("support", "Support (period low)", "{:.2f}"),
            ("resistance", "Resistance (period high)", "{:.2f}"),
            ("SMA20_slope_pct", "SMA20 slope (% / bar)", "{:.3f}"),
        ]
        for k, label, fmt in ind_keys:
            v = ind.get(k)
            if v is not None:
                try:
                    lines.append(f"  - {label}: {fmt.format(v)}")
                except (TypeError, ValueError):
                    lines.append(f"  - {label}: {v}")
        lines.append("- Signal bullets:")
        for b in s.get("bullets", []):
            lines.append(f"  - [{b.get('tone')}] {b.get('label')}: {b.get('text')}")
        lines.append("")
    except Exception as exc:  # noqa: BLE001
        log.info("AI context: analyze failed for %s: %s", ticker, exc)

    # Fundamentals
    try:
        result = widget_fundamentals(ticker)
        data = result.get("data", {}) or {}
        lines.append("## Fundamentals")
        for key, label in [
            ("longName", "Company"), ("sector", "Sector"), ("industry", "Industry"),
            ("marketCap", "Market cap"), ("trailingPE", "P/E (TTM)"),
            ("forwardPE", "Forward P/E"), ("trailingEps", "EPS (TTM)"),
            ("dividendYield", "Dividend yield (%)"),
            ("beta", "Beta"),
            ("fiftyTwoWeekLow", "52w low"), ("fiftyTwoWeekHigh", "52w high"),
            ("fiftyDayAverage", "50-day avg"), ("twoHundredDayAverage", "200-day avg"),
            ("averageVolume", "Avg volume (20d)"),
        ]:
            v = data.get(key)
            if v is not None:
                lines.append(f"- {label}: {v}")
        lines.append("")
    except Exception as exc:  # noqa: BLE001
        log.info("AI context: fundamentals failed for %s: %s", ticker, exc)

    # News + sentiment
    try:
        result = widget_news(ticker)
        agg = result.get("sentiment") or {}
        items = result.get("items", []) or []
        if items:
            lines.append("## Recent news headlines")
            if agg:
                lines.append(
                    f"- Aggregate sentiment: **{agg.get('label')}** "
                    f"(mean compound score {agg.get('mean_compound', 0):+.2f}; "
                    f"{agg.get('positive', 0)} pos / {agg.get('neutral', 0)} neu / "
                    f"{agg.get('negative', 0)} neg across {agg.get('total', 0)} items)"
                )
            for it in items[:8]:
                s = it.get("sentiment") or {}
                lab = s.get("label", "neutral") if s else "neutral"
                lines.append(f"- [{lab}] {it.get('title', '').strip()} ({it.get('source', '').strip()})")
            lines.append("")
    except Exception as exc:  # noqa: BLE001
        log.info("AI context: news failed for %s: %s", ticker, exc)

    # Reddit + sentiment (may be unavailable without OAuth — that's fine)
    try:
        result = widget_reddit(ticker)
        agg = result.get("sentiment") or {}
        posts = result.get("posts", []) or []
        if posts:
            lines.append("## Reddit chatter")
            if agg:
                lines.append(
                    f"- Aggregate sentiment: **{agg.get('label')}** "
                    f"({agg.get('positive', 0)} pos / {agg.get('neutral', 0)} neu / "
                    f"{agg.get('negative', 0)} neg across {agg.get('total', 0)} posts)"
                )
            for p in posts[:8]:
                s = p.get("sentiment") or {}
                lab = s.get("label", "neutral") if s else "neutral"
                lines.append(
                    f"- [{lab}] r/{p.get('subreddit')}: {p.get('title')} "
                    f"(▲{p.get('score', 0)}, 💬{p.get('num_comments', 0)})"
                )
            lines.append("")
    except Exception:  # noqa: BLE001
        pass

    return "\n".join(lines)


_AI_SYSTEM_PREFIX = (
    "You are a financial analyst helping a user understand a stock. Below "
    "is the data we've gathered about the ticker they're asking about. "
    "Use it to answer their questions clearly and specifically.\n\n"
    "Guidelines:\n"
    "- Be concrete: cite the actual indicator values, sentiment, and headlines from the data.\n"
    "- If something isn't in the data, say so plainly — don't guess at recent news, "
    "  earnings results, or analyst targets you weren't given.\n"
    "- You are not giving investment advice. You're helping the user *interpret* signals.\n"
    "- Keep responses concise and structured (markdown is fine).\n"
    "- It's OK to disagree with the verdict label if the underlying signals tell a different story.\n\n"
)


@app.post("/ai/chat")
async def ai_chat(req: Request):
    """Proxy to OpenRouter chat completions with SSE streaming.

    Body: { ticker?: str, model?: str, messages: [{role, content}, ...] }
    """
    if not _openrouter_enabled():
        raise HTTPException(503, "AI chat requires OPENROUTER_API_KEY env var.")

    try:
        body = await req.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Invalid JSON body: {exc}") from exc

    ticker = (body.get("ticker") or "").strip().upper()
    model = (body.get("model") or DEFAULT_AI_MODEL).strip()
    user_messages = body.get("messages") or []

    if model not in ALLOWED_AI_MODELS:
        raise HTTPException(400, f"Model not allowed. Pick one of: {sorted(ALLOWED_AI_MODELS)}")
    if not isinstance(user_messages, list) or not user_messages:
        raise HTTPException(400, "messages must be a non-empty array")
    if len(user_messages) > 30:
        user_messages = user_messages[-30:]

    # Validate / cap each message
    cleaned: list[dict[str, Any]] = []
    for m in user_messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        if len(content) > 8000:
            content = content[:8000]
        cleaned.append({"role": role, "content": content})
    if not cleaned:
        raise HTTPException(400, "no valid messages")

    # Build system prompt with ticker context
    context_block = _build_ai_context_for_ticker(ticker) if ticker else ""
    system_content = _AI_SYSTEM_PREFIX + (context_block or "(No ticker selected — answer general questions only.)")

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_content}] + cleaned,
        "stream": True,
        "max_tokens": 2000,
        "temperature": 0.4,
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        # OpenRouter asks for these for analytics + per-app routing
        "HTTP-Referer": "https://stock-ticker-analysis.onrender.com",
        "X-Title": "Ticker Tracker",
    }

    def stream():
        try:
            with requests.post(
                f"{OPENROUTER_BASE}/chat/completions",
                headers=headers,
                json=payload,
                stream=True,
                timeout=120,
            ) as r:
                if r.status_code != 200:
                    try:
                        body = r.json()
                        err_msg = body.get("error", {}).get("message") or body.get("message") or r.text[:300]
                    except Exception:  # noqa: BLE001
                        err_msg = r.text[:300]
                    err = json.dumps({"error": f"OpenRouter HTTP {r.status_code}: {err_msg}"})
                    yield f"data: {err}\n\n".encode("utf-8")
                    yield b"data: [DONE]\n\n"
                    return

                for raw in r.iter_lines(decode_unicode=False):
                    if raw is None:
                        continue
                    if not raw:
                        # blank line — SSE event separator
                        yield b"\n"
                        continue
                    # Pass the SSE line through verbatim, plus the required blank line
                    yield raw + b"\n\n"
        except Exception as exc:  # noqa: BLE001
            err = json.dumps({"error": str(exc)})
            yield f"data: {err}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",  # disable nginx buffering if any
    })


@app.get("/debug/data")
def debug_data(ticker: str = "AAPL"):
    """One-shot diagnostic: probes FMP + yfinance and returns status + raw
    error bodies so we can tell whether the issue is the API key, the
    endpoint path, the plan tier, or yfinance being blocked from this IP."""
    ticker = ticker.strip().upper() or "AAPL"
    out: dict[str, Any] = {
        "ticker": ticker,
        "fmp_api_key_set": bool(FMP_API_KEY),
        "fmp_api_key_length": len(FMP_API_KEY) if FMP_API_KEY else 0,
        "openrouter_set": _openrouter_enabled(),
    }

    # FMP probe — hit /profile directly with raw HTTP to capture the body
    if FMP_API_KEY:
        try:
            r = requests.get(
                f"{FMP_BASE}/profile/{ticker}",
                params={"apikey": FMP_API_KEY},
                timeout=10,
            )
            body_preview = r.text[:500]
            try:
                parsed = r.json()
                if isinstance(parsed, list) and parsed:
                    parsed_summary = f"list of {len(parsed)} item(s); first={list(parsed[0].keys())[:5]}…"
                elif isinstance(parsed, dict):
                    parsed_summary = f"dict; keys={list(parsed.keys())[:8]}"
                else:
                    parsed_summary = str(type(parsed))
            except Exception:  # noqa: BLE001
                parsed_summary = "non-JSON response"
            out["fmp"] = {
                "endpoint":   f"/profile/{ticker}",
                "http":       r.status_code,
                "parsed":     parsed_summary,
                "body":       body_preview,
            }
        except Exception as exc:  # noqa: BLE001
            out["fmp"] = {"error": str(exc)}

        # Also try /quote since that's where PE/EPS come from
        try:
            r = requests.get(
                f"{FMP_BASE}/quote/{ticker}",
                params={"apikey": FMP_API_KEY},
                timeout=10,
            )
            out["fmp_quote"] = {
                "http": r.status_code,
                "body_preview": r.text[:300],
            }
        except Exception as exc:  # noqa: BLE001
            out["fmp_quote"] = {"error": str(exc)}
    else:
        out["fmp"] = {"error": "FMP_API_KEY env var not set"}

    # yfinance probe — .info often returns empty on Render's datacenter IP
    try:
        info = yf.Ticker(ticker).info or {}
        out["yfinance_info"] = {
            "keys_returned": len(info),
            "has_PE":     info.get("trailingPE") is not None,
            "has_EPS":    info.get("trailingEps") is not None,
            "has_beta":   info.get("beta") is not None,
            "has_divYield": info.get("dividendYield") is not None,
            "name":       info.get("longName") or info.get("shortName"),
        }
    except Exception as exc:  # noqa: BLE001
        out["yfinance_info"] = {"error": str(exc)}

    # fast_info as fallback indicator
    try:
        fi = yf.Ticker(ticker).fast_info
        out["yfinance_fast_info"] = {
            "last_price":  getattr(fi, "last_price", None),
            "market_cap":  getattr(fi, "market_cap", None),
            "year_high":   getattr(fi, "year_high", None),
        }
    except Exception as exc:  # noqa: BLE001
        out["yfinance_fast_info"] = {"error": str(exc)}

    return out


@app.get("/ai/models")
def ai_models():
    """Expose the curated allow-list so the frontend doesn't have to hardcode it."""
    return {
        "default": DEFAULT_AI_MODEL,
        "models": sorted(ALLOWED_AI_MODELS),
        "enabled": _openrouter_enabled(),
    }


# ----------------------------- Purgatory Method alerts -----------------------------
#
# Intraday 4-minute strategy from Reddit:
#   CALL = 5 EMA above 9 EMA AND both above VWAP AND both above 30 EMA
#   PUT  = inverse
# Fires only on a *fresh* cross — the previous closed bar did NOT meet the
# condition, the current closed bar does. Stops repeated alerts during sustained
# trends.
#
# Data: Alpaca IEX feed (free real-time for one major exchange).
# Notify: Slack incoming webhook.
# Schedule: external cron pings /purgatory/scan every 4 min during market hours.

ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "").strip()
ALPACA_API_SECRET = os.environ.get("ALPACA_API_SECRET", "").strip()
ALPACA_DATA_BASE = "https://data.alpaca.markets/v2"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "").strip()

PURGATORY_FILE = Path(__file__).parent / "purgatory_state.json"
_purgatory_lock = threading.Lock()
_purgatory_signals: list[dict[str, Any]] = []   # last ~100 signals (in-memory)
_purgatory_alerted: dict[tuple, float] = {}      # (ticker, signal, bar_ts) → fired_at
_PURGATORY_MAX_SIGNALS = 100


def _alpaca_enabled() -> bool:
    return bool(ALPACA_API_KEY and ALPACA_API_SECRET)


def _slack_enabled() -> bool:
    return bool(SLACK_WEBHOOK_URL)


_PURGATORY_TABLE = "purgatory_watchlist"


def _load_purgatory_state() -> set[str]:
    """Load the persisted watchlist. Tries Supabase first (survives Render
    redeploys); falls back to JSON file on disk (lost on redeploy)."""
    if _supabase_client is not None:
        try:
            res = (
                _supabase_client.table(_PURGATORY_TABLE)
                .select("ticker")
                .execute()
            )
            tickers = {
                row["ticker"]
                for row in (res.data or [])
                if isinstance(row, dict) and isinstance(row.get("ticker"), str)
            }
            log.info("Purgatory watchlist: loaded %d tickers from Supabase", len(tickers))
            return tickers
        except Exception as exc:  # noqa: BLE001
            log.warning("Supabase purgatory load failed (%s); falling back to JSON", exc)

    # Fallback: local JSON file
    if not PURGATORY_FILE.exists():
        return set()
    try:
        data = json.loads(PURGATORY_FILE.read_text())
        return set(x for x in data.get("watchlist", []) if isinstance(x, str))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_purgatory_state(watchlist: set[str]) -> None:
    """Persist the watchlist. Writes to Supabase when configured (the
    durable path) and also to the JSON file as a local cache. Full
    replace each time — the set is small (< ~50 tickers in practice)."""
    if _supabase_client is not None:
        try:
            # Delete everything then re-insert. Supabase requires a filter
            # on delete; the .neq trick matches every row.
            _supabase_client.table(_PURGATORY_TABLE).delete().neq("ticker", "").execute()
            if watchlist:
                rows = [{"ticker": t} for t in sorted(watchlist)]
                _supabase_client.table(_PURGATORY_TABLE).insert(rows).execute()
        except Exception as exc:  # noqa: BLE001
            log.warning("Supabase purgatory save failed (%s); JSON fallback only", exc)

    # Always also write to JSON — cheap and gives a local cache that
    # works even if Supabase is briefly unreachable on the next read.
    try:
        PURGATORY_FILE.write_text(json.dumps({"watchlist": sorted(watchlist)}, indent=2))
    except OSError as exc:
        log.warning("Local purgatory JSON write failed: %s", exc)


def _fetch_alpaca_bars(symbols: list[str], timeframe: str = "4Min", lookback_hours: int = 12) -> dict[str, list[dict]]:
    """Fetch recent bars for multiple symbols in one request. Returns
    {ticker: [bar, ...]} where each bar has t, o, h, l, c, v, vw.

    Uses IEX feed which is free on Alpaca's basic plan and gives real-time
    data (one exchange, not SIP, but enough for liquid names like SPY/AVGO/TSLA)."""
    if not _alpaca_enabled():
        raise RuntimeError("ALPACA_API_KEY / ALPACA_API_SECRET not set")
    if not symbols:
        return {}

    start = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
    headers = {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_API_SECRET,
    }
    params = {
        "symbols": ",".join(symbols),
        "timeframe": timeframe,
        "start": start,
        "feed": "iex",
        "limit": "10000",
    }

    r = requests.get(f"{ALPACA_DATA_BASE}/stocks/bars", headers=headers, params=params, timeout=15)
    r.raise_for_status()
    body = r.json() or {}
    bars_by_sym = body.get("bars") or {}
    out: dict[str, list[dict]] = {}
    for sym in symbols:
        out[sym] = bars_by_sym.get(sym) or []
    return out


# Filter thresholds (env-overridable so we can tighten/loosen without redeploy)
# Default raised 0.05 → 0.10 after one week of data showed signals with
# breakout depth < 0.10% had only 32% win rate vs 49% for 0.10-0.20%.
PURGATORY_MIN_BREAKOUT_PCT = float(os.environ.get("PURGATORY_MIN_BREAKOUT_PCT", "0.10"))   # %
PURGATORY_TREND_FILTER_PCT = float(os.environ.get("PURGATORY_TREND_FILTER_PCT", "0.5"))    # %

# Time-of-day windows in ET. Three windows showed consistently bad outcomes
# in the data (open-noise, lunch-chop, end-of-day-chaos) so we skip them.
_CHOP_WINDOWS = {"open_first_15", "lunch_chop", "close_chop"}

# Auto-disable thresholds for (ticker, direction) pairs
_AUTO_DISABLE_MIN_N = 10
_AUTO_DISABLE_MAX_WIN_RATE = 30.0     # %
_AUTO_DISABLE_MIN_AVG_FAV = -0.20     # %  (any pair worse than this avg is disabled)


def _bar_window_category(bar_time_iso: str) -> str:
    """Classify a bar close time into a session window. Used both to filter
    out chop-zone signals and to annotate Slack alerts with the context."""
    try:
        bt = pd.Timestamp(bar_time_iso).tz_convert("America/New_York")
    except Exception:  # noqa: BLE001
        return "unknown"
    mins = bt.hour * 60 + bt.minute
    if mins < 570:        return "pre_market"          # before 9:30 ET
    if mins < 585:        return "open_first_15"       # 9:30 - 9:45 (chop)
    if mins < 600:        return "open_settle"         # 9:45 - 10:00
    if mins < 660:        return "prime_morning"       # 10:00 - 11:00 ⭐ 76% wr in data
    if mins < 690:        return "pre_lunch"           # 11:00 - 11:30
    if mins < 750:        return "lunch_chop"          # 11:30 - 12:30 (chop, 18% wr)
    if mins < 840:        return "post_lunch"          # 12:30 - 14:00
    if mins < 900:        return "prime_afternoon"     # 14:00 - 15:00 ⭐ 67% wr
    if mins < 915:        return "pre_close"           # 15:00 - 15:15
    if mins < 960:        return "close_chop"          # 15:15 - 16:00 (chop, 25% wr)
    return "after_hours"


_PRIME_WINDOWS = {"prime_morning", "prime_afternoon"}

_WINDOW_LABELS = {
    "pre_market":       "pre-market",
    "open_first_15":    "9:30–9:45 ET open",
    "open_settle":      "9:45–10:00 ET settle",
    "prime_morning":    "10:00–11:00 ET",
    "pre_lunch":        "11:00–11:30 ET",
    "lunch_chop":       "11:30–12:30 ET lunch",
    "post_lunch":       "12:30–14:00 ET",
    "prime_afternoon":  "14:00–15:00 ET",
    "pre_close":        "15:00–15:15 ET",
    "close_chop":       "15:15–16:00 ET close",
    "after_hours":      "after hours",
    "unknown":          "unknown",
}


def _window_label(w: str) -> str:
    return _WINDOW_LABELS.get(w, w)


# Disabled-pairs cache. Recomputed every N minutes (cheap query).
_disabled_pairs_cache: tuple[float, set[tuple[str, str]]] = (0.0, set())
_DISABLED_CACHE_TTL = 600  # 10 min


def _get_disabled_pairs() -> set[tuple[str, str]]:
    """Return (ticker, direction) pairs that consistently underperform over
    the last 30 days. Cached for 10 min so we don't re-query Supabase on
    every scan. Pairs are disabled when N >= 10 scored signals AND
    (win_rate <= 30% OR avg_favorable_15m < -0.20%)."""
    global _disabled_pairs_cache
    now = time.time()
    last_ts, last_val = _disabled_pairs_cache
    if now - last_ts < _DISABLED_CACHE_TTL:
        return last_val
    if _supabase_client is None:
        _disabled_pairs_cache = (now, set())
        return set()
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        res = (
            _supabase_client.table(_PURGATORY_SIGNALS_TABLE)
            .select("ticker, signal, outcome, favorable_15m")
            .gte("bar_time", since)
            .not_.is_("outcome", "null")
            .execute()
        )
        rows = list(res.data or [])
    except Exception as exc:  # noqa: BLE001
        log.warning("Disabled-pairs query failed: %s", exc)
        _disabled_pairs_cache = (now, set())
        return set()

    buckets: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        k = (r.get("ticker"), r.get("signal"))
        if not all(k):
            continue
        buckets.setdefault(k, []).append(r)

    disabled: set[tuple[str, str]] = set()
    for key, group in buckets.items():
        if len(group) < _AUTO_DISABLE_MIN_N:
            continue
        wins = sum(1 for r in group if r.get("outcome") == "win")
        win_rate = wins / len(group) * 100.0
        f15s = [float(r["favorable_15m"]) for r in group if r.get("favorable_15m") is not None]
        avg_fav = sum(f15s) / len(f15s) if f15s else 0.0
        if win_rate <= _AUTO_DISABLE_MAX_WIN_RATE or avg_fav < _AUTO_DISABLE_MIN_AVG_FAV:
            disabled.add(key)

    _disabled_pairs_cache = (now, disabled)
    return disabled


def _check_purgatory_signal(ticker: str, bars: list[dict]) -> dict[str, Any] | None:
    """Detect a fresh Purgatory CALL or PUT signal on the latest closed bar.

    Conditions (CALL):
      ema5 > ema9 AND ema5 > vwap AND ema5 > ema30
                  AND ema9 > vwap AND ema9 > ema30
    PUT is the inverse. "Fresh" = previous bar did NOT satisfy the condition.

    Two extra filters applied on top of the raw condition (added after day-1
    retro showed ~44% of signals were noise during chop):

      • Breakout-depth filter: require |EMA5 − nearest opposing line
        (VWAP / EMA30)| / price >= PURGATORY_MIN_BREAKOUT_PCT. Kills signals
        where all four lines are clustered within a few cents.

      • Trend filter: skip CALL if the day's net move (open → current close)
        is below −PURGATORY_TREND_FILTER_PCT. Skip PUT if above
        +PURGATORY_TREND_FILTER_PCT. Don't fade strong one-way days.

    VWAP is intraday-only (resets each day). EMAs use the whole window so
    they're well-converged."""
    if not bars or len(bars) < 31:
        return None

    df = pd.DataFrame(bars)
    if df.empty:
        return None
    df["t"] = pd.to_datetime(df["t"], utc=True)
    df = df.sort_values("t").reset_index(drop=True)
    df["c"] = df["c"].astype(float)
    df["h"] = df["h"].astype(float)
    df["l"] = df["l"].astype(float)
    df["v"] = df["v"].astype(float)

    # EMAs across the whole window — gives stable values
    df["ema5"]  = df["c"].ewm(span=5,  adjust=False).mean()
    df["ema9"]  = df["c"].ewm(span=9,  adjust=False).mean()
    df["ema30"] = df["c"].ewm(span=30, adjust=False).mean()

    # Intraday VWAP — group by trading day, cumulative sum within each day.
    # Uses ET to define the day so a 9:30 ET open isn't split across UTC days.
    et_t = df["t"].dt.tz_convert("America/New_York")
    df["date"] = et_t.dt.date
    typ_price = (df["h"] + df["l"] + df["c"]) / 3
    df["tpv"] = typ_price * df["v"]
    df["cum_tpv"] = df.groupby("date")["tpv"].cumsum()
    df["cum_v"] = df.groupby("date")["v"].cumsum()
    df["vwap"] = df["cum_tpv"] / df["cum_v"].replace(0, np.nan)

    today_date = df["date"].iloc[-1]
    today_bars = df[df["date"] == today_date].reset_index(drop=True)
    if len(today_bars) < 2:
        return None

    prev = today_bars.iloc[-2]
    cur = today_bars.iloc[-1]

    def is_call(b: pd.Series) -> bool:
        try:
            return bool(
                b["ema5"] > b["ema9"]
                and b["ema5"] > b["vwap"] and b["ema5"] > b["ema30"]
                and b["ema9"] > b["vwap"] and b["ema9"] > b["ema30"]
            )
        except (TypeError, ValueError):
            return False

    def is_put(b: pd.Series) -> bool:
        try:
            return bool(
                b["ema5"] < b["ema9"]
                and b["ema5"] < b["vwap"] and b["ema5"] < b["ema30"]
                and b["ema9"] < b["vwap"] and b["ema9"] < b["ema30"]
            )
        except (TypeError, ValueError):
            return False

    signal_type: str | None = None
    if is_call(cur) and not is_call(prev):
        signal_type = "call"
    elif is_put(cur) and not is_put(prev):
        signal_type = "put"
    if not signal_type:
        return None

    cur_price = float(cur["c"])
    cur_ema5  = float(cur["ema5"])
    cur_ema30 = float(cur["ema30"])
    cur_vwap  = float(cur["vwap"])

    # --- Filter B: breakout depth ---
    # For CALL: how far is EMA5 above the highest "purgatory line" (VWAP/EMA30)?
    # For PUT: how far below the lowest? Express as % of current price.
    if signal_type == "call":
        opposing = max(cur_vwap, cur_ema30)
        depth_pct = (cur_ema5 - opposing) / cur_price * 100.0
    else:  # put
        opposing = min(cur_vwap, cur_ema30)
        depth_pct = (opposing - cur_ema5) / cur_price * 100.0

    if depth_pct < PURGATORY_MIN_BREAKOUT_PCT:
        log.info("Purgatory filter (%s): breakout depth %.3f%% < %.3f%% threshold — skipping",
                 ticker, depth_pct, PURGATORY_MIN_BREAKOUT_PCT)
        return None

    # --- Filter E: trend filter ---
    # Skip CALL if day is clearly down; skip PUT if day is clearly up.
    day_open = float(today_bars.iloc[0]["o"])
    day_move_pct = (cur_price - day_open) / day_open * 100.0 if day_open else 0.0
    if signal_type == "call" and day_move_pct < -PURGATORY_TREND_FILTER_PCT:
        log.info("Purgatory filter (%s CALL): day move %.2f%% too bearish — skipping",
                 ticker, day_move_pct)
        return None
    if signal_type == "put" and day_move_pct > PURGATORY_TREND_FILTER_PCT:
        log.info("Purgatory filter (%s PUT): day move %.2f%% too bullish — skipping",
                 ticker, day_move_pct)
        return None

    bar_time_iso = cur["t"].isoformat()

    # --- Filter: time-of-day chop windows ---
    window = _bar_window_category(bar_time_iso)
    if window in _CHOP_WINDOWS:
        log.info("Purgatory filter (%s %s): bar in chop window '%s' — skipping",
                 ticker, signal_type, window)
        return None

    # --- Filter: auto-disabled (ticker, direction) pairs ---
    if (ticker, signal_type) in _get_disabled_pairs():
        log.info("Purgatory filter (%s %s): pair auto-disabled (poor 30d record) — skipping",
                 ticker, signal_type)
        return None

    return {
        "ticker":       ticker,
        "signal":       signal_type,
        "bar_time":     bar_time_iso,
        "price":        cur_price,
        "ema5":         cur_ema5,
        "ema9":         float(cur["ema9"]),
        "ema30":        cur_ema30,
        "vwap":         cur_vwap,
        "depth_pct":    depth_pct,
        "day_move_pct": day_move_pct,
        "window":       window,
    }


# --- Signal persistence + outcome back-fill (Supabase) ---

_PURGATORY_SIGNALS_TABLE = "purgatory_signals"


def _persist_signal(signal: dict[str, Any]) -> str | None:
    """Insert a signal into Supabase. Returns the new row id (or None if
    Supabase unavailable / insert failed). Idempotent via the unique
    (ticker, signal, bar_time) constraint — re-inserts return existing row."""
    if _supabase_client is None:
        return None
    try:
        res = _supabase_client.table(_PURGATORY_SIGNALS_TABLE).upsert({
            "ticker":      signal["ticker"],
            "signal":      signal["signal"],
            "bar_time":    signal["bar_time"],
            "entry_price": signal["price"],
            "ema5":        signal.get("ema5"),
            "ema9":        signal.get("ema9"),
            "ema30":       signal.get("ema30"),
            "vwap":        signal.get("vwap"),
            "slack_sent":  signal.get("slack_sent", False),
        }, on_conflict="ticker,signal,bar_time").execute()
        if res.data and isinstance(res.data, list) and res.data:
            return res.data[0].get("id")
    except Exception as exc:  # noqa: BLE001
        log.warning("Supabase signal persist failed: %s", exc)
    return None


def _fetch_persisted_signals(limit: int = 100) -> list[dict[str, Any]]:
    """Pull recent signals from Supabase. Returns newest first."""
    if _supabase_client is None:
        return []
    try:
        res = (
            _supabase_client.table(_PURGATORY_SIGNALS_TABLE)
            .select("*")
            .order("alerted_at", desc=True)
            .limit(limit)
            .execute()
        )
        return list(res.data or [])
    except Exception as exc:  # noqa: BLE001
        log.warning("Supabase signal fetch failed: %s", exc)
        return []


def _backfill_outcomes_for_matured_signals() -> int:
    """Find signals that are >= 35 min old, have null outcome, and have
    enough bars available to score. Compute their favorable at +5/+10/+15/
    +20/+25/+30m and an overall outcome, then update the row.

    Returns the number of signals back-filled in this pass."""
    if _supabase_client is None or not _alpaca_enabled():
        return 0

    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=35)).isoformat()
        res = (
            _supabase_client.table(_PURGATORY_SIGNALS_TABLE)
            .select("*")
            .is_("outcome", "null")
            .lt("bar_time", cutoff)
            .order("bar_time", desc=False)
            .limit(50)
            .execute()
        )
        pending = list(res.data or [])
    except Exception as exc:  # noqa: BLE001
        log.warning("Outcome backfill query failed: %s", exc)
        return 0

    if not pending:
        return 0

    # Batch one Alpaca call covering all tickers + time range needed
    tickers = sorted({s["ticker"] for s in pending})
    bar_times = [datetime.fromisoformat(s["bar_time"].replace("Z", "+00:00")) for s in pending]
    earliest = min(bar_times)
    latest = max(bar_times) + timedelta(minutes=32)
    try:
        r = requests.get(
            f"{ALPACA_DATA_BASE}/stocks/bars",
            headers={
                "APCA-API-KEY-ID":     ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": ALPACA_API_SECRET,
            },
            params={
                "symbols":   ",".join(tickers),
                "timeframe": "1Min",
                "start":     earliest.isoformat(),
                "end":       latest.isoformat(),
                "feed":      "iex",
                "limit":     "10000",
            },
            timeout=20,
        )
        r.raise_for_status()
        body = r.json() or {}
        bars_by_sym = body.get("bars") or {}
    except Exception as exc:  # noqa: BLE001
        log.warning("Outcome backfill Alpaca fetch failed: %s", exc)
        return 0

    # Index parsed bars per ticker for fast lookup
    indexed: dict[str, list[tuple[datetime, float]]] = {}
    for t in tickers:
        rows = []
        for b in (bars_by_sym.get(t) or []):
            try:
                ts = datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
                rows.append((ts, float(b["c"])))
            except (KeyError, ValueError, TypeError):
                continue
        rows.sort(key=lambda x: x[0])
        indexed[t] = rows

    def close_at_or_after(ticker: str, target: datetime) -> float | None:
        for ts, c in indexed.get(ticker, []):
            if ts >= target:
                return c
        return None

    n_backfilled = 0
    for s in pending:
        try:
            bt = datetime.fromisoformat(s["bar_time"].replace("Z", "+00:00"))
            entry = float(s["entry_price"])
            side = s["signal"]
        except (KeyError, ValueError, TypeError):
            continue

        favorables: dict[str, float | None] = {}
        for h in (5, 10, 15, 20, 25, 30):
            price = close_at_or_after(s["ticker"], bt + timedelta(minutes=h))
            if price is None:
                favorables[f"favorable_{h}m"] = None
            else:
                move_pct = (price - entry) / entry * 100.0
                fav = move_pct if side == "call" else -move_pct
                favorables[f"favorable_{h}m"] = fav

        # Overall outcome based on best favorable across horizons
        valid = [v for v in favorables.values() if v is not None]
        if not valid:
            # Not enough data yet — leave outcome null, try again next scan
            continue
        best = max(valid)
        outcome = "win" if best > 0.10 else ("flat" if best > -0.10 else "loss")

        try:
            _supabase_client.table(_PURGATORY_SIGNALS_TABLE).update({
                **favorables,
                "outcome": outcome,
            }).eq("id", s["id"]).execute()
            n_backfilled += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("Outcome update failed for signal %s: %s", s.get("id"), exc)

    return n_backfilled


def _recent_stats_for_ticker_direction(ticker: str, direction: str, n: int = 10) -> dict[str, Any] | None:
    """Return win-rate + average favorable for the last N signals on
    (ticker, direction). Only counts signals where outcome has been scored
    (i.e., not the brand-new one we're currently firing)."""
    if _supabase_client is None:
        return None
    try:
        res = (
            _supabase_client.table(_PURGATORY_SIGNALS_TABLE)
            .select("outcome, favorable_10m, favorable_15m")
            .eq("ticker", ticker)
            .eq("signal", direction)
            .not_.is_("outcome", "null")
            .order("bar_time", desc=True)
            .limit(n)
            .execute()
        )
        rows = list(res.data or [])
    except Exception as exc:  # noqa: BLE001
        log.warning("Recent-stats query failed: %s", exc)
        return None

    if not rows:
        return None
    wins = sum(1 for r in rows if r.get("outcome") == "win")
    avg_15 = [float(r["favorable_15m"]) for r in rows if r.get("favorable_15m") is not None]
    return {
        "n":             len(rows),
        "wins":          wins,
        "win_rate_pct":  wins / len(rows) * 100.0,
        "avg_favorable_15m": (sum(avg_15) / len(avg_15)) if avg_15 else None,
    }


def _send_slack_alert(signal: dict[str, Any], stats: dict[str, Any] | None = None) -> bool:
    """POST the signal to the configured Slack incoming webhook. Returns
    True on success, False otherwise (does not raise). Optionally appends
    a 'last N {ticker} {direction}: X wins / Y losses, avg favorable Z%'
    context line so the user can gauge confidence at a glance."""
    if not _slack_enabled():
        return False
    emoji = "🟢" if signal["signal"] == "call" else "🔴"
    direction = "BUY CALLS" if signal["signal"] == "call" else "BUY PUTS"
    ticker = signal["ticker"]
    price = signal["price"]

    # Time-of-day context (lights up vs. cautions on the alert)
    window = signal.get("window") or "unknown"
    if window in _PRIME_WINDOWS:
        window_note = f"🟢 *Prime window* ({_window_label(window)}) — strongest historical win rate"
    elif window in {"open_settle", "pre_lunch", "post_lunch", "pre_close"}:
        window_note = f"⚪ *Mid-range window* ({_window_label(window)}) — mediocre historical performance"
    else:
        window_note = f"⚠️ *Soft window* ({_window_label(window)}) — outside the strongest windows"

    fields = [
        {"type": "mrkdwn", "text": f"*EMA 5/9/30*\n{signal['ema5']:.2f} / {signal['ema9']:.2f} / {signal['ema30']:.2f}"},
        {"type": "mrkdwn", "text": f"*VWAP*\n{signal['vwap']:.2f}"},
        {"type": "mrkdwn", "text": f"*Bar time*\n{signal['bar_time']}"},
    ]
    if "depth_pct" in signal and "day_move_pct" in signal:
        fields.append({"type": "mrkdwn",
            "text": f"*Breakout depth*\n{signal['depth_pct']:.3f}% · day {signal['day_move_pct']:+.2f}%"})

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn",
            "text": f"{emoji} *{ticker}* — Purgatory signal: *{direction}*  @  *${price:.2f}*"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": window_note}]},
        {"type": "section", "fields": fields},
    ]

    if stats and stats.get("n"):
        avg_str = f"avg +0.00%" if stats.get("avg_favorable_15m") is None else f"avg {stats['avg_favorable_15m']:+.2f}%"
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn",
                "text": (f"📊 *Last {stats['n']} {ticker} {signal['signal'].upper()}s*: "
                         f"{stats['wins']}/{stats['n']} wins ({stats['win_rate_pct']:.0f}%) · "
                         f"{avg_str} favorable @ +15m")}
        ]})

    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": "Hold target: ~20–25 min from signal close (42% of winners peak at +20m). Not investment advice."}
    ]})

    payload = {"text": f"{emoji} {ticker} — Purgatory {direction} @ ${price:.2f}", "blocks": blocks}
    try:
        r = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=5)
        return 200 <= r.status_code < 300
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack alert post failed: %s", exc)
        return False


# Initialize the watchlist. The load hits Supabase over the network, so run
# it in a background thread — a slow or unreachable Supabase must never delay
# app startup. A long boot makes Render's edge return 503 to the scan cron,
# which then auto-disables the job (and silences notifications). The watchlist
# is empty for at most a second or two after boot, until this completes.
_purgatory_watchlist: set[str] = set()


def _init_purgatory_state() -> None:
    global _purgatory_watchlist
    loaded = _load_purgatory_state()
    with _purgatory_lock:
        _purgatory_watchlist = loaded


threading.Thread(target=_init_purgatory_state, name="purgatory-init", daemon=True).start()


@app.get("/purgatory/watchlist")
def purgatory_watchlist_get():
    return {
        "watchlist": sorted(_purgatory_watchlist),
        "alpaca_enabled": _alpaca_enabled(),
        "slack_enabled": _slack_enabled(),
    }


class _PurgatoryAddRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)


@app.post("/purgatory/watchlist")
def purgatory_watchlist_add(req: _PurgatoryAddRequest):
    t = req.ticker.strip().upper()
    if not t:
        raise HTTPException(400, "ticker required")
    with _purgatory_lock:
        _purgatory_watchlist.add(t)
        _save_purgatory_state(_purgatory_watchlist)
    return {"watchlist": sorted(_purgatory_watchlist)}


@app.delete("/purgatory/watchlist/{ticker}")
def purgatory_watchlist_remove(ticker: str):
    t = ticker.strip().upper()
    with _purgatory_lock:
        _purgatory_watchlist.discard(t)
        _save_purgatory_state(_purgatory_watchlist)
    return {"watchlist": sorted(_purgatory_watchlist)}


@app.post("/purgatory/scan")
def purgatory_scan():
    """Run one scan pass for every watched ticker, then back-fill outcomes
    on any matured signals. Called by external cron every 1-4 min during
    market hours."""
    if not _alpaca_enabled():
        raise HTTPException(503, "Purgatory scan requires ALPACA_API_KEY and ALPACA_API_SECRET env vars.")

    tickers = sorted(_purgatory_watchlist)
    new_signals: list[dict[str, Any]] = []

    if tickers:
        # One batched API call for all watched symbols
        try:
            bars_by_sym = _fetch_alpaca_bars(tickers, timeframe="4Min", lookback_hours=24)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Alpaca fetch failed: {exc}") from exc

        for t in tickers:
            bars = bars_by_sym.get(t) or []
            sig = _check_purgatory_signal(t, bars)
            if not sig:
                continue
            # Dedupe by (ticker, signal-type, bar_time)
            key = (t, sig["signal"], sig["bar_time"])
            if key in _purgatory_alerted:
                continue
            _purgatory_alerted[key] = time.time()
            sig["alerted_at"] = _now_iso()

            # Look up recent stats for this ticker+direction to enrich the alert (C)
            stats = _recent_stats_for_ticker_direction(t, sig["signal"], n=10)
            sig["recent_stats"] = stats

            sig["slack_sent"] = _send_slack_alert(sig, stats=stats)
            new_signals.append(sig)
            _purgatory_signals.append(sig)
            if len(_purgatory_signals) > _PURGATORY_MAX_SIGNALS:
                del _purgatory_signals[:-_PURGATORY_MAX_SIGNALS]

            # Persist to Supabase
            _persist_signal(sig)

    # Back-fill outcomes for matured signals (>= 25 min old, no outcome yet).
    # Runs every scan so the data piles up over the trading day.
    n_backfilled = _backfill_outcomes_for_matured_signals()

    # Garbage-collect dedupe entries older than 24h
    cutoff = time.time() - 86400
    for k, fired_at in list(_purgatory_alerted.items()):
        if fired_at < cutoff:
            del _purgatory_alerted[k]

    # End-of-day retro: fires once at the first scan >= 16:05 ET on weekdays
    # if today's retro hasn't been posted yet. Computes + Slack + AI analysis.
    retro_fired = False
    try:
        retro = _run_daily_retro_if_due()
        retro_fired = retro is not None
    except Exception as exc:  # noqa: BLE001
        log.warning("Daily retro auto-trigger failed: %s", exc)

    return {
        "scanned":       len(tickers),
        "tickers":       tickers,
        "signals":       new_signals,
        "backfilled":    n_backfilled,
        "retro_fired":   retro_fired,
        "ts":            _now_iso(),
    }


@app.get("/purgatory/signals")
def purgatory_signals_get(limit: int = 50):
    """Recent signals. Prefers Supabase (survives redeploys, includes
    back-filled outcomes); falls back to in-memory list."""
    limit = max(1, min(int(limit), _PURGATORY_MAX_SIGNALS))
    persisted = _fetch_persisted_signals(limit=limit)
    if persisted:
        # Normalize keys to match the frontend's expectations
        normalized = []
        for s in persisted:
            normalized.append({
                "ticker":        s.get("ticker"),
                "signal":        s.get("signal"),
                "bar_time":      s.get("bar_time"),
                "price":         s.get("entry_price"),
                "ema5":          s.get("ema5"),
                "ema9":          s.get("ema9"),
                "ema30":         s.get("ema30"),
                "vwap":          s.get("vwap"),
                "alerted_at":    s.get("alerted_at"),
                "slack_sent":    s.get("slack_sent"),
                "outcome":       s.get("outcome"),
                "favorable_5m":  s.get("favorable_5m"),
                "favorable_10m": s.get("favorable_10m"),
                "favorable_15m": s.get("favorable_15m"),
                "favorable_20m": s.get("favorable_20m"),
                "favorable_25m": s.get("favorable_25m"),
                "favorable_30m": s.get("favorable_30m"),
            })
        return {"signals": normalized, "source": "supabase"}
    return {
        "signals": list(reversed(_purgatory_signals[-limit:])),
        "source": "memory",
    }


@app.get("/purgatory/stats")
def purgatory_stats(days: int = 30):
    """Per-(ticker, direction) win rate + average favorable move at +15m
    over the last `days` days of signals with computed outcomes."""
    if _supabase_client is None:
        raise HTTPException(503, "Stats require Supabase (SUPABASE_URL / SUPABASE_KEY env vars).")

    days = max(1, min(int(days), 365))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        res = (
            _supabase_client.table(_PURGATORY_SIGNALS_TABLE)
            .select("ticker, signal, outcome, favorable_10m, favorable_15m, favorable_20m")
            .gte("bar_time", since)
            .not_.is_("outcome", "null")
            .execute()
        )
        rows = list(res.data or [])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Supabase stats query failed: {exc}") from exc

    # Bucket by (ticker, direction)
    buckets: dict[tuple, list[dict]] = {}
    for r in rows:
        k = (r.get("ticker"), r.get("signal"))
        buckets.setdefault(k, []).append(r)

    out = []
    for (ticker, direction), bucket in sorted(buckets.items()):
        wins = sum(1 for r in bucket if r.get("outcome") == "win")
        losses = sum(1 for r in bucket if r.get("outcome") == "loss")
        flats = sum(1 for r in bucket if r.get("outcome") == "flat")
        f15 = [float(r["favorable_15m"]) for r in bucket if r.get("favorable_15m") is not None]
        out.append({
            "ticker":              ticker,
            "direction":           direction,
            "n":                   len(bucket),
            "wins":                wins,
            "losses":              losses,
            "flats":               flats,
            "win_rate_pct":        wins / len(bucket) * 100.0 if bucket else 0.0,
            "avg_favorable_15m":   (sum(f15) / len(f15)) if f15 else None,
        })
    return {
        "days":     days,
        "n_total":  len(rows),
        "buckets":  out,
        "ts":       _now_iso(),
    }


@app.get("/purgatory/status")
def purgatory_status():
    disabled = sorted(_get_disabled_pairs())
    return {
        "alpaca_enabled":          _alpaca_enabled(),
        "slack_enabled":           _slack_enabled(),
        "watchlist_count":         len(_purgatory_watchlist),
        "watchlist":               sorted(_purgatory_watchlist),
        "signals_logged":          len(_purgatory_signals),
        "min_breakout_pct":        PURGATORY_MIN_BREAKOUT_PCT,
        "trend_filter_pct":        PURGATORY_TREND_FILTER_PCT,
        "auto_disabled_pairs":     [{"ticker": t, "direction": d} for t, d in disabled],
        "supabase_signals":        _supabase_client is not None,
        "ts":                      _now_iso(),
    }


# ----------------------------- Daily retro + AI analysis -----------------------------

_PURGATORY_SUMMARIES_TABLE = "purgatory_daily_summaries"
_ET = "America/New_York"


def _now_et_date():
    """Current date in ET — used to define a 'trading day'."""
    return pd.Timestamp.now(tz=_ET).date()


def _retro_already_posted(date_str: str) -> bool:
    """Check if the daily retro for this date has already been pushed to Slack."""
    if _supabase_client is None:
        return False
    try:
        res = (
            _supabase_client.table(_PURGATORY_SUMMARIES_TABLE)
            .select("slack_posted")
            .eq("date", date_str)
            .limit(1)
            .execute()
        )
        if res.data:
            return bool(res.data[0].get("slack_posted"))
    except Exception as exc:  # noqa: BLE001
        log.warning("Retro check query failed: %s", exc)
    return False


def _should_run_retro_now() -> bool:
    """Run retro if it's >= 16:05 ET on a weekday and today hasn't posted yet."""
    now_et = pd.Timestamp.now(tz=_ET)
    if now_et.weekday() >= 5:  # Sat/Sun
        return False
    if (now_et.hour, now_et.minute) < (16, 5):
        return False
    return not _retro_already_posted(now_et.date().isoformat())


def _compute_daily_retro(date_str: str) -> dict[str, Any] | None:
    """Aggregate signals for one date. Returns a dict suitable for storing
    in purgatory_daily_summaries + posting to Slack."""
    if _supabase_client is None:
        return None

    start = f"{date_str}T00:00:00+00:00"
    end = f"{date_str}T23:59:59+00:00"
    try:
        res = (
            _supabase_client.table(_PURGATORY_SIGNALS_TABLE)
            .select("*")
            .gte("bar_time", start)
            .lte("bar_time", end)
            .order("bar_time", desc=False)
            .execute()
        )
        signals = list(res.data or [])
    except Exception as exc:  # noqa: BLE001
        log.warning("Retro query failed: %s", exc)
        return None

    if not signals:
        return {
            "date": date_str, "total_signals": 0,
            "wins": 0, "losses": 0, "flats": 0, "pending": 0,
            "win_rate_pct": None, "avg_favorable_15m": None,
            "best_signal": None, "worst_signal": None,
            "per_ticker": {}, "per_direction": {},
        }

    def _best_favorable(s: dict) -> float | None:
        vals = [s.get(k) for k in ("favorable_5m", "favorable_10m", "favorable_15m", "favorable_20m") if s.get(k) is not None]
        vals = [float(v) for v in vals]
        return max(vals) if vals else None

    wins = sum(1 for s in signals if s.get("outcome") == "win")
    losses = sum(1 for s in signals if s.get("outcome") == "loss")
    flats = sum(1 for s in signals if s.get("outcome") == "flat")
    pending = sum(1 for s in signals if not s.get("outcome"))
    scored = wins + losses + flats

    f15s = [float(s["favorable_15m"]) for s in signals if s.get("favorable_15m") is not None]

    # Best and worst — based on peak favorable (best across horizons)
    enriched = [(s, _best_favorable(s)) for s in signals]
    enriched = [(s, b) for s, b in enriched if b is not None]
    best = max(enriched, key=lambda x: x[1])[0] if enriched else None
    worst = min(enriched, key=lambda x: x[1])[0] if enriched else None

    def _slim(s: dict | None) -> dict | None:
        if not s:
            return None
        return {
            "ticker":          s.get("ticker"),
            "signal":          s.get("signal"),
            "bar_time":        s.get("bar_time"),
            "entry_price":     float(s.get("entry_price")) if s.get("entry_price") is not None else None,
            "favorable_5m":    float(s["favorable_5m"]) if s.get("favorable_5m") is not None else None,
            "favorable_10m":   float(s["favorable_10m"]) if s.get("favorable_10m") is not None else None,
            "favorable_15m":   float(s["favorable_15m"]) if s.get("favorable_15m") is not None else None,
            "favorable_20m":   float(s["favorable_20m"]) if s.get("favorable_20m") is not None else None,
            "outcome":         s.get("outcome"),
        }

    # Per-ticker breakdown
    per_ticker: dict[str, dict] = {}
    for s in signals:
        t = s.get("ticker") or "—"
        d = s.get("signal") or "—"
        bucket = per_ticker.setdefault(t, {"call": {"n": 0, "wins": 0, "losses": 0, "flats": 0, "pending": 0},
                                            "put":  {"n": 0, "wins": 0, "losses": 0, "flats": 0, "pending": 0}})
        if d not in bucket:
            continue
        bucket[d]["n"] += 1
        oc = s.get("outcome")
        if oc == "win":
            bucket[d]["wins"] += 1
        elif oc == "loss":
            bucket[d]["losses"] += 1
        elif oc == "flat":
            bucket[d]["flats"] += 1
        else:
            bucket[d]["pending"] += 1

    # Per-direction summary
    per_direction = {}
    for direction in ("call", "put"):
        rows = [s for s in signals if s.get("signal") == direction]
        if not rows:
            continue
        d_wins = sum(1 for s in rows if s.get("outcome") == "win")
        d_losses = sum(1 for s in rows if s.get("outcome") == "loss")
        d_flats = sum(1 for s in rows if s.get("outcome") == "flat")
        per_direction[direction] = {
            "n":              len(rows),
            "wins":           d_wins,
            "losses":         d_losses,
            "flats":          d_flats,
            "pending":        len(rows) - d_wins - d_losses - d_flats,
            "win_rate_pct":   (d_wins / max(d_wins + d_losses + d_flats, 1)) * 100.0,
        }

    # Daily P&L estimate — sum of favorables (in %), summed over scored
    # signals. A positive sum means hypothetical net-positive day if you
    # took every signal at uniform size and exited at +15m. Doesn't account
    # for option premium decay or slippage, so the real number is worse.
    sum_favorable_15m = sum(f15s) if f15s else None

    return {
        "date":              date_str,
        "total_signals":     len(signals),
        "wins":              wins,
        "losses":            losses,
        "flats":             flats,
        "pending":           pending,
        "win_rate_pct":      (wins / scored * 100.0) if scored else None,
        "avg_favorable_15m": (sum(f15s) / len(f15s)) if f15s else None,
        "sum_favorable_15m": sum_favorable_15m,
        "best_signal":       _slim(best),
        "worst_signal":      _slim(worst),
        "per_ticker":        per_ticker,
        "per_direction":     per_direction,
    }


def _post_daily_retro_to_slack(summary: dict[str, Any]) -> bool:
    """Format and POST the daily retro to the Slack webhook."""
    if not _slack_enabled():
        return False
    if summary["total_signals"] == 0:
        # Skip — no point announcing a no-signal day
        return False

    date_pretty = summary["date"]
    try:
        date_pretty = pd.Timestamp(summary["date"]).strftime("%a %b %d")
    except Exception:  # noqa: BLE001
        pass

    win_rate = f"{summary['win_rate_pct']:.0f}%" if summary.get("win_rate_pct") is not None else "—"
    avg_fav = f"{summary['avg_favorable_15m']:+.2f}%" if summary.get("avg_favorable_15m") is not None else "—"
    sum_fav = summary.get("sum_favorable_15m")
    pnl_str = "—" if sum_fav is None else f"{sum_fav:+.2f}%"
    pnl_emoji = "⚪" if sum_fav is None else ("🟢" if sum_fav > 0 else "🔴")

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📊 Purgatory Daily Retro — {date_pretty}"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Total signals*\n{summary['total_signals']}"},
            {"type": "mrkdwn", "text": f"*Outcomes*\n🟢 {summary['wins']} W · 🔴 {summary['losses']} L · ⚫ {summary['flats']} flat" + (f" · ⏳ {summary['pending']}" if summary["pending"] else "")},
            {"type": "mrkdwn", "text": f"*Win rate (scored)*\n{win_rate}"},
            {"type": "mrkdwn", "text": f"*Avg favorable @ +15m*\n{avg_fav}"},
            {"type": "mrkdwn", "text": f"*Expected total move*\n{pnl_emoji} {pnl_str} sum @ +15m"},
        ]},
    ]

    # Surface what's currently auto-disabled
    disabled = _get_disabled_pairs()
    if disabled:
        d_str = ", ".join(f"{t} {d.upper()}" for t, d in sorted(disabled))
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
            "text": f"🚫 Auto-disabled (≥10 scored signals, ≤30% wr or ≤−0.20% avg): `{d_str}`"}]})

    if summary.get("best_signal"):
        b = summary["best_signal"]
        best_pct = b.get("favorable_15m") or b.get("favorable_10m") or b.get("favorable_20m") or 0
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": f"🏆 *Best*: `{b['ticker']}` *{b['signal'].upper()}* — peak +{best_pct:.2f}% favorable"}})
    if summary.get("worst_signal"):
        w = summary["worst_signal"]
        worst_vals = [w.get(k) for k in ("favorable_5m", "favorable_10m", "favorable_15m", "favorable_20m") if w.get(k) is not None]
        worst_low = min(worst_vals) if worst_vals else 0
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": f"💀 *Worst*: `{w['ticker']}` *{w['signal'].upper()}* — drawdown {worst_low:+.2f}% favorable"}})

    # Per-ticker mini-table
    if summary.get("per_ticker"):
        lines = []
        for t in sorted(summary["per_ticker"]):
            buckets = summary["per_ticker"][t]
            parts = []
            for d in ("call", "put"):
                b = buckets.get(d, {})
                if b.get("n"):
                    parts.append(f"{d.upper()} {b['wins']}/{b['n']}")
            if parts:
                lines.append(f"• `{t}`: " + " · ".join(parts))
        if lines:
            blocks.append({"type": "section", "text": {"type": "mrkdwn",
                "text": "*By ticker* (wins / total)\n" + "\n".join(lines)}})

    # Per-direction
    if summary.get("per_direction"):
        pd_lines = []
        for direction in ("call", "put"):
            d = summary["per_direction"].get(direction)
            if d:
                pd_lines.append(f"• *{direction.upper()}*: {d['wins']}/{d['n']} ({d['win_rate_pct']:.0f}%)")
        if pd_lines:
            blocks.append({"type": "section", "text": {"type": "mrkdwn",
                "text": "*By direction*\n" + "\n".join(pd_lines)}})

    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": "🧠 AI analysis follows in the next message…"}
    ]})

    payload = {"text": f"📊 Purgatory Daily Retro — {date_pretty}", "blocks": blocks}
    try:
        r = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        return 200 <= r.status_code < 300
    except Exception as exc:  # noqa: BLE001
        log.warning("Daily retro Slack post failed: %s", exc)
        return False


def _save_daily_summary(summary: dict[str, Any], slack_posted: bool) -> None:
    """Persist (upsert by date) the daily summary."""
    if _supabase_client is None:
        return
    try:
        _supabase_client.table(_PURGATORY_SUMMARIES_TABLE).upsert({
            "date":              summary["date"],
            "total_signals":     summary["total_signals"],
            "wins":              summary["wins"],
            "losses":            summary["losses"],
            "flats":             summary["flats"],
            "pending":           summary["pending"],
            "win_rate_pct":      summary.get("win_rate_pct"),
            "avg_favorable_15m": summary.get("avg_favorable_15m"),
            "best_signal":       summary.get("best_signal"),
            "worst_signal":      summary.get("worst_signal"),
            "per_ticker":        summary.get("per_ticker"),
            "per_direction":     summary.get("per_direction"),
            "slack_posted":      slack_posted,
        }, on_conflict="date").execute()
    except Exception as exc:  # noqa: BLE001
        log.warning("Save daily summary failed: %s", exc)


def _ai_analyze_daily_summary(summary: dict[str, Any]) -> str | None:
    """Send the daily summary to OpenRouter (Claude Sonnet 4) and get back
    2-3 specific tuning suggestions. Returns the model's text response, or
    None if disabled/failed."""
    if not _openrouter_enabled():
        return None
    if summary["total_signals"] == 0 or summary["wins"] + summary["losses"] == 0:
        return None  # not enough data to analyze

    # Compact context so we don't waste tokens on full signal-by-signal data
    compact = {
        "date":                summary["date"],
        "total":               summary["total_signals"],
        "wins":                summary["wins"],
        "losses":              summary["losses"],
        "flats":               summary["flats"],
        "pending":             summary["pending"],
        "win_rate_pct":        summary.get("win_rate_pct"),
        "avg_favorable_15m":   summary.get("avg_favorable_15m"),
        "best":                summary.get("best_signal"),
        "worst":               summary.get("worst_signal"),
        "per_ticker":          summary.get("per_ticker"),
        "per_direction":       summary.get("per_direction"),
        "filters_in_use": {
            "min_breakout_pct":  PURGATORY_MIN_BREAKOUT_PCT,
            "trend_filter_pct":  PURGATORY_TREND_FILTER_PCT,
        },
    }

    system_prompt = (
        "You are tuning a 4-minute intraday options-signal generator called the "
        "Purgatory Method. The signal fires when 5-EMA and 9-EMA cross above (CALL) "
        "or below (PUT) both VWAP and 30-EMA, with two configurable filters: "
        "(1) breakout-depth threshold — EMA5 must be at least N% beyond the nearest "
        "purgatory line; (2) trend filter — skip CALL if day is down >X% (or PUT "
        "if up). Outcomes are scored by 'favorable %' move at +5/+10/+15/+20 min "
        "after the signal bar's close (positive favorable = trade direction was right).\n\n"
        "The user wants concrete, specific tuning suggestions — not generic trading "
        "advice. Be ruthless. Cite the actual numbers. Keep it under 200 words."
    )

    user_prompt = (
        "Here's today's data:\n\n"
        + json.dumps(compact, indent=2, default=str)
        + "\n\nGive me 2–3 specific tweaks for tomorrow. Examples of the right shape:\n"
        "• 'Raise min_breakout_pct from 0.05 to 0.08 — it would have killed N "
        "noise signals that all ended flat.'\n"
        "• 'Disable {TICKER} CALL signals — 0/N wins this week.'\n"
        "• 'Hold target should be +12m not +8m — best favorable shifted further out.'\n\n"
        "If today doesn't have enough signal to justify a change, say so. "
        "Don't invent a recommendation just to have one."
    )

    try:
        r = requests.post(
            f"{OPENROUTER_BASE}/chat/completions",
            headers={
                "Authorization":   f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type":    "application/json",
                "HTTP-Referer":    "https://stock-ticker-analysis.onrender.com",
                "X-Title":         "Ticker Tracker — Daily Retro",
            },
            json={
                "model": DEFAULT_AI_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                "max_tokens":  600,
                "temperature": 0.3,
            },
            timeout=45,
        )
        if r.status_code != 200:
            log.warning("OpenRouter analysis HTTP %d: %s", r.status_code, r.text[:300])
            return None
        body = r.json() or {}
        choice = (body.get("choices") or [{}])[0]
        return (choice.get("message") or {}).get("content")
    except Exception as exc:  # noqa: BLE001
        log.warning("OpenRouter analysis call failed: %s", exc)
        return None


def _post_ai_analysis_to_slack(text: str) -> bool:
    if not _slack_enabled() or not text:
        return False
    payload = {
        "text": "🧠 AI analysis of today's signals",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "🧠 AI tuning suggestions"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}},
            {"type": "context", "elements": [
                {"type": "mrkdwn",
                 "text": f"Generated by {DEFAULT_AI_MODEL} from today's signal data. Apply at your discretion — set env vars in Render to change filters."}
            ]},
        ],
    }
    try:
        r = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        return 200 <= r.status_code < 300
    except Exception as exc:  # noqa: BLE001
        log.warning("AI analysis Slack post failed: %s", exc)
        return False


def _run_daily_retro_if_due(force_date: str | None = None) -> dict[str, Any] | None:
    """Compute + post the daily retro + AI analysis. Returns the summary dict
    (or None if skipped). When force_date is provided, runs unconditionally
    for that date (used by the manual /purgatory/retro trigger)."""
    if force_date is None:
        if not _should_run_retro_now():
            return None
        date_str = pd.Timestamp.now(tz=_ET).date().isoformat()
    else:
        date_str = force_date

    summary = _compute_daily_retro(date_str)
    if summary is None:
        return None

    slack_ok = _post_daily_retro_to_slack(summary) if summary["total_signals"] > 0 else False
    _save_daily_summary(summary, slack_ok)

    # Phase 2: AI analysis. Only run if Slack post landed (otherwise no point).
    ai_text = None
    if slack_ok:
        ai_text = _ai_analyze_daily_summary(summary)
        if ai_text:
            ai_posted = _post_ai_analysis_to_slack(ai_text)
            if _supabase_client is not None:
                try:
                    _supabase_client.table(_PURGATORY_SUMMARIES_TABLE).update({
                        "ai_analysis":  ai_text,
                        "ai_posted_at": _now_iso() if ai_posted else None,
                    }).eq("date", date_str).execute()
                except Exception as exc:  # noqa: BLE001
                    log.warning("AI analysis save failed: %s", exc)

    summary["slack_posted"] = slack_ok
    summary["ai_analysis"]  = ai_text
    return summary


@app.post("/purgatory/retro")
def purgatory_retro(date: str | None = None):
    """Manually trigger today's retro + AI analysis. Useful for testing and
    for re-running if the auto-trigger missed (e.g., cron didn't run after
    16:05 ET)."""
    target = date or pd.Timestamp.now(tz=_ET).date().isoformat()
    result = _run_daily_retro_if_due(force_date=target)
    if result is None:
        raise HTTPException(503, "Retro could not be computed (Supabase or Slack not configured?)")
    return result


@app.get("/purgatory/summaries")
def purgatory_summaries(days: int = 30):
    """Return the last N days of daily summaries. Used by the (next-week)
    Retro tab in the UI."""
    if _supabase_client is None:
        raise HTTPException(503, "Summaries require Supabase.")
    days = max(1, min(int(days), 365))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    try:
        res = (
            _supabase_client.table(_PURGATORY_SUMMARIES_TABLE)
            .select("*")
            .gte("date", since)
            .order("date", desc=True)
            .execute()
        )
        return {"days": days, "summaries": list(res.data or [])}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Supabase query failed: {exc}") from exc


class _ReplaySignal(BaseModel):
    ticker:   str
    signal:   str  # "call" | "put"
    bar_time: str  # ISO timestamp
    price:    float


class _PurgatoryReplayRequest(BaseModel):
    signals: list[_ReplaySignal]
    horizons_min: list[int] = Field(default_factory=lambda: [5, 10, 15, 20])


@app.post("/purgatory/replay")
def purgatory_replay(req: _PurgatoryReplayRequest):
    """Given a list of past signals (ticker, side, bar_time, entry price),
    pull 1-minute bars from Alpaca around each signal and compute the
    realized % move + win/loss at each requested horizon. Used to measure
    how much time you actually have before/after a signal goes stale."""
    if not _alpaca_enabled():
        raise HTTPException(503, "Replay requires ALPACA_API_KEY and ALPACA_API_SECRET")
    if not req.signals:
        return {"results": [], "aggregates": {}, "n_signals": 0}

    horizons = sorted(set(int(h) for h in req.horizons_min if int(h) > 0))[:10]
    if not horizons:
        horizons = [5, 10, 15, 20]

    # Parse + dedupe signals
    cleaned: list[dict[str, Any]] = []
    for s in req.signals:
        side = s.signal.strip().lower()
        if side not in ("call", "put"):
            continue
        try:
            bt = datetime.fromisoformat(s.bar_time.replace("Z", "+00:00"))
        except ValueError:
            continue
        cleaned.append({
            "ticker":   s.ticker.strip().upper(),
            "signal":   side,
            "bar_time": bt,
            "price":    float(s.price),
        })
    if not cleaned:
        raise HTTPException(400, "No valid signals after parsing")

    # Fetch 1-min bars for every ticker in one batched call covering the
    # full range of signals + the max horizon + small buffer.
    tickers = sorted({s["ticker"] for s in cleaned})
    min_t = min(s["bar_time"] for s in cleaned)
    max_t = max(s["bar_time"] for s in cleaned) + timedelta(minutes=max(horizons) + 5)
    try:
        r = requests.get(
            f"{ALPACA_DATA_BASE}/stocks/bars",
            headers={
                "APCA-API-KEY-ID":     ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": ALPACA_API_SECRET,
            },
            params={
                "symbols":   ",".join(tickers),
                "timeframe": "1Min",
                "start":     min_t.isoformat(),
                "end":       max_t.isoformat(),
                "feed":      "iex",
                "limit":     "10000",
            },
            timeout=30,
        )
        r.raise_for_status()
        body = r.json() or {}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Alpaca fetch failed: {exc}") from exc

    bars_by_sym = body.get("bars") or {}
    bars_index: dict[str, list[tuple[datetime, float]]] = {}
    for t in tickers:
        raw = bars_by_sym.get(t, []) or []
        parsed: list[tuple[datetime, float]] = []
        for b in raw:
            try:
                ts = datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
                parsed.append((ts, float(b["c"])))
            except (KeyError, ValueError, TypeError):
                continue
        parsed.sort(key=lambda x: x[0])
        bars_index[t] = parsed

    def price_at_or_after(ticker: str, target: datetime) -> tuple[float | None, datetime | None]:
        """First bar close at or after target. Returns (price, actual_ts)."""
        for ts, c in bars_index.get(ticker, []):
            if ts >= target:
                return c, ts
        return None, None

    results: list[dict[str, Any]] = []
    for s in cleaned:
        horizons_out: dict[str, Any] = {}
        for h in horizons:
            target = s["bar_time"] + timedelta(minutes=h)
            price, actual_ts = price_at_or_after(s["ticker"], target)
            if price is None:
                horizons_out[f"+{h}m"] = {"price": None, "move_pct": None, "outcome": None}
                continue
            move_abs = price - s["price"]
            move_pct = (move_abs / s["price"] * 100.0) if s["price"] else 0.0
            # For CALL: profit = price up. For PUT: profit = price down.
            favorable_pct = move_pct if s["signal"] == "call" else -move_pct
            if favorable_pct > 0.05:
                outcome = "win"
            elif favorable_pct < -0.05:
                outcome = "loss"
            else:
                outcome = "flat"
            horizons_out[f"+{h}m"] = {
                "price":         price,
                "move_pct":      move_pct,
                "favorable_pct": favorable_pct,
                "outcome":       outcome,
                "actual_ts":     actual_ts.isoformat() if actual_ts else None,
            }
        results.append({
            "ticker":      s["ticker"],
            "signal":      s["signal"],
            "bar_time":    s["bar_time"].isoformat(),
            "entry_price": s["price"],
            "horizons":    horizons_out,
        })

    # Aggregates per horizon
    aggregates: dict[str, Any] = {}
    for h in horizons:
        key = f"+{h}m"
        vals = [
            r["horizons"][key]
            for r in results
            if r["horizons"].get(key) and r["horizons"][key]["move_pct"] is not None
        ]
        if not vals:
            aggregates[key] = {"n": 0}
            continue
        favorable = [v["favorable_pct"] for v in vals]
        wins = sum(1 for v in vals if v["outcome"] == "win")
        losses = sum(1 for v in vals if v["outcome"] == "loss")
        flats = sum(1 for v in vals if v["outcome"] == "flat")
        aggregates[key] = {
            "n":              len(vals),
            "wins":           wins,
            "losses":         losses,
            "flats":          flats,
            "win_rate_pct":   wins / len(vals) * 100.0,
            "avg_favorable":  sum(favorable) / len(favorable),
            "max_favorable":  max(favorable),
            "min_favorable":  min(favorable),
            "median_favorable": sorted(favorable)[len(favorable) // 2],
        }

    return {
        "n_signals":  len(cleaned),
        "horizons":   horizons,
        "tickers":    tickers,
        "results":    results,
        "aggregates": aggregates,
    }


@app.post("/purgatory/test")
def purgatory_test():
    """Send a synthetic 'TEST' alert to the configured Slack webhook so
    the user can verify the channel routing and message format without
    waiting for a real market signal. The message is clearly marked as
    a test and the values are placeholder."""
    if not _slack_enabled():
        raise HTTPException(503, "SLACK_WEBHOOK_URL not set — nothing to test.")

    test_signal = {
        "ticker":   "TEST",
        "signal":   "call",
        "bar_time": _now_iso(),
        "price":    100.00,
        "ema5":     100.05,
        "ema9":     99.95,
        "ema30":    99.50,
        "vwap":     99.80,
    }

    # Use a slightly different message body for the test so it's unmistakable
    if not _slack_enabled():
        return {"ok": False, "error": "slack disabled"}
    payload = {
        "text": "🧪 Ticker Tracker test — if you can see this, Slack is wired up correctly.",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "🧪 Test alert (not a real signal)"}},
            {"type": "section", "text": {"type": "mrkdwn",
                "text": "This is a one-off connectivity test from the Ticker Tracker app. The example below is a *mock* signal — do **not** act on it."}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Ticker:* TEST (placeholder)"},
                {"type": "mrkdwn", "text": f"*Direction:* CALL"},
                {"type": "mrkdwn", "text": f"*EMA 5/9/30:* 100.05 / 99.95 / 99.50"},
                {"type": "mrkdwn", "text": f"*VWAP:* 99.80"},
            ]},
            {"type": "context", "elements": [
                {"type": "mrkdwn", "text": "If the formatting and channel look right, real Purgatory signals will use the same template during market hours."}
            ]},
        ],
    }
    try:
        r = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=5)
        ok = 200 <= r.status_code < 300
        return {"ok": ok, "http_status": r.status_code, "body_preview": r.text[:200], "echo_signal": test_signal}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Slack POST failed: {exc}") from exc


# --- Static frontend ---
ROOT = Path(__file__).parent
INDEX = ROOT / "index.html"
STATIC_DIR = ROOT / "static"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Serve favicon.ico at root path because browsers auto-fetch /favicon.ico."""
    f = STATIC_DIR / "favicon.ico"
    if f.exists():
        return FileResponse(f, media_type="image/x-icon")
    raise HTTPException(status_code=404)


@app.get("/healthz")
def healthz():
    """Cheap liveness probe — no Supabase, Alpaca, or disk I/O. Use this as
    the keep-warm / uptime-monitor target so the instance stays awake (and
    cold boots report healthy fast) without hammering the heavy scan."""
    return {"ok": True, "ts": _now_iso()}


@app.get("/")
def index():
    if not INDEX.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(INDEX)
