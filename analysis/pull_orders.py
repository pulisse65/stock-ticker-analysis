"""Pull closed paper-account option round-trips for every session day found in signals.csv.

Usage:  python analysis/pull_orders.py [output_dir]   (default: ./analysis/data)
Run pull_signals.py first — this reads signals.csv from the same directory for the day list.

Output: orders_raw.json and orders.csv (with ET entry time + day-of-week columns).
"""
import json, os, subprocess, sys, time
import pandas as pd

OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "data")
sig = pd.read_csv(os.path.join(OUT_DIR, "signals.csv"))
days = sorted(sig[sig["scored_from"] == "alerted_at"]["et_date"].unique())

rows = []
for d in days:
    url = f"https://tickertracker.dev/purgatory/orders?date={d}&account=paper"
    out = subprocess.run(["curl", "-s", "--max-time", "60", url], capture_output=True, text=True)
    try:
        data = json.loads(out.stdout)
    except Exception as e:
        print(d, "parse error", e)
        continue
    for o in data.get("orders") or data.get("trades") or []:
        o["_day"] = d
        rows.append(o)
    print(d, len(rows), flush=True)
    time.sleep(0.3)

with open(os.path.join(OUT_DIR, "orders_raw.json"), "w") as f:
    json.dump(rows, f)

df = pd.DataFrame(rows)
ts = pd.to_datetime(df["entry_submitted_at"], utc=True, format="ISO8601", errors="coerce")
et = ts.dt.tz_convert("America/New_York")
df["et_time"] = et.dt.strftime("%H:%M")
df["dow"] = et.dt.day_name()
csv_path = os.path.join(OUT_DIR, "orders.csv")
df.to_csv(csv_path, index=False)
print(f"wrote {len(df)} order rows -> {csv_path}")
