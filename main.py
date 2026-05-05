from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
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
        "indicators": {
            "SMA20": sma20, "SMA50": sma50, "SMA200": sma200,
            "RSI": rsi, "MACD": macd_v, "MACD_signal": macd_sig_v,
            "BB_upper": bbu, "BB_lower": bbl,
        },
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


# ----------------------------- Dashboard widgets -----------------------------
#
# Five server-fed widget endpoints. The TradingView mini-chart is fully
# client-side and doesn't need a backend.
#
# All endpoints are wrapped in a tiny in-memory TTL cache so we don't hammer
# yfinance / Reddit / Google News on every dashboard refresh.

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


@app.get("/widgets/reddit")
def widget_reddit(ticker: str):
    ticker = ticker.strip().upper()
    if not ticker:
        raise HTTPException(400, "Missing ticker.")

    cache_key = ("reddit", ticker)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    subs = "wallstreetbets+stocks+investing+StockMarket"
    url = (
        f"https://www.reddit.com/r/{subs}/search.json"
        f"?q={ticker}&restrict_sr=on&sort=new&limit=15&t=month"
    )
    headers = {"User-Agent": "stock-ticker-analysis/1.0 (https://github.com/pulisse65/stock-ticker-analysis)"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Reddit fetch failed: {exc}") from exc

    posts = []
    for child in (data.get("data") or {}).get("children", []):
        d = child.get("data") or {}
        posts.append({
            "title": d.get("title"),
            "subreddit": d.get("subreddit"),
            "score": d.get("score", 0),
            "num_comments": d.get("num_comments", 0),
            "created_utc": d.get("created_utc"),
            "permalink": f"https://www.reddit.com{d.get('permalink', '')}",
            "author": d.get("author"),
            "flair": d.get("link_flair_text"),
        })

    result = {"ticker": ticker, "posts": posts}
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
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "link": (it.findtext("link") or "").strip(),
            "pub_date": (it.findtext("pubDate") or "").strip(),
            "source": (it.findtext("source") or "").strip(),
        })

    result = {"ticker": ticker, "items": items}
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

    info = _safe(lambda: yf.Ticker(ticker).info, default={}) or {}
    if not info:
        raise HTTPException(404, f"No fundamentals available for '{ticker}'.")

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
    data: dict[str, Any] = {}
    for k in fields:
        v = info.get(k)
        if isinstance(v, float) and math.isnan(v):
            v = None
        data[k] = v

    result = {"ticker": ticker, "data": data}
    _cache_set(cache_key, result, ttl=600)  # 10 min
    return result


@app.get("/widgets/earnings")
def widget_earnings(ticker: str):
    ticker = ticker.strip().upper()
    if not ticker:
        raise HTTPException(400, "Missing ticker.")

    cache_key = ("earnings", ticker)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    t = yf.Ticker(ticker)

    # `calendar` shape varies by yfinance version: dict in newer, DataFrame in older.
    calendar: dict[str, Any] = {}
    raw_cal = _safe(lambda: t.calendar)
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

    earnings_dates: list[dict[str, Any]] = []
    raw_ed = _safe(lambda: t.earnings_dates)
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
                "date": _ts_to_iso(row.get(date_col)),
                "eps_estimate": _f("EPS Estimate"),
                "eps_actual": _f("Reported EPS"),
                "surprise_pct": _f("Surprise(%)"),
            })

    result = {"ticker": ticker, "calendar": calendar, "earnings_dates": earnings_dates}
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

    # Try to enrich with company short-name (cheap; uses already-cached info
    # path inside yfinance). Best-effort — don't fail the whole request if
    # one name lookup blows up.
    items: list[dict[str, Any]] = []
    for t in raw:
        v = scored.get(t, {})
        if "error" in v:
            items.append({"ticker": t, "error": v["error"]})
            continue
        name = _safe(lambda t=t: yf.Ticker(t).info.get("shortName") or yf.Ticker(t).info.get("longName"))
        items.append({
            "ticker": t,
            "name": name,
            "price": v.get("price"),
            "prev_close": v.get("prev_close"),
            "change_pct": v.get("change_pct"),
            "change_abs": v.get("change_abs"),
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

        sectors_out.append({
            "name": sec["name"],
            "etf": {
                "ticker": sec["etf"],
                "price": etf_v.get("price"),
                "change_pct": etf_v.get("change_pct"),
                "verdict": etf_v.get("verdict"),
            } if "error" not in etf_v else {"ticker": sec["etf"], "error": etf_v.get("error")},
            "components": components_out,
            "tally": tally,
        })

    result = {"sectors": sectors_out, "as_of": _now_iso()}
    _cache_set(cache_key, result, ttl=900)  # 15 min
    return result


# --- Static frontend ---
INDEX = Path(__file__).parent / "index.html"


@app.get("/")
def index():
    if not INDEX.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(INDEX)
