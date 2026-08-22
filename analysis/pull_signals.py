"""Pull every persisted signal from production with offset paging; save raw JSON + flat CSV.

Usage:  python analysis/pull_signals.py [output_dir]   (default: ./analysis/data)

Output: signals_raw.json (full records) and signals.csv (flat, with ET time columns).
Only rows with scored_from == 'alerted_at' are honestly scored — filter on that in analysis.
"""
import json, os, subprocess, sys, time

BASE = "https://tickertracker.dev/purgatory/signals"
OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "data")
os.makedirs(OUT_DIR, exist_ok=True)

rows, offset = [], 0
while True:
    url = f"{BASE}?limit=1000&offset={offset}"
    out = subprocess.run(["curl", "-s", "--max-time", "60", url], capture_output=True, text=True, check=True)
    batch = json.loads(out.stdout).get("signals", [])
    rows.extend(batch)
    print(f"offset {offset}: +{len(batch)} (total {len(rows)})", flush=True)
    if len(batch) < 1000:
        break
    offset += 1000
    time.sleep(0.5)

with open(os.path.join(OUT_DIR, "signals_raw.json"), "w") as f:
    json.dump(rows, f)

import pandas as pd

flat = []
for s in rows:
    meta = s.get("meta") or {}
    plan = meta.get("plan") or {}
    flat.append({
        "strategy": s.get("strategy"),
        "ticker": s.get("ticker"),
        "direction": s.get("signal"),
        "bar_time": s.get("bar_time"),
        "alerted_at": s.get("alerted_at"),
        "price": s.get("price"),
        "scored_from": s.get("scored_from"),
        "outcome": s.get("outcome"),
        "f5": s.get("favorable_5m"),
        "f10": s.get("favorable_10m"),
        "f15": s.get("favorable_15m"),
        "f20": s.get("favorable_20m"),
        "f25": s.get("favorable_25m"),
        "f30": s.get("favorable_30m"),
        "plan_outcome": plan.get("outcome"),
        "plan_net_pct": plan.get("net_pct"),
        "plan_exit_reason": plan.get("exit_reason"),
    })

df = pd.DataFrame(flat)
df["alerted_at"] = pd.to_datetime(df["alerted_at"], utc=True, format="ISO8601")
et = df["alerted_at"].dt.tz_convert("America/New_York")
df["et_date"] = et.dt.date.astype(str)
df["et_time"] = et.dt.strftime("%H:%M")
df["et_hour"] = et.dt.hour
df["et_minute"] = et.dt.minute
df["dow"] = et.dt.day_name()
csv_path = os.path.join(OUT_DIR, "signals.csv")
df.to_csv(csv_path, index=False)
print(f"wrote {len(df)} rows -> {csv_path}")
print("honest-scored (scored_from=alerted_at):", (df["scored_from"] == "alerted_at").sum())
print(df["outcome"].value_counts(dropna=False).to_dict())
print("date range:", df["et_date"].min(), "->", df["et_date"].max())
