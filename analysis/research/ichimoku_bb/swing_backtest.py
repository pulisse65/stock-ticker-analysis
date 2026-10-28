import yfinance as yf, pandas as pd, numpy as np, math, warnings; warnings.filterwarnings("ignore")
WATCH=['AAPL','AMZN','ASST','AVGO','INTC','IWM','META','MSFT','MSTR','NOK','ORCL','QCOM','QQQ','SMCI','SPCX','TSLA','TSLL']
CTRL=['SPY','NVDA','GOOGL','JPM','XOM','COIN','PLTR','AMD','NFLX','BA','DIS','PFE','KO','WMT','UNH','CAT','GS','HOOD','RIOT','MARA']
ALL=sorted(set(WATCH+CTRL))
raw=yf.download(ALL,period="6y",interval="1d",auto_adjust=True,progress=False,group_by="ticker")
def wl(k,n,z=1.96):
    if not n: return float("nan")
    p=k/n; return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)
def ichi(d,tk=9,kj=26,sb=52,bbn=20,bbk=2.0):
    h,l,c=d.High,d.Low,d.Close
    tenkan=(h.rolling(tk).max()+l.rolling(tk).min())/2; kijun=(h.rolling(kj).max()+l.rolling(kj).min())/2
    spanA=((tenkan+kijun)/2).shift(kj); spanB=((h.rolling(sb).max()+l.rolling(sb).min())/2).shift(kj)
    ma=c.rolling(bbn).mean(); sd=c.rolling(bbn).std()
    return dict(tenkan=tenkan,kijun=kijun,spanA=spanA,spanB=spanB,up=ma+bbk*sd,lo=ma-bbk*sd,
        cross_up=(tenkan>kijun)&(tenkan.shift(1)<=kijun.shift(1)), cross_dn=(tenkan<kijun)&(tenkan.shift(1)>=kijun.shift(1)),
        above=c>np.maximum(spanA,spanB), below=c<np.minimum(spanA,spanB), chikou_up=c>c.shift(kj))
def backtest(d, rule, exit_rule, max_hold, tf):
    I=ichi(d); c=d.Close; trades=[]; i=0; idx=d.index
    longc={"A":I["cross_up"]&I["above"]&I["chikou_up"]&(c>I["up"]), "B":I["cross_up"]&I["above"]&I["chikou_up"], "E":(I["above"]&~I["above"].shift(1).fillna(False))&I["chikou_up"]}[rule]
    sig=np.where(longc.fillna(False).values)[0]
    pos_until=-1
    for s in sig:
        if s<=pos_until or s+1>=len(c): continue
        e=s+1; entry=c.iloc[e]   # enter next bar close (no lookahead)
        x=None
        for j in range(e+1,min(e+max_hold,len(c)-1)+1):
            if exit_rule=="cloud" and (c.iloc[j]<min(I["spanA"].iloc[j],I["spanB"].iloc[j])): x=j; break
            if exit_rule=="kijun" and (c.iloc[j]<I["kijun"].iloc[j]): x=j; break
            if exit_rule=="cross" and I["cross_dn"].iloc[j]: x=j; break
        if x is None: x=min(e+max_hold,len(c)-1)
        trades.append(dict(entry=idx[e],exit=idx[x],bars=x-e,ret=c.iloc[x]/entry-1))
        pos_until=x
    return pd.DataFrame(trades)
res=[]
for t in ALL:
    d=raw[t].dropna() if isinstance(raw.columns,pd.MultiIndex) else raw
    if len(d)<300: continue
    d=d[d.index>="2020-10-01"]
    bh=d.Close.iloc[-1]/d.Close.iloc[0]-1
    W=d.resample("W-FRI").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
    for tf,frame,mh in (("daily",d,60),("weekly",W,26)):
        for rule in ("A","B","E"):
            for ex in ("cloud","kijun"):
                T=backtest(frame,rule,ex,mh,tf)
                if T.empty: continue
                # time in market and compounded return
                comp=np.prod(1+T.ret)-1
                res.append(dict(ticker=t,group="watch" if t in WATCH else "control",tf=tf,rule=rule,exit=ex,n=len(T),win=(T.ret>0).mean(),avg=T.ret.mean(),med=T.ret.median(),comp=comp,bh=bh,bars_in=T.bars.sum(),bars_total=len(frame),worst=T.ret.min(),best=T.ret.max()))
R=pd.DataFrame(res); R.to_csv("ichi_swing_results.csv",index=False)
pd.set_option("display.width",220)
def pool(g):
    return pd.Series({"tickers":g.ticker.nunique(),"trades":int(g.n.sum()),"win":round((g.win*g.n).sum()/g.n.sum(),3),"avg_ret%":round(100*(g.avg*g.n).sum()/g.n.sum(),2),"median_comp%":round(100*g.comp.median(),1),"median_bh%":round(100*g.bh.median(),1),"beat_bh_share":round((g.comp>g.bh).mean(),2),"time_in_mkt":round(g.bars_in.sum()/g.bars_total.sum(),2)})
print("== pooled by timeframe / rule / exit / group (Oct-2020 .. Oct-2026, long only, enter next close)")
print(R.groupby(["tf","rule","exit","group"]).apply(pool,include_groups=False).to_string())
print("\n== MSTR / ASST / SPY / QQQ detail, rule A (article) and B, daily + weekly, cloud exit")
print(R[(R.ticker.isin(["MSTR","ASST","SPY","QQQ","TSLA","SMCI"]))&(R.exit=="cloud")&(R.rule.isin(["A","B"]))].sort_values(["ticker","tf","rule"])[["ticker","tf","rule","n","win","avg","med","comp","bh","worst","best"]].round(3).to_string(index=False))
# A null: random entries with same hold distribution per ticker (daily, rule B cloud) to see if the rule adds anything over random timing
rng=np.random.default_rng(7); null=[]
for t in ALL:
    d=raw[t].dropna(); d=d[d.index>="2020-10-01"]; c=d.Close
    if len(c)<300: continue
    for _ in range(200):
        e=rng.integers(60,len(c)-61); h=rng.integers(5,40); null.append(c.iloc[e+h]/c.iloc[e]-1)
null=np.array(null); print(f"\nNULL random daily entries, 5-40 day holds, same tickers: n={len(null)} win={(null>0).mean():.3f} avg={100*null.mean():.2f}% median={100*np.median(null):.2f}%")
