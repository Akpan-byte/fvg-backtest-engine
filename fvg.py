# CHANGE_SUMMARY
# 2026-07-14  kimi-swarm
#   - Created fvg.py: Fair Value Gap (FVG) + Breakaway Gap (BAG) detection and
#     state tracking over candle sequences (find_fvgs, update_gap_states,
#     active_gaps, consequent_timeframe, requires_consequent_zoom).
# WHY: This is the core signal primitive — every higher module (context,
#      structure, engine) consumes the gaps produced and maintained here.
"""
Fair Value Gap (FVG) and Breakaway Gap (BAG) detection.

Implements the mechanical ICT gap rules from the strategy brief:

- Bullish FVG: high(C1) < low(C3)   ->  zone = [high(C1), low(C3)].
- Bearish FVG: low(C1) > high(C3)   ->  zone = [high(C3), low(C1)].
  The wicks of C1 and C3 must NOT touch (hence the strict inequalities).
- BAG: an FVG whose C3 closes beyond C2's extreme (high for bullish, low for
  bearish) AND closes strong — within config.BAG_CLOSE_STRENGTH (0.30) of its
  own range extreme.
- Gaps are single-use: the first time price taps a zone it is spent forever.
- A BAG on a timeframe above M5 is not traded directly; the strategy zooms to
  the consequent (next lower) timeframe and looks for a plain FVG there.
"""
from __future__ import annotations

import config
from models import Candle, Direction, FairValueGap, GapType

__all__ = [
    "find_fvgs",
    "update_gap_states",
    "active_gaps",
    "consequent_timeframe",
    "requires_consequent_zoom",
    "IncrementalGapTracker",
]


def _is_strong_close(candle: Candle, direction: Direction) -> bool:
    """True if `candle` closes within config.BAG_CLOSE_STRENGTH of its own range
    extreme in `direction` (top 30% of range for bullish, bottom 30% for bearish).

    Implements the BAG "closes strong" requirement. The check multiplies instead
    of dividing so a degenerate zero-range candle (high == low) is never treated
    as a momentum bar.
    """
    rng = candle.high - candle.low
    if rng <= 0:
        return False
    if direction == Direction.BULLISH:
        distance_from_extreme = candle.high - candle.close
    else:
        distance_from_extreme = candle.close - candle.low
    return distance_from_extreme <= config.BAG_CLOSE_STRENGTH * rng


def _classify_gap(c2: Candle, c3: Candle, direction: Direction) -> GapType:
    """Return GapType.BAG if the gap is a breakaway gap, else GapType.FVG.

    BAG rule: C3 closes beyond C2's extreme (above C2.high for bullish, below
    C2.low for bearish) AND C3 closes strong (within BAG_CLOSE_STRENGTH of its
    own range extreme). Both conditions must hold.
    """
    if direction == Direction.BULLISH:
        closes_beyond = c3.close > c2.high
    else:
        closes_beyond = c3.close < c2.low
    if closes_beyond and _is_strong_close(c3, direction):
        return GapType.BAG
    return GapType.FVG


def find_fvgs(candles: list[Candle], timeframe: str) -> list[FairValueGap]:
    """Scan every consecutive 3-candle window and return all FVGs/BAGs found.

    Implements the gap geometry rule:
      Bullish FVG: high(C1) < low(C3)  -> zone [high(C1), low(C3)] (bottom, top).
      Bearish FVG: low(C1) > high(C3)  -> zone [high(C3), low(C1)] (bottom, top).
    Strict inequalities reject touching C1/C3 wicks. `created_at` is C3's
    timestamp; `gap_type` is BAG when C3 closes beyond C2's extreme with a
    strong close, otherwise FVG. Bullish and bearish conditions are mutually
    exclusive for any real candle (low <= high), so `elif` is safe.
    """
    gaps: list[FairValueGap] = []
    for i in range(len(candles) - 2):
        c1, c2, c3 = candles[i], candles[i + 1], candles[i + 2]
        if c1.high < c3.low:
            gaps.append(
                FairValueGap(
                    direction=Direction.BULLISH,
                    gap_type=_classify_gap(c2, c3, Direction.BULLISH),
                    top=c3.low,
                    bottom=c1.high,
                    created_at=c3.ts,
                    timeframe=timeframe,
                )
            )
        elif c1.low > c3.high:
            gaps.append(
                FairValueGap(
                    direction=Direction.BEARISH,
                    gap_type=_classify_gap(c2, c3, Direction.BEARISH),
                    top=c1.low,
                    bottom=c3.high,
                    created_at=c3.ts,
                    timeframe=timeframe,
                )
            )
    return gaps


def update_gap_states(gaps: list[FairValueGap], candle: Candle) -> None:
    """Update mitigation/spent flags on `gaps` against a newly arrived candle.

    If the candle's wick range [low, high] enters a gap zone, that gap is marked
    mitigated. The FIRST touch also marks it spent — the single-use rule: once
    spent it stays spent and can never be reused, regardless of later price
    action.
    """
    for gap in gaps:
        if gap.overlaps(candle.low, candle.high):
            gap.mitigated = True
            if not gap.spent:
                gap.spent = True


def active_gaps(
    gaps: list[FairValueGap], direction: Direction | None = None
) -> list[FairValueGap]:
    """Return only unmitigated, unspent gaps, most recent (latest created_at) first.

    The strategy trades only the most recent unmitigated gap, so ordering is by
    created_at descending. Optionally filter to a single direction.
    """
    active = [g for g in gaps if not g.mitigated and not g.spent]
    if direction is not None:
        active = [g for g in active if g.direction == direction]
    active.sort(key=lambda g: g.created_at, reverse=True)
    return active


def consequent_timeframe(tf: str) -> str | None:
    """Return the next lower timeframe in config.TF_ORDER, else None.

    Returns None at the bottom of the order (M1) or for an unknown timeframe.
    Backs the BAG zoom rule: a breakaway gap on a higher timeframe sends the
    strategy down to the consequent timeframe to look for a plain FVG.
    """
    order = config.TF_ORDER
    try:
        idx = order.index(tf)
    except ValueError:
        return None
    if idx + 1 >= len(order):
        return None
    return order[idx + 1]


def requires_consequent_zoom(gap: FairValueGap) -> bool:
    """True when `gap` must be resolved on its consequent (lower) timeframe.

    Implements the BAG zoom rule: a breakaway gap on a timeframe ABOVE M5 (i.e.
    not in config.BAG_DIRECT_TFS) is not traded directly — the strategy zooms to
    the consequent timeframe and looks for a plain FVG there instead. Plain FVGs
    and BAGs on M5/M1 never require a zoom.
    """
    return gap.gap_type == GapType.BAG and gap.timeframe not in config.BAG_DIRECT_TFS


class IncrementalGapTracker:
    """Maintain FVG/BAG state for a single timeframe incrementally.

    The original engine recomputed ``find_fvgs`` on the full candle history for
    every bar, giving O(n²) behaviour.  This tracker processes each candle once:

    - Discover new 3-candle FVG/BAG windows as they close.
    - Age existing gaps against newly closed candles (single-use rule).
    - Return gaps active for the latest candle, matching the semantics of
      ``find_fvgs(candles)`` followed by ``_age_gaps(gaps, candles[:-1])``.

    The tracker assumes ``candles`` is appended to monotonically ( chronological
    backtest replay).  It is not safe if history is truncated or reordered.

    To keep CPU bounded, only the most recent ``max_gaps`` unspent gaps are kept
    per timeframe.  The strategy trades the most recent structure anyway, so
    ancient unmitigated gaps are not economically relevant.
    """

    def __init__(self, max_gaps: int = 100) -> None:
        self._max_gaps = max_gaps
        self._gaps: dict[str, list[FairValueGap]] = {}
        # Index of the last candle used to age gaps.  -1 means nothing aged yet.
        self._aged_through: dict[str, int] = {}
        # Index of the last candle for which an FVG ending there was discovered.
        self._discovered_through: dict[str, int] = {}

    def get_gaps(self, candles: list[Candle], timeframe: str) -> list[FairValueGap]:
        """Return active gaps for the latest candle in ``candles``."""
        if len(candles) < 3:
            return []

        if timeframe not in self._gaps:
            self._gaps[timeframe] = []
            self._aged_through[timeframe] = -1
            self._discovered_through[timeframe] = -1

        gaps = self._gaps[timeframe]
        N = len(candles)

        # 1) Discover new FVGs ending at indices we have not yet processed.
        last_disc = self._discovered_through[timeframe]
        for end_idx in range(max(2, last_disc + 1), N):
            c1, c2, c3 = candles[end_idx - 2], candles[end_idx - 1], candles[end_idx]
            if c1.high < c3.low:
                gaps.append(
                    FairValueGap(
                        direction=Direction.BULLISH,
                        gap_type=_classify_gap(c2, c3, Direction.BULLISH),
                        top=c3.low,
                        bottom=c1.high,
                        created_at=c3.ts,
                        timeframe=timeframe,
                    )
                )
            elif c1.low > c3.high:
                gaps.append(
                    FairValueGap(
                        direction=Direction.BEARISH,
                        gap_type=_classify_gap(c2, c3, Direction.BEARISH),
                        top=c1.low,
                        bottom=c3.high,
                        created_at=c3.ts,
                        timeframe=timeframe,
                    )
                )
        self._discovered_through[timeframe] = N - 1

        # 2) Age all unspent gaps against candles that have closed since the last
        #    update, EXCLUDING the latest candle (it is allowed to touch/tap a gap).
        #    Spent gaps are removed immediately to keep the list small.
        last_aged = self._aged_through[timeframe]
        for age_idx in range(last_aged + 1, N - 1):
            c = candles[age_idx]
            keep: list[FairValueGap] = []
            for gap in gaps:
                if c.ts > gap.created_at and gap.overlaps(c.low, c.high):
                    gap.mitigated = True
                    gap.spent = True
                    continue
                keep.append(gap)
            gaps = keep
        self._gaps[timeframe] = gaps
        self._aged_through[timeframe] = N - 2

        # 3) Strategy fidelity: only the most recent structures matter.  Drop
        #    oldest unspent gaps if we exceed the per-timeframe cap.
        if len(gaps) > self._max_gaps:
            gaps.sort(key=lambda g: g.created_at, reverse=True)
            gaps = gaps[: self._max_gaps]
            self._gaps[timeframe] = gaps

        return [g for g in gaps if not g.mitigated and not g.spent]
