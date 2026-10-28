import yfinance as yf, pandas as pd, numpy as np, math, warnings; warnings.filterwarnings("ignore")
H="/Users/paululisse/Documents/Stock Ticker Analysis/analysis/handoff/2026-10-21"
sig=pd.read_csv(f"{H}/signals.csv"); sig=sig[sig.scored_from=="alerted_at"].copy()
sig["bar_time"]=pd.to_datetime(sig.bar_time,utc=True); sig["date"]=sig.bar_time.dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
ord_=pd.read_csv(f"{H}/orders.csv"); ord_["date"]=pd.to_datetime(ord_.date)
tickers=sorted(set(sig.ticker)|set(ord_.ticker))
raw=yf.download(tickers,start="2023-01-01",interval="1d",auto_adjust=True,progress=False,group_by="ticker")
def regime_table(d):
    W=d.resample("W-FRI").agg({"High":"max","Low":"min","Close":"last"}).dropna()
    h,l,c=W.High,W.Low,W.Close
    tenkan=(h.rolling(9).max()+l.rolling(9).min())/2; kijun=(h.rolling(26).max()+l.rolling(26).min())/2
    spanA=((tenkan+kijun)/2).shift(26); spanB=((h.rolling(52).max()+l.rolling(52).min())/2).shift(26)
    top=np.maximum(spanA,spanB); bot=np.minimum(spanA,spanB)
    reg=pd.Series(np.where(c>top,"above",np.where(c<bot,"below","inside")),index=W.index)
    reg[top.isna()]="n/a"
    # regime known at the close of week t applies to the NEXT week's sessions
    return reg.shift(1)
R={}
for t in tickers:
    try: d=raw[t].dropna()
    except Exception: continue
    if len(d)<60: continue
    R[t]=regime_table(d)
def lookup(t,date):
    r=R.get(t)
    if r is None: return "n/a"
    wk=(date+pd.offsets.Week(weekday=4)) if date.weekday()!=4 else date   # Friday ending that week
    wk=pd.Timestamp(wk).normalize()
    v=r.get(wk)
    return v if isinstance(v,str) else "n/a"
sig["regime"]=[lookup(t,d) for t,d in zip(sig.ticker,sig.date)]
ord_["regime"]=[lookup(t,d) for t,d in zip(ord_.ticker,ord_.date)]
sig["net"]=sig.f15-0.05; sig["win15"]=sig.net>=0
def wl(k,n,z=1.96):
    if not n: return float("nan")
    p=k/n; return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)
def sg(g):
    f=g.net.dropna(); k=int((f>=0).sum()); return pd.Series({"n":len(g),"win15":round(k/len(f),3) if len(f) else None,"wilson":round(wl(k,len(f)),3) if len(f) else None,"net_mean":round(f.mean(),3),"net_med":round(f.median(),3)})
pd.set_option("display.width",200)
print("== weekly-cloud regime (prior week's close) x signal direction, ALL honest signals")
print(sig.groupby(["regime","direction"]).apply(sg,include_groups=False).to_string())
print("\n== purgatory only"); print(sig[sig.strategy=="purgatory"].groupby(["regime","direction"]).apply(sg,include_groups=False).to_string())
print("\n== aligned (above+call, below+put) vs counter (above+put, below+call), purgatory")
P=sig[sig.strategy=="purgatory"].copy(); P["align"]=np.where(((P.regime=="above")&(P.direction=="call"))|((P.regime=="below")&(P.direction=="put")),"with regime",np.where(((P.regime=="above")&(P.direction=="put"))|((P.regime=="below")&(P.direction=="call")),"against regime","inside/na"))
print(P.groupby("align").apply(sg,include_groups=False).to_string())
print("\n== by strategy, with vs against"); S=sig.copy(); S["align"]=np.where(((S.regime=="above")&(S.direction=="call"))|((S.regime=="below")&(S.direction=="put")),"with",np.where(((S.regime=="above")&(S.direction=="put"))|((S.regime=="below")&(S.direction=="call")),"against","other"))
print(S[S["align"]!="other"].groupby(["strategy","align"]).apply(sg,include_groups=False).to_string())
o=ord_[ord_.account.fillna("paper")=="paper"].copy(); o["align"]=np.where(((o.regime=="above")&(o.direction=="call"))|((o.regime=="below")&(o.direction=="put")),"with",np.where(((o.regime=="above")&(o.direction=="put"))|((o.regime=="below")&(o.direction=="call")),"against","other"))
def og(g): return pd.Series({"n":len(g),"pnl":round(g.pnl.sum()),"avg":round(g.pnl.mean(),1),"wr":round((g.pnl>0).mean(),3),"stops":int((g.exit_reason=="stop_loss").sum())})
print("\n== PAPER FILLS by regime alignment (all strategies)"); print(o.groupby("align").apply(og,include_groups=False).to_string())
print("\n== PAPER FILLS purgatory by regime x direction"); print(o[o.strategy=="purgatory"].groupby(["regime","direction"]).apply(og,include_groups=False).to_string())
print("\n== monthly: purgatory paper fills, with vs against"); o["mo"]=o.date.dt.strftime("%Y-%m"); print(o[(o.strategy=="purgatory")&(o["align"]!="other")].groupby(["mo","align"]).apply(og,include_groups=False).to_string())
print("\n== current regime per watchlist ticker (as of last completed week):"); print({t:R[t].dropna().iloc[-1] for t in sorted(R) if len(R[t].dropna())})
sig.to_csv("signals_with_regime.csv",index=False); o.to_csv("orders_with_regime.csv",index=False)
