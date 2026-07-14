# CHANGE_SUMMARY
# 2026-07-14  kimi-swarm
#   - Created structure.py: fractal swing points, liquidity-sweep detection,
#     CISD events, breaker blocks, and the Unicorn (breaker+FVG overlap) flag.
# WHY: The entry engine times entries off mechanical market structure:
#      liquidity sweep -> CISD -> breaker/unicorn retest. These primitives
#      must be deterministic so every module reads structure identically.
"""
Market-structure primitives for the ICT FVG execution engine.

Strategy rules encoded here:
- Liquidity sweep / stop hunt: a candle's wick exceeds a swing price but its
  close returns back inside the swing price (rule: wick beyond, close inside).
- CISD (Change in State of Delivery): only valid AFTER a liquidity sweep of
  the swing; the trigger is a *close* through the open of the final
  consecutive body candle that formed the swept swing.
- Breaker block: after a higher-high sweep that then breaks the intervening
  swing low, the last up-close candle before that swing low is a bearish
  breaker (zone = that candle's high/low); mirror for bullish breakers.
- Unicorn model: a breaker whose zone overlaps an *active* FVG (not
  mitigated, not spent). FVGs are single-use; spent/mitigated ones never count.

Conventions (kept deterministic on purpose):
- Swings are strict fractals: neighbors' highs/lows must be strictly worse.
- All structure breaks and CISD triggers require a CLOSE through the level,
  never a mere wick.
- At most one event per swing/pivot (first qualifying trigger wins).
"""
from __future__ import annotations

from typing import Optional

try:
    from .models import (
        BreakerBlock,
        Candle,
        CISDEvent,
        Direction,
        FairValueGap,
        SwingPoint,
    )
except ImportError:  # module run as top-level (e.g. `python3 -m unittest` from pkg dir)
    from models import (  # type: ignore[no-redef]
        BreakerBlock,
        Candle,
        CISDEvent,
        Direction,
        FairValueGap,
        SwingPoint,
    )


def find_swing_points(
    candles: list[Candle], left: int = 2, right: int = 2
) -> list[SwingPoint]:
    """Fractal swing highs/lows — the liquidity anchors of the strategy.

    A candle is a swing high when its high strictly exceeds the highs of the
    `left` candles before it and the `right` candles after it; mirror for
    swing lows. Boundary candles (fewer than `left`/`right` neighbors) can
    never qualify. One candle may be both a swing high and a swing low
    (outside bar). Returned in chronological order.
    """
    swings: list[SwingPoint] = []
    for i in range(left, len(candles) - right):
        c = candles[i]
        neighbors = candles[i - left : i] + candles[i + 1 : i + right + 1]
        if all(c.high > n.high for n in neighbors):
            swings.append(SwingPoint(ts=c.ts, price=c.high, kind="high"))
        if all(c.low < n.low for n in neighbors):
            swings.append(SwingPoint(ts=c.ts, price=c.low, kind="low"))
    return swings


def _is_sweep(candle: Candle, price: float, kind: str) -> bool:
    """Rule: wick trades beyond the swing price, close returns back inside."""
    if kind == "high":
        return candle.high > price and candle.close < price
    return candle.low < price and candle.close > price


def swept(candles: list[Candle], swing: SwingPoint) -> bool:
    """True if any candle AFTER `swing` sweeps it (liquidity sweep / stop hunt).

    Sweep rule: a later candle's wick exceeds the swing price but the candle
    closes back inside it. A close beyond the swing price is a break, not a
    sweep, and does not qualify. `swing` is located by timestamp; if it is not
    present in `candles`, returns False.
    """
    start = None
    for i, c in enumerate(candles):
        if c.ts == swing.ts:
            start = i
            break
    if start is None:
        return False
    return any(_is_sweep(c, swing.price, swing.kind) for c in candles[start + 1 :])


def _final_body_open(candles: list[Candle], i: int, bullish: bool) -> Optional[float]:
    """Open of the final consecutive body candle that formed a swing.

    Walks back from the swing candle to the most recent candle of the given
    body color (bullish for a swing high, bearish for a swing low) — i.e. the
    last candle of the consecutive same-color run that printed the swing.
    None if no such candle exists.
    """
    j = i
    while j >= 0 and candles[j].is_bullish != bullish:
        j -= 1
    return candles[j].open if j >= 0 else None


def find_cisd(candles: list[Candle], timeframe: str) -> list[CISDEvent]:
    """Change in State of Delivery events (post-sweep close through the body).

    Bearish CISD: after a liquidity sweep of a swing high, a candle closes
    below the open of the final consecutive bullish candle body that formed
    that high. Bullish CISD: mirror — sweep of a swing low, then a close
    above the final consecutive bearish candle's open. The sweep is a hard
    precondition: closes through the level before any sweep do NOT count.
    The sweep and the triggering close may be the same candle. At most one
    event per swing; results are chronological. Swings use the default
    2/2 fractal window.
    """
    idx_by_ts = {c.ts: i for i, c in enumerate(candles)}
    hits: list[tuple[int, CISDEvent]] = []
    for swing in find_swing_points(candles):
        i = idx_by_ts[swing.ts]
        bearish = swing.kind == "high"
        level = _final_body_open(candles, i, bullish=bearish)
        if level is None:
            continue
        seen_sweep = False
        for k in range(i + 1, len(candles)):
            c = candles[k]
            if _is_sweep(c, swing.price, swing.kind):
                seen_sweep = True
            if seen_sweep and (c.close < level if bearish else c.close > level):
                hits.append(
                    (
                        k,
                        CISDEvent(
                            direction=Direction.BEARISH if bearish else Direction.BULLISH,
                            level=level,
                            ts=c.ts,
                            timeframe=timeframe,
                        ),
                    )
                )
                break
    hits.sort(key=lambda t: t[0])
    return [event for _, event in hits]


def _first_sweep_index(
    candles: list[Candle], start: int, pivots: list[tuple[int, SwingPoint]], kind: str
) -> Optional[int]:
    """First candle index > `start` that sweeps any of the given pivots."""
    for k in range(start + 1, len(candles)):
        if any(_is_sweep(candles[k], p.price, kind) for _, p in pivots):
            return k
    return None


def _last_body_before(candles: list[Candle], i: int, bullish: bool) -> Optional[int]:
    """Index of the last up-close (or down-close) candle strictly before `i`."""
    for j in range(i - 1, -1, -1):
        if candles[j].is_bullish == bullish:
            return j
    return None


def _active_fvg_overlap(
    fvgs: Optional[list[FairValueGap]], bottom: float, top: float
) -> bool:
    """True when any ACTIVE FVG overlaps [bottom, top].

    FVGs are single-use: mitigated or spent gaps are dead and never count
    toward the Unicorn overlap.
    """
    if not fvgs:
        return False
    return any(
        not f.mitigated and not f.spent and f.overlaps(bottom, top) for f in fvgs
    )


def find_breakers(
    candles: list[Candle],
    timeframe: str,
    fvgs: Optional[list[FairValueGap]] = None,
) -> list[BreakerBlock]:
    """Breaker blocks created by sweep-then-break failure of a swing.

    Bearish breaker: a prior swing high is swept (higher-high liquidity run)
    and price then CLOSES below the intervening swing low; the last up-close
    (bullish) candle before that swing low becomes the breaker, zone =
    [that candle's low, that candle's high]. Bullish breaker: mirror — sweep
    of a prior swing low, close above the intervening swing high, breaker =
    last down-close (bearish) candle before that swing high.

    `created_at` is the timestamp of the candle that broke the swing (the
    breaker only exists once structure breaks). When `fvgs` is given,
    `has_fvg_overlap` is set if any active FVG overlaps the breaker zone —
    the 'Unicorn' model. At most one breaker per pivot; chronological order.
    """
    idx_by_ts = {c.ts: i for i, c in enumerate(candles)}
    swings = find_swing_points(candles)
    highs = [(idx_by_ts[s.ts], s) for s in swings if s.kind == "high"]
    lows = [(idx_by_ts[s.ts], s) for s in swings if s.kind == "low"]

    hits: list[tuple[int, BreakerBlock]] = []

    def emit(
        pivot_idx: int,
        pivot: SwingPoint,
        priors: list[tuple[int, SwingPoint]],
        prior_kind: str,
        direction: Direction,
        breaks_when_below: bool,
        body_bullish: bool,
    ) -> None:
        # Only the most recent opposing pivot can produce the sweep that creates
        # a breaker.  It must also be a genuine external liquidity sweep beyond
        # the pivot that is about to be broken.
        if not priors:
            return
        prior_idx, prior = priors[-1]
        if breaks_when_below and prior.price <= pivot.price:
            return
        if not breaks_when_below and prior.price >= pivot.price:
            return

        sweep_idx = _first_sweep_index(candles, pivot_idx, [(prior_idx, prior)], prior_kind)
        if sweep_idx is None:
            return
        for k in range(sweep_idx + 1, len(candles)):
            close = candles[k].close
            if (close < pivot.price) if breaks_when_below else (close > pivot.price):
                body_idx = _last_body_before(candles, pivot_idx, body_bullish)
                if body_idx is None:
                    return
                body = candles[body_idx]
                hits.append(
                    (
                        k,
                        BreakerBlock(
                            direction=direction,
                            top=body.high,
                            bottom=body.low,
                            created_at=candles[k].ts,
                            timeframe=timeframe,
                            has_fvg_overlap=_active_fvg_overlap(
                                fvgs, body.low, body.high
                            ),
                        ),
                    )
                )
                return

    # Bearish: sweep of the most recent prior swing HIGH, then close below the swing LOW.
    for i_low, low in lows:
        prior_highs = [(i, s) for i, s in highs if i < i_low]
        if prior_highs:
            emit(i_low, low, prior_highs, "high", Direction.BEARISH, True, True)

    # Bullish: sweep of the most recent prior swing LOW, then close above the swing HIGH.
    for i_high, high in highs:
        prior_lows = [(i, s) for i, s in lows if i < i_high]
        if prior_lows:
            emit(i_high, high, prior_lows, "low", Direction.BULLISH, False, False)

    hits.sort(key=lambda t: t[0])
    return [block for _, block in hits]


def is_unicorn(breaker: BreakerBlock) -> bool:
    """Unicorn model: True when the breaker zone overlaps an active FVG.

    The overlap flag is computed at detection time by find_breakers(); this
    helper is the canonical read of it used by the entry engine.
    """
    return breaker.has_fvg_overlap
