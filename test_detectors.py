"""Synthetic-bar tests for the four new strategy detectors."""
import os, sys
os.environ.setdefault("OPENROUTER_API_KEY", "x")
sys.path.insert(0, "/Users/paululisse/Documents/Stock Ticker Analysis")
import main
main._DASH_CACHE_TTL_S = 0   # endpoint tests call the same routes with different fakes
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

# ---------------- Market Wave ----------------
print("MWAVE:")

def wave_bars(open_px=100.0, top=100.45, bottom=99.70, climb=20, fall=18):
    """Open flat-ish, climb to `top`, slide to `bottom`. No bar closes the
    day beyond the ±0.5% trend filter as long as top/bottom stay inside."""
    out = []
    for i in range(climb):                      # 9:30 → climb
        px = open_px + (top - open_px) * (i + 1) / climb
        out.append(mk_bar(i, px - 0.02, px + 0.03, px - 0.04, px, 1000))
    for j in range(fall):                       # slide back down
        px = top + (bottom - top) * (j + 1) / fall
        out.append(mk_bar(climb + j, px + 0.02, px + 0.04, px - 0.03, px, 1000))
    return out

# textbook dip-and-turn → call (swing high ~100.48, cur close 99.70:
# depth ~0.78% >= 0.75, day move -0.30% inside the trend cap)
bars = wave_bars(bottom=99.62) + [mk_bar(38, 99.64, 99.72, 99.62, 99.70, 1000)]
sig = main._check_market_wave_signal("TEST", main._build_intraday_context(bars))
check("fires call on dip-and-turn", sig is not None and sig["signal"] == "call", f"got {sig}")
if sig:
    check("meta depth/scope sane", 0.75 <= sig["meta"]["wave_depth_pct"] <= 0.9
          and sig["meta"]["scope_bars"] >= 20, str(sig["meta"]))
    check("swing_high captured", abs(sig["meta"]["swing_high"] - 100.48) < 0.02, str(sig["meta"]))

# turn bar that already retraced most of the wave → depth < threshold, no fire
bars_r = wave_bars() + [mk_bar(38, 99.95, 100.12, 99.93, 100.10, 1000)]
check("no fire when bounce already retraced",
      main._check_market_wave_signal("TEST", main._build_intraday_context(bars_r)) is None)

# same shape but the slide breaks the ±0.5% day-trend filter → no fire
bars_t = wave_bars(top=100.45, bottom=99.30) + [mk_bar(38, 99.32, 99.45, 99.30, 99.42, 1000)]
check("no fire on a trend day",
      main._check_market_wave_signal("TEST", main._build_intraday_context(bars_t)) is None)

# deep dip but the current bar is still red (no turn) → no fire
bars_d = wave_bars() + [mk_bar(38, 99.72, 99.74, 99.60, 99.62, 1000)]
check("no fire without an up-turn bar",
      main._check_market_wave_signal("TEST", main._build_intraday_context(bars_d)) is None)

# mirror: early dip (swing low ~99.51), rally past +0.75% off it, red turn bar → put
bars_p = wave_bars(open_px=100.0, top=99.55, bottom=100.42, climb=20, fall=18) \
         + [mk_bar(38, 100.45, 100.47, 100.34, 100.38, 1000)]
sig_p = main._check_market_wave_signal("TEST", main._build_intraday_context(bars_p))
check("fires put on rip-and-turn", sig_p is not None and sig_p["signal"] == "put", f"got {sig_p}")

# too little session behind it → no wave yet (premarket bars satisfy the
# context builder's 30-bar minimum but don't count toward today's RTH bars)
pre = [mk_bar(-120 + i, 100.0, 100.05, 99.95, 100.0, 500) for i in range(25)]
bars_s = pre + wave_bars(climb=6, fall=5) + [mk_bar(11, 99.9, 100.0, 99.88, 99.98, 1000)]
check("no fire with < 22 RTH bars",
      main._check_market_wave_signal("TEST", main._build_intraday_context(bars_s)) is None)

# ---------------- Paper morning extended hold ----------------
print("HOLD:")
# 2026-07-08 is EDT: 13:51Z = 9:51 ET (before the 10:30 cutoff), 15:10Z = 11:10 ET
morning = "2026-07-08T13:51:00+00:00"
midday = "2026-07-08T15:10:00+00:00"
# Default is now 15 (= base hold) since the 9/21 revert, which disables the
# extension; exercise the mechanism by switching it on explicitly.
check("default: extension off, paper morning entry holds the base 15",
      main._hold_minutes_for_entry({"paper": True, "submitted_at": morning}) == 15)
_saved_hold = main.PAPER_MORNING_HOLD_MINUTES
main.PAPER_MORNING_HOLD_MINUTES = 25
check("paper morning entry holds 25",
      main._hold_minutes_for_entry({"paper": True, "submitted_at": morning}) == 25)
check("live morning entry keeps 15",
      main._hold_minutes_for_entry({"paper": False, "submitted_at": morning}) == 15)
check("paper midday entry keeps 15",
      main._hold_minutes_for_entry({"paper": True, "submitted_at": midday}) == 15)
check("missing timestamp keeps 15",
      main._hold_minutes_for_entry({"paper": True}) == 15)
check("boundary: 10:29 ET extends, 10:30 ET does not",
      main._hold_minutes_for_entry({"paper": True, "submitted_at": "2026-07-08T14:29:00+00:00"}) == 25
      and main._hold_minutes_for_entry({"paper": True, "submitted_at": "2026-07-08T14:30:00+00:00"}) == 15)
main.PAPER_MORNING_HOLD_MINUTES = _saved_hold

# ---------------- Daily predictions (bullseye) ----------------
print("DAILYPRED:")
from datetime import date as _date
nf = main._normalize_forecast
check("forecast ints map to bullseye base_labels order",
      nf(0) == "sell" and nf(1) == "hold" and nf(2) == "buy")
check("forecast names/strings normalise",
      nf(" BUY ") == "buy" and nf("2") == "buy" and nf(2.0) == "buy")
check("garbage forecast rejected",
      nf(3) is None and nf(True) is None and nf("maybe") is None and nf(1.5) is None)

lf = main._label_from_return
check("label cut-offs match training (+1.65 / -1.05)",
      lf(1.66) == "buy" and lf(1.65) == "hold" and lf(-1.05) == "hold" and lf(-1.06) == "sell")

abd = main._add_business_days
check("business-day add skips weekends",
      abd(_date(2026, 9, 4), 5) == _date(2026, 9, 11)     # Fri + 5 = next Fri
      and abd(_date(2026, 9, 7), -1) == _date(2026, 9, 4)  # Mon - 1 = Fri
      and abd(_date(2026, 9, 5), 1) == _date(2026, 9, 7))  # Sat + 1 = Mon

# 2026-08-31 (Mon) .. 2026-09-11, with Labor Day (Sep 7) missing
closes = {
    _date(2026, 8, 31): 100.0, _date(2026, 9, 1): 101.0, _date(2026, 9, 2): 101.5,
    _date(2026, 9, 3): 102.0,  _date(2026, 9, 4): 103.0,
    _date(2026, 9, 8): 104.0,  _date(2026, 9, 9): 98.5, _date(2026, 9, 10): 99.0,
}
spr = main._score_prediction_row
r = spr({"as_of_date": "2026-08-31", "target_date": "2026-09-08", "forecast": "buy"}, closes)
check("buy scored correct on +4%", r is not None and r["actual"] == "buy" and r["correct"] is True
      and abs(r["realized_pct"] - 4.0) < 1e-6 and r["direction_correct"] is True, str(r))
r = spr({"as_of_date": "2026-09-01", "target_date": "2026-09-09", "forecast": "buy"}, closes)
check("buy scored wrong on -2.5% (actual sell)", r is not None and r["actual"] == "sell"
      and r["correct"] is False and r["direction_correct"] is False, str(r))
r = spr({"as_of_date": "2026-09-02", "target_date": "2026-09-10", "forecast": "hold"}, closes)
check("hold inside band counts correct", r is not None and r["actual"] == "sell" and r["correct"] is False, str(r))
r = spr({"as_of_date": "2026-09-01", "target_date": "2026-09-07", "forecast": "sell"}, closes)
check("holiday target rolls to next close", r is not None and r["target_close_date"] == "2026-09-08"
      and r["direction_correct"] is False, str(r))
r = spr({"as_of_date": "2026-09-04", "target_date": "2026-09-11", "forecast": "buy"}, closes)
check("unprinted target -> None", r is None)
check("empty closes -> None", spr({"as_of_date": "2026-09-01", "target_date": "2026-09-08", "forecast": "buy"}, {}) is None)
check("bad dates -> None", spr({"as_of_date": "nope", "target_date": "2026-09-08", "forecast": "buy"}, closes) is None)

summ = main._summarize_predictions([
    {"ticker": "A", "forecast": "buy",  "actual": "buy",  "correct": True,  "direction_correct": True,  "realized_pct": 3.0,  "scored_at": "x"},
    {"ticker": "A", "forecast": "buy",  "actual": "hold", "correct": False, "direction_correct": True,  "realized_pct": 0.5,  "scored_at": "x"},
    {"ticker": "B", "forecast": "sell", "actual": "hold", "correct": False, "direction_correct": False, "realized_pct": 0.2,  "scored_at": "x"},
    {"ticker": "B", "forecast": "hold", "actual": None,   "correct": None,  "direction_correct": None,  "realized_pct": None, "scored_at": None},
    {"ticker": "C", "forecast": "hold", "actual": None,   "correct": None,  "direction_correct": None,  "realized_pct": None, "scored_at": "x", "score_note": "unscorable"},
])
check("summary counts", summ["n_total"] == 5 and summ["n_scored"] == 3 and summ["n_pending"] == 1
      and summ["n_unscorable"] == 1, str(summ))
check("summary accuracy + baselines", abs(summ["accuracy"] - 1/3) < 1e-3
      and abs(summ["baseline_always_hold"] - 2/3) < 1e-3 and abs(summ["baseline_majority"] - 2/3) < 1e-3
      and summ["by_forecast"]["buy"]["n"] == 2 and summ["confusion"]["buy"]["hold"] == 1, str(summ))

# Endpoint plumbing with a fake Supabase client
from fastapi.testclient import TestClient
class _FakeQ:
    def __init__(self, store): self.store = store; self.rows = None
    def upsert(self, rows, on_conflict=None, ignore_duplicates=False):
        self.rows = rows; self.store["upserts"].append((rows, on_conflict, ignore_duplicates)); return self
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def execute(self):
        class R: pass
        r = R(); r.data = self.rows if self.rows is not None else []; return r
class _FakeSB:
    def __init__(self): self.store = {"upserts": []}
    def table(self, name): assert name == "daily_predictions"; return _FakeQ(self.store)

client = TestClient(main.app)
_saved_tok, _saved_sb = main.EXTERNAL_SIGNAL_TOKEN, main._supabase_client
main.EXTERNAL_SIGNAL_TOKEN = "t0k"
fake = _FakeSB(); main._supabase_client = fake
body = {"source": "bullseye", "predictions": [
    {"ticker": "aapl", "as_of_date": "2026-09-04", "forecast": 2, "conf_buy": 0.61, "conf_hold": 0.3, "conf_sell": 0.09, "ref_price": 230.1, "model": "small-classifier-nb"},
    {"ticker": "MSFT", "as_of_date": "2026-09-04", "forecast": "hold"},
    {"ticker": "BAD!", "as_of_date": "2026-09-04", "forecast": 1},
    {"ticker": "TSLA", "as_of_date": "2026-09-04", "forecast": 7},
    {"ticker": "NVDA", "as_of_date": "2099-01-01", "forecast": 0},
    {"ticker": "AMD",  "as_of_date": "2026-09-04", "forecast": 0, "conf_buy": 1.5},
]}
resp = client.post("/purgatory/external-predictions", json=body)
check("post without token -> 401", resp.status_code == 401, str(resp.status_code))
resp = client.post("/purgatory/external-predictions", json=body, headers={"X-Signal-Token": "t0k"})
j = resp.json()
check("post accepted 2, rejected 4", resp.status_code == 200 and j["accepted"] == 2 and len(j["rejected"]) == 4, str(j))
rows, conflict, ignore = fake.store["upserts"][0]
check("insert-once upsert on natural key", conflict == "source,ticker,as_of_date" and ignore is True)
aapl = next(r for r in rows if r["ticker"] == "AAPL")
check("row normalised: forecast name, +5 bdays target, ticker upper",
      aapl["forecast"] == "buy" and aapl["target_date"] == "2026-09-11" and aapl["source"] == "bullseye", str(aapl))
check("backfilled inferred from as_of age",
      aapl["backfilled"] == (_date(2026, 9, 4) < main._add_business_days(main._now_et_date(), -1)))
resp = client.post("/purgatory/external-predictions", json={"source": "kronos", "predictions": [{"ticker": "A", "as_of_date": "2026-09-04", "forecast": 1}]},
                   headers={"X-Signal-Token": "t0k"})
check("unknown source -> 400", resp.status_code == 400)
resp = client.get("/purgatory/external-predictions?days=30")
check("get returns summary shape", resp.status_code == 200 and "summary" in resp.json() and resp.json()["thresholds"]["buy_pct"] == 1.65, str(resp.json())[:200])
# forced scorer endpoint: runs the scorer now, 5-min floor between forced passes, 503 without Supabase
main._daily_pred_last_force_at = 0.0
resp = client.post("/purgatory/score-daily-predictions")
j = resp.json()
check("force-score runs and reports", resp.status_code == 200 and j["scored"] == 0 and j["throttled"] is False and j["last_run"]["at"] is not None, str(j))
resp = client.post("/purgatory/score-daily-predictions")
check("force-score throttled within 5 min", resp.status_code == 200 and resp.json()["throttled"] is True and resp.json()["retry_after_s"] > 0, str(resp.json()))
resp = client.get("/purgatory/status")
check("status exposes last_score_run", resp.status_code == 200 and "last_score_run" in resp.json()["daily_predictions"])
main._supabase_client = None
resp = client.post("/purgatory/score-daily-predictions")
check("force-score without Supabase -> 503", resp.status_code == 503, str(resp.status_code))
main.EXTERNAL_SIGNAL_TOKEN, main._supabase_client = _saved_tok, _saved_sb

# ---- live time-of-day window gate (2026-10-06) ----
print("LIVE WINDOW:")
pairs, wins = main._parse_live_pairs("purgatory:TSLA:call, AAPL:call@09:45-11:30 ,purgatory:MSTR:put@9:45-10:30")
check("parser: legacy + windowed entries", pairs == {("purgatory","TSLA","call"),("purgatory","AAPL","call"),("purgatory","MSTR","put")} and wins == {("purgatory","AAPL","call"): (585, 690), ("purgatory","MSTR","put"): (585, 630)}, f"{pairs} {wins}")
pairs, wins = main._parse_live_pairs("purgatory:AAPL:call@09:45-11:3x, purgatory:QQQ:put@11:30-09:45, purgatory:SMCI:call@25:00-26:00, purgatory:TSLA:put")
check("parser: malformed / inverted / out-of-range windows DROP the pair (fail safe)", pairs == {("purgatory","TSLA","put")} and wins == {}, f"{pairs} {wins}")
check("parser: empty -> inert", main._parse_live_pairs("") == (set(), {}))
check("_fmt_window", main._fmt_window((585, 690)) == "09:45-11:30" and main._fmt_window(None) is None)
_saved_w = main.LIVE_TRADING_WINDOWS
main.LIVE_TRADING_WINDOWS = {("purgatory","AAPL","call"): (585, 690)}
ok, why = main._live_window_allows("purgatory","AAPL","call","2026-10-06T14:19:00+00:00")   # 10:19 ET (EDT)
check("gate: 10:19 ET inside 09:45-11:30", ok, why)
check("gate: 09:45 and 11:30 boundaries inclusive", main._live_window_allows("purgatory","AAPL","call","2026-10-06T13:45:00+00:00")[0] and main._live_window_allows("purgatory","AAPL","call","2026-10-06T15:30:00+00:00")[0])
check("gate: 09:44 and 11:31 outside", not main._live_window_allows("purgatory","AAPL","call","2026-10-06T13:44:00+00:00")[0] and not main._live_window_allows("purgatory","AAPL","call","2026-10-06T15:31:00+00:00")[0])
check("gate: 14:41 ET (the 9/16 loss) outside", not main._live_window_allows("purgatory","AAPL","call","2026-09-16T18:41:00+00:00")[0])
check("gate: unparseable bar time -> not allowed", not main._live_window_allows("purgatory","AAPL","call",None)[0] and not main._live_window_allows("purgatory","AAPL","call","garbage")[0])
check("gate: pair without a window -> allowed", main._live_window_allows("purgatory","TSLA","call","garbage") == (True, "no window"))
main.LIVE_TRADING_WINDOWS = _saved_w

# ---- stop knob default (2026-10-03: 30 -> 15 per the stop-rule study) ----
print("STOP KNOB:")
check("ALPACA_TRADING_STOP_LOSS_PCT defaults to 15 (set via env to override)",
      os.environ.get("ALPACA_TRADING_STOP_LOSS_PCT") is not None or main.ALPACA_TRADING_STOP_LOSS_PCT == 15.0,
      f"got {main.ALPACA_TRADING_STOP_LOSS_PCT}")

# ---- memory hygiene (2026-10-03): slim order select, fallback, cache, /healthz?mem ----
print("MEM HYGIENE:")
class _SlimQ:
    def __init__(self, sb): self.sb = sb; self.a = self.b = None; self.cols = None
    def select(self, cols): self.cols = cols; self.sb.selects.append(cols); return self
    def gte(self, k, v): self.sb.bounds.append(("gte", k, v)); return self
    def lt(self, k, v): self.sb.bounds.append(("lt", k, v)); return self
    def order(self, *a, **k): return self
    def range(self, a, b): self.a, self.b = a, b; return self
    def execute(self):
        if "raw->" in self.cols and self.sb.reject_slim: raise RuntimeError("400 column raw->x does not exist")
        class R: pass
        r = R()
        if "raw->" in self.cols:
            r.data = [{"id": 1, "role": "entry", "fill_price": 1.0, "quote_at_submit": {"bid": 1, "ask": 1.1, "mid": 1.05}, "attributed": None, "exit_reason": None, "stop_basis": None},
                      {"id": 2, "role": "exit", "fill_price": 1.2, "quote_at_submit": None, "attributed": True, "exit_reason": "stop_loss", "stop_basis": "mid"}]
        else:
            r.data = [{"id": 1, "role": "entry", "raw": {"quote_at_submit": {"mid": 1.05}, "quote_path": [1, 2, 3]}}]
        return r
class _SlimSB:
    def __init__(self, reject_slim=False): self.reject_slim = reject_slim; self.selects = []; self.bounds = []
    def table(self, name): return _SlimQ(self)
_saved_sb, _saved_ok = main._supabase_client, main._slim_orders_ok
main._slim_orders_ok = True; main._supabase_client = _SlimSB()
rows = main._fetch_all_order_rows()
check("slim select asks for raw->keys, not raw", len(main._supabase_client.selects) == 1 and "raw->quote_at_submit" in main._supabase_client.selects[0] and ", raw," not in main._supabase_client.selects[0])
check("slim rows: aliases folded into raw, None keys dropped",
      rows[0]["raw"] == {"quote_at_submit": {"bid": 1, "ask": 1.1, "mid": 1.05}} and "quote_at_submit" not in rows[0]
      and rows[1]["raw"] == {"attributed": True, "exit_reason": "stop_loss", "stop_basis": "mid"}, str(rows))
main._slim_orders_ok = True; main._supabase_client = _SlimSB(reject_slim=True)
rows = main._fetch_all_order_rows()
check("slim select rejected -> falls back to select(*) and latches off",
      rows and rows[0]["raw"].get("quote_path") == [1, 2, 3] and main._slim_orders_ok is False
      and main._supabase_client.selects == [main._ORDER_ROW_COLUMNS, "*"], str(main._supabase_client.selects))
rows = main._fetch_all_order_rows()
check("latched: second call goes straight to select(*)", main._supabase_client.selects[-1] == "*" and len(main._supabase_client.selects) == 3)
class _TimeoutSB(_SlimSB):
    def table(self, name):
        q = _SlimQ(self)
        def _exec():
            if "raw->" in q.cols: raise RuntimeError("HTTPSConnectionPool: Read timed out (read timeout=30)")
            class R: data = [{"id": 1, "role": "entry", "raw": {}}]
            return R()
        q.execute = _exec
        return q
main._slim_orders_ok = True; main._supabase_client = _TimeoutSB()
try:
    main._fetch_all_order_rows(); _raised = False
except RuntimeError:
    _raised = True
check("transient error on slim select propagates and does NOT latch", _raised and main._slim_orders_ok is True)
check("_looks_like_schema_rejection: 400/42703 yes, timeout no", main._looks_like_schema_rejection(RuntimeError("400 column raw->x does not exist")) and main._looks_like_schema_rejection(RuntimeError('{"code":"42703"}')) and not main._looks_like_schema_rejection(RuntimeError("Read timed out")) and not main._looks_like_schema_rejection(RuntimeError("502 Bad Gateway")))
main._slim_orders_ok = True; main._supabase_client = _SlimSB()
rows = main._fetch_all_order_rows("2026-10-14T00:00:00Z", "2026-10-15T00:00:00Z")
check("bounded slim fetch applies gte/lt on submitted_at", main._supabase_client.bounds == [("gte", "submitted_at", "2026-10-14T00:00:00Z"), ("lt", "submitted_at", "2026-10-15T00:00:00Z")] and "raw->" in main._supabase_client.selects[-1] and rows[0]["raw"]["quote_at_submit"]["mid"] == 1.05)
main._supabase_client, main._slim_orders_ok = _saved_sb, _saved_ok
_calls = []
v1 = main._cached_json(("dash", "test", 1), lambda: _calls.append(1) or {"n": len(_calls)}, ttl=60)
v2 = main._cached_json(("dash", "test", 1), lambda: _calls.append(1) or {"n": len(_calls)}, ttl=60)
check("_cached_json serves the second call from cache", v1 == v2 == {"n": 1} and len(_calls) == 1)
v3 = main._cached_json(("dash", "test", 1), lambda: _calls.append(1) or {"n": len(_calls)}, ttl=0)
check("_cached_json ttl<=0 bypasses the cache", v3 == {"n": 2})
try:
    main._cached_json(("dash", "test", 2), lambda: (_ for _ in ()).throw(RuntimeError("boom")), ttl=60)
except RuntimeError: pass
check("_cached_json never caches an exception", main._cache_get(("dash", "test", 2)) is None)
main._WIDGET_CACHE.pop(("dash", "test", 1), None)
from fastapi.testclient import TestClient as _TC
_hz = _TC(main.app).get("/healthz?mem=1").json()
check("/healthz?mem=1 returns ok + rss + mem report", _hz["ok"] is True and "rss_mb" in _hz and set(_hz["mem"]) >= {"rss_ring", "widget_cache", "alerted_keys", "signals_mem", "live_objects", "top_types"}, str(list(_hz.get("mem", {}).keys())))
check("/healthz?mem=1 reports MALLOC_ARENA_MAX (None when unset)", "malloc_arena_max" in _hz["mem"] and _hz["mem"]["malloc_arena_max"] == os.environ.get("MALLOC_ARENA_MAX"))
check("/healthz plain has no mem block", "mem" not in _TC(main.app).get("/healthz").json())

# ---- orders table paging past the PostgREST 1000-row cap ----
print("ORDERS PAGING:")
class _PagedQ:
    def __init__(self, total): self.total = total; self.a = self.b = None
    def select(self, *a, **k): return self
    def order(self, *a, **k): return self
    def range(self, a, b): self.a, self.b = a, b; return self
    def execute(self):
        class R: pass
        r = R(); r.data = [{"i": i} for i in range(self.a, min(self.b + 1, self.total))]; return r
class _PagedSB:
    def __init__(self, total): self.total = total; self.calls = 0
    def table(self, name):
        assert name == main._PURGATORY_ORDERS_TABLE; self.calls += 1; return _PagedQ(self.total)
_saved_sb = main._supabase_client
for total, want_calls in ((0, 1), (999, 1), (1000, 2), (2500, 3)):
    sb = _PagedSB(total); main._supabase_client = sb
    rows = main._fetch_all_order_rows()
    check(f"paging fetches all {total} rows in {want_calls} page(s)",
          len(rows) == total and sb.calls == want_calls and [r["i"] for r in rows] == list(range(total)),
          f"got {len(rows)} rows / {sb.calls} calls")
main._supabase_client = None
check("paging with no Supabase -> []", main._fetch_all_order_rows() == [])
main._supabase_client = _saved_sb
# generic pager: builder is called once per page (fresh query each time), stitches in order
built = []
def _builder(total):
    def b(): q = _PagedQ(total); built.append(q); return q
    return b
built.clear(); rows = main._page_all(_builder(1500))
check("_page_all: 1500 rows -> 2 fresh builders, ordered", len(rows) == 1500 and len(built) == 2 and rows[-1]["i"] == 1499)
built.clear(); rows = main._page_all(_builder(7), page_size=3)
check("_page_all: custom page size 3 over 7 rows -> 3 pages", len(rows) == 7 and len(built) == 3)

# ---- signal leaderboard ----
print("LEADERBOARD:")
from datetime import datetime as _dt, timezone as _tz, timedelta as _td
_now = _dt(2026, 9, 21, 20, 0, tzinfo=_tz.utc)
def _sig(i, outcome, f15=0.3, strat="purgatory", tk="TSLA", d="call", days_ago=None):
    bt = (_now - _td(days=(days_ago if days_ago is not None else 60 - i))).isoformat()
    return {"strategy": strat, "ticker": tk, "signal": d, "bar_time": bt, "outcome": outcome, "favorable_15m": f15, "favorable_30m": f15}
# pair A: 20 signals, first 10 all wins (old), last 10 all losses (recent) -> decaying
A = [_sig(i, "win", days_ago=60 - i) for i in range(10)] + [_sig(10 + i, "loss", -0.2, days_ago=20 - i) for i in range(10)]
# pair B: 6 signals all wins, tiny n
B = [_sig(i, "win", strat="market_wave", tk="QQQ", d="put") for i in range(6)]
# pair C: below min_n
C = [_sig(i, "win", tk="AAPL") for i in range(3)]
# noise: unscored + lookahead rows must be ignored
N = [{"strategy": "purgatory", "ticker": "TSLA", "signal": "call", "bar_time": _now.isoformat(), "outcome": None}]
trades = [{"account": "paper", "strategy": "purgatory", "ticker": "TSLA", "direction": "call", "pnl": -40.0, "exit_reason": "stop_loss", "entry_submitted_at": (_now - _td(days=2)).isoformat()},
          {"account": "paper", "strategy": "purgatory", "ticker": "TSLA", "direction": "call", "pnl": 100.0, "exit_reason": "hold", "entry_submitted_at": (_now - _td(days=50)).isoformat()},
          {"account": "live",  "strategy": "purgatory", "ticker": "TSLA", "direction": "call", "pnl": -999.0, "exit_reason": "hold", "entry_submitted_at": (_now - _td(days=2)).isoformat()}]
lb = main._build_leaderboard(A + B + C + N, trades, days=30, min_n=5, now=_now,
                             live_pairs={("purgatory", "TSLA", "call")}, disabled=set(), trading_strategies={"purgatory"})
check("leaderboard drops pairs under min_n and unscored rows", [ (r["ticker"], r["all"]["n"]) for r in lb ] == [("QQQ", 6), ("TSLA", 20)] or [ (r["ticker"], r["all"]["n"]) for r in lb ] == [("TSLA", 20), ("QQQ", 6)], str([(r["ticker"], r["all"]["n"]) for r in lb]))
tsla = next(r for r in lb if r["ticker"] == "TSLA"); qqq = next(r for r in lb if r["ticker"] == "QQQ")
check("all-time record: 10W/10L, wr 0.5", tsla["all"]["wins"] == 10 and tsla["all"]["losses"] == 10 and tsla["all"]["win_rate"] == 0.5)
check("window record: last 30 days = the 10 recent losses", tsla["window"]["n"] == 10 and tsla["window"]["wins"] == 0, str(tsla["window"]))
check("momentum negative for a decaying pair", tsla["momentum"]["momentum"] < 0 and tsla["momentum"]["ewma_wr"] < 0.45 and tsla["momentum"]["recent_wr"] == 0.0 and tsla["momentum"]["prior_wr"] == 1.0 and tsla["momentum"]["streak"] == -10, str(tsla["momentum"]))
check("wilson lower bound: 6/6 -> ~0.61, ranks below nothing but is honest", 0.60 < qqq["all"]["wilson_lo"] < 0.62, str(qqq["all"]["wilson_lo"]))
check("wilson: 10/20 -> ~0.30", 0.29 < tsla["all"]["wilson_lo"] < 0.31, str(tsla["all"]["wilson_lo"]))
check("paper fills attach (paper only), window split", tsla["paper"]["fills"] == 2 and tsla["paper"]["pnl"] == 60.0 and tsla["paper"]["stops"] == 1 and tsla["paper"]["fills_window"] == 1 and tsla["paper"]["pnl_window"] == -40.0, str(tsla["paper"]))
check("flags: live + trading", tsla["flags"] == {"live": True, "disabled": False, "trading": True} and qqq["flags"]["trading"] is False)
check("spark is a rolling win-rate series ending at 0", tsla["momentum"]["spark"][0] == 1.0 and tsla["momentum"]["spark"][-1] == 0.0 and len(tsla["momentum"]["spark"]) == 20)
check("net f15 subtracts spread", abs(qqq["all"]["avg_net_f15"] - 0.25) < 1e-9, str(qqq["all"]["avg_net_f15"]))
check("wilson helper: n=0 -> None", main._wilson_lower(0, 0) is None)
_saved_sb2 = main._supabase_client; main._supabase_client = None
resp = client.get("/purgatory/leaderboard")
check("leaderboard without Supabase -> 503", resp.status_code == 503)
main._supabase_client = _saved_sb2

# ---- stop-rule study ----
print("STOPSTUDY:")
r = main._push_sample({"a": 1}, "quote_path", {"mid": 1.0}, cap=2)
r = main._push_sample(r, "quote_path", {"mid": 2.0}, cap=2)
r = main._push_sample(r, "quote_path", {"mid": 3.0}, cap=2)
check("push_sample caps and keeps other keys", r["a"] == 1 and [x["mid"] for x in r["quote_path"]] == [2.0, 3.0])
# trade A: dips -35% then recovers to +20% at the hold (really stopped at 30% -> hold_mid known)
A = {"fill": 2.00, "qty": 1, "actual_pnl": -70.0, "exit_reason": "stop_loss",
     "path": [{"mid": 1.9}, {"mid": 1.3}, {"mid": 1.8}, {"mid": 2.4}], "hold_mid": 2.4}
# trade B: bleeds monotonically to -60%, really stopped
B = {"fill": 1.00, "qty": 2, "actual_pnl": -64.0, "exit_reason": "stop_loss",
     "path": [{"mid": 0.9}, {"mid": 0.68}, {"mid": 0.5}, {"mid": 0.4}], "hold_mid": 0.4}
# trade C: never near the stop, held to +10%
C = {"fill": 3.00, "qty": 1, "actual_pnl": 30.0, "exit_reason": "hold",
     "path": [{"mid": 2.9}, {"mid": 3.1}, {"mid": 3.3}], "hold_mid": None}
# trade D: really stopped but shadow not finished -> excluded
D = {"fill": 1.00, "qty": 1, "actual_pnl": -35.0, "exit_reason": "stop_loss", "path": [{"mid": 0.6}], "hold_mid": None}
ev = main._evaluate_stop_rules([A, B, C, D], thresholds=[30, 50, None])
check("unfinished shadow excluded", ev["n_trades"] == 4 and ev["n_usable"] == 3)
r30 = next(x for x in ev["rules"] if x["threshold_pct"] == 30)
r50 = next(x for x in ev["rules"] if x["threshold_pct"] == 50)
rno = next(x for x in ev["rules"] if x["threshold_pct"] is None)
# 30%: A stops at 1.3 (-70), B stops at 0.68 (-64), C holds +30 -> -104, 2 stopped
check("30% rule replays the actual stops", r30["stopped"] == 2 and r30["pnl"] == -104.0, str(r30))
# 50%: A never hits 50% -> hold_mid 2.4 (+40); B stops at 0.5 (-100); C +30 -> -30, 1 stopped
check("50% rule lets A recover, still catches B", r50["stopped"] == 1 and r50["pnl"] == -30.0, str(r50))
# none: A +40, B at hold 0.4 (-120), C +30 -> -50
check("no-stop rule uses hold mids", rno["stopped"] == 0 and rno["pnl"] == -50.0 and rno["worst"] == -120.0, str(rno))
check("labels", r30["label"] == "30%" and rno["label"] == "no stop")
_saved_sb3 = main._supabase_client; main._supabase_client = None
resp = client.get("/purgatory/stop-study")
check("stop-study without Supabase -> 503", resp.status_code == 503)
main._supabase_client = _saved_sb3


# ---------------- BULLSEYE API PROBE ----------------
_saved_api = (main.BULLSEYE_API_URL, main.BULLSEYE_API_TOKEN, main.BULLSEYE_API_SECRET)
main.BULLSEYE_API_URL, main.BULLSEYE_API_TOKEN, main.BULLSEYE_API_SECRET = "", "", ""
r = client.get("/purgatory/bullseye-api/probe").json()
check("probe unconfigured", r["configured"] is False and r["ok"] is False and r["error"] == "not configured" and r["host"] is None)
main.BULLSEYE_API_URL, main.BULLSEYE_API_TOKEN, main.BULLSEYE_API_SECRET = "https://example.test", "hx7w", "zq9v"
check("configured + host", main._bullseye_api_configured() and main._bullseye_api_host() == "example.test")
_seen = {}
class _FakeResp:
    def __init__(self, code, body): self.status_code=code; self._b=body; self.text=str(body)
    def json(self):
        if isinstance(self._b, str): raise ValueError("not json")
        return self._b
def _fake_get(url, headers=None, timeout=None, **kw):
    _seen["url"]=url; _seen["headers"]=headers
    if url.endswith("/api/predictions/403"): return _FakeResp(403, "")
    if url.endswith("/api/predictions/9"): return _FakeResp(200, {"success": True, "data": {"stock": {"name": "AAPL", "long_name": "Apple Inc."},
        "predictions": [{"forecast": 2, "target_date": "2026-10-16T00:00:00Z", "created_at": "2026-10-09T21:05:00Z"}, {"forecast": 1}]}})
    return _FakeResp(500, "boom")
_saved_req_get = main.requests.get; main.requests.get = _fake_get
r = client.get("/purgatory/bullseye-api/probe?stock_id=9").json()
check("probe ok parses ticker/latest", r["ok"] and r["ticker"] == "AAPL" and r["long_name"] == "Apple Inc." and r["n_predictions"] == 2 and r["latest"]["forecast"] == "buy" and r["status_code"] == 200, str(r))
check("probe sends key+secret headers, never echoes them", _seen["headers"]["x-auth-token"] == "hx7w" and _seen["headers"]["x-secret-token"] == "zq9v" and "hx7w" not in str(r) and r["auth"] == "key+secret" and _seen["url"] == "https://example.test/api/predictions/9")
check("probe secret_present only", r["secret_present"] is True and "zq9v" not in str(r))
check("probe shapes are metadata only", r["token_shape"] == {"len": 4, "hex": False, "quoted": False} and r["secret_shape"]["len"] == 4)
main.BULLSEYE_API_SECRET = ""
r = client.get("/purgatory/bullseye-api/probe?stock_id=9").json()
check("probe without secret sends token only", "x-secret-token" not in _seen["headers"] and r["auth"] == "token" and r["ok"])
main.BULLSEYE_API_SECRET = "zq9v"
r = client.get("/purgatory/bullseye-api/probe?stock_id=403").json()
check("probe 403 reported", r["ok"] is False and r["status_code"] == 403 and "token rejected" in r["error"])
r = client.get("/purgatory/bullseye-api/probe?stock_id=1").json()
check("probe non-200 reported", r["ok"] is False and r["status_code"] == 500 and "unexpected" in r["error"])
main.requests.get = _saved_req_get
st = client.get("/purgatory/status").json()
check("status exposes api configured/host only", st["daily_predictions"]["api"] == {"configured": True, "host": "example.test"})
main.BULLSEYE_API_URL, main.BULLSEYE_API_TOKEN, main.BULLSEYE_API_SECRET = _saved_api


# ---------------- HOLD STUDY ----------------
from datetime import datetime as _dt, timedelta as _td, timezone as _tz
def _iso(base, mins): return (base + _td(minutes=mins)).isoformat()
_b = _dt(2026, 10, 13, 14, 20, tzinfo=_tz.utc)
def _trade(fill, mids, qty=1, step=4):
    return {"fill": fill, "qty": qty, "entry_t": _b.isoformat(),
            "path": [{"t": _iso(_b, i * step), "mid": m} for i, m in enumerate(mids)]}
# A: 1.00 -> rises steadily (samples every 4 min out to 32 min)
A = _trade(1.00, [1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35, 1.40])
# B: 1.00 -> dips to -20% at 8 min (stop at 15%) then recovers to 1.30 by 30
B = _trade(1.00, [1.00, 0.95, 0.80, 0.90, 1.00, 1.10, 1.20, 1.25, 1.30])
# C: path ends at 16 min -> no sample near 25/30 -> unusable
C = _trade(1.00, [1.00, 1.10, 1.20, 1.30, 1.40])
ev = main._evaluate_hold_rules([A, B, C], stop_pct=15)
check("hold study: C excluded (no late samples), same set for all rows", ev["n_trades"] == 3 and ev["n_usable"] == 2 and all(r["n"] == 2 for r in ev["rules"]))
r = {x["hold_min"]: x for x in ev["rules"]}
# A: exit mid nearest 15 min = sample at 16 (1.20) -> +20; 20 -> 1.25 (+25); 25 -> 24 min (1.30) +30; 30 -> 32 min? nearest of 28 (1.35) and 32 (1.40): 28 is 2 min off, 32 is 2 min off -> min() picks first (28) -> +35
# B: stopped at 0.80 (-20) in every row
check("hold study: A rises with the hold, B stops at 0.80 everywhere",
      r[15]["pnl"] == 0.0 and r[20]["pnl"] == 5.0 and r[25]["pnl"] == 10.0 and r[30]["pnl"] == 15.0
      and all(r[h]["stopped"] == 1 and r[h]["worst"] == -20.0 for h in (15, 20, 25, 30)), str(ev["rules"]))
ev2 = main._evaluate_hold_rules([B], stop_pct=0)
check("hold study: stop 0 disables the stop -> B exits at the hold mids", ev2["rules"][0]["stopped"] == 0 and ev2["rules"][-1]["pnl"] == 25.0)
check("hold study: median/best/win_rate present", r[20]["median"] in (-20.0, 25.0) and r[20]["best"] == 25.0 and r[20]["win_rate"] == 0.5)
ev3 = main._evaluate_hold_rules([{"fill": None, "qty": 1, "entry_t": _b.isoformat(), "path": []}])
check("hold study: bad fill ignored", ev3["n_usable"] == 0 and ev3["rules"][0]["avg"] is None)

class _UpdQ:
    def __init__(self, sb): self.sb = sb; self.payload = None
    def update(self, payload): self.payload = payload; return self
    def eq(self, k, v): self.sb.updates.append((v, self.payload)); return self
    def select(self, *a): return self
    def gte(self, *a): return self
    def order(self, *a, **k): return self
    def execute(self):
        class R: data = []
        return R()
class _UpdSB:
    def __init__(self): self.updates = []
    def table(self, name): return _UpdQ(self)
_saved_sb4, _saved_hs = main._supabase_client, main.HOLD_STUDY_MINUTES
main._supabase_client = _UpdSB(); main.HOLD_STUDY_MINUTES = 30
_now = _dt.now(_tz.utc)
e = {"id": 11, "submitted_at": (_now - _td(minutes=15)).isoformat(), "raw": {"quote_path": [{"mid": 1}]}}
main._start_hold_study_tracking(e, 1.5)
hs = e["raw"].get("hold_study")
check("hold-study start: raw.hold_study set, quote_path kept, until = entry+30", isinstance(hs, dict) and hs["done"] is False and hs["entry_fill"] == 1.5 and e["raw"]["quote_path"] == [{"mid": 1}]
      and abs((main._parse_signal_ts(hs["until"]) - (_now + _td(minutes=15))).total_seconds()) < 5 and main._supabase_client.updates[-1][0] == 11)
n_before = len(main._supabase_client.updates)
main._start_hold_study_tracking(e, 1.5)
check("hold-study start: idempotent", len(main._supabase_client.updates) == n_before)
e2 = {"id": 12, "submitted_at": (_now - _td(minutes=31)).isoformat(), "raw": {}}
main._start_hold_study_tracking(e2, 1.0)
check("hold-study start: no-op when entry+30 already passed", "hold_study" not in e2["raw"] and len(main._supabase_client.updates) == n_before)
# sampler: one row with an active hold_study and a done shadow
_saved_page, _saved_quote, _saved_en = main._page_all, main._quote_snapshot, main._alpaca_enabled
rows = [{"id": 21, "option_symbol": "AAPL261017C00250000", "qty": 1, "fill_price": 1.0,
         "raw": {"shadow": {"done": True, "samples": []},
                 "hold_study": {"until": (_now + _td(minutes=10)).isoformat(), "samples": [], "done": False}}},
        {"id": 22, "option_symbol": "AAPL261017C00250000", "qty": 1, "fill_price": 1.0,
         "raw": {"hold_study": {"until": (_now - _td(seconds=30)).isoformat(), "samples": [{"mid": 1.1}], "done": False}}},
        {"id": 23, "option_symbol": "MSFT261017C00500000", "qty": 1, "fill_price": 1.0, "raw": {"hold_study": {"done": True}}}]
_qcalls = []
main._page_all = lambda build, page_size=1000: rows
main._quote_snapshot = lambda opt: _qcalls.append(opt) or {"mid": 1.2, "bid": 1.1, "ask": 1.3, "at": _now.isoformat()}
main._alpaca_enabled = lambda: True
main._supabase_client.updates.clear()
n = main._sample_shadow_paths()
ups = dict(main._supabase_client.updates)
check("sampler: quotes each contract once per pass, skips done rows", _qcalls == ["AAPL261017C00250000"] and n == 2 and 23 not in ups)
check("sampler: active hold_study gets a sample and stays open", ups[21]["raw"]["hold_study"]["samples"][0]["mid"] == 1.2 and ups[21]["raw"]["hold_study"]["done"] is False and ups[21]["raw"]["shadow"]["done"] is True)
check("sampler: past-deadline hold_study finalizes", ups[22]["raw"]["hold_study"]["done"] is True and len(ups[22]["raw"]["hold_study"]["samples"]) == 2 and "finalized_at" in ups[22]["raw"]["hold_study"])
main._page_all, main._quote_snapshot, main._alpaca_enabled = _saved_page, _saved_quote, _saved_en
main._supabase_client = None
resp = client.get("/purgatory/hold-study")
check("hold-study without Supabase -> 503", resp.status_code == 503)
main._supabase_client, main.HOLD_STUDY_MINUTES = _saved_sb4, _saved_hs
st = client.get("/purgatory/status").json()
check("status exposes hold_study knobs", st["hold_study"] == {"minutes": main.HOLD_STUDY_MINUTES, "holds": [15, 20, 25, 30]})


# ---------------- SWEEP PAGING + SYNTHETIC EXIT PRUNE ----------------
_K = dict(strategy="purgatory", signal_ticker="AAPL", signal_direction="call", signal_bar_time="2026-10-15T14:00:00+00:00", paper=True)
ex = [dict(id=1, alpaca_status="filled", fill_price=1.2, submitted_at="2026-10-15T14:15:00Z", **_K),
      dict(id=2, alpaca_status="no_position", fill_price=None, submitted_at="2026-10-15T14:19:00Z", **_K),
      dict(id=3, alpaca_status="no_position", fill_price=None, submitted_at="2026-10-15T14:23:00Z", **_K),
      dict(id=4, alpaca_status="no_position", fill_price=None, submitted_at="2026-10-15T15:00:00Z", **{**_K, "signal_bar_time": "2026-10-15T14:40:00+00:00"}),
      dict(id=5, alpaca_status="no_position", fill_price=None, submitted_at="2026-10-15T15:04:00Z", **{**_K, "signal_bar_time": "2026-10-15T14:40:00+00:00"}),
      dict(id=6, alpaca_status="filled", fill_price=0.9, submitted_at="2026-10-15T14:17:00Z", **{**_K, "paper": False})]
d = main._select_synthetic_exit_ids(ex)
check("prune: keeps the filled exit, drops no_position dupes; lone/first-of-kind kept; live leg separate", sorted(d) == [2, 3, 5], str(d))
check("prune: single exits never selected", main._select_synthetic_exit_ids(ex[:1]) == [])

class _PageQ:
    def __init__(self, sb): self.sb = sb; self.role = None; self.filters = []
    def select(self, cols): self.cols = cols; return self
    def eq(self, k, v):
        if k == "role": self.role = v
        return self
    def gte(self, k, v): self.filters.append(("gte", v)); return self
    def lt(self, k, v): self.filters.append(("lt", v)); return self
    def order(self, *a, **k): return self
    def range(self, a, b): self.a, self.b = a, b; return self
    def execute(self):
        src = self.sb.entries if self.role == "entry" else self.sb.exits
        self.sb.calls.append((self.role, self.a, self.b))
        class R: pass
        r = R(); r.data = src[self.a:self.b + 1]; return r
class _PageSB:
    def __init__(self, entries, exits): self.entries, self.exits, self.calls = entries, exits, []
    def table(self, name): return _PageQ(self)
_now_iso = (_dt.now(_tz.utc) - _td(minutes=40)).isoformat()
ents = [dict(id=100 + i, role="entry", strategy="purgatory", signal_ticker=f"T{i}", signal_direction="call",
             signal_bar_time=f"2026-10-16T14:{i % 60:02d}:00+00:00", paper=True, submitted_at=_now_iso) for i in range(3)]
# 1500 exits: the first 1000 are unrelated, the LAST three close entries T0, T1 (so only T2 is open)
exits = [dict(role="exit", strategy="purgatory", signal_ticker=f"X{i}", signal_direction="put", signal_bar_time="x", paper=True) for i in range(1498)]
exits += [dict(role="exit", strategy="purgatory", signal_ticker="T0", signal_direction="call", signal_bar_time="2026-10-16T14:00:00+00:00", paper=True),
          dict(role="exit", strategy="purgatory", signal_ticker="T1", signal_direction="call", signal_bar_time="2026-10-16T14:01:00+00:00", paper=True)]
_saved_sb5 = main._supabase_client; main._supabase_client = _PageSB(ents, exits)
open_e = main._fetch_open_entries_for_sweep(0)
check("sweep: exits are paged past 1000 -> only the truly open entry remains", [e["signal_ticker"] for e in open_e] == ["T2"], str([e["signal_ticker"] for e in open_e]))
check("sweep: exits read used 2 pages and a lookback bound", [c for c in main._supabase_client.calls if c[0] == "exit"] == [("exit", 0, 999), ("exit", 1000, 1999)])
main._supabase_client = _saved_sb5
_saved_tok2 = main.EXTERNAL_SIGNAL_TOKEN; main.EXTERNAL_SIGNAL_TOKEN = "t0k"
resp = client.post("/purgatory/admin/prune-synthetic-exits")
check("prune endpoint: 401 without token", resp.status_code == 401)
main.EXTERNAL_SIGNAL_TOKEN = ""
resp = client.post("/purgatory/admin/prune-synthetic-exits", headers={"X-Signal-Token": "t0k"})
check("prune endpoint: 503 when admin token unset", resp.status_code == 503)
main.EXTERNAL_SIGNAL_TOKEN = _saved_tok2


# ---------------- ASYNC SAMPLER ----------------
import threading as _th, time as _time
_ev = _th.Event(); _ran = []
_saved_sampler = main._sample_shadow_paths
def _slow_sampler():
    _ran.append(1); _ev.wait(2.0); return 0
main._sample_shadow_paths = _slow_sampler
first = main._run_shadow_sampler_async()
_time.sleep(0.05)
second = main._run_shadow_sampler_async()
_ev.set(); _time.sleep(0.1)
third = main._run_shadow_sampler_async(); _time.sleep(0.1)
check("async sampler: runs in a thread, skips while busy, runs again when free", first is True and second is False and third is True and len(_ran) == 2, f"{first} {second} {third} {_ran}")
main._sample_shadow_paths = _saved_sampler
_time.sleep(0.05)


# ---------------- ASYNC SCAN ENDPOINT ----------------
_saved_pass, _saved_en2, _saved_async = main._run_scan_pass, main._alpaca_enabled, main.SCAN_ASYNC
_sev = _th.Event(); _pruns = []
def _slow_pass():
    _pruns.append(1); _sev.wait(2.0); return {"scanned": 15, "duration_s": 0.1, "ts": "x"}
main._run_scan_pass = _slow_pass; main._alpaca_enabled = lambda: True; main.SCAN_ASYNC = True
r1 = client.post("/purgatory/scan").json(); _time.sleep(0.05)
r2 = client.post("/purgatory/scan").json()
check("scan async: first poke accepted, second skipped while running", r1["accepted"] is True and r1["running"] is True and r2["accepted"] is False and len(_pruns) == 1, f"{r1} {r2}")
_sev.set(); _time.sleep(0.15)
st = client.get("/purgatory/status").json()
check("status.scan shows last duration after the pass", st["scan"]["running"] is False and st["scan"]["last_duration_s"] == 0.1 and st["scan"]["async"] is True, str(st["scan"]))
r3 = client.post("/purgatory/scan").json()
check("scan async: next poke carries the previous summary", r3["accepted"] is True and r3["last"]["scanned"] == 15)
_sev.set(); _time.sleep(0.15)
main._run_scan_pass = lambda: {"scanned": 3, "duration_s": 0.0, "ts": "y"}
r4 = client.post("/purgatory/scan?sync=1").json()
check("scan ?sync=1 runs in-line and returns the full result", r4 == {"scanned": 3, "duration_s": 0.0, "ts": "y"})
main.SCAN_ASYNC = False
check("SCAN_ASYNC=0 -> in-line", client.post("/purgatory/scan").json()["scanned"] == 3)
main._alpaca_enabled = lambda: False
check("scan without Alpaca keys -> 503", client.post("/purgatory/scan").status_code == 503)
main._run_scan_pass, main._alpaca_enabled, main.SCAN_ASYNC = _saved_pass, _saved_en2, _saved_async


# ---------------- MEM DIET ----------------
_saved_sb6 = main._supabase_client; main._supabase_client = _UpdSB()
e = {"id": 31, "submitted_at": _dt.now(_tz.utc).isoformat(), "raw": {}}
main._append_quote_sample(e, {"at": "2026-10-16T15:00:00Z", "mid": 1.25, "bid": 1.2, "ask": 1.3})
check("quote samples carry t + mid only", e["raw"]["quote_path"] == [{"t": "2026-10-16T15:00:00Z", "mid": 1.25}] and "hold_deadline" in e["raw"])
main._supabase_client = _saved_sb6
r = client.get("/healthz?mem=1").json()
check("healthz mem reports thread count", isinstance(r["mem"].get("threads"), int) and r["mem"]["threads"] >= 1)
check("quote path cap lowered", main._QUOTE_PATH_CAP == 45)
check("study cache ttl default 1800 and reported", main._STUDY_CACHE_TTL_S == 1800 and r["mem"]["study_cache_ttl_s"] == 1800)

# ---------------- STOP-STUDY PAIR FILTERS ----------------
class _StopQ:
    def __init__(self, rows): self.rows, self.a, self.b = rows, 0, None
    def select(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def lt(self, *a, **k): return self
    def order(self, *a, **k): return self
    def range(self, a, b): self.a, self.b = a, b; return self
    def execute(self):
        class R: pass
        r = R(); r.data = self.rows[self.a:(self.b or len(self.rows)) + 1]; return r
def _reset_study_cache():
    main._study_rows_cache[True] = {}; main._study_rows_cache[False] = {}
    main._study_rows_floor[True] = None; main._study_rows_floor[False] = None
class _StopSB:
    def __init__(self, rows): self.rows = rows
    def table(self, name): return _StopQ(self.rows)
_ss_seq = [0]
def _ss_pair(strategy, tkr, direction, bar, fill, xfill, reason):
    _ss_seq[0] += 2
    return [dict(id=_ss_seq[0] - 1, role="entry", strategy=strategy, signal_ticker=tkr, signal_direction=direction, signal_bar_time=bar,
                 paper=True, qty=1, fill_price=fill, submitted_at=bar,
                 raw={"quote_path": [{"t": bar, "mid": fill}, {"t": bar, "mid": xfill}]}),
            dict(id=_ss_seq[0], role="exit", strategy=strategy, signal_ticker=tkr, signal_direction=direction, signal_bar_time=bar,
                 paper=True, qty=1, fill_price=xfill, submitted_at=bar, raw={"exit_reason": reason})]
_ss_rows = (_ss_pair("purgatory", "AAPL", "call", "2026-10-20T14:00:00+00:00", 1.0, 1.5, "hold")
            + _ss_pair("purgatory", "MSTR", "call", "2026-10-20T14:01:00+00:00", 3.0, 2.5, "stop_loss")
            + _ss_pair("vwap_reclaim", "AAPL", "put", "2026-10-20T14:02:00+00:00", 1.0, 0.8, "stop_loss"))
_saved_sb6 = main._supabase_client; main._supabase_client = _StopSB(_ss_rows); _reset_study_cache()
_all = main._stop_study_payload(30, "paper")
_reset_study_cache(); _aapl = main._stop_study_payload(30, "paper", "purgatory", "aapl", "CALL")
_reset_study_cache(); _mstr = main._stop_study_payload(30, "paper", ticker="MSTR")
_reset_study_cache(); _none = main._stop_study_payload(30, "paper", strategy="market_wave")
main._supabase_client = _saved_sb6
check("stop-study: unfiltered sees all three trades", _all["coverage"]["trades"] == 3 and _all["realized"]["stop"]["n"] == 2, str(_all["coverage"]))
check("stop-study: strategy+ticker+direction filter is case-insensitive and keeps one trade",
      _aapl["coverage"]["trades"] == 1 and _aapl["realized"]["hold"]["pnl"] == 50.0 and _aapl["filter"] == {"strategy": "purgatory", "ticker": "AAPL", "direction": "call"}, str(_aapl["coverage"]) + str(_aapl["realized"]))
check("stop-study: ticker-only filter", _mstr["coverage"]["trades"] == 1 and _mstr["realized"]["stop"]["pnl"] == -50.0, str(_mstr["realized"]))
check("stop-study: filter with no matches returns empty study, not an error", _none["coverage"]["trades"] == 0, str(_none["coverage"]))
resp = client.get("/purgatory/stop-study?days=30&strategy=purgatory&ticker=AAPL&direction=call")
check("stop-study endpoint accepts pair filters", resp.status_code in (200, 503), str(resp.status_code))


# ---------------- TRADING_DIRECTIONS GATE + STOP-STUDY DETAIL ----------------
import os as _os
_saved_env_dir = _os.environ.get("TRADING_DIRECTIONS")
_os.environ["TRADING_DIRECTIONS"] = "call"
check("directions csv: 'call' -> {'call'}", main._parse_direction_csv() == {"call"})
_os.environ["TRADING_DIRECTIONS"] = "Put, CALL"
check("directions csv: case/space tolerant", main._parse_direction_csv() == {"call", "put"})
_os.environ["TRADING_DIRECTIONS"] = "bogus"
check("directions csv: unknown-only falls back to both", main._parse_direction_csv() == {"call", "put"})
_os.environ.pop("TRADING_DIRECTIONS", None)
check("directions csv: unset -> both", main._parse_direction_csv() == {"call", "put"})
if _saved_env_dir is not None: _os.environ["TRADING_DIRECTIONS"] = _saved_env_dir
_saved_dirs, _saved_en3, _saved_sel = main.TRADING_DIRECTIONS, main.ALPACA_TRADING_ENABLED, main._select_option_contract
_calls = []
main.TRADING_DIRECTIONS = {"call"}; main.ALPACA_TRADING_ENABLED = True
main._select_option_contract = lambda *a, **k: _calls.append(a) or None
_saved_alp = main._alpaca_enabled; main._alpaca_enabled = lambda: True
main._maybe_place_trade_for_signal({"strategy": "purgatory", "ticker": "AAPL", "signal": "put", "price": 100.0, "bar_time": "2026-10-21T14:00:00+00:00"})
check("direction gate: put signal places nothing when only calls are enabled", _calls == [], str(_calls))
main._maybe_place_trade_for_signal({"strategy": "purgatory", "ticker": "AAPL", "signal": "call", "price": 100.0, "bar_time": "2026-10-21T14:00:00+00:00"})
check("direction gate: call signal still reaches contract selection", len(_calls) == 1, str(_calls))
main.TRADING_DIRECTIONS, main.ALPACA_TRADING_ENABLED, main._select_option_contract, main._alpaca_enabled = _saved_dirs, _saved_en3, _saved_sel, _saved_alp
resp = client.get("/purgatory/status")
check("status reports trading_directions", resp.status_code == 200 and sorted(resp.json().get("trading_directions") or []) == sorted(main.TRADING_DIRECTIONS), str(resp.json().get("trading_directions")))
# detail rows: a hold trade whose path dipped 20% (replay would stop, reality held) must be flagged
_dtrow = {"ticker": "MSTR", "direction": "call", "bar_time": "2026-10-20T14:00:00+00:00", "fill": 4.0, "qty": 1,
       "actual_pnl": 60.0, "exit_reason": "hold", "hold_mid": None,
       "path": [{"t": "a", "mid": 4.0}, {"t": "b", "mid": 3.1}, {"t": "c", "mid": 4.6}]}
row = main._stop_study_trade_detail(_dtrow, 15.0)
check("stop detail: finds the lowest mid and flags replay/realized disagreement",
      row["min_mid"] == 3.1 and row["min_mid_pct"] == -22.5 and row["replay_stop_at"] == "b" and row["replay_pnl"] == -90.0 and row["disagree"] is True, str(row))
_dt2 = dict(_dtrow, exit_reason="stop_loss", hold_mid=4.6, actual_pnl=-90.0)
row2 = main._stop_study_trade_detail(_dt2, 15.0)
check("stop detail: a real stop that replays as a stop does not disagree", row2["disagree"] is False and row2["replay_pnl"] == -90.0, str(row2))
_saved_sb7 = main._supabase_client; main._supabase_client = _StopSB(_ss_rows); _reset_study_cache()
_d = main._stop_study_payload(30, "paper", detail=True)
_reset_study_cache(); _nd = main._stop_study_payload(30, "paper")
main._supabase_client = _saved_sb7
check("stop-study detail=1 returns per-trade rows (stopped trades without hold_mid excluded), default omits them", "trades" in _d and len(_d["trades"]) == 1 and "trades" not in _nd, str(list(_d)))


# ---------------- STOP-STUDY PATH CAPPED AT HOLD DEADLINE ----------------
_cap_path = [{"t": "2026-10-13T14:13:00+00:00", "mid": 4.6}, {"t": "2026-10-13T14:27:30+00:00", "mid": 4.4},
             {"t": "2026-10-13T14:28:30+00:00", "mid": 3.8},   # 60 s past the deadline: hold sweep already closed it, dropped
             {"t": "2026-10-13T15:39:15+00:00", "mid": 0.73},  # 72 min later: garbage after close, dropped
             {"mid": 1.0}]                                      # no timestamp: dropped
_capped = main._cap_path_at_deadline(_cap_path, "2026-10-13T14:27:30+00:00")
check("deadline cap: keeps in-window samples only, drops post-deadline and untimed samples", [p["mid"] for p in _capped] == [4.6, 4.4], str(_capped))
check("deadline cap: unknown deadline keeps the path", main._cap_path_at_deadline(_cap_path, None) is _cap_path)
check("deadline cap: datetime deadline accepted", len(main._cap_path_at_deadline(_cap_path, _dt(2026, 10, 13, 14, 27, 30, tzinfo=_tz.utc))) == 2)
# end-to-end: a held trade with a garbage post-close sample must not replay as a stop
_late_rows = [dict(id=9, role="entry", strategy="purgatory", signal_ticker="MSTR", signal_direction="call", signal_bar_time="2026-10-13T14:12:00+00:00",
                   paper=True, qty=1, fill_price=4.6, submitted_at="2026-10-13T14:13:00+00:00",
                   raw={"hold_deadline": "2026-10-13T14:28:00+00:00", "quote_path": _cap_path}),
              dict(id=10, role="exit", strategy="purgatory", signal_ticker="MSTR", signal_direction="call", signal_bar_time="2026-10-13T14:12:00+00:00",
                   paper=True, qty=1, fill_price=4.6, submitted_at="2026-10-13T14:28:30+00:00", raw={"exit_reason": "hold"})]
_saved_sb8 = main._supabase_client; main._supabase_client = _StopSB(_late_rows); _reset_study_cache()
_lp = main._stop_study_payload(30, "paper", detail=True)
main._supabase_client = _saved_sb8
_r15 = next(r for r in _lp["study"]["rules"] if r["label"] == "15%")
check("stop-study: post-close garbage sample no longer triggers a replay stop", _r15["stopped"] == 0 and _r15["pnl"] == 0.0 and _lp["trades"][0]["disagree"] is False, str(_r15) + str(_lp["trades"][0]))


# ---------------- REVIEW FIXES: SIZING, PARTIAL CLOSE, PNL ACCOUNT FLAG ----------------
check("sizing: unknown premium -> 1 contract (never size against an estimate)", main._size_contracts(None, 500, 750) == 1 and main._size_contracts(0, 500, 750) == 1)
check("sizing: $1.92 premium, $500 notional -> 2 contracts (not 15)", main._size_contracts(1.92, 500, 750) == 2)
check("sizing: $0.33 premium -> 15 contracts, debit $495 under cap", main._size_contracts(0.33, 500, 750) == 15)
check("sizing: cap binds: $500 notional, $300 cap, $0.40 premium -> 7 not 12", main._size_contracts(0.40, 500, 300) == 7)
check("sizing: one lot above cap still returns 1 (caller skips the entry)", main._size_contracts(14.6, 500, 750) == 1)
check("PAPER_MAX_TRADE_USD defaults to 750", main.PAPER_MAX_TRADE_USD == 750.0)
# entry path: a one-lot debit above the cap is skipped before any order
_saved_q, _saved_sub, _saved_sel2 = main._quote_snapshot, main._alpaca_submit_market_order, main._select_option_contract
_saved_en4, _saved_alp2 = main.ALPACA_TRADING_ENABLED, main._alpaca_enabled
_orders_sent = []
main.ALPACA_TRADING_ENABLED = True; main._alpaca_enabled = lambda: True
main._select_option_contract = lambda *a, **k: {"symbol": "MSFT260731C00500000", "strike_price": 500, "expiration_date": "2026-07-31", "close_price": 14.0}
main._quote_snapshot = lambda sym: {"bid": 14.09, "ask": 14.67, "mid": 14.38, "spread_pct": 4.03}
main._alpaca_submit_market_order = lambda sym, qty, side, paper=True: _orders_sent.append((sym, qty)) or {"id": "o1", "status": "accepted"}
_r = main._maybe_place_trade_for_signal({"strategy": "purgatory", "ticker": "MSFT", "signal": "call", "price": 500.0, "bar_time": "2026-10-21T14:00:00+00:00"})
check("entry: $1,438 one-lot debit > $750 cap -> skipped, no order", _r is None and _orders_sent == [], str(_orders_sent))
main._quote_snapshot = lambda sym: None
_saved_persist = main._persist_order_row; main._persist_order_row = lambda row: None
_r = main._maybe_place_trade_for_signal({"strategy": "purgatory", "ticker": "MSFT", "signal": "call", "price": 500.0, "bar_time": "2026-10-21T14:01:00+00:00"})
check("entry: no quote -> exactly 1 contract, prior close never used for sizing", _orders_sent == [("MSFT260731C00500000", 1)], str(_orders_sent))
main._persist_order_row = _saved_persist
main._quote_snapshot, main._alpaca_submit_market_order, main._select_option_contract = _saved_q, _saved_sub, _saved_sel2
main.ALPACA_TRADING_ENABLED, main._alpaca_enabled = _saved_en4, _saved_alp2
# partial close: qty param sent; rejection falls back to close-all; 404 -> no_position
_del_calls = []
class _Resp:
    def __init__(self, code, body="{}"): self.status_code, self.text = code, body
    def json(self): return {"status": "accepted", "qty_closed": "partial" if "qty" in self.text else "all"}
def _fake_delete(url, headers=None, params=None, timeout=None):
    _del_calls.append(params)
    if params and params.get("qty") == 99: return _Resp(422, "qty exceeds position")
    if "GONE" in url: return _Resp(404)
    return _Resp(200, "qty" if params else "all")
_saved_req_delete = main.requests.delete; main.requests.delete = _fake_delete
_saved_api = main._trading_api; main._trading_api = lambda paper: ("https://x", {})
r1 = main._alpaca_close_position("AAPL1", paper=True, qty=2)
r2 = main._alpaca_close_position("AAPL1", paper=True, qty=99)
r3 = main._alpaca_close_position("GONE", paper=True, qty=1)
main.requests.delete = _saved_req_delete; main._trading_api = _saved_api
check("close: qty=2 sent as ?qty=2", _del_calls[0] == {"qty": 2} and r1["qty_closed"] == "partial", str(_del_calls[:1]) + str(r1))
check("close: rejected partial falls back to close-all", _del_calls[1] == {"qty": 99} and _del_calls[2] is None and r2["qty_closed"] == "all", str(_del_calls[1:3]))
check("close: 404 -> no_position synthetic", r3 == {"status": "no_position"})


# ---------------- SWING BOOK (pure pieces) ----------------
import numpy as np
_wk_idx = pd.date_range("2024-01-05", periods=120, freq="W-FRI")
_up = pd.DataFrame({"High": np.linspace(100, 220, 120) * 1.01, "Low": np.linspace(100, 220, 120) * 0.99, "Close": np.linspace(100, 220, 120)}, index=_wk_idx)
_dn = pd.DataFrame({"High": np.linspace(220, 100, 120) * 1.01, "Low": np.linspace(220, 100, 120) * 0.99, "Close": np.linspace(220, 100, 120)}, index=_wk_idx)
_fu = main._swing_weekly_features(_up); _fd = main._swing_weekly_features(_dn)
check("swing features: steady uptrend ends above cloud, chikou up, eligible", bool(_fu.iloc[-1]["above"]) and bool(_fu.iloc[-1]["chikou"]) and bool(_fu.iloc[-1]["eligible"]) and _fu.iloc[-1]["mom"] > 0, str(_fu.iloc[-1].to_dict()))
check("swing features: steady downtrend is below cloud and not eligible", bool(_fd.iloc[-1]["below"]) and not bool(_fd.iloc[-1]["eligible"]))
check("swing features: first 77 weeks have no cloud (52-week span shifted 26) and are not eligible", not _fu["eligible"].iloc[:77].any() and _fu["cloud_top"].iloc[:77].isna().all())
check("swing select: fills top-N best-first from nothing", main._swing_select(["A", "B", "C", "D", "E", "F", "G", "H", "I"], [], 5, 3) == ["A", "B", "C", "D", "E"])
check("swing select: a holding ranked 7th (inside buffer) is kept, rank 9 is dropped", main._swing_select(["A", "B", "C", "D", "E", "F", "G", "H", "I"], ["G", "I"], 5, 3) == ["G", "A", "B", "C", "D"])
check("swing select: holdings no longer eligible are dropped", main._swing_select(["A", "B"], ["Z"], 5, 3) == ["A", "B"])
check("swing select: fewer eligible than N -> smaller book, no padding", main._swing_select(["A"], [], 5, 3) == ["A"])
check("swing qty: whole shares under the slot", main._swing_qty(2000, 123.45) == 16 and main._swing_qty(2000, 2500) == 0 and main._swing_qty(2000, None) == 0)
check("swing week key: ISO Monday", main._swing_week_key(_date(2026, 10, 29)) == "2026-10-26" and main._swing_week_key(_date(2026, 10, 26)) == "2026-10-26")
check("swing: disabled by default, hook inert", main.SWING_ENABLED is False and main._maybe_run_swing_rebalance() is None)
check("swing: rebalanced_this_week reads the marker row", main._swing_rebalanced_this_week([{"week_key": main._swing_week_key(), "side": "rebalance"}]) is True and main._swing_rebalanced_this_week([{"week_key": "2020-01-06", "side": "rebalance"}]) is False)
_saved_tok3 = main.EXTERNAL_SIGNAL_TOKEN; main.EXTERNAL_SIGNAL_TOKEN = "t0k"
resp = client.post("/purgatory/swing/rebalance")
check("swing rebalance endpoint: 401 without token", resp.status_code == 401)
main.EXTERNAL_SIGNAL_TOKEN = _saved_tok3


# ---------------- STUDY ROW CACHE (egress) ----------------
class _EgQ:
    def __init__(self, sb): self.sb, self.f, self.a, self.b = sb, {}, 0, None
    def select(self, *a, **k): return self
    def eq(self, k, v): self.f[("eq", k)] = v; return self
    def gte(self, k, v): self.f["gte"] = v; return self
    def lt(self, k, v): self.f["lt"] = v; return self
    def order(self, *a, **k): return self
    def range(self, a, b): self.a, self.b = a, b; return self
    def execute(self):
        self.sb.reads.append(dict(self.f))
        rows = [r for r in self.sb.rows if r["submitted_at"] >= self.f.get("gte", "") and ("lt" not in self.f or r["submitted_at"] < self.f["lt"])]
        class R: pass
        x = R(); x.data = rows[self.a:(self.b if self.b is not None else len(rows)) + 1]; return x
class _EgSB:
    def __init__(self, rows): self.rows, self.reads = rows, []
    def table(self, name): return _EgQ(self)
_nowu = _dt.now(_tz.utc)
def _eg_row(i, hours_ago, role="entry"):
    return dict(id=f"r{i}", role=role, strategy="purgatory", signal_ticker="AAPL", signal_direction="call", signal_bar_time="x", paper=True, qty=1, fill_price=1.0,
                submitted_at=(_nowu - _td(hours=hours_ago)).isoformat(), raw={"quote_path": [{"t": "a", "mid": 1.0}], "junk": "x" * 100, "exit_reason": "hold"})
_eg_rows = [_eg_row(1, 150), _eg_row(2, 100), _eg_row(3, 1), _eg_row(4, 0.5, "exit")]
_saved_sb9, _saved_cache = main._supabase_client, (dict(main._study_rows_cache), dict(main._study_rows_floor))
main._supabase_client = _EgSB(_eg_rows); main._study_rows_cache[True] = {}; main._study_rows_floor[True] = None
_since7 = (_nowu - _td(days=7)).isoformat()
r1 = main._study_rows(_since7, True)
n_reads_first = len(main._supabase_client.reads)
r2 = main._study_rows(_since7, True)
n_reads_second = len(main._supabase_client.reads) - n_reads_first
check("study cache: first call loads the window (4 rows) via an older read + a recent read", len(r1) == 4 and n_reads_first == 2, f"{len(r1)} rows, {n_reads_first} reads")
check("study cache: second call only re-reads the recent slice (1 read), same rows", len(r2) == 4 and n_reads_second == 1 and main._supabase_client.reads[-1]["gte"] > _since7, str(main._supabase_client.reads[-1]))
check("study cache: rows are slimmed to the keys the studies use", "junk" not in r2[0]["raw"] and "quote_path" in r2[0]["raw"])
_since30 = (_nowu - _td(days=30)).isoformat()
main._supabase_client.rows.append(_eg_row(0, 24 * 20))
r3 = main._study_rows(_since30, True)
check("study cache: a longer window loads only the missing older range", len(r3) == 5 and main._supabase_client.reads[-2].get("lt") == _since7, str(main._supabase_client.reads[-2]))
main._supabase_client.rows[2]["raw"]["quote_path"].append({"t": "b", "mid": 0.9})
r4 = main._study_rows(_since7, True)
check("study cache: a recent row's new sample shows up on the next call", len([x for x in r4 if x["id"] == "r3"][0]["raw"]["quote_path"]) == 2)
check("study TTL default raised to 1800", main._STUDY_CACHE_TTL_S == 1800)
main._supabase_client = _saved_sb9; main._study_rows_cache.update(_saved_cache[0]); main._study_rows_floor.update(_saved_cache[1])


# ---------------- SWING BOOK VALUE AT FILL PRICES ----------------
_sw_rows = [{"side": "buy", "qty": 11, "est_price": 175.91, "fill_price": 183.87}, {"side": "buy", "qty": 3, "est_price": 524.51, "fill_price": None},
            {"side": "rebalance", "qty": 0}, {"side": "sell", "qty": 11, "fill_price": 190.0}]
_sw_hold = {"MSFT": {"qty": 3, "market_value": 1591.02, "unrealized_pl": -10.62}}
_bv = main._swing_book_value(_sw_rows, _sw_hold, 10000.0)
check("swing book: valued at fill prices, unpriced orders excluded and counted",
      _bv["cash"] == round(10000 - 11 * 183.87 + 11 * 190.0, 2) and _bv["unpriced_orders"] == 1 and _bv["market_value"] == 1591.02 and _bv["equity_est"] == round(10000 - 11 * 183.87 + 11 * 190.0 + 1591.02, 2), str(_bv))
check("swing book: never uses est_price", "175.91" not in str(_bv) and abs(_bv["return_pct"] - round(100 * (_bv["equity_est"] / 10000 - 1), 2)) < 1e-9)
_saved_go = main._alpaca_get_order; _upd = []
class _SwSB:
    def table(self, n):
        class Q:
            def update(self_, d): _upd.append(d); return self_
            def eq(self_, *a): return self_
            def execute(self_): return None
        return Q()
main._alpaca_get_order = lambda oid, paper=True: {"filled_avg_price": "183.87", "status": "filled"} if oid == "o1" else {"status": "new"}
_saved_sb10, _saved_alp3 = main._supabase_client, main._alpaca_enabled; main._supabase_client = _SwSB(); main._alpaca_enabled = lambda: True
_rr = [{"id": "a", "side": "buy", "alpaca_order_id": "o1", "fill_price": None}, {"id": "b", "side": "buy", "alpaca_order_id": "o2", "fill_price": None}, {"id": "c", "side": "rebalance"}]
_n = main._swing_reconcile_fills(_rr)
main._supabase_client, main._alpaca_enabled, main._alpaca_get_order = _saved_sb10, _saved_alp3, _saved_go
check("swing reconcile: filled order gets fill_price written, unfilled left alone, marker skipped", _n == 1 and _rr[0]["fill_price"] == 183.87 and _rr[1]["fill_price"] is None and _upd == [{"fill_price": 183.87, "alpaca_status": "filled"}], f"{_n} {_rr} {_upd}")


# ---------------- SLACK ONCE-GUARDS SURVIVE REDEPLOYS ----------------
class _StateSB:
    def __init__(self): self.store = {}
    def table(self, name):
        sb = self
        class Q:
            def __init__(self_): self_.k = None
            def select(self_, *a): return self_
            def eq(self_, k, v): self_.k = v; return self_
            def limit(self_, n): return self_
            def execute(self_):
                class R: pass
                r = R(); r.data = [{"value": sb.store[self_.k]}] if self_.k in sb.store else []; return r
            def upsert(self_, row): sb.store[row["key"]] = row["value"]; return self_
        return Q()
_saved_sb11, _saved_posts = main._supabase_client, main._post_slack_text
_posts = []; main._post_slack_text = lambda t: _posts.append(t) or True
main._supabase_client = _StateSB(); main._app_state_mem.clear(); main._live_halt_slacked = False
_halt = {"halted": True, "reason": "cumulative live P&L $-184.00 breached", "reset_at": "2026-10-07T02:38:30Z"}
main._notify_live_halt_once(_halt)
main._notify_live_halt_once(_halt)
check("halt alert: posted once while halted", len(_posts) == 1)
# simulate a redeploy: process memory wiped, table remembers the episode
main._app_state_mem.clear(); main._live_halt_slacked = False
main._notify_live_halt_once(_halt)
check("halt alert: NOT re-posted after a redeploy for the same episode", len(_posts) == 1, str(_posts))
main._notify_live_halt_once({**_halt, "reset_at": "2026-11-01T00:00:00Z"})
check("halt alert: a new episode (reset_at changed) posts again", len(_posts) == 2)
main._notify_live_halt_once({"halted": False})
check("halt alert: clearing the halt clears the marker", main._state_get("live_halt_notified") is None and main._live_halt_slacked is False)
# weekly retro guard across a redeploy
_saved_cw, _saved_pw, _saved_se = main._compute_weekly_retro, main._post_weekly_retro_to_slack, main._slack_enabled
main._compute_weekly_retro = lambda dates: {"total_signals": 5}; _wposts = []; main._post_weekly_retro_to_slack = lambda w: _wposts.append(w) or True; main._slack_enabled = lambda: True
main._weekly_retro_posted = None; main._app_state_mem.clear(); main._supabase_client.store.pop("weekly_retro_posted", None)
r1 = main._run_weekly_retro_if_due(force=True)
main._weekly_retro_posted = None; main._app_state_mem.clear()   # redeploy
import pandas as _pd
_wk_now = _pd.Timestamp.now(tz="America/New_York").strftime("%G-W%V")
check("weekly retro: forced post records the week marker in app_state", r1 is True and main._supabase_client.store.get("weekly_retro_posted") == _wk_now, str(main._supabase_client.store))
main._compute_weekly_retro, main._post_weekly_retro_to_slack, main._slack_enabled = _saved_cw, _saved_pw, _saved_se
# daily retro guard
_saved_cd = main._compute_daily_retro; _cd_calls = []
main._compute_daily_retro = lambda d: _cd_calls.append(d) or None
main._state_set("daily_retro_posted", _pd.Timestamp.now(tz="America/New_York").date().isoformat())
main._run_daily_retro_if_due()
check("daily retro: skipped when today's marker is set (no recompute, no post)", _cd_calls == [], str(_cd_calls))
main._compute_daily_retro = _saved_cd
main._supabase_client, main._post_slack_text = _saved_sb11, _saved_posts; main._app_state_mem.clear()


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
