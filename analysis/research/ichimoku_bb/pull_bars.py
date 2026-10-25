import yfinance as yf, pandas as pd, numpy as np, math, warnings, datetime as dt
warnings.filterwarnings("ignore")
TICKERS=['AAPL','AMZN','ASST','AVGO','INTC','IWM','META','MSFT','MSTR','NOK','ORCL','QCOM','QQQ','SMCI','SPCX','TSLA','TSLL']
end=dt.datetime.now(); frames=[]
for t in TICKERS:
    parts=[]
    for k in range(4):
        e=end-dt.timedelta(days=7*k); s=e-dt.timedelta(days=7)
        try:
            d=yf.download(t,start=s.strftime("%Y-%m-%d"),end=(e+dt.timedelta(days=1)).strftime("%Y-%m-%d"),interval="1m",progress=False,auto_adjust=False)
        except Exception as ex: print(t,"err",ex); continue
        if d is None or d.empty: continue
        if isinstance(d.columns,pd.MultiIndex): d.columns=d.columns.get_level_values(0)
        parts.append(d)
    if not parts: print(t,"no data"); continue
    d=pd.concat(parts).sort_index(); d=d[~d.index.duplicated()]
    d.index=d.index.tz_convert("America/New_York"); d["ticker"]=t; frames.append(d)
    print(t, len(d), d.index.min().date(), d.index.max().date(), flush=True)
pd.concat(frames).to_pickle("bars1m.pkl"); print("saved")
