"""Synthetic-data tests for orb_ntz_strategy. Run: python test_orb.py"""

from datetime import datetime, timedelta
from orb_ntz_strategy import (
    Bar, Direction, ORBConfig, ORBEngine, SizeTier, SizingTracker,
    compute_ntz, find_pivot_levels, nearest_levels, ET,
)


def mk(day, hh, mm, o, h, l, c):
    return Bar(ts=datetime(2026, 7, day, hh, mm, tzinfo=ET),
               open=o, high=h, low=l, close=c, volume=1000)


def stream(engine, bars):
    sigs = []
    for b in bars:
        s = engine.on_bar(b)
        if s:
            sigs.append(s)
    return sigs


def test_ntz():
    pm = [mk(9, 8, 0, 100, 101.5, 99.5, 100.2), mk(9, 9, 0, 100.2, 102.0, 100.0, 101.0)]
    ntz = compute_ntz(pm, prev_day_high=103.0, prev_day_low=99.0)
    assert ntz.high == 103.0, ntz.high     # yesterday's high wins
    assert ntz.low == 99.0, ntz.low        # yesterday's low wins
    ntz2 = compute_ntz(pm, prev_day_high=101.0, prev_day_low=99.8)
    assert ntz2.high == 102.0              # premarket high wins
    assert ntz2.low == 99.5
    print("PASS  NTZ computation")


def test_pivots():
    bars = []
    base = datetime(2026, 7, 6, 9, 0, tzinfo=ET)
    prices = [100, 101, 103, 101, 100, 99, 97, 99, 100, 102, 104, 102, 101]
    for i, p in enumerate(prices):
        ts = base + timedelta(hours=i)
        bars.append(Bar(ts=ts, open=p, high=p + 0.5, low=p - 0.5, close=p))
    levels = find_pivot_levels(bars, pivot_window=2)
    assert levels, "should find pivot levels"
    assert any(abs(l - 103.5) < 1 for l in levels), levels   # swing high ~103.5
    assert any(abs(l - 96.5) < 1 for l in levels), levels    # swing low ~96.5
    below, above = nearest_levels(levels, 100.0)
    assert all(l < 100 for l in below) and all(l > 100 for l in above)
    print("PASS  pivot level detection:", [round(l, 2) for l in levels])


def happy_path_bars():
    """Break below ORB (outside NTZ), retest, hold, entry next candle."""
    bars = []
    # Premarket: range 99.5-101.0
    bars += [mk(9, 8, 0, 100, 101.0, 99.5, 100.2)]
    # ORB 9:30-9:45 (2-min bars): range 99.8-100.6
    bars += [
        mk(9, 9, 30, 100.2, 100.6, 100.0, 100.3),
        mk(9, 9, 32, 100.3, 100.5, 99.9, 100.1),
        mk(9, 9, 34, 100.1, 100.4, 99.8, 100.0),
        mk(9, 9, 36, 100.0, 100.3, 99.9, 100.2),
        mk(9, 9, 38, 100.2, 100.5, 100.0, 100.4),
        mk(9, 9, 40, 100.4, 100.6, 100.1, 100.2),
        mk(9, 9, 42, 100.2, 100.4, 99.9, 100.0),
        mk(9, 9, 44, 100.0, 100.2, 99.8, 99.9),
    ]
    # NTZ is [98.5, 101.5] (prev day). Break candle must close < ORB low
    # AND < NTZ low to be valid outside-NTZ.
    bars += [
        mk(9, 9, 46, 99.9, 99.9, 98.2, 98.3),   # closes below ORB low & NTZ low
        mk(9, 9, 48, 98.3, 98.5, 97.9, 98.1),   # impulse continues... wait, 98.5 tags
    ]
    # Note: 9:48 high of 98.5 already tags the NTZ low (98.5) — but its
    # close (98.1) holds below, so it IS the retest candle.
    bars += [
        mk(9, 9, 50, 98.1, 98.2, 97.5, 97.6),   # ENTRY candle (open 98.1)
        mk(9, 9, 52, 97.6, 97.7, 97.0, 97.1),
    ]
    return bars


def test_happy_path_puts():
    eng = ORBEngine("TEST", ORBConfig())
    eng.set_session_context(prev_day_high=101.5, prev_day_low=98.5,
                            exit_levels=[97.0, 98.0, 102.0, 103.0],
                            seed_closes=[101.0] * 200)  # SMA ~101 -> price below = puts OK
    sigs = stream(eng, happy_path_bars())
    assert len(sigs) == 1, f"expected 1 signal, got {len(sigs)}"
    s = sigs[0]
    assert s.direction is Direction.PUTS
    assert abs(s.entry_price - 98.1) < 1e-9, s.entry_price   # OPEN of candle AFTER retest
    assert abs(s.stop_price - 100.6) < 1e-9, s.stop_price    # other side of ORB
    assert s.targets and s.targets[0] == 98.0, s.targets     # nearest level below first
    assert not s.inside_ntz
    print("PASS  happy path puts:", s.summary())


def test_trend_filter_blocks():
    eng = ORBEngine("TEST", ORBConfig(allow_without_trend_filter=False))
    # SMA seeded at 95 -> price ~99 is ABOVE SMA -> puts not allowed.
    eng.set_session_context(101.5, 98.5, seed_closes=[95.0] * 200)
    sigs = stream(eng, happy_path_bars())
    assert len(sigs) == 0, "trend filter should block counter-trend puts"
    print("PASS  200 SMA trend filter blocks counter-trend signal")


def test_break_inside_ntz_ignored():
    eng = ORBEngine("TEST", ORBConfig())
    # Huge NTZ swallows the break -> no signal.
    eng.set_session_context(prev_day_high=110.0, prev_day_low=90.0,
                            seed_closes=[101.0] * 200)
    sigs = stream(eng, happy_path_bars())
    assert len(sigs) == 0, "break inside NTZ must be ignored"
    print("PASS  break inside NTZ suppressed")


def test_no_retest_no_trade():
    eng = ORBEngine("TEST", ORBConfig())
    eng.set_session_context(101.5, 98.5, seed_closes=[101.0] * 200)
    bars = happy_path_bars()[:10]  # break + impulse, but cut before the retest
    bars += [mk(9, 9, 50, 98.1, 98.2, 97.5, 97.6),  # keeps falling, never retests
             mk(9, 9, 52, 97.6, 97.7, 97.0, 97.1)]
    sigs = stream(eng, bars)
    assert len(sigs) == 0, "no retest must mean no trade"
    print("PASS  no retest -> no trade")


def test_failed_retest_invalidates():
    eng = ORBEngine("TEST", ORBConfig())
    eng.set_session_context(101.5, 98.5, seed_closes=[101.0] * 200)
    bars = happy_path_bars()[:10]  # premarket + ORB + break candle only
    # Retest candle tags the level (98.5) but closes back ABOVE it -> failed.
    bars += [mk(9, 9, 48, 98.3, 99.0, 98.2, 98.9),
             mk(9, 9, 50, 98.9, 99.1, 98.6, 99.0)]
    sigs = stream(eng, bars)
    assert len(sigs) == 0, "retest candle closing back through level must invalidate"
    print("PASS  failed retest invalidates setup")


def test_cutoff():
    eng = ORBEngine("TEST", ORBConfig())
    eng.set_session_context(101.5, 98.5, seed_closes=[101.0] * 200)
    bars = happy_path_bars()[:10]
    # Retest happens at 11:05 — past the cutoff, no signal.
    bars += [mk(9, 11, 5, 98.1, 99.82, 98.0, 99.5),
             mk(9, 11, 7, 99.4, 99.5, 98.0, 98.2)]
    sigs = stream(eng, bars)
    assert len(sigs) == 0, "signals after 11:00 must be suppressed"
    print("PASS  11:00 cutoff enforced")


def test_sizing():
    st = SizingTracker()
    assert st.current_tier() is SizeTier.SMALL
    st.record_result(True)
    assert st.current_tier() is SizeTier.NORMAL
    st.record_result(True)
    assert st.current_tier() is SizeTier.LARGE
    st.record_result(False)
    assert st.current_tier() is SizeTier.SMALL
    st.record_result(False)
    assert st.current_tier() is SizeTier.STAND_DOWN
    st.reset_day()
    assert st.current_tier() is SizeTier.SMALL
    print("PASS  bell-curve sizing tracker")


def test_purgatory_gate_helper():
    eng = ORBEngine("TEST", ORBConfig())
    eng.set_session_context(101.5, 98.5, seed_closes=[101.0] * 200)
    for b in happy_path_bars()[:2]:
        eng.on_bar(b)
    assert eng.price_inside_ntz(100.0) is True
    assert eng.price_inside_ntz(98.0) is False
    print("PASS  price_inside_ntz() gate for Purgatory signals")


if __name__ == "__main__":
    test_ntz()
    test_pivots()
    test_happy_path_puts()
    test_trend_filter_blocks()
    test_break_inside_ntz_ignored()
    test_no_retest_no_trade()
    test_failed_retest_invalidates()
    test_cutoff()
    test_sizing()
    test_purgatory_gate_helper()
    print("\nAll tests passed.")
