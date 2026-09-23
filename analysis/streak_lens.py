"""Streak lens — does a pair's recent hot/cold record predict its NEXT signals?

Usage:  python analysis/streak_lens.py [data_dir]   (default: ./analysis/data)
Reads signals.csv + orders.csv (from pull_signals.py / pull_orders.py) and writes:
  streak_persistence.csv — platform-wide tables: trailing-10 bucket / streak length / EWMA
                           momentum -> next-signal and next-5 win rates vs each pair's own base
  streak_pairs.csv       — every pair's CURRENT streak position (consecutive wins, trailing-10,
                           EWMA, signals since trailing-10 was last below 60%, ride phase)
  streak_lens.md         — the same, rendered for the sweep agents

Method (pre-registered 2026-09-23 from a one-off test, see analysis/README.md):
  * honest rows only (scored_from == 'alerted_at'); win = outcome == 'win'; wr = W/(W+L+F)
  * for every signal of every pair with >= MIN_PAIR_N signals, the pair's state is measured
    BEFORE that signal fires (trailing-10 win rate, consecutive wins, EWMA half-life 8), then
    compared with the outcome of that signal (next1) and the next five (next5)
  * "excess" = next1 win rate minus the pair's own all-time win rate — a momentum effect must
    beat the pair's base rate, not the platform's
  * hot regime = trailing-10 >= HOT; it "ends" when trailing-10 drops below COOL
  * ride phase (purgatory finding, n small — a hypothesis, not a rule):
      early = 2-3 consecutive wins, mid = 4-5, late = 6+, none otherwise
Wilson 95% lower bounds are printed next to every bucket rate so thin cells are visibly thin.
"""
import math, os, sys
import numpy as np
import pandas as pd

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "data")
MIN_PAIR_N, HOT, COOL, HALF_LIFE, SPREAD = 15, 0.80, 0.60, 8, 0.05


def wilson_lo(k, n, z=1.96):
    if n <= 0:
        return 0.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    adj = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - adj) / den)


def ewma(xs, hl=HALF_LIFE):
    a = 1 - 0.5 ** (1 / hl)
    out, m = [], None
    for v in xs:
        m = v if m is None else a * v + (1 - a) * m
        out.append(m)
    return out


def phase_of(streak):
    if 2 <= streak <= 3:
        return "early"
    if 4 <= streak <= 5:
        return "mid"
    if streak >= 6:
        return "late"
    return "none"


s = pd.read_csv(os.path.join(DATA, "signals.csv"))
s = s[s.scored_from == "alerted_at"].copy()
s["bar_time"] = pd.to_datetime(s.bar_time, utc=True)
s = s.sort_values("bar_time")
s["win"] = (s.outcome == "win").astype(int)
s["nf15"] = s.f15 - SPREAD
try:
    o = pd.read_csv(os.path.join(DATA, "orders.csv"))
    o["bar_time"] = pd.to_datetime(o.bar_time, utc=True)
except FileNotFoundError:
    o = pd.DataFrame(columns=["strategy", "ticker", "direction", "bar_time", "pnl", "exit_reason"])

states, pairs, durations = [], [], []
for (st, tk, dr), g in s.groupby(["strategy", "ticker", "direction"]):
    g = g.sort_values("bar_time").reset_index(drop=True)
    w, nf = g.win.values, g.nf15.values
    base = w.mean()
    tr10_after = pd.Series(w).rolling(10).mean().values            # trailing-10 INCLUDING this signal
    tr10 = pd.Series(tr10_after).shift(1).values                   # ... BEFORE this signal
    ew_after = np.array(ewma(w))
    ew = pd.Series(ew_after).shift(1).values
    streak_before, c = [], 0
    for v in w:
        streak_before.append(c)
        c = c + 1 if v == 1 else 0
    streak_now = c
    if len(g) >= MIN_PAIR_N:
        for i in range(len(g)):
            if np.isnan(tr10[i]):
                continue
            n5 = w[i:i + 5]
            states.append(dict(pair=f"{st}:{tk}:{dr}", strategy=st, base=base, tr10=tr10[i], ew=ew[i],
                               streak=streak_before[i], next1=w[i], next1_nf=nf[i],
                               next5=n5.mean() if len(n5) == 5 else np.nan,
                               next5_nf=nf[i:i + 5].mean() if len(n5) == 5 else np.nan))
        # hot-regime episodes (measured on trailing-10 before each signal)
        i = 0
        while i < len(tr10):
            if not np.isnan(tr10[i]) and tr10[i] >= HOT:
                j = i
                while j < len(tr10) and tr10[j] >= COOL:
                    j += 1
                durations.append(dict(pair=f"{st}:{tk}:{dr}", start=str(g.et_date[i]), length=(j - i) if j < len(tr10) else np.nan))
                i = j
            else:
                i += 1
    # current position
    hot_since = None
    if len(g) >= 10 and tr10_after[-1] >= COOL:
        k = len(g) - 1
        while k >= 0 and not np.isnan(tr10_after[k]) and tr10_after[k] >= COOL:
            k -= 1
        hot_since = len(g) - 1 - k
    fills = o[(o.strategy == st) & (o.ticker == tk) & (o.direction == dr)]
    pairs.append(dict(pair=f"{st}:{tk}:{dr}", strategy=st, ticker=tk, direction=dr, n=len(g),
                      base_wr=round(base, 3), wilson_lo=round(wilson_lo(int(w.sum()), len(g)), 3),
                      net_f15=round(float(np.nanmean(nf)), 3),
                      trailing10_wr=None if np.isnan(tr10_after[-1]) else round(float(tr10_after[-1]), 2),
                      ewma_wr=round(float(ew_after[-1]), 2), momentum=round(float(ew_after[-1] - base), 2),
                      consecutive_wins=streak_now, ride_phase=phase_of(streak_now),
                      signals_since_cooled=hot_since, last_signal=str(g.et_date.iloc[-1]),
                      last_10=''.join('W' if x == 'win' else 'L' if x == 'loss' else 'F' for x in g.outcome.values[-10:]),
                      paper_fills=len(fills), paper_pnl=round(float(fills.pnl.sum()), 0) if len(fills) else 0.0,
                      paper_stops=int((fills.exit_reason == 'stop_loss').sum()) if len(fills) else 0))

m = pd.DataFrame(states)
P = pd.DataFrame(pairs).sort_values(["ride_phase", "wilson_lo"], key=lambda c: c.map({"early": 0, "mid": 1, "late": 2, "none": 3}) if c.name == "ride_phase" else -c)
D = pd.DataFrame(durations)


def bucket_table(df, col, edges, labels):
    df = df.assign(b=pd.cut(df[col], edges, labels=labels))
    t = df.groupby("b", observed=True).agg(n=("next1", "size"), next1_wins=("next1", "sum"), next1_wr=("next1", "mean"),
                                           next5_wr=("next5", "mean"), next5_net_f15=("next5_nf", "mean"), pair_base=("base", "mean"))
    t["next1_wilson_lo"] = [wilson_lo(int(k), int(n)) for k, n in zip(t.next1_wins, t.n)]
    t["excess_vs_base"] = t.next1_wr - t.pair_base
    return t.round(3)


tables = []
for scope, sub in [("all_strategies", m), ("purgatory", m[m.strategy == "purgatory"])]:
    if sub.empty:
        continue
    t = bucket_table(sub, "tr10", [-0.01, 0.39, 0.59, 0.79, 1.0], ["cold <40%", "mid 40-59%", "warm 60-79%", "hot >=80%"])
    t.insert(0, "test", "trailing10"); t.insert(0, "scope", scope); tables.append(t.reset_index())
    t = bucket_table(sub, "streak", [-1, 0, 1, 2, 3, 5, 99], ["0", "1", "2", "3", "4-5", "6+"])
    t.insert(0, "test", "consecutive_wins"); t.insert(0, "scope", scope); tables.append(t.reset_index())
    t = bucket_table(sub.assign(mom=sub.ew - sub.base), "mom", [-1, -0.15, -0.05, 0.05, 0.15, 1], ["<-.15", "-.15..-.05", "-.05..+.05", "+.05..+.15", ">+.15"])
    t.insert(0, "test", "ewma_momentum"); t.insert(0, "test_note", "ewma - pair base"); t.insert(0, "scope", scope); tables.append(t.reset_index())
T = pd.concat(tables, ignore_index=True)

T.to_csv(os.path.join(DATA, "streak_persistence.csv"), index=False)
P.to_csv(os.path.join(DATA, "streak_pairs.csv"), index=False)

ended = D.length.dropna() if len(D) else pd.Series(dtype=float)
lines = ["# Streak lens", "",
         f"Signal-states: {len(m)} across {m.pair.nunique() if len(m) else 0} pairs with >= {MIN_PAIR_N} honest signals; "
         f"data through {s.et_date.max()}.", "",
         "A momentum effect must beat the pair's OWN base rate (excess_vs_base), not the platform's.", ""]
for scope in T.scope.unique():
    for test in T[T.scope == scope].test.unique():
        sub = T[(T.scope == scope) & (T.test == test)]
        lines += [f"## {scope} — {test}", "",
                  "| state before signal | n | next1 wr | wilson lo | next5 wr | next5 net_f15 | pair base | excess |",
                  "|---|---|---|---|---|---|---|---|"]
        for _, r in sub.iterrows():
            lines.append(f"| {r.b} | {int(r.n)} | {r.next1_wr:.3f} | {r.next1_wilson_lo:.2f} | {r.next5_wr:.3f} | {r.next5_net_f15:+.3f} | {r.pair_base:.3f} | {r.excess_vs_base:+.3f} |")
        lines.append("")
lines += ["## Hot-regime lifespan", "",
          f"Episodes where trailing-10 reached >= {HOT:.0%}: {len(D)}; ended (fell below {COOL:.0%}): {int(ended.size)}; still hot: {int(D.length.isna().sum()) if len(D) else 0}.",
          (f"Ended-episode length in signals: median {ended.median():.1f}, mean {ended.mean():.1f}, min {ended.min():.0f}, max {ended.max():.0f}." if ended.size else ""), "",
          "## Current streak position, every pair (early = 2-3 consecutive wins, mid = 4-5, late = 6+)", "",
          "| pair | n | base wr | wilson lo | net_f15 | trailing10 | ewma | mom | consec wins | phase | signals since trailing-10 was last <60% | last 10 (old→new) | paper fills / pnl / stops | last signal |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
for _, r in P[P.n >= 8].iterrows():
    lines.append(f"| {r.pair} | {r.n} | {r.base_wr:.2f} | {r.wilson_lo:.2f} | {r.net_f15:+.3f} | {'' if r.trailing10_wr is None or pd.isna(r.trailing10_wr) else f'{r.trailing10_wr:.2f}'} | {r.ewma_wr:.2f} | {r.momentum:+.2f} | {r.consecutive_wins} | {r.ride_phase} | {'' if r.signals_since_cooled is None or pd.isna(r.signals_since_cooled) else int(r.signals_since_cooled)} | {r.last_10} | {r.paper_fills} / {r.paper_pnl:+.0f} / {r.paper_stops} | {r.last_signal} |")
lines += ["", "Reading guide: 'hot >=80%' excess near zero or negative = a hot record does not persist; the 'early' phase bump is the only",
          "pattern seen on 9/23 (purgatory, n=33/29) and must be re-tested here, not assumed. Never nominate on streak alone."]
md = "\n".join(lines)
open(os.path.join(DATA, "streak_lens.md"), "w").write(md)
print(md)
