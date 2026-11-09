"""Join purgatory signals + paper fills to earnings reaction sessions. Re-runnable; reads cached raw files."""
import json, glob, os, sys, math
from datetime import date, timedelta
import pandas as pd, numpy as np

RAW = "/private/tmp/claude-501/-Users-paululisse-Documents-Stock-Ticker-Analysis/ad76049f-741b-48bb-ab11-f80ff3406ba8/scratchpad/earnings_raw"
OUT = os.path.dirname(os.path.abspath(__file__))
START = pd.Timestamp("2026-08-10", tz="UTC")
E_LO, E_HI = pd.Timestamp("2026-07-15").date(), pd.Timestamp("2026-11-30").date()
HOLIDAYS = {date(2026, 9, 7)}
NOTES = []

def is_td(d): return d.weekday() < 5 and d not in HOLIDAYS
def next_td(d):
    d += timedelta(days=1)
    while not is_td(d): d += timedelta(days=1)
    return d
def td_index(d0, d1):
    """signed number of trading sessions from d0 to d1"""
    if d0 == d1: return 0
    sign = 1 if d1 > d0 else -1
    a, b = (d0, d1) if sign == 1 else (d1, d0)
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if is_td(d): n += 1
    return sign * n
def bucket(k):
    if k is None: return "other"
    if -5 <= k <= -1: return "pre"
    if k == 0: return "reaction"
    if k == 1: return "post1"
    if 2 <= k <= 5: return "post2_5"
    return "other"
BUCKETS = ["pre", "reaction", "post1", "post2_5", "other"]

# watchlist
import requests
wf = os.path.join(RAW, "status.json")
if not os.path.exists(wf):
    open(wf, "w").write(requests.get("https://tickertracker.dev/purgatory/status", timeout=90).text)
watch = json.load(open(wf))["watchlist"]

# earnings
ef = os.path.join(OUT, "earnings_dates.csv")
if not os.path.exists(ef):
    import yfinance as yf
    rows = []
    for t in watch:
        try:
            df = yf.Ticker(t).get_earnings_dates(limit=16)
            if df is None or len(df) == 0: raise ValueError("no data")
            for ts in df.index:
                ts = ts.tz_convert("America/New_York") if ts.tzinfo else ts.tz_localize("America/New_York")
                if not (E_LO <= ts.date() <= E_HI): continue
                before = (ts.hour, ts.minute) < (9, 30)
                rd = ts.date() if before and is_td(ts.date()) else next_td(ts.date()) if not before else next_td(ts.date() - timedelta(days=1))
                rows.append(dict(ticker=t, report_ts=ts.isoformat(), report_date=ts.date().isoformat(),
                                 timing="BMO" if before else "AMC/intraday", reaction_session=rd.isoformat()))
        except Exception as e:
            print("earnings failed", t, e); rows.append(dict(ticker=t, report_ts="FAILED: %s" % str(e)[:80]))
    pd.DataFrame(rows).to_csv(ef, index=False)
ed = pd.read_csv(ef)
ok = ed[~ed.report_ts.str.startswith("FAILED", na=False)].copy()
ok["rs"] = pd.to_datetime(ok.reaction_session).dt.date
ev_by_t = {t: sorted(g.rs.tolist()) for t, g in ok.groupby("ticker")}

def join(df):
    sess, ks, rss = [], [], []
    for ts, t in zip(df.bar_time, df.ticker):
        d = ts.tz_convert("America/New_York").date(); sess.append(d)
        best = None
        for rs in ev_by_t.get(t, []):
            k = td_index(d, rs) * -1  # sessions from row date to reaction: row - reaction (neg = before)
            if best is None or abs(k) < abs(best): best = k
        ks.append(best); rss.append(None)
    df["session_date"] = sess; df["sessions_to_reaction"] = ks
    df["bucket"] = [bucket(k) for k in ks]
    return df

# Note: sessions_to_reaction defined as (reaction_session - row_session) negative=before? Spec: "number of sessions FROM row date TO reaction (negative = before)".
# With pre = -5..-1 meaning row is BEFORE reaction, value = row_session - reaction_session. Implemented above via td_index(d, rs)*-1.

# signals
sig = []
for f in sorted(glob.glob(os.path.join(RAW, "signals_*.json"))):
    sig += json.load(open(f))["signals"]
sg = pd.DataFrame(sig)
sg["bar_time"] = pd.to_datetime(sg.bar_time, utc=True, format="ISO8601")
n_raw_sig = len(sg)
sg = sg.drop_duplicates(subset=["strategy", "ticker", "signal", "bar_time"])
sg = sg[sg.bar_time >= START].copy()
sg = join(sg)
sg["fav15"] = pd.to_numeric(sg.get("favorable_15m"), errors="coerce")
keep = ["strategy", "ticker", "signal", "bar_time", "session_date", "outcome", "favorable_15m", "window", "sessions_to_reaction", "bucket"]
sg[[c for c in keep if c in sg.columns]].to_csv(os.path.join(OUT, "signals_joined.csv"), index=False)

# fills
tr = []
for f in sorted(glob.glob(os.path.join(RAW, "orders_*.json"))):
    d = json.load(open(f)); tr += d.get("trades", []) or []
fl = pd.DataFrame(tr)
fl["bar_time"] = pd.to_datetime(fl.bar_time, utc=True, format="ISO8601")
fl = join(fl)
fl["ticker_in_watch"] = fl.ticker.isin(watch)
fl["ticker_has_earnings"] = fl.ticker.isin(ev_by_t)
fk = ["strategy", "account", "ticker", "direction", "bar_time", "session_date", "qty", "entry", "exit", "pnl", "pnl_at_mid", "execution_drag", "exit_reason", "date", "sessions_to_reaction", "bucket"]
fl[fk].to_csv(os.path.join(OUT, "fills_joined.csv"), index=False)

# ---- tables
def wilson_lo(w, n, z=1.96):
    if n == 0: return float("nan")
    p = w / n; den = 1 + z * z / n
    c = p + z * z / (2 * n); m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / den
def md(df):
    cols = list(df.columns); L = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows(): L.append("| " + " | ".join("" if (isinstance(v, float) and np.isnan(v)) else (f"{v:.3f}" if isinstance(v, float) else str(v)) for v in r) + " |")
    return "\n".join(L)
def pct(x): return round(100 * x, 1)

def tab_A(s):
    R = []
    for b in BUCKETS:
        g = s[s.bucket == b]; sc = g.outcome.isin(["win", "loss", "flat"]).sum(); f = g.fav15.notna().sum()
        R.append(dict(bucket=b, n=len(g), scored=sc, stored_win_pct=pct((g.outcome == "win").sum() / sc) if sc else np.nan,
                      fav15_n=f, fixed15_win_pct=pct((g.fav15 >= 0.05).sum() / f) if f else np.nan,
                      mean_fav15=round(g.fav15.mean(), 4) if f else np.nan))
    return md(pd.DataFrame(R))
def tab_B(x):
    R = []
    for b in BUCKETS:
        g = x[x.bucket == b]; n = len(g); w = int((g.pnl > 0).sum())
        R.append(dict(bucket=b, n=n, total_pnl=round(g.pnl.sum(), 2), mean_pnl=round(g.pnl.mean(), 2) if n else np.nan,
                      win_pct=pct(w / n) if n else np.nan, wilson95_lo_pct=pct(wilson_lo(w, n)) if n >= 10 else "",
                      stop_pct=pct((g.exit_reason == "stop_loss").mean()) if n else np.nan, total_pnl_at_mid=round(g.pnl_at_mid.sum(), 2)))
    return md(pd.DataFrame(R))
def tab_C(x):
    R = []
    for b in BUCKETS:
        for d in ["call", "put"]:
            g = x[(x.bucket == b) & (x.direction == d)]; n = len(g)
            R.append(dict(bucket=b, direction=d, n=n, total_pnl=round(g.pnl.sum(), 2), stop_pct=pct((g.exit_reason == "stop_loss").mean()) if n else np.nan))
    return md(pd.DataFrame(R))
def tab_D(s, x):
    R = []
    for _, e in ok.sort_values(["ticker", "reaction_session"]).iterrows():
        row = dict(ticker=e.ticker, report=e.report_ts[:16], reaction_session=e.reaction_session)
        for b in BUCKETS[:4]:
            # attribute rows to this event if this event is that row's nearest event
            ss = s[(s.ticker == e.ticker) & (s.bucket == b) & (s.session_date.map(lambda d: td_index(d, e.rs) * -1) == s.sessions_to_reaction)]
            ff = x[(x.ticker == e.ticker) & (x.bucket == b) & (x.session_date.map(lambda d: td_index(d, e.rs) * -1) == x.sessions_to_reaction)]
            row[f"sig_{b}"] = len(ss); row[f"fills_{b}"] = len(ff); row[f"pnl_{b}"] = round(ff.pnl.sum(), 2)
        R.append(row)
    return md(pd.DataFrame(R))

out = ["# Earnings join results", "",
       "Factual tables only. Definitions: `sessions_to_reaction` = row session (bar_time in ET) minus ticker's nearest reaction_session, in NYSE trading sessions (negative = row before reaction; Labor Day 2026-09-07 closed, other holidays ignored). "
       "Buckets: pre = -5..-1, reaction = 0, post1 = +1, post2_5 = +2..+5, other = everything else / no earnings in 2026-07-15..2026-11-30. "
       "reaction_session = report date if report time < 09:30 ET else next trading day. Stored win = outcome=='win' / (win+loss+flat). Fixed-15 win = favorable_15m >= 0.05 / rows with favorable_15m. "
       "Win rate on fills = pnl>0. Wilson = 95% lower bound on win rate, shown n>=10 only. Signals de-duplicated on (strategy,ticker,signal,bar_time); signals with bar_time >= 2026-08-10.", ""]
for label, s, x in [("Purgatory only", sg[sg.strategy == "purgatory"], fl[fl.strategy == "purgatory"]), ("All strategies", sg, fl)]:
    out += [f"## {label}", "", "### A. Signals by bucket", tab_A(s), "", "### B. Fills by bucket", tab_B(x), "",
            "### C. Fills by bucket x direction", tab_C(x), "", "### D. Per-event (rows attributed to the event that is their nearest reaction session)", tab_D(s, x), ""]
sess_sig = sg.session_date.nunique(); 
out += ["## E. Coverage", "",
        f"- Signals: {len(sg)} rows (raw fetched {n_raw_sig}); date range {sg.bar_time.min()} to {sg.bar_time.max()}; {sess_sig} distinct sessions; strategies: {sg.strategy.value_counts().to_dict()}",
        f"- Fills: {len(fl)} rows; date range {fl.date.min()} to {fl.date.max()}; {fl.date.nunique()} sessions with fills; strategies: {fl.strategy.value_counts().to_dict()}",
        f"- Watchlist ({len(watch)}): {watch}",
        f"- Tickers with earnings events in window: {sorted(ev_by_t)}; events: {len(ok)}",
        f"- Watchlist tickers without earnings found: {[t for t in watch if t not in ev_by_t]}",
        f"- earnings fetch failures: {ed[ed.report_ts.str.startswith('FAILED', na=False)][['ticker','report_ts']].values.tolist()}",
        f"- Fills with ticker in watchlist: {int(fl.ticker_in_watch.sum())}; not in watchlist: {int((~fl.ticker_in_watch).sum())} ({sorted(fl[~fl.ticker_in_watch].ticker.unique())})",
        f"- Fills with ticker having earnings in window: {int(fl.ticker_has_earnings.sum())}; without: {int((~fl.ticker_has_earnings).sum())}",
        f"- Signals tickers not in watchlist: {sorted(set(sg.ticker) - set(watch))}",
        f"- Signals with outcome None: {int(sg.outcome.isna().sum())}; favorable_15m None: {int(sg.fav15.isna().sum())}", ""]
open(os.path.join(OUT, "JOIN_RESULTS.md"), "w").write("\n".join(out))
print("\n".join(out))
