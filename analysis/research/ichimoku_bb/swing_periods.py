import yfinance as yf, pandas as pd, numpy as np, warnings; warnings.filterwarnings("ignore")
exec(open("ichi_swing.py").read().split("res=[]")[0].split("raw=yf.download")[0])  # imports + lists + helpers
raw=yf.download(ALL,period="6y",interval="1d",auto_adjust=True,progress=False,group_by="ticker")
exec("def wl" + open("ichi_swing.py").read().split("def wl",1)[1].split("res=[]")[0])
def equity(frame, rule, exit_rule, mh):
    T=backtest(frame,rule,exit_rule,mh,"x"); c=frame.Close
    pos=pd.Series(0.0,index=c.index)
    for _,t in T.iterrows(): pos.loc[t.entry:t.exit]=1.0
    r=c.pct_change().fillna(0); strat=(1+r*pos.shift(1).fillna(0)).cumprod(); bh=(1+r).cumprod()
    return strat,bh,T
rows=[]
for t in ALL:
    d=raw[t].dropna(); d=d[d.index>="2020-10-01"]
    if len(d)<300: continue
    W=d.resample("W-FRI").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
    for tf,frame,mh,rule,ex in (("daily",d,60,"B","cloud"),("weekly",W,26,"E","cloud"),("weekly",W,26,"B","cloud")):
        s,b,T=equity(frame,rule,ex,mh)
        for per,(a,z) in {"2022 bear":("2022-01-01","2022-12-31"),"2023-26 bull":("2023-01-01","2026-12-31"),"full":("2020-10-01","2026-12-31")}.items():
            ss=s[a:z]; bb=b[a:z]
            if len(ss)<5: continue
            sr=ss.iloc[-1]/ss.iloc[0]-1; br=bb.iloc[-1]/bb.iloc[0]-1
            sdd=(ss/ss.cummax()-1).min(); bdd=(bb/bb.cummax()-1).min()
            rows.append(dict(ticker=t,group="watch" if t in WATCH else "control",tf=tf,rule=rule,period=per,strat=sr,bh=br,strat_dd=sdd,bh_dd=bdd))
R=pd.DataFrame(rows); pd.set_option("display.width",200)
def pool(g): return pd.Series({"tickers":g.ticker.nunique(),"strat_med%":round(100*g.strat.median(),1),"bh_med%":round(100*g.bh.median(),1),"beat_bh":round((g.strat>g.bh).mean(),2),"strat_dd_med%":round(100*g.strat_dd.median(),1),"bh_dd_med%":round(100*g.bh_dd.median(),1)})
print(R.groupby(["tf","rule","period","group"]).apply(pool,include_groups=False).to_string())
print("\nMSTR / SPY / QQQ by period, weekly E:"); print(R[(R.ticker.isin(["MSTR","SPY","QQQ","TSLA"]))&(R.rule=="E")].round(3).to_string(index=False))
R.to_csv("ichi_swing_periods.csv",index=False)
