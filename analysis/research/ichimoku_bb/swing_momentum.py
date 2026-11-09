import yfinance as yf, pandas as pd, numpy as np, warnings; warnings.filterwarnings("ignore")
WATCH=['AAPL','AMZN','AVGO','INTC','IWM','META','MSFT','MSTR','NOK','ORCL','QCOM','QQQ','SMCI','SPCX','TSLA','TSLL']
CTRL=['SPY','NVDA','GOOGL','JPM','XOM','COIN','PLTR','AMD','NFLX','BA','DIS','PFE','KO','WMT','UNH','CAT','GS','HOOD','RIOT','MARA']
def load(tk):
    raw=yf.download(tk,period="6y",interval="1d",auto_adjust=True,progress=False,group_by="ticker")
    W={}
    for t in tk:
        d=raw[t].dropna()
        if len(d)<300: continue
        W[t]=d.resample("W-FRI").agg({"High":"max","Low":"min","Close":"last"}).dropna()
    return W
def feats(w):
    h,l,c=w.High,w.Low,w.Close
    tenkan=(h.rolling(9).max()+l.rolling(9).min())/2; kijun=(h.rolling(26).max()+l.rolling(26).min())/2
    spanA=((tenkan+kijun)/2).shift(26); spanB=((h.rolling(52).max()+l.rolling(52).min())/2).shift(26)
    above=c>np.maximum(spanA,spanB); chik=c>c.shift(26)
    return pd.DataFrame({"close":c,"above":above,"chik":chik,"mom12":c/c.shift(12)-1,"mom26":c/c.shift(26)-1,"kijun":kijun})
def run(W, topn=5, mom="mom12", require_cloud=True, buffer=3, start="2020-10-01", exit_kijun=False):
    F={t:feats(w) for t,w in W.items()}
    idx=sorted(set().union(*[f.index for f in F.values()])); idx=[d for d in idx if d>=pd.Timestamp(start)]
    hold=set(); eq=[1.0]; dates=[idx[0]]; turn=0
    for i in range(1,len(idx)):
        d0,d1=idx[i-1],idx[i]
        # decide at d0 close, earn d0->d1
        cands=[]
        for t,f in F.items():
            if d0 not in f.index or pd.isna(f.loc[d0,mom]): continue
            ok=(f.loc[d0,"above"] and f.loc[d0,"chik"]) if require_cloud else True
            if ok: cands.append((f.loc[d0,mom],t))
        cands.sort(reverse=True); ranked=[t for _,t in cands]
        keep={t for t in hold if t in ranked[:topn+buffer]}
        for t in ranked:
            if len(keep)>=topn: break
            keep.add(t)
        turn+=len(keep-hold)+len(hold-keep); hold=keep
        r=0.0
        for t in hold:
            f=F[t]
            if d0 in f.index and d1 in f.index: r+=(f.loc[d1,"close"]/f.loc[d0,"close"]-1)/topn
        eq.append(eq[-1]*(1+r)); dates.append(d1)
    s=pd.Series(eq,index=dates); yrs=(s.index[-1]-s.index[0]).days/365.25
    m=s.resample("ME").last().pct_change().dropna()
    return dict(cagr=round(100*(s.iloc[-1]**(1/yrs)-1),1),maxdd=round(100*(s/s.cummax()-1).min(),1),pos_months=round((m>0).mean(),2),worst_month=round(100*m.min(),1),y2022=round(100*(s["2022-12-31":].iloc[0]/s[:"2021-12-31"].iloc[-1]-1),1) if len(s[:"2021-12-31"]) else None,turn_per_wk=round(turn/len(idx),2)), s
def bh(W,tk,start="2020-10-01"):
    R=pd.concat([W[t].Close.pct_change() for t in tk if t in W],axis=1).fillna(0); R=R[R.index>=start]; s=(1+R.mean(axis=1)).cumprod(); yrs=(s.index[-1]-s.index[0]).days/365.25; m=s.resample("ME").last().pct_change().dropna()
    return dict(cagr=round(100*(s.iloc[-1]**(1/yrs)-1),1),maxdd=round(100*(s/s.cummax()-1).min(),1),pos_months=round((m>0).mean(),2),worst_month=round(100*m.min(),1),y2022=round(100*(s["2022-12-31":].iloc[0]/s[:"2021-12-31"].iloc[-1]-1),1))
W=load(sorted(set(WATCH+CTRL)))
rows=[]
for uni_name,uni in (("watchlist16",WATCH),("all36",WATCH+CTRL)):
    Wu={t:W[t] for t in uni if t in W}
    rows.append(dict(universe=uni_name,variant="buy&hold equal weight",**bh(Wu,uni)))
    for topn in (3,5,8):
        for mom in ("mom12","mom26"):
            for rc in (True,False):
                st,_=run(Wu,topn=topn,mom=mom,require_cloud=rc); rows.append(dict(universe=uni_name,variant=f"top{topn} {mom} cloud={rc}",**st))
    st,_=run(Wu,topn=99,mom="mom12",require_cloud=True); rows.append(dict(universe=uni_name,variant="all above cloud, equal weight",**st))
pd.set_option("display.width",220); R=pd.DataFrame(rows); print(R.to_string(index=False)); R.to_csv("swing_mom_results.csv",index=False)
# rolling 13-week windows: how often does top5/mom12/cloud beat SPY over a quarter?
Wu={t:W[t] for t in WATCH+CTRL if t in W}; _,s=run(Wu,5,"mom12",True); spy=W["SPY"].Close[W["SPY"].Close.index>="2020-10-01"]; spy=spy/spy.iloc[0]
q=pd.DataFrame({"strat":s,"spy":spy}).dropna(); r13=q.pct_change(13).dropna()
print(f"\n13-week windows n={len(r13)}: strat median {100*r13.strat.median():.1f}% vs SPY {100*r13.spy.median():.1f}% | strat>SPY {(r13.strat>r13.spy).mean():.2f} | strat>0 {(r13.strat>0).mean():.2f} | SPY>0 {(r13.spy>0).mean():.2f}")
r52=q.pct_change(52).dropna(); print(f"52-week windows n={len(r52)}: strat median {100*r52.strat.median():.1f}% vs SPY {100*r52.spy.median():.1f}% | strat>SPY {(r52.strat>r52.spy).mean():.2f} | strat>0 {(r52.strat>0).mean():.2f}")
