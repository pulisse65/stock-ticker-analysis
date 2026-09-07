#!/usr/bin/env python3
"""Bullseye runner (Mac): daily BUY/HOLD/SELL predictions -> Ticker Tracker.

Runs the bullseye classifier (a HistGradientBoosting model over 40 daily
bars, forecasting the 5-session-ahead return) in-process against
bullseye's own sqlite store, then POSTs the calls to
/purgatory/external-predictions where the server scores them against
realized closes. Nothing here trades or alerts — it's a measurement feed.

The bullseye checkout is treated as untrusted third-party code: it runs
in its own venv, needs no Alpaca keys, and only ever talks to yfinance
and the app.

Usage (from the bullseye venv — see BULLSEYE_SETUP.md):
  python bullseye_runner.py run                  # one pass for each ticker's last completed session
  python bullseye_runner.py backfill --days 60   # walk-forward replay; rows are flagged backfilled
  python bullseye_runner.py daemon               # weekdays at BULLSEYE_RUN_AT_ET, forever
Flags: --tickers AAPL TSLA ...  (override the app watchlist)
       --dry-run               (print the batch instead of POSTing)
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import math
import os
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger("bullseye-runner")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ET = ZoneInfo("America/New_York")

APP_URL = os.environ.get("TICKER_APP_URL", "https://tickertracker.dev").rstrip("/")
SIGNAL_TOKEN = os.environ.get("EXTERNAL_SIGNAL_TOKEN", "").strip()
BULLSEYE_REPO = os.path.expanduser(os.environ.get("BULLSEYE_REPO", "~/Downloads/bullseye-main"))
MODEL_PATH = os.environ.get("BULLSEYE_MODEL", "models/small-classifier-nb.dmp")
HISTORY_PERIOD = os.environ.get("BULLSEYE_HISTORY_PERIOD", "3y")   # first-load depth; BB(20) only needs ~30 bars
RUN_AT_ET = os.environ.get("BULLSEYE_RUN_AT_ET", "17:00")           # daemon: after yfinance has the day's settle
SOURCE = "bullseye"
POST_CHUNK = 400


# ----------------------------- bullseye bootstrap -----------------------------

def _load_bullseye():
    """Import bullseye's db/utils from the checkout and load the classifier.
    db.py opens ./stocks.db and the model path is repo-relative, so chdir
    into the repo the way its own CLI expects."""
    if not os.path.isfile(os.path.join(BULLSEYE_REPO, "utils.py")):
        sys.exit(f"BULLSEYE_REPO={BULLSEYE_REPO} doesn't look like the bullseye checkout (no utils.py)")
    os.chdir(BULLSEYE_REPO)
    sys.path.insert(0, BULLSEYE_REPO)
    try:
        import joblib
        import db as bdb
    except ImportError as exc:
        sys.exit(f"bullseye deps missing in this interpreter ({exc}) — run from the bullseye venv, see BULLSEYE_SETUP.md")
    # Tables must exist BEFORE utils is imported: one of its type
    # annotations (`list(YieldCurve)`) runs a query at import time.
    bdb.connect_db()
    import utils as butils
    if not os.path.isfile(MODEL_PATH):
        sys.exit(f"Model not found: {os.path.join(BULLSEYE_REPO, MODEL_PATH)}")
    clf = joblib.load(MODEL_PATH)
    classes = [int(c) for c in getattr(clf, "classes_", [])]
    if classes != [0, 1, 2]:
        sys.exit(f"Unexpected classifier classes {classes}; expected [0, 1, 2] = SELL/HOLD/BUY")
    log.info("bullseye loaded: repo=%s model=%s (%s, %d features)",
             BULLSEYE_REPO, MODEL_PATH, type(clf).__name__, int(getattr(clf, "n_features_in_", 0)))
    return bdb, butils, clf


def _to_date(raw) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _quiet(fn, *args, **kwargs):
    """bullseye prints progress from library code; keep the runner log clean."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


# ----------------------------- data refresh (mirrors app.py -s / -u) -----------------------------

def _refresh_history(bdb, butils, symbol: str):
    """Ensure the Stock exists, pull new daily bars from yfinance, and
    recompute technicals. Same column mapping as bullseye's own -s/-u
    paths; dates are stored as YYYY-MM-DD."""
    import yfinance as yf

    Stock, Historical = bdb.Stock, bdb.Historical
    q = Stock.select().where(Stock.symbol == symbol)
    stock = q.get() if q.exists() else Stock.create(symbol=symbol, include=False)

    last_rows = list(
        Historical.select().where(Historical.stock_id == stock.id).order_by(-Historical.created_at).limit(1)
    )
    tk = yf.Ticker(symbol)
    if last_rows:
        last = last_rows[0]
        last_day = _to_date(last.created_at)
        hist = tk.history(interval="1d", start=last_day.isoformat())
    else:
        last, last_day = None, None
        hist = tk.history(interval="1d", period=HISTORY_PERIOD)

    n_new = n_upd = 0
    for idx, row in hist.iterrows():
        d = idx.strftime("%Y-%m-%d")
        try:
            vals = {
                "open":     float(row["Open"]),
                "high":     float(row["High"]),
                "low":      float(row["Low"]),
                "close":    float(row["Close"]),
                "volume":   int(row["Volume"]) if not math.isnan(float(row["Volume"])) else 0,
                "dividend": float(row.get("Dividends", 0.0) or 0.0),
                "split":    float(row.get("Stock Splits", 0.0) or 0.0),
            }
        except (KeyError, TypeError, ValueError):
            continue
        if any(math.isnan(vals[k]) for k in ("open", "high", "low", "close")):
            continue
        if last is not None and last_day is not None and d == last_day.isoformat():
            for k, v in vals.items():
                setattr(last, k, v)
            last.save()
            n_upd += 1
        elif last_day is None or d > last_day.isoformat():
            Historical.create(stock_id=stock.id, created_at=d, **vals)
            n_new += 1

    # Technicals are derived over the whole series; bullseye rebuilds them
    # from scratch on every update, so do the same.
    if n_new or n_upd or last is None:
        _quiet(butils.compute_technicals, stock)
    total = Historical.select().where(Historical.stock_id == stock.id).count()
    log.info("%s: %d bars (%d new, %d updated)", symbol, total, n_new, n_upd)
    return stock


def _sector_index(bdb) -> dict:
    """Same construction as app.py -p: enumerate distinct sectors over the
    Stock table in insertion order. Sectors are None on a fresh DB."""
    sectors: dict = {}
    for s in bdb.Stock.select():
        sectors.setdefault(s.sector, len(sectors))
    return sectors


# ----------------------------- prediction (mirrors app.py -p) -----------------------------

def _predict(bdb, butils, clf, stock, sectors: dict, when: date) -> tuple[dict | None, str | None]:
    """One prediction for `stock` as of session `when`. Returns
    (row_for_server, None) or (None, reason)."""
    from peewee import fn

    Historical, Technicals = bdb.Historical, bdb.Technicals
    q = (
        Historical.select()
        .join(Technicals, on=(Technicals.historical_id == Historical.id), attr="tech")
        .where((Historical.stock_id == stock.id) & (Historical.created_at < fn.date(when.isoformat(), "+1 day")))
        .order_by(-Historical.created_at)
        .limit(butils.STEP + 3)
    )
    history = list(q)[::-1]
    if len(history) < butils.STEP + 1:
        return None, f"insufficient history ({len(history)} bars)"
    end = history[-1]
    as_of = _to_date(end.created_at)
    if as_of != when:
        return None, f"no session on {when} (last bar {as_of})"

    target = butils.date_add_bus(when, butils.FORWARD_STEP)
    # yield_curve=[] is deliberate: app.py passes the raw YieldCurve list
    # here too, and get_nearest_yield_curve_score() does a membership test
    # against it that never matches, so the feature is 0 in production.
    # Passing [] reproduces production behaviour without the treasury feed.
    ok, out = _quiet(
        butils.predict, history, [], stock, sectors, clf, target, when.isoformat(),
        False, False, False, True,
    )
    if not ok or not out:
        return None, "predict() returned nothing"
    probs = [float(p) for p in out["probability"]]
    if len(probs) != 3 or any(math.isnan(p) for p in probs):
        return None, f"bad probabilities {probs}"
    forecast = int(out["forecast"])
    return {
        "ticker":      stock.symbol,
        "as_of_date":  as_of.isoformat(),
        "target_date": target.isoformat(),
        "forecast":    forecast,                    # 0/1/2 — server maps to sell/hold/buy
        "conf_sell":   round(probs[0], 6),
        "conf_hold":   round(probs[1], 6),
        "conf_buy":    round(probs[2], 6),
        "ref_price":   round(float(end.close), 4),
        "model":       os.path.splitext(os.path.basename(MODEL_PATH))[0],
        "meta":        {"label": out.get("forecast_label"), "bullseye_end_date": out.get("end_date")},
    }, None


# ----------------------------- app I/O -----------------------------

def _fetch_watchlist() -> list[str]:
    res = requests.get(f"{APP_URL}/purgatory/status", timeout=20)
    res.raise_for_status()
    wl = res.json().get("watchlist") or []
    return sorted({str(t).upper() for t in wl})


def _post(rows: list[dict], backfilled: bool | None, dry_run: bool) -> dict:
    totals = {"accepted": 0, "duplicates": 0, "rejected": []}
    if not rows:
        return totals
    if backfilled is not None:
        rows = [{**r, "backfilled": backfilled} for r in rows]
    for i in range(0, len(rows), POST_CHUNK):
        body = {"source": SOURCE, "predictions": rows[i:i + POST_CHUNK]}
        if dry_run:
            print(json.dumps(body, indent=1))
            totals["accepted"] += len(body["predictions"])
            continue
        res = requests.post(
            f"{APP_URL}/purgatory/external-predictions", json=body,
            headers={"X-Signal-Token": SIGNAL_TOKEN}, timeout=60,
        )
        if res.status_code >= 400:
            raise RuntimeError(f"POST {res.status_code}: {res.text[:300]}")
        j = res.json()
        totals["accepted"] += int(j.get("accepted", 0))
        totals["duplicates"] += int(j.get("duplicates", 0))
        totals["rejected"] += list(j.get("rejected") or [])
    return totals


def _fail_fast_config(dry_run: bool) -> None:
    if not SIGNAL_TOKEN and not dry_run:
        sys.exit("EXTERNAL_SIGNAL_TOKEN is not set (export it, or use --dry-run)")


# ----------------------------- modes -----------------------------

def _weekdays_back(days: int, end_exclusive: date) -> list[date]:
    out = []
    d = end_exclusive - timedelta(days=1)
    stop = end_exclusive - timedelta(days=days)
    while d >= stop:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def _last_complete_session_cutoff() -> date:
    """Exclusive upper bound on as_of dates that can be predicted right
    now: today joins once the session has settled (after 16:30 ET)."""
    now = datetime.now(ET)
    return now.date() + timedelta(days=1) if (now.hour, now.minute) >= (16, 30) else now.date()


def run_once(tickers: list[str], dry_run: bool, backfill_days: int | None = None) -> None:
    bdb, butils, clf = _load_bullseye()
    cutoff = _last_complete_session_cutoff()
    rows: list[dict] = []
    skipped: dict[str, int] = {}
    for sym in tickers:
        try:
            stock = _refresh_history(bdb, butils, sym)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: refresh failed: %s", sym, exc)
            continue
        sectors = _sector_index(bdb)
        if backfill_days:
            whens = _weekdays_back(backfill_days, cutoff)
        else:
            last = list(bdb.Historical.select().where(bdb.Historical.stock_id == stock.id)
                        .order_by(-bdb.Historical.created_at).limit(1))
            last_day = _to_date(last[0].created_at) if last else None
            whens = [last_day] if (last_day and last_day < cutoff) else []
        for when in whens:
            try:
                row, why = _predict(bdb, butils, clf, stock, sectors, when)
            except Exception as exc:  # noqa: BLE001
                row, why = None, f"error: {exc}"
            if row is None:
                skipped[why.split(" (")[0]] = skipped.get(why.split(" (")[0], 0) + 1
                continue
            rows.append(row)
            if not backfill_days:
                log.info("%s as of %s -> %s (buy %.2f / hold %.2f / sell %.2f) target %s",
                         sym, row["as_of_date"], row["meta"]["label"], row["conf_buy"],
                         row["conf_hold"], row["conf_sell"], row["target_date"])
    if skipped:
        log.info("Skipped: %s", ", ".join(f"{k} x{v}" for k, v in sorted(skipped.items())))
    totals = _post(rows, True if backfill_days else None, dry_run)
    log.info("%s: %d prediction(s) -> accepted %d, duplicates %d, rejected %d",
             "DRY RUN" if dry_run else APP_URL, len(rows), totals["accepted"], totals["duplicates"],
             len(totals["rejected"]))
    for rj in totals["rejected"][:10]:
        log.warning("rejected: %s", rj)


def _seconds_until_next_run() -> float:
    hh, mm = (int(x) for x in RUN_AT_ET.split(":"))
    now = datetime.now(ET)
    nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


def daemon(tickers_override: list[str] | None, dry_run: bool) -> None:
    log.info("Daemon up: app=%s run_at=%s ET weekdays", APP_URL, RUN_AT_ET)
    while True:
        wait = _seconds_until_next_run()
        log.info("Next run in %.1f h", wait / 3600)
        while wait > 0:
            step = min(wait, 3600)
            time.sleep(step)
            wait -= step
        try:
            tickers = tickers_override or _fetch_watchlist()
            run_once(tickers, dry_run)
        except Exception as exc:  # noqa: BLE001
            log.warning("Run failed: %s", exc)
        time.sleep(120)   # step past RUN_AT_ET so the next wait targets tomorrow


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["run", "backfill", "daemon"])
    ap.add_argument("--days", type=int, default=60, help="backfill: calendar days to replay (default 60)")
    ap.add_argument("--tickers", nargs="*", help="override the app watchlist")
    ap.add_argument("--dry-run", action="store_true", help="print the batch instead of POSTing")
    args = ap.parse_args()
    _fail_fast_config(args.dry_run)
    tickers = sorted({t.upper() for t in args.tickers}) if args.tickers else None

    if args.mode == "daemon":
        daemon(tickers, args.dry_run)
        return
    tickers = tickers or _fetch_watchlist()
    if not tickers:
        sys.exit("No tickers (empty watchlist and no --tickers)")
    log.info("Tickers: %s", ", ".join(tickers))
    run_once(tickers, args.dry_run, backfill_days=args.days if args.mode == "backfill" else None)


if __name__ == "__main__":
    main()
