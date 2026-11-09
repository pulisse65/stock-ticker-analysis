"""PEAD backtest implementing the frozen rules in EARNINGS_DRIFT.md. Analysis only."""
import os, pickle, math, warnings, time
import numpy as np, pandas as pd, yfinance as yf
warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = "/private/tmp/claude-501/-Users-paululisse-Documents-Stock-Ticker-Analysis/ad76049f-741b-48bb-ab11-f80ff3406ba8/scratchpad/pead_raw"
os.makedirs(RAW, exist_ok=True)
COST = 0.0010
SEED = 20261108
HOLDS = [5, 10, 20]
WATCHLIST = "AAPL AMZN ASST AVGO INTC META MSFT MSTR NOK ORCL QCOM SMCI SPCX TSLA".split()
# Current S&P 100 (GOOGL omitted: same issuer/earnings as GOOG, would double count events)
SP100 = ("AAPL ABBV ABT ACN ADBE AIG AMD AMGN AMT AMZN AVGO AXP BA BAC BK BKNG BLK BMY BRK-B C CAT CHTR CL CMCSA COF "
         "COP COST CRM CSCO CVS CVX DE DHR DIS DUK EMR FDX GD GE GILD GM GOOG GS HD HON IBM INTC INTU ISRG JNJ JPM KO "
         "LIN LLY LMT LOW MA MCD MDLZ MDT MET META MMM MO MRK MS MSFT NEE NFLX NKE NOW NVDA ORCL PEP PFE PG PLTR PM "
         "PYPL QCOM RTX SBUX SCHW SO SPG T TGT TMO TMUS TSLA TXN UBER UNH UNP UPS USB V VZ WFC WMT XOM").split()
ALL = sorted(set(WATCHLIST) | set(SP100))

# ---------- prices ----------
pf = f"{RAW}/prices.pkl"
if os.path.exists(pf):
    px = pickle.load(open(pf, "rb"))
else:
    px = yf.download(ALL + ["SPY"], start="2016-01-01", end="2026-11-07", auto_adjust=True,
                     group_by="ticker", threads=True, progress=False)
    pickle.dump(px, open(pf, "wb"))
bars = {}
for t in ALL + ["SPY"]:
    try:
        d = px[t][["Open", "Close"]].dropna()
        d.index = pd.DatetimeIndex(d.index).tz_localize(None).normalize()
        if len(d) > 100: bars[t] = d
    except Exception:
        pass
no_price = [t for t in ALL if t not in bars]

# ---------- earnings dates ----------
def get_ed(t):
    f = f"{RAW}/ed_{t}.pkl"
    if os.path.exists(f): return pickle.load(open(f, "rb"))
    res, err = None, None
    for lim in (80, 40, 12):
        try:
            res = yf.Ticker(t).get_earnings_dates(limit=lim)
            if res is not None: break
        except Exception as e:
            err = str(e)[:100]
        time.sleep(0.5)
    pickle.dump((res, err), open(f, "wb"))
    return res, err

drops = {"outside_window": 0, "duplicate_date": 0, "no_price_bar": 0, "no_sigma_or_prev": 0}
events, ed_info, ed_fail = [], {}, []
for t in ALL:
    if t not in bars: continue
    ed, err = get_ed(t)
    if ed is None or len(ed) == 0:
        ed_fail.append((t, err)); continue
    idx = ed.index
    if idx.tz is None: idx = idx.tz_localize("America/New_York")
    else: idx = idx.tz_convert("America/New_York")
    b = bars[t]; pidx = b.index
    seen = set(); rows = []
    for ts in sorted(idx):
        if not (pd.Timestamp("2016-01-01", tz="America/New_York") <= ts < pd.Timestamp("2026-10-16", tz="America/New_York")):
            drops["outside_window"] += 1; continue
        d = ts.tz_localize(None).normalize()
        if d in seen: drops["duplicate_date"] += 1; continue
        seen.add(d)
        before_open = (ts.hour * 60 + ts.minute) < 9 * 60 + 30
        pos = pidx.searchsorted(d, side="left" if before_open else "right")
        if pos >= len(pidx) or (pidx[pos] - d).days > 5:
            drops["no_price_bar"] += 1; continue
        if pos < 61:
            drops["no_sigma_or_prev"] += 1; continue
        c = b["Close"].values
        r = c[pos] / c[pos - 1] - 1
        rets = pd.Series(c[pos - 60:pos]).pct_change().dropna()  # 60 sessions ending at prev session -> 59 returns+; use 60 rets below
        rets = pd.Series(c[pos - 61:pos]).pct_change().dropna()  # 60 daily returns ending at prev session
        if rets.notna().sum() < 40 or rets.std() == 0:
            drops["no_sigma_or_prev"] += 1; continue
        z = r / rets.std()
        rows.append(dict(ticker=t, ed_date=d, reaction_idx=pos, reaction_date=pidx[pos], r=r, z=z))
    events += rows
    ed_info[t] = (len(rows), min([x["ed_date"] for x in rows]) if rows else None)
ev = pd.DataFrame(events)
ev.to_csv(f"{HERE}/pead_events.csv", index=False)

# ---------- trades ----------
rng = np.random.default_rng(SEED)
spy = bars["SPY"]
ev_idx = {t: set(g.reaction_idx) for t, g in ev.groupby("ticker")}

def rand_baseline(t, H):
    b = bars[t]; n = len(b)
    ex = np.zeros(n + 1, bool)
    for e in ev_idx[t]:
        ex[max(0, e - 9): min(n, e + 10)] = True  # >=10 sessions away
    cand = np.array([i for i in range(1, n - H) if not ex[i] and i + H < n])
    if len(cand) == 0: return np.nan
    pick = rng.choice(cand, size=min(20, len(cand)), replace=False)
    o, c = b["Open"].values, b["Close"].values
    return float(np.mean(c[pick + H] / o[pick] - 1 - COST))

def signals(df, sset):
    q80 = df["r"].quantile(0.8)
    return {"z>=2": df[df.z >= 2], "top-quintile": df[df.r >= q80], "z<=-2": df[df.z <= -2]}, q80

trade_rows = []
sets = {"SP100": SP100, "WATCHLIST": WATCHLIST}
q80s, shares = {}, {}
for sname, lst in sets.items():
    df = ev[ev.ticker.isin(lst)]
    sigs, q80 = signals(df, sname)
    q80s[sname] = q80
    shares[sname] = (len(df), int((df.z >= 2).sum()), int((df.z <= -2).sum()))
    for sig, sub in sigs.items():
        for _, e in sub.sort_values(["ticker", "reaction_idx"]).iterrows():
            b = bars[e.ticker]; ent = int(e.reaction_idx) + 1
            for H in HOLDS:
                if ent + H >= len(b): continue
                o = b["Open"].values[ent]; x = b["Close"].values[ent + H]
                ret = x / o - 1 - COST
                d0, d1 = b.index[ent], b.index[ent + H]
                try:
                    so = spy.loc[d0, "Open"]; sx = spy.loc[d1, "Close"]; sr = sx / so - 1 - COST
                except KeyError:
                    sr = np.nan
                trade_rows.append(dict(set=sname, signal=sig, ticker=e.ticker, ed_date=e.ed_date, reaction_date=e.reaction_date,
                                       entry_date=d0, exit_date=d1, hold=H, r=e.r, z=e.z, net_ret=ret,
                                       rand_ret=rand_baseline(e.ticker, H), spy_ret=sr))
tr = pd.DataFrame(trade_rows)
tr.to_csv(f"{HERE}/pead_trades.csv", index=False)

# ---------- stats ----------
def wilson_lo(k, n, z=1.96):
    if n == 0: return np.nan
    p = k / n
    return (p + z*z/(2*n) - z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))) / (1 + z*z/n)

def tstat(x):
    x = pd.Series(x).dropna()
    if len(x) < 2 or x.std() == 0: return np.nan
    return x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))

def cell(g):
    n = len(g)
    return dict(n=n, mean=g.net_ret.mean()*100 if n else np.nan, median=g.net_ret.median()*100 if n else np.nan,
                hit=(g.net_ret > 0).mean()*100 if n else np.nan,
                wilson=wilson_lo(int((g.net_ret > 0).sum()), n)*100 if n else np.nan,
                rand=g.rand_ret.mean()*100 if n else np.nan, spy=g.spy_ret.mean()*100 if n else np.nan,
                t_rand=tstat(g.net_ret - g.rand_ret), t_spy=tstat(g.net_ret - g.spy_ret))
grid = []
for s in sets:
    for sig in ["z>=2", "top-quintile", "z<=-2"]:
        for H in HOLDS:
            g = tr[(tr.set == s) & (tr.signal == sig) & (tr.hold == H)]
            grid.append(dict(set=s, signal=sig, hold=H, **cell(g)))
grid = pd.DataFrame(grid); grid.to_csv(f"{HERE}/pead_grid.csv", index=False)

def md(df, floatfmt=2):
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join((f"{v:.{floatfmt}f}" if isinstance(v, (float, np.floating)) else str(v)) for v in r.values) + " |")
    return "\n".join(out)

def prim(s):
    return tr[(tr.set == s) & (tr.signal == "z>=2") & (tr.hold == 10)].copy()
P = prim("SP100"); W = prim("WATCHLIST")
by_year = P.groupby(P.entry_date.dt.year).net_ret.agg(n="count", mean_pct=lambda x: x.mean()*100,
                                                       hit_pct=lambda x: (x > 0).mean()*100).reset_index().rename(columns={"entry_date": "year"})
by_tk = P.groupby("ticker").net_ret.agg(n="count", mean_pct=lambda x: x.mean()*100, total_pct=lambda x: x.sum()*100).reset_index().sort_values("total_pct", ascending=False)
best = by_tk.iloc[0].ticker if len(by_tk) else None
ex_best = P[P.ticker != best]
P_pos_years = (by_year[by_year.n >= 10].mean_pct > 0)
by_year_w = W.groupby(W.entry_date.dt.year).net_ret.agg(n="count", mean_pct=lambda x: x.mean()*100).reset_index()
by_year.to_csv(f"{HERE}/pead_primary_by_year.csv", index=False); by_tk.to_csv(f"{HERE}/pead_primary_by_ticker.csv", index=False)

# ---------- report ----------
L = []
L.append("# PEAD backtest results (rules frozen in EARNINGS_DRIFT.md)\n")
L.append("Generated by `pead_backtest.py`. Factual output only; no verdict recorded here.\n")
L.append("## Definitions\n")
L.append("- Reaction session: report date if timestamp < 09:30 ET, else next session in the ticker's price index. r = close[reaction]/close[prev] - 1.")
L.append("- sigma60 = std of the 60 daily close-to-close returns ending at the prior session (>=40 valid); z = r/sigma60.")
L.append("- Signals: z>=2 (primary); top-quintile = pooled r >= 80th percentile of r within each set; z<=-2 (mirror, long).")
L.append(f"- Quintile thresholds: SP100 r >= {q80s['SP100']*100:.2f}%, WATCHLIST r >= {q80s['WATCHLIST']*100:.2f}%.")
L.append("- Entry = open of session after reaction session (idx0). Exit = close at idx0+H, H in 5/10/20. Net = exit/entry - 1 - 0.0010. Trades with exit past data skipped.")
L.append(f"- rand_ret: mean of 20 random same-ticker sessions >=10 sessions from any of that ticker's events, same open/close/cost, seed {SEED}. spy_ret: SPY same entry/exit dates open->close, same cost.")
L.append("- t_rand / t_spy: paired t of (ret - baseline). Wilson = 95% lower bound of hit rate (ret>0), in %.")
L.append("- Universe: current constituents (survivorship bias, not corrected). GOOGL omitted from SP100 list (duplicate of GOOG's earnings events); list is from memory.\n")
L.append("## Data coverage\n")
L.append(f"- Tickers requested: {len(ALL)} unique (SP100 {len(SP100)}, WATCHLIST {len(WATCHLIST)}). With price data: {len(bars)-1}. Without price data: {no_price or 'none'}.")
L.append(f"- Price range of data: {px.index.min().date()} to {px.index.max().date()}.")
L.append(f"- get_earnings_dates failed/empty for: {ed_fail or 'none'}.")
cnt = pd.Series({t: v[0] for t, v in ed_info.items()})
for sname, lst in sets.items():
    c = cnt[[t for t in lst if t in cnt.index]]
    em = ev[ev.ticker.isin(lst)].ed_date
    L.append(f"- {sname}: tickers with events {len(c)}; events/ticker median {c.median():.0f}, min {c.min()} ({c.idxmin()}), max {c.max()} ({c.idxmax()}); total {int(c.sum())}; earliest event {em.min().date()}, latest {em.max().date()}.")
L.append(f"- Events dropped (all tickers, counts): {drops}.")
L.append("- Share of events with z>=2 / z<=-2 (events with valid z):")
for s, (n, a, b_) in shares.items():
    L.append(f"  - {s}: n={n}, z>=2: {a} ({a/n*100:.1f}%), z<=-2: {b_} ({b_/n*100:.1f}%)")
L.append("\nEvents per ticker (n, earliest):\n")
L.append(md(pd.DataFrame([(t, v[0], str(v[1].date()) if v[1] is not None else "") for t, v in sorted(ed_info.items())], columns=["ticker", "events", "earliest"]), 0))
L.append("\nEarliest-event-year distribution (SP100 events by year):\n")
L.append(md(ev[ev.ticker.isin(SP100)].groupby(ev.ed_date.dt.year).size().reset_index(name="events").rename(columns={"ed_date": "year"}), 0))
L.append("\n## Full grid\n")
for H in HOLDS:
    g = grid[grid.hold == H].drop(columns="hold")
    L.append(f"### Hold {H}\n"); L.append(md(g)); L.append("")
L.append("Columns: mean/median/hit/wilson/rand/spy in %.\n")
L.append("## Primary cell (SP100, z>=2, hold 10)\n")
L.append(md(pd.DataFrame([cell(P)])) + "\n")
L.append("### By calendar year (of entry)\n"); L.append(md(by_year, 2) + "\n")
L.append(f"Years with >=10 trades: {int((by_year.n>=10).sum())}; of those with positive mean: {int(P_pos_years.sum())}.\n")
L.append("### By ticker (sorted by total contribution)\n"); L.append(md(by_tk) + "\n")
L.append(f"Best ticker by total contribution: {best}. Primary mean excluding it: {ex_best.net_ret.mean()*100:.2f}% (n={len(ex_best)}); t vs random {tstat(ex_best.net_ret-ex_best.rand_ret):.2f}.\n")
L.append("## Primary cell for WATCHLIST (z>=2, hold 10)\n")
L.append(md(pd.DataFrame([cell(W)])) + "\n")
L.append("By year:\n"); L.append(md(by_year_w) + "\n")
L.append("Watchlist trades:\n"); L.append(md(W[["ticker", "entry_date", "r", "z", "net_ret", "rand_ret", "spy_ret"]].assign(entry_date=W.entry_date.dt.date), 4) + "\n")
open(f"{HERE}/PEAD_RESULTS.md", "w").write("\n".join(L))
print("\n".join(L[:30])); print(grid[grid.hold == 10].to_string()); print(by_year.to_string())
