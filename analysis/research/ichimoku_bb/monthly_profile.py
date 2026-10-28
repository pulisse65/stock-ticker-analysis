import yfinance as yf, pandas as pd, numpy as np, warnings; warnings.filterwarnings("ignore")
src=open("ichi_swing.py").read()
exec(src.split("raw=yf.download")[0])            # imports, WATCH/CTRL/ALL
exec("def wl"+src.split("def wl",1)[1].split("res=[]")[0])   # wl, ichi, backtest
raw=yf.download(ALL,period="6y",interval="1d",auto_adjust=True,progress=False,group_by="ticker")
def equity(frame, rule, ex, mh):
    T=backtest(frame,rule,ex,mh,"x"); c=frame.Close; pos=pd.Series(0.0,index=c.index)
    for _,t in T.iterrows(): pos.loc[t.entry:t.exit]=1.0
    r=c.pct_change().fillna(0); return (1+r*pos.shift(1).fillna(0)).cumprod(), (1+r).cumprod(), pos
def stats(eq,label):
    m=eq.resample("ME").last().pct_change().dropna(); q=eq.resample("QE").last().pct_change().dropna()
    dd=(eq/eq.cummax()-1).min(); yrs=(eq.index[-1]-eq.index[0]).days/365.25; cagr=eq.iloc[-1]**(1/yrs)-1
    return dict(label=label,cagr=round(100*cagr,1),months=len(m),pos_months=round((m>0).mean(),2),med_month=round(100*m.median(),1),worst_month=round(100*m.min(),1),best_month=round(100*m.max(),1),pos_qtrs=round((q>0).mean(),2),med_qtr=round(100*q.median(),1),worst_qtr=round(100*q.min(),1),max_dd=round(100*dd,1))
rows=[]
baskets={"QQQ":["QQQ"],"SPY":["SPY"],"MSTR":["MSTR"],"watchlist basket (16, equal weight)":[t for t in WATCH if t!="ASST"],"controls basket (20)":CTRL}
for name,tk in baskets.items():
    for rule,tf in (("E","weekly"),("B","daily")):
        S=[];Bh=[]
        for t in tk:
            d=raw[t].dropna(); d=d[d.index>="2020-10-01"]
            if len(d)<300: continue
            frame=d.resample("W-FRI").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna() if tf=="weekly" else d
            s,b,_=equity(frame,rule,"cloud",26 if tf=="weekly" else 60); S.append(s.pct_change().fillna(0)); Bh.append(b.pct_change().fillna(0))
        S=pd.concat(S,axis=1).mean(axis=1); Bh=pd.concat(Bh,axis=1).mean(axis=1)
        rows.append(stats((1+S).cumprod(),f"{name} | cloud {rule} {tf}"))
        if rule=="E": rows.append(stats((1+Bh).cumprod(),f"{name} | buy & hold"))
pd.set_option("display.width",250); R=pd.DataFrame(rows); print(R.to_string(index=False)); R.to_csv("ichi_monthly.csv",index=False)
# last 12 months, month by month, watchlist basket weekly E vs B&H
S=[];Bh=[]
for t in [t for t in WATCH if t!="ASST"]:
    d=raw[t].dropna(); d=d[d.index>="2020-10-01"]; W=d.resample("W-FRI").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
    s,b,_=equity(W,"E","cloud",26); S.append(s.pct_change().fillna(0)); Bh.append(b.pct_change().fillna(0))
S=(1+pd.concat(S,axis=1).mean(axis=1)).cumprod(); Bh=(1+pd.concat(Bh,axis=1).mean(axis=1)).cumprod()
m=pd.DataFrame({"cloud_E_weekly%":100*S.resample("ME").last().pct_change(),"buy_hold%":100*Bh.resample("ME").last().pct_change()}).dropna().tail(13).round(1)
print("\nlast 13 months, watchlist basket:"); print(m.to_string())
