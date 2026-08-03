"""Synthetic-bar tests for the four new strategy detectors."""
import os, sys
os.environ.setdefault("OPENROUTER_API_KEY", "x")
sys.path.insert(0, "/Users/paululisse/Documents/Stock Ticker Analysis")
import main
import pandas as pd

# 2026-07-08 is EDT: 9:30 ET = 13:30 UTC
BASE = pd.Timestamp("2026-07-08T13:30:00Z")

def mk_bar(i_min, o, h, l, c, v):
    t = (BASE + pd.Timedelta(minutes=i_min)).isoformat().replace("+00:00", "Z")
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "vw": (h + l + c) / 3}

def flat_bars(start, n, px=100.0, amp=0.05, v=1000):
    out = []
    for i in range(n):
        c = px + (amp if i % 2 == 0 else -amp)
        out.append(mk_bar(start + i, px, px + amp, px - amp, c, v))
    return out

passed = failed = 0
def check(name, cond, detail=""):
    global passed, failed
    if cond: passed += 1; print(f"  ok   {name}")
    else:    failed += 1; print(f"  FAIL {name} {detail}")

# ---------------- ORB ----------------
print("ORB:")
# 9:30-9:44 opening range ~99.5-100.5 (1.0%), then inside bars, then 10:00 breakout
bars = flat_bars(0, 15, px=100.0, amp=0.5)              # OR: h=100.5 l=99.5
bars += flat_bars(15, 14, px=100.0, amp=0.2)            # 9:45-9:58 inside
bars.append(mk_bar(30, 100.2, 100.9, 100.1, 100.8, 2000))  # 10:00 breakout, 2x vol
ctx = main._build_intraday_context(bars)
sig = main._check_orb_signal("TEST", ctx)
check("fires call on textbook breakout", sig is not None and sig["signal"] == "call",
      f"got {sig}")
if sig:
    check("meta or_high/or_range", abs(sig["meta"]["or_high"] - 100.5) < 1e-6
          and 0.9 < sig["meta"]["or_range_pct"] < 1.1, str(sig["meta"]))
    check("strategy/window fields", sig["strategy"] == "orb" and sig["window"], str(sig))

# stale: one more bar after the breakout — first-breakout is no longer last
bars2 = bars + [mk_bar(31, 100.8, 101.0, 100.7, 100.9, 2000)]
check("no fire when breakout is stale", main._check_orb_signal("TEST", main._build_intraday_context(bars2)) is None)

# low volume breakout
bars3 = bars[:-1] + [mk_bar(30, 100.2, 100.9, 100.1, 100.8, 1200)]
check("no fire on weak volume", main._check_orb_signal("TEST", main._build_intraday_context(bars3)) is None)

# after cutoff (11:00 = minute 90)
bars4 = flat_bars(0, 15, px=100.0, amp=0.5) + flat_bars(15, 76, px=100.0, amp=0.2)
bars4.append(mk_bar(91, 100.2, 100.9, 100.1, 100.8, 2000))
check("no fire after 11:00 ET", main._check_orb_signal("TEST", main._build_intraday_context(bars4)) is None)

# OR range too narrow (0.04%)
bars5 = flat_bars(0, 15, px=100.0, amp=0.02) + flat_bars(15, 14, px=100.0, amp=0.01)
bars5.append(mk_bar(30, 100.0, 100.3, 100.0, 100.25, 2000))
check("no fire when OR range < 0.10%", main._check_orb_signal("TEST", main._build_intraday_context(bars5)) is None)

# put side
bars6 = flat_bars(0, 15, px=100.0, amp=0.5) + flat_bars(15, 14, px=100.0, amp=0.2)
bars6.append(mk_bar(30, 99.8, 99.9, 99.1, 99.2, 2000))
sig6 = main._check_orb_signal("TEST", main._build_intraday_context(bars6))
check("fires put on downside break", sig6 is not None and sig6["signal"] == "put", f"got {sig6}")

# ---------------- VWAP reversion ----------------
print("VWAP-R:")
# Flat chop 9:30 → 11:05 then a fresh 2σ up-stretch → PUT
bars = flat_bars(0, 96, px=100.0, amp=0.05)             # through 11:05 (mins 570..665)
bars.append(mk_bar(96, 100.0, 100.5, 100.0, 100.45, 1000))   # 11:06 stretch up
ctx = main._build_intraday_context(bars)
sig = main._check_vwap_reversion_signal("TEST", ctx)
check("fires put on fresh 2σ up-stretch", sig is not None and sig["signal"] == "put", f"got {sig}")
if sig:
    check("deviation > 2σ in meta", sig["meta"]["deviation_sigma"] >= 2.0, str(sig["meta"]))
    check("day_move small", abs(sig["meta"]["day_move_pct"]) <= 0.5, str(sig["meta"]))

# same stretch but before 11:00 → no fire
bars_b = flat_bars(0, 80, px=100.0, amp=0.05)
bars_b.append(mk_bar(80, 100.0, 100.5, 100.0, 100.45, 1000))  # 10:50
check("no fire before 11:00", main._check_vwap_reversion_signal("TEST", main._build_intraday_context(bars_b)) is None)

# trend day → no fire (ramp 100 -> 101.2 = +1.2%)
bars_c = []
for i in range(97):
    px = 100.0 + i * 0.0125
    bars_c.append(mk_bar(i, px, px + 0.05, px - 0.05, px, 1000))
bars_c.append(mk_bar(97, 101.2, 101.8, 101.2, 101.75, 1000))
check("no fire on trend day", main._check_vwap_reversion_signal("TEST", main._build_intraday_context(bars_c)) is None)

# down-stretch → CALL
bars_d = flat_bars(0, 96, px=100.0, amp=0.05)
bars_d.append(mk_bar(96, 100.0, 100.0, 99.5, 99.55, 1000))
sig_d = main._check_vwap_reversion_signal("TEST", main._build_intraday_context(bars_d))
check("fires call on down-stretch", sig_d is not None and sig_d["signal"] == "call", f"got {sig_d}")

# ---------------- EMA pullback ----------------
print("EMA-PB:")
# Phase 1: steady ramp to establish ema9>ema30>vwap
ramp = []
for i in range(70):
    px = 100.0 + i * 0.05
    ramp.append(mk_bar(i, px, px + 0.06, px - 0.03, px + 0.02, 1000))
# Determine current EMAs to place the pullback precisely
ctx_r = main._build_intraday_context(ramp)
row = ctx_r["today"].iloc[-1]
e9, e30 = float(row["ema9"]), float(row["ema30"])
assert e9 > e30 > float(row["vwap"]), "ramp failed to establish trend"
# Phase 2: 3-bar orderly pullback — close below ema9, above ema30, volume 500
pb_px = (e9 + e30) / 2
pull = [mk_bar(70 + j, pb_px + 0.02, pb_px + 0.05, pb_px - 0.03, pb_px, 500) for j in range(3)]
# Phase 3: trigger — close back above ema9 and above prior bar high, normal volume
trig_c = e9 + 0.30
trig = [mk_bar(73, pb_px, trig_c + 0.05, pb_px - 0.01, trig_c, 1100)]
bars = ramp + pull + trig
sig = main._check_ema_pullback_signal("TEST", main._build_intraday_context(bars))
check("fires call on pullback recross", sig is not None and sig["signal"] == "call", f"got {sig}")
if sig:
    check("meta trend/pullback fields", sig["meta"]["trend_bars"] >= main.EMA_PB_TREND_BARS
          and sig["meta"]["pullback_vol_ratio"] < 1.0, str(sig["meta"]))

# same but pullback volume HIGH (unhealthy) → no fire
pull_hot = [mk_bar(70 + j, pb_px + 0.02, pb_px + 0.05, pb_px - 0.03, pb_px, 1500) for j in range(3)]
bars_h = ramp + pull_hot + trig
check("no fire when pullback volume is high", main._check_ema_pullback_signal("TEST", main._build_intraday_context(bars_h)) is None)

# no trend (flat day) → no fire
flat = flat_bars(0, 74, px=100.0, amp=0.05)
check("no fire without established trend", main._check_ema_pullback_signal("TEST", main._build_intraday_context(flat)) is None)

# ---------------- BB squeeze ----------------
print("BB-SQZ:")
# 60 noisy bars → 75 ultra-tight bars → volume breakout above band + vwap
noisy = flat_bars(0, 60, px=100.0, amp=0.30)
tight = flat_bars(60, 75, px=100.0, amp=0.02)
brk = [mk_bar(135, 100.02, 100.7, 100.0, 100.6, 2000)]
bars = noisy + tight + brk
sig = main._check_bb_squeeze_signal("TEST", main._build_intraday_context(bars))
check("fires call on squeeze breakout", sig is not None and sig["signal"] == "call", f"got {sig}")
if sig:
    check("meta squeeze_bars >= 10", sig["meta"]["squeeze_bars"] >= 10, str(sig["meta"]))
    check("meta vol_ratio >= 1.5", sig["meta"]["vol_ratio"] >= 1.5, str(sig["meta"]))

# weak volume → no fire
brk_lo = [mk_bar(135, 100.02, 100.7, 100.0, 100.6, 1100)]
check("no fire on weak volume", main._check_bb_squeeze_signal("TEST", main._build_intraday_context(noisy + tight + brk_lo)) is None)

# no squeeze (still noisy) → no fire
brk2 = [mk_bar(135, 100.3, 101.2, 100.2, 101.1, 2000)]
check("no fire without squeeze", main._check_bb_squeeze_signal("TEST", main._build_intraday_context(noisy + flat_bars(60, 75, px=100.0, amp=0.30) + brk2)) is None)

# ---------------- cooldown + filters ----------------
print("cooldown/filters:")
main._strategy_last_fired.clear()
check("cooldown allows first fire", main._strategy_cooldown_ok("orb", "TEST", "call"))
main._strategy_mark_fired("orb", "TEST", "call")
check("cooldown blocks refire", not main._strategy_cooldown_ok("orb", "TEST", "call"))
check("cooldown per-direction for orb", main._strategy_cooldown_ok("orb", "TEST", "put"))
main._strategy_mark_fired("bb_squeeze", "TEST", "call")
check("bb cooldown is per-ticker", not main._strategy_cooldown_ok("bb_squeeze", "TEST", "put"))
check("purgatory has no cooldown", main._strategy_cooldown_ok("purgatory", "TEST", "call"))

sig_fake = {"strategy": "ema_pullback", "ticker": "X", "signal": "call", "window": "open_first_15"}
check("skip-window blocks ema_pullback at open", not main._passes_common_strategy_filters(sig_fake))
sig_fake2 = {"strategy": "vwap_reversion", "ticker": "X", "signal": "call", "window": "lunch_chop"}
check("vwap_reversion allowed in lunch chop", main._passes_common_strategy_filters(sig_fake2))



# ---------------- PD-LVL (prev-day level break + hold) ----------------
print("PD-LVL:")
import pandas as _pd
_today_et = _pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d")
main._pd_levels_cache = (_today_et, {"TEST": (100.6, 99.4)})

# 40 flat bars around 100, then a volume break above PDH 100.6
base = flat_bars(0, 40, px=100.0, amp=0.05)
brk = [mk_bar(40, 100.05, 100.9, 100.0, 100.8, 1500)]
sig = main._check_pd_level_signal("TEST", main._build_intraday_context(base + brk))
check("fires call on first PDH break", sig is not None and sig["signal"] == "call", f"got {sig}")
if sig:
    check("meta level/dist", abs(sig["meta"]["level"] - 100.6) < 1e-6 and sig["meta"]["dist_pct"] > 0, str(sig["meta"]))

# weak volume → no fire
brk_lo = [mk_bar(40, 100.05, 100.9, 100.0, 100.8, 1100)]
check("no fire on weak volume", main._check_pd_level_signal("TEST", main._build_intraday_context(base + brk_lo)) is None)

# not the FIRST break of the day → no fire (earlier bar already closed above)
early = flat_bars(0, 20, px=100.0, amp=0.05)
early_brk = [mk_bar(20, 100.05, 100.9, 100.0, 100.8, 1500)]      # first break, earlier
back_in = flat_bars(21, 19, px=100.0, amp=0.05)
re_brk = [mk_bar(40, 100.05, 100.9, 100.0, 100.8, 1500)]         # re-cross later
check("no fire on a re-cross (first-break only)",
      main._check_pd_level_signal("TEST", main._build_intraday_context(early + early_brk + back_in + re_brk)) is None)

# put mirror at PDL
brk_dn = [mk_bar(40, 99.95, 100.0, 99.1, 99.2, 1500)]
sig_dn = main._check_pd_level_signal("TEST", main._build_intraday_context(base + brk_dn))
check("fires put on first PDL break", sig_dn is not None and sig_dn["signal"] == "put", f"got {sig_dn}")

# no cached levels for the ticker → no fire
main._pd_levels_cache = (_today_et, {"OTHER": (1.0, 0.5)})
check("no fire without prev-day levels", main._check_pd_level_signal("TEST", main._build_intraday_context(base + brk)) is None)



# ---------------- VWAP-RC (reclaim + retest) ----------------
print("VWAP-RC:")

# Reclaim CALL: open near 101 drags session VWAP up, price sags below it,
# then a strong-volume bullish close back through VWAP.
ph1 = flat_bars(0, 30, px=101.0, amp=0.05)
ph2 = flat_bars(30, 30, px=100.3, amp=0.05)
ctx_r = main._build_intraday_context(ph1 + ph2)
V = float(ctx_r["today"].iloc[-1]["vwap"])
assert float(ctx_r["today"].iloc[-1]["c"]) < V, "fixture: price should sit below vwap"
brk = [mk_bar(60, V * 0.999, V * 1.003, V * 0.9985, V * 1.002, 1500)]
sig = main._check_vwap_reclaim_signal("TEST", main._build_intraday_context(ph1 + ph2 + brk))
check("reclaim call fires on close through VWAP", sig is not None and sig["signal"] == "call", f"got {sig}")
if sig:
    check("entry_type=reclaim + margin recorded", sig["meta"]["entry_type"] == "reclaim"
          and sig["meta"]["margin_pct"] >= main.VWAPX_MARGIN_PCT, str(sig["meta"]))

# weak volume → no fire
brk_lo = [mk_bar(60, V * 0.999, V * 1.003, V * 0.9985, V * 1.002, 1000)]
check("no reclaim on weak volume", main._check_vwap_reclaim_signal("TEST", main._build_intraday_context(ph1 + ph2 + brk_lo)) is None)

# wick-through / marginal close → no fire (the 'wait for a real CLOSE' rule)
brk_thin = [mk_bar(60, V * 0.999, V * 1.003, V * 0.9985, V * 1.0002, 1500)]
check("no reclaim on marginal close", main._check_vwap_reclaim_signal("TEST", main._build_intraday_context(ph1 + ph2 + brk_thin)) is None)

# Reclaim PUT mirror: open low, price rides above VWAP, then loses it
ph1p = flat_bars(0, 30, px=100.0, amp=0.05)
ph2p = flat_bars(30, 30, px=100.7, amp=0.05)
ctx_p = main._build_intraday_context(ph1p + ph2p)
Vp = float(ctx_p["today"].iloc[-1]["vwap"])
brk_dn = [mk_bar(60, Vp * 1.001, Vp * 1.0015, Vp * 0.997, Vp * 0.998, 1500)]
sig_p = main._check_vwap_reclaim_signal("TEST", main._build_intraday_context(ph1p + ph2p + brk_dn))
check("reclaim put fires on close losing VWAP", sig_p is not None and sig_p["signal"] == "put", f"got {sig_p}")

# Retest CALL: steady ramp holds above VWAP, 3-bar pullback tags VWAP
# (wicks touch, closes hold), then a bounce bar takes out the prior high.
ramp = []
for i in range(60):
    px = 100.0 + i * 0.02
    ramp.append(mk_bar(i, px, px + 0.03, px - 0.02, px + 0.015, 1000))
ctx0 = main._build_intraday_context(ramp)
V0 = float(ctx0["today"].iloc[-1]["vwap"])
tol = main.VWAPX_RETEST_TOL_PCT / 100.0
pull = [mk_bar(60 + j, V0 * (1 + tol), V0 * (1 + 3 * tol), V0 * (1 - tol / 2), V0 * (1 + tol), 800) for j in range(3)]
ctx1 = main._build_intraday_context(ramp + pull)
V1 = float(ctx1["today"].iloc[-1]["vwap"])
prev_h = V0 * (1 + 3 * tol)
bounce_c = max(V1 * (1 + 2 * main.VWAPX_MARGIN_PCT / 100.0), prev_h * 1.0005)
bounce = [mk_bar(63, V1 * (1 + tol), bounce_c * 1.0005, V1 * (1 + tol / 2), bounce_c, 1000)]
sig_rt = main._check_vwap_reclaim_signal("TEST", main._build_intraday_context(ramp + pull + bounce))
check("retest call fires on VWAP-hold bounce", sig_rt is not None and sig_rt["signal"] == "call"
      and sig_rt["meta"]["entry_type"] == "retest", f"got {sig_rt}")

# pullback that LOSES vwap on a closing basis → no retest fire
pull_bad = [mk_bar(60 + j, V0, V0 * (1 + tol), V0 * 0.996, V0 * 0.997, 800) for j in range(3)]
ctx2 = main._build_intraday_context(ramp + pull_bad)
V2 = float(ctx2["today"].iloc[-1]["vwap"])
bounce2 = [mk_bar(63, V2, bounce_c * 1.0005, V2 * 0.999, bounce_c, 1000)]
check("no retest after closes lost VWAP",
      main._check_vwap_reclaim_signal("TEST", main._build_intraday_context(ramp + pull_bad + bounce2)) is None)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
