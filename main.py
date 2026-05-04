from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

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

HISTORY_FILE = Path(__file__).parent / "history.json"
_history_lock = threading.Lock()


def _load_history() -> dict[str, dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return {}
    try:
        data = json.loads(HISTORY_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_history(data: dict[str, dict[str, Any]]) -> None:
    tmp = HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(HISTORY_FILE)


def _record_search(ticker: str, period: str) -> None:
    with _history_lock:
        h = _load_history()
        entry = h.get(ticker) or {"count": 0, "last_period": None, "last_searched": None}
        now = datetime.now(timezone.utc).isoformat()
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last_period"] = period
        entry["last_searched"] = now
        if not entry.get("first_searched"):
            entry["first_searched"] = now
        h[ticker] = entry
        _save_history(h)


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
    if score >= 3:
        verdict = "bullish"
        verdict_text = "an overall bullish setup"
    elif score >= 1:
        verdict = "lean-bullish"
        verdict_text = "a slight bullish lean"
    elif score <= -3:
        verdict = "bearish"
        verdict_text = "an overall bearish setup"
    elif score <= -1:
        verdict = "lean-bearish"
        verdict_text = "a slight bearish lean"
    else:
        verdict = "neutral"
        verdict_text = "a mixed/neutral picture"

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
    h = _load_history()
    items = [{"ticker": ticker, **entry} for ticker, entry in h.items()]
    items.sort(key=lambda x: (x.get("count", 0), x.get("last_searched") or ""), reverse=True)
    total = sum(int(item.get("count", 0)) for item in items)
    return {"items": items, "unique": len(items), "total": total}


@app.delete("/history")
def clear_history():
    with _history_lock:
        if HISTORY_FILE.exists():
            HISTORY_FILE.unlink()
    return {"ok": True}


# --- Static frontend ---
INDEX = Path(__file__).parent / "index.html"


@app.get("/")
def index():
    if not INDEX.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(INDEX)
