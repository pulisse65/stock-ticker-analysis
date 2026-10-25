import pandas as pd, numpy as np, math, warnings; warnings.filterwarnings("ignore")
B=pd.read_pickle("bars1m.pkl")
def wl(k,n,z=1.96):
    if not n: return float("nan")
    p=k/n; return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)
def ichi(d, tk=9, kj=26, sb=52, bbn=20, bbk=2.0):
    h,l,c=d.High,d.Low,d.Close
    tenkan=(h.rolling(tk).max()+l.rolling(tk).min())/2
    kijun=(h.rolling(kj).max()+l.rolling(kj).min())/2
    spanA=((tenkan+kijun)/2).shift(kj)              # cloud as it stands NOW (projected 26 bars ago)
    spanB=((h.rolling(sb).max()+l.rolling(sb).min())/2).shift(kj)
    chikou_up=c>c.shift(kj)                         # lagging span above price 26 bars ago
    ma=c.rolling(bbn).mean(); sd=c.rolling(bbn).std()
    up,lo=ma+bbk*sd, ma-bbk*sd
    cross_up=(tenkan>kijun)&(tenkan.shift(1)<=kijun.shift(1)); cross_dn=(tenkan<kijun)&(tenkan.shift(1)>=kijun.shift(1))
    above=c>np.maximum(spanA,spanB); below=c<np.minimum(spanA,spanB)
    return dict(cross_up=cross_up,cross_dn=cross_dn,above=above,below=below,chikou_up=chikou_up,chikou_dn=~chikou_up,bb_up=c>up,bb_dn=c<lo,inside=(c<=up)&(c>=lo))
def run(tf="1min", tk=9,kj=26,sb=52, horizon_min=15):
    out=[]
    for t,g in B.groupby("ticker"):
        d=g[["Open","High","Low","Close","Volume"]].copy()
        if tf!="1min": d=d.resample(tf).agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
        d=d.between_time("09:30","15:59")
        # continuity across days is fine for a rough test (same as the app's rolling windows)
        I=ichi(d,tk,kj,sb); c=d.Close
        step=int(horizon_min/ (1 if tf=="1min" else int(tf.replace("min",""))))
        f=(c.shift(-step)/c-1)*100
        fwd30=(c.shift(-2*step)/c-1)*100
        et=d.index
        ok=(et.time>=pd.Timestamp("09:45").time())&(et.time<=pd.Timestamp("15:30").time())
        for name,longc,shortc in [
            ("A article: cross+cloud+chikou+BB break", I["cross_up"]&I["above"]&I["chikou_up"]&I["bb_up"], I["cross_dn"]&I["below"]&I["chikou_dn"]&I["bb_dn"]),
            ("B no BB: cross+cloud+chikou", I["cross_up"]&I["above"]&I["chikou_up"], I["cross_dn"]&I["below"]&I["chikou_dn"]),
            ("C BB as filter: cross+cloud+chikou+inside bands", I["cross_up"]&I["above"]&I["chikou_up"]&I["inside"], I["cross_dn"]&I["below"]&I["chikou_dn"]&I["inside"]),
            ("D cloud+BB break only (no cross)", I["above"]&I["chikou_up"]&I["bb_up"]&~I["bb_up"].shift(1).fillna(False), I["below"]&I["chikou_dn"]&I["bb_dn"]&~I["bb_dn"].shift(1).fillna(False)),
        ]:
            for dirn,mask,sign in (("call",longc,1),("put",shortc,-1)):
                m=mask&ok&f.notna()
                for ts in d.index[m.values]:
                    out.append((name,t,dirn,ts,sign*f[ts],sign*fwd30[ts] if pd.notna(fwd30[ts]) else np.nan))
    R=pd.DataFrame(out,columns=["variant","ticker","dir","ts","f15","f30"]); R["net"]=R.f15-0.05; R["win"]=R.net>=0
    return R
def summarize(R,label):
    print(f"\n==== {label}")
    for v,g in R.groupby("variant"):
        for dirn,gg in list(g.groupby("dir"))+[("both",g)]:
            n=len(gg); k=int(gg.win.sum())
            print(f"{v:50s} {dirn:4s} n={n:5d} win={k/n if n else float('nan'):.3f} wl={wl(k,n):.3f} net_mean={gg.net.mean():+.3f} med={gg.net.median():+.3f} f30_mean={(gg.f30-0.05).mean():+.3f} sessions={gg.ts.dt.date.nunique()}")
R1=run("1min"); summarize(R1,"1-minute bars, 15-min horizon, RTH 09:45-15:30, 9/26/52, BB 20/2")
# baseline: every RTH bar, both directions
base=[]
for t,g in B.groupby("ticker"):
    c=g.Close.between_time("09:45","15:30"); f=(c.shift(-15)/c-1)*100
    base.append(pd.DataFrame({"ticker":t,"f15":f}).dropna())
base=pd.concat(base); print(f"\nBASELINE all RTH 1-min bars: n={len(base)} long win(f15>=.05)={(base.f15>=0.05).mean():.3f} short win={(-base.f15>=0.05).mean():.3f} |f15| mean={base.f15.abs().mean():.3f}")
R5=run("5min",horizon_min=15); summarize(R5,"5-minute bars, 15-min horizon (3 bars)")
R10=run("10min",horizon_min=30); summarize(R10,"10-minute bars (article timeframe), 30-min horizon")
A=R1[R1.variant.str.startswith("A")]
print("\nvariant A by ticker (1-min):"); print(A.groupby(["ticker","dir"]).agg(n=("win","size"),win=("win","mean"),net=("net","mean")).round(3).to_string())
print("\nvariant A by hour (1-min):"); print(A.groupby(A.ts.dt.hour).agg(n=("win","size"),win=("win","mean"),net=("net","mean")).round(3).to_string())
R1.to_csv("ichi_bb_signals_1m.csv",index=False)
