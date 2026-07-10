"""
ORB + NTZ Strategy Module
=========================

Implements the "boring" opening-range-breakout system:

  1. NTZ (No Trading Zone)  — box built from premarket high/low and the
     previous day's RTH high/low. All signals are suppressed while price
     is inside the box. Exposed standalone so it can also gate your
     existing Purgatory Method signals.
  2. ORB entry              — first-15-minute range (9:30–9:45 ET).
     Sequence required: candle CLOSES beyond the ORB (outside the NTZ)
     -> price pulls back and RETESTS the broken level -> signal fires on
     the OPEN of the candle AFTER the retest candle.
  3. Trend filter           — 200 SMA on the feed timeframe. Breakout
     direction must agree (above = calls only, below = puts only).
  4. Confluence scoring     — retest quality: 8 EMA tag, Fib 0.236/0.382
     pullback zone, proximity to a pre-marked hourly level.
  5. Exit levels            — hourly swing-pivot levels (2-3 above and
     below the open), attached to each signal as scale-out targets.
  6. Bell-curve sizing      — daily P&L state machine that emits a size
     tier ("small" / "normal" / "stand_down") for each alert.

Integration surface (see integration_guide.md):

    engine = ORBEngine(config=ORBConfig())
    engine.set_session_context(prev_day_high, prev_day_low, exit_levels)
    for bar in intraday_bars:            # chronological, single ticker
        signal = engine.on_bar(bar)
        if signal:
            notify(signal)               # your existing notifier

All timestamps are assumed to be US/Eastern (naive or tz-aware both
work; naive datetimes are treated as ET).

No third-party dependencies — stdlib only — so it drops into the
FastAPI app without touching requirements.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# --------------------------------------------------------------------------
# Data types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Bar:
    """One OHLCV bar. `ts` is the bar's START time in US/Eastern."""
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def et(self) -> datetime:
        """Return ts normalized to US/Eastern."""
        if self.ts.tzinfo is None:
            return self.ts.replace(tzinfo=ET)
        return self.ts.astimezone(ET)


class Direction(str, enum.Enum):
    CALLS = "calls"   # broke above ORB high
    PUTS = "puts"     # broke below ORB low


class SizeTier(str, enum.Enum):
    SMALL = "small"
    NORMAL = "normal"
    LARGE = "large"
    STAND_DOWN = "stand_down"


@dataclass
class Signal:
    """Emitted once per qualifying setup. Feed straight to your notifier."""
    ticker: str
    ts: datetime                  # open time of the entry candle
    direction: Direction
    entry_price: float            # open of the entry candle
    stop_price: float             # other side of the ORB
    targets: list[float]          # nearest pre-marked levels, closest first
    orb_high: float
    orb_low: float
    confluence_score: int         # 0-3
    confluence_reasons: list[str]
    size_tier: SizeTier
    inside_ntz: bool              # should always be False for ORB signals
    note: str = ""

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["direction"] = self.direction.value
        d["size_tier"] = self.size_tier.value
        d["ts"] = self.ts.isoformat()
        return d

    def summary(self) -> str:
        tgt = ", ".join(f"{t:.2f}" for t in self.targets) or "n/a"
        return (
            f"{self.ticker} {self.direction.value.upper()} @ {self.entry_price:.2f} | "
            f"stop {self.stop_price:.2f} | targets [{tgt}] | "
            f"confluence {self.confluence_score}/3 ({'; '.join(self.confluence_reasons) or 'none'}) | "
            f"size: {self.size_tier.value}"
        )


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


@dataclass
class ORBConfig:
    market_open: time = time(9, 30)
    orb_end: time = time(9, 45)          # first 15 minutes
    signal_cutoff: time = time(11, 0)    # no new signals after this
    premarket_start: time = time(4, 0)

    sma_period: int = 200                # trend filter, feed timeframe
    ema_period: int = 8                  # confluence EMA

    # Retest tolerance: how close price must come back to the broken ORB
    # level to count as a retest, as a fraction of price (0.0005 = 0.05%).
    retest_tolerance_pct: float = 0.0005

    # Confluence: how close (fraction of price) counts as "tagging"
    # the 8 EMA / a fib level / a pre-marked level.
    confluence_tolerance_pct: float = 0.0015

    # If the trend filter can't be computed (not enough bars for the
    # 200 SMA), allow the signal anyway but note it. Set False to be strict.
    allow_without_trend_filter: bool = True

    # Minimum confluence score required to emit a signal (0 = emit all,
    # score is included so you can filter downstream).
    min_confluence: int = 0

    # If the ORB break candle closes while still inside the NTZ, ignore it.
    require_break_outside_ntz: bool = True


# --------------------------------------------------------------------------
# NTZ — No Trading Zone
# --------------------------------------------------------------------------


@dataclass
class NTZ:
    """Box from premarket high/low widened by yesterday's high/low."""
    high: float
    low: float

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high

    def candle_inside(self, bar: Bar) -> bool:
        """True if the bar's close is inside the box."""
        return self.contains(bar.close)


def compute_ntz(
    premarket_bars: Sequence[Bar],
    prev_day_high: float,
    prev_day_low: float,
) -> NTZ:
    """
    NTZ high = max(premarket high, yesterday's high)
    NTZ low  = min(premarket low,  yesterday's low)

    `premarket_bars` should be today's extended-hours bars before 9:30 ET.
    """
    if premarket_bars:
        pm_high = max(b.high for b in premarket_bars)
        pm_low = min(b.low for b in premarket_bars)
    else:
        # No premarket data — fall back to yesterday's range alone.
        pm_high, pm_low = prev_day_high, prev_day_low
    return NTZ(high=max(pm_high, prev_day_high), low=min(pm_low, prev_day_low))


# --------------------------------------------------------------------------
# Exit levels — hourly swing pivots
# --------------------------------------------------------------------------


def find_pivot_levels(
    hourly_bars: Sequence[Bar],
    lookback_sessions: int = 5,
    pivot_window: int = 2,
    cluster_pct: float = 0.002,
) -> list[float]:
    """
    Detect the video's "bends": local highs/lows on the hourly chart
    (extended hours included) over roughly the last `lookback_sessions`
    days, then merge levels within `cluster_pct` of each other.

    Returns all clustered levels sorted ascending. Use `nearest_levels()`
    to pick the 2-3 above/below the open.
    """
    if not hourly_bars:
        return []

    cutoff = hourly_bars[-1].et() - timedelta(days=lookback_sessions + 2)
    bars = [b for b in hourly_bars if b.et() >= cutoff]
    n = len(bars)
    raw: list[float] = []
    w = pivot_window
    for i in range(w, n - w):
        window = bars[i - w : i + w + 1]
        hi = bars[i].high
        lo = bars[i].low
        if hi == max(b.high for b in window):
            raw.append(hi)
        if lo == min(b.low for b in window):
            raw.append(lo)

    if not raw:
        return []

    raw.sort()
    clustered: list[list[float]] = [[raw[0]]]
    for lvl in raw[1:]:
        anchor = clustered[-1][0]
        if anchor and abs(lvl - anchor) / anchor <= cluster_pct:
            clustered[-1].append(lvl)
        else:
            clustered.append([lvl])
    return [sum(c) / len(c) for c in clustered]


def nearest_levels(
    levels: Sequence[float], ref_price: float, per_side: int = 3
) -> tuple[list[float], list[float]]:
    """Split levels around ref_price: (below desc-by-distance? no —
    below sorted nearest-first, above sorted nearest-first)."""
    below = sorted((l for l in levels if l < ref_price), key=lambda l: ref_price - l)
    above = sorted((l for l in levels if l > ref_price), key=lambda l: l - ref_price)
    return below[:per_side], above[:per_side]


# --------------------------------------------------------------------------
# Indicators (incremental, no pandas required)
# --------------------------------------------------------------------------


class RollingSMA:
    def __init__(self, period: int):
        self.period = period
        self.values: list[float] = []
        self._sum = 0.0

    def update(self, value: float) -> Optional[float]:
        self.values.append(value)
        self._sum += value
        if len(self.values) > self.period:
            self._sum -= self.values.pop(0)
        if len(self.values) < self.period:
            return None
        return self._sum / self.period

    @property
    def current(self) -> Optional[float]:
        if len(self.values) < self.period:
            return None
        return self._sum / self.period


class RollingEMA:
    def __init__(self, period: int):
        self.period = period
        self.k = 2.0 / (period + 1)
        self.value: Optional[float] = None
        self._seed: list[float] = []

    def update(self, price: float) -> Optional[float]:
        if self.value is None:
            self._seed.append(price)
            if len(self._seed) >= self.period:
                self.value = sum(self._seed) / len(self._seed)
            return self.value
        self.value = price * self.k + self.value * (1 - self.k)
        return self.value


# --------------------------------------------------------------------------
# Bell-curve sizing tracker
# --------------------------------------------------------------------------


class SizingTracker:
    """
    First trade of the day: SMALL.
    Green + clean: step up (SMALL -> NORMAL -> LARGE).
    Red: step back down; two consecutive losses: STAND_DOWN for the day.
    Call `record_result(win: bool)` from wherever you track outcomes;
    if you don't track outcomes yet it just stays on SMALL, which is
    the safe default.
    """

    def __init__(self):
        self.reset_day()

    def reset_day(self) -> None:
        self.trades_today = 0
        self.consecutive_losses = 0
        self.tier = SizeTier.SMALL
        self.stopped = False

    def current_tier(self) -> SizeTier:
        if self.stopped:
            return SizeTier.STAND_DOWN
        if self.trades_today == 0:
            return SizeTier.SMALL
        return self.tier

    def record_result(self, win: bool) -> None:
        self.trades_today += 1
        if win:
            self.consecutive_losses = 0
            self.tier = {
                SizeTier.SMALL: SizeTier.NORMAL,
                SizeTier.NORMAL: SizeTier.LARGE,
                SizeTier.LARGE: SizeTier.LARGE,
            }.get(self.tier, SizeTier.NORMAL)
        else:
            self.consecutive_losses += 1
            self.tier = SizeTier.SMALL
            if self.consecutive_losses >= 2:
                self.stopped = True


# --------------------------------------------------------------------------
# ORB engine — the state machine
# --------------------------------------------------------------------------


class ORBState(str, enum.Enum):
    PREMARKET = "premarket"           # collecting premarket bars
    FORMING = "forming"               # 9:30-9:45, building the ORB
    ARMED = "armed"                   # ORB locked, waiting for a break
    BROKEN = "broken"                 # closed beyond ORB, waiting for retest
    RETESTED = "retested"             # retest candle closed, fire on next open
    SIGNALED = "signaled"             # signal emitted (one per direction)
    DONE = "done"                     # past cutoff / stood down


@dataclass
class _BreakContext:
    direction: Direction
    level: float          # the ORB level that was broken
    break_close: float    # close of the break candle
    impulse_extreme: float  # furthest price reached since the break (for fibs)


class ORBEngine:
    """
    Single-ticker, single-session engine. Instantiate one per ticker per
    day (or call `reset_session()` each morning).

    Feed bars in chronological order via `on_bar(bar)`. Premarket bars
    (before 9:30 ET) are consumed automatically to build the NTZ, so you
    can just stream the whole extended-hours session through it.
    """

    def __init__(
        self,
        ticker: str = "",
        config: Optional[ORBConfig] = None,
        sizing: Optional[SizingTracker] = None,
    ):
        self.ticker = ticker
        self.cfg = config or ORBConfig()
        self.sizing = sizing or SizingTracker()
        self.reset_session()

    # -- session lifecycle -------------------------------------------------

    def reset_session(self) -> None:
        self.state = ORBState.PREMARKET
        self.premarket_bars: list[Bar] = []
        self.ntz: Optional[NTZ] = None
        self.prev_day_high: Optional[float] = None
        self.prev_day_low: Optional[float] = None
        self.exit_levels: list[float] = []
        self.orb_high: float = -math.inf
        self.orb_low: float = math.inf
        self.sma = RollingSMA(self.cfg.sma_period)
        self.ema8 = RollingEMA(self.cfg.ema_period)
        self._break: Optional[_BreakContext] = None
        self._signaled_directions: set[Direction] = set()
        self._pending_entry: Optional[_BreakContext] = None
        self._retest_confluence: tuple[int, list[str]] = (0, [])

    def set_session_context(
        self,
        prev_day_high: float,
        prev_day_low: float,
        exit_levels: Optional[Iterable[float]] = None,
        seed_closes: Optional[Iterable[float]] = None,
    ) -> None:
        """
        Call once each morning before streaming bars.

        prev_day_high / prev_day_low : yesterday's RTH high and low.
        exit_levels : output of find_pivot_levels() on hourly bars.
        seed_closes : optional prior closes (same timeframe as the feed)
            to pre-warm the 200 SMA so the trend filter is live from the
            open instead of needing 200 intraday bars.
        """
        self.prev_day_high = prev_day_high
        self.prev_day_low = prev_day_low
        self.exit_levels = sorted(exit_levels or [])
        for c in seed_closes or []:
            self.sma.update(c)
            self.ema8.update(c)

    # -- helpers -----------------------------------------------------------

    def _near(self, a: float, b: float, tol_pct: float) -> bool:
        ref = max(abs(a), abs(b), 1e-9)
        return abs(a - b) / ref <= tol_pct

    def _trend_allows(self, direction: Direction, price: float) -> tuple[bool, str]:
        sma = self.sma.current
        if sma is None:
            if self.cfg.allow_without_trend_filter:
                return True, "trend filter unavailable (SMA not warm)"
            return False, "trend filter unavailable"
        if direction is Direction.CALLS and price > sma:
            return True, "above 200 SMA"
        if direction is Direction.PUTS and price < sma:
            return True, "below 200 SMA"
        return False, "against 200 SMA"

    def _fib_levels(self, brk: _BreakContext) -> list[float]:
        """0.236 / 0.382 retracements of the impulse from the ORB level."""
        span = brk.impulse_extreme - brk.level
        return [brk.impulse_extreme - span * r for r in (0.236, 0.382)]

    def _score_confluence(self, bar: Bar, brk: _BreakContext) -> tuple[int, list[str]]:
        score, reasons = 0, []
        tol = self.cfg.confluence_tolerance_pct
        touch = bar.low if brk.direction is Direction.CALLS else bar.high

        ema = self.ema8.value
        if ema is not None and self._near(touch, ema, tol):
            score += 1
            reasons.append("tagged 8 EMA")

        for fib in self._fib_levels(brk):
            if self._near(touch, fib, tol * 2):
                score += 1
                reasons.append("fib 0.236/0.382 zone")
                break

        for lvl in self.exit_levels:
            if self._near(touch, lvl, tol):
                score += 1
                reasons.append(f"pre-marked level {lvl:.2f}")
                break

        return score, reasons

    def price_inside_ntz(self, price: float) -> bool:
        """Public helper — use this to gate your Purgatory signals too."""
        return self.ntz.contains(price) if self.ntz else False

    # -- main entry point ----------------------------------------------------

    def on_bar(self, bar: Bar) -> Optional[Signal]:
        t = bar.et().time()
        cfg = self.cfg

        # 1) Premarket: accumulate for the NTZ.
        if t < cfg.market_open:
            if t >= cfg.premarket_start:
                self.premarket_bars.append(bar)
            return None

        # 2) First RTH bar: lock the NTZ.
        if self.ntz is None:
            if self.prev_day_high is None or self.prev_day_low is None:
                raise RuntimeError(
                    "set_session_context() must be called with yesterday's "
                    "high/low before regular-hours bars arrive"
                )
            self.ntz = compute_ntz(
                self.premarket_bars, self.prev_day_high, self.prev_day_low
            )
            self.state = ORBState.FORMING

        # Indicators update on every RTH bar regardless of state.
        self.sma.update(bar.close)
        self.ema8.update(bar.close)

        # 3) Hard cutoff.
        if t >= cfg.signal_cutoff:
            self.state = ORBState.DONE
            return None

        # 4) Build the ORB during the first 15 minutes.
        if t < cfg.orb_end:
            self.orb_high = max(self.orb_high, bar.high)
            self.orb_low = min(self.orb_low, bar.low)
            return None
        if self.state is ORBState.FORMING:
            self.state = ORBState.ARMED

        # 5) A retest was confirmed on the previous bar -> this bar's open
        #    is the entry. This runs before break/retest detection so the
        #    entry uses the OPEN of the candle after the retest candle.
        if self.state is ORBState.RETESTED and self._pending_entry is not None:
            return self._emit_signal(bar)

        # 6) Waiting for a break: candle must CLOSE beyond the ORB.
        if self.state is ORBState.ARMED:
            direction: Optional[Direction] = None
            level = 0.0
            if bar.close > self.orb_high:
                direction, level = Direction.CALLS, self.orb_high
            elif bar.close < self.orb_low:
                direction, level = Direction.PUTS, self.orb_low

            if direction and direction not in self._signaled_directions:
                if cfg.require_break_outside_ntz and self.ntz.contains(bar.close):
                    return None  # broke ORB but still inside NTZ — not valid
                ok, _ = self._trend_allows(direction, bar.close)
                if not ok:
                    return None
                # Retest level = the OUTERMOST broken structure. If the NTZ
                # edge is beyond the ORB level in the break direction, a
                # pullback hits the NTZ boundary first — that's the retest
                # (per the video: "came back and retested the NTZ"). This
                # also keeps the entry outside the box.
                if direction is Direction.CALLS:
                    level = max(level, self.ntz.high)
                else:
                    level = min(level, self.ntz.low)
                self._break = _BreakContext(
                    direction=direction,
                    level=level,
                    break_close=bar.close,
                    impulse_extreme=bar.high if direction is Direction.CALLS else bar.low,
                )
                self.state = ORBState.BROKEN
            return None

        # 7) Broken: track the impulse and watch for the retest.
        if self.state is ORBState.BROKEN and self._break is not None:
            brk = self._break
            if brk.direction is Direction.CALLS:
                brk.impulse_extreme = max(brk.impulse_extreme, bar.high)
                # Failed break: close back below the ORB high -> re-arm.
                if bar.close < brk.level and self.ntz.contains(bar.close):
                    self.state = ORBState.ARMED
                    self._break = None
                    return None
                tol = brk.level * cfg.retest_tolerance_pct
                touched = bar.low <= brk.level + tol
            else:
                brk.impulse_extreme = min(brk.impulse_extreme, bar.low)
                if bar.close > brk.level and self.ntz.contains(bar.close):
                    self.state = ORBState.ARMED
                    self._break = None
                    return None
                tol = brk.level * cfg.retest_tolerance_pct
                touched = bar.high >= brk.level - tol

            if touched:
                # This is the retest candle. Per the rules we do NOT enter
                # here — we enter on the next candle's open, provided the
                # retest candle didn't close back through the level.
                held = (
                    bar.close >= brk.level
                    if brk.direction is Direction.CALLS
                    else bar.close <= brk.level
                )
                if held:
                    self._retest_confluence = self._score_confluence(bar, brk)
                    self._pending_entry = brk
                    self.state = ORBState.RETESTED
                else:
                    # Retest failed (closed back through) — invalidated.
                    self.state = ORBState.ARMED
                    self._break = None
            return None

        return None

    # -- signal construction -------------------------------------------------

    def _emit_signal(self, entry_bar: Bar) -> Optional[Signal]:
        brk = self._pending_entry
        assert brk is not None
        self._pending_entry = None
        self._break = None
        self._signaled_directions.add(brk.direction)
        # Allow the opposite direction later in the window:
        self.state = ORBState.ARMED

        score, reasons = self._retest_confluence
        if score < self.cfg.min_confluence:
            return None

        entry = entry_bar.open
        stop = self.orb_low if brk.direction is Direction.CALLS else self.orb_high
        below, above = nearest_levels(self.exit_levels, entry)
        targets = above if brk.direction is Direction.CALLS else below

        ok, trend_note = self._trend_allows(brk.direction, entry)
        return Signal(
            ticker=self.ticker,
            ts=entry_bar.et(),
            direction=brk.direction,
            entry_price=entry,
            stop_price=stop,
            targets=list(targets),
            orb_high=self.orb_high,
            orb_low=self.orb_low,
            confluence_score=score,
            confluence_reasons=reasons,
            size_tier=self.sizing.current_tier(),
            inside_ntz=self.ntz.contains(entry) if self.ntz else False,
            note=f"ORB break+retest; {trend_note}",
        )
