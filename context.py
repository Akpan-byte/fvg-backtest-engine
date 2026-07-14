# CHANGE_SUMMARY
# 2026-07-14  kimi-swarm
#   - Created context.py: higher-timeframe alignment, PDA assembly, trapped-order-flow
#     lock, and probability filtering for the FVG execution engine.
#   - Updated after audit: gaps are now aged against the full price history before
#     bias/PDA selection, trapped-order-flow is evaluated per-timeframe, and the
#     exact timeframe matrix is exposed via operational_context_tf / allowed_entry_tfs.
# WHY: The original implementation left raw FVGs un-aged in the analyzer, which
#      could mark already-tapped gaps as active PDAs. It also did not surface the
#      matrix row needed by the engine to enforce the core setup matrix.
"""
Higher-timeframe alignment and probability filtering.

Public API:
- ContextAnalyzer.analyze(snapshot, asset_class, style) -> dict
- detect_bias(candles) -> Direction | None
- trapped_order_flow(context_fvgs, price) -> tuple[bool, str | None]
- timeframe_options(asset_class, style) -> tuple[context_tfs, pda_tfs, entry_tfs]

Strategy rules implemented here:
- Context timeframes are asset-class dependent (M/W/D for forex, M/W/D/H4 for indices).
- PDA (premium/discount array) and entry timeframes are style dependent.
- FVGs must be aged against price history: a gap touched by price is spent and
  cannot be used for bias, PDA, or trapped-flow logic.
- Bias is the aligned directional intent across context timeframes, read from
  the most recent active FVG on each timeframe.
- Trapped order flow: conflicting active FVGs across timeframes, or price inside
  an active opposing FVG relative to the overall bias, locks context until price
  closes outside the conflicting zone.
- The operational context timeframe is the lowest context timeframe with an
  active FVG aligned to the overall bias; allowed entry TFs come from the
  intersection of config.TIMEFRAME_MATRIX[operational_tf] and the style/asset
  entry set, enforcing the core setup matrix.
- Midnight open is the premium/discount baseline.
"""
from __future__ import annotations

from typing import Optional

try:
    from . import config
    from .fvg import active_gaps, find_fvgs, IncrementalGapTracker
    from .models import AssetClass, Candle, Direction, FairValueGap, TradeStyle
    from .structure import find_swing_points
    from .timefilters import midnight_open, premium_discount
except ImportError:  # module run as top-level (e.g. `python3 -m unittest` from pkg dir)
    import config  # type: ignore[no-redef]
    from fvg import active_gaps, find_fvgs, IncrementalGapTracker  # type: ignore[no-redef]
    from models import AssetClass, Candle, Direction, FairValueGap, TradeStyle  # type: ignore[no-redef]
    from structure import find_swing_points  # type: ignore[no-redef]
    from timefilters import midnight_open, premium_discount  # type: ignore[no-redef]

__all__ = [
    "ContextAnalyzer",
    "detect_bias",
    "trapped_order_flow",
    "timeframe_options",
]


def timeframe_options(
    asset_class: AssetClass, style: TradeStyle
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return (context_tfs, pda_tfs, entry_tfs) for the given asset class and style.

    Uses the constants in config.py exactly:
      - Forex context: M/W/D (never H4).
      - Index context:  M/W/D/H4.
      - Intraday PDA:  D/H4/H1; entry M15/M5/M1.
      - Swing PDA+entry: H4/H1.
      - Forex entries are always H4/H1, overriding the intraday matrix.
    """
    context_tfs = (
        config.CONTEXT_TFS_INDEX
        if asset_class == AssetClass.INDEX
        else config.CONTEXT_TFS_FOREX
    )

    if style == TradeStyle.SWING:
        pda_tfs = config.PDA_TFS_SWING
        entry_tfs = config.ENTRY_TFS_SWING
    else:
        pda_tfs = config.PDA_TFS_INTRADAY
        if asset_class == AssetClass.FOREX:
            entry_tfs = config.ENTRY_TFS_FOREX
        else:
            entry_tfs = config.ENTRY_TFS_INTRADAY

    return context_tfs, pda_tfs, entry_tfs


def _age_gaps(gaps: list[FairValueGap], candles: list[Candle]) -> None:
    """Mark gaps mitigated/spent once price has traded into them.

    A gap cannot be touched by the candle that created it; only candles with a
    timestamp strictly greater than the gap's created_at count.
    """
    for g in gaps:
        for c in candles:
            if c.ts > g.created_at and g.overlaps(c.low, c.high):
                g.mitigated = True
                g.spent = True
                break


def detect_bias(
    candles: list[Candle], gaps: list[FairValueGap] | None = None
) -> Direction | None:
    """Classify a single timeframe's directional intent.

    Rule: read the most recent active (aged, unmitigated, unspent) FVG.  If it
    is bullish and lies below current price, bias is bullish.  If it is bearish
    and lies above current price, bias is bearish.  Otherwise there is no clear
    bias. The midnight-open baseline is available to callers via
    timefilters.midnight_open for additional premium/discount confirmation.

    If ``gaps`` is provided they are used directly (caller has already aged
    them through the prior bar); otherwise FVGs are computed from scratch.
    """
    if len(candles) < 3:
        return None

    if gaps is None:
        gaps = find_fvgs(candles, "tf")
        # Exclude the latest candle from aging: the gap is still active for the
        # current bar so the engine can react to a tap on this bar.
        _age_gaps(gaps, candles[:-1])
    active = active_gaps(gaps)
    if not active:
        return None

    latest = active[0]
    price = candles[-1].close

    if latest.direction == Direction.BULLISH and latest.top <= price:
        return Direction.BULLISH
    if latest.direction == Direction.BEARISH and latest.bottom >= price:
        return Direction.BEARISH
    return None


def _nearest_gap_to_price(
    gaps: list[FairValueGap], price: float, direction: Direction | None = None
) -> FairValueGap | None:
    """Return the active gap whose zone is closest to `price`.

    If `direction` is given, only consider gaps in that direction.
    """
    filtered = gaps if direction is None else [g for g in gaps if g.direction == direction]
    if not filtered:
        return None

    def distance(g: FairValueGap) -> float:
        if g.contains(price):
            return 0.0
        return min(abs(price - g.top), abs(price - g.bottom))

    return min(filtered, key=distance)


def trapped_order_flow(
    context_fvgs: dict[str, list[FairValueGap]], price: float
) -> tuple[bool, str | None]:
    """Return (locked, reason) when higher-timeframe order flow is trapped.

    Lock conditions:
      1. Price is inside an active FVG whose direction opposes the most recent
         active FVG across all context timeframes.
      2. Price is inside both an active bullish FVG and an active bearish FVG.

    The context unlocks only when price closes outside the conflicting FVG,
    which is reflected by re-calling this function with updated gap states.
    """
    # Per-timeframe most-recent active gap.
    per_tf_latest: dict[str, FairValueGap] = {}
    for tf, gaps in context_fvgs.items():
        active = active_gaps(gaps)
        if active:
            per_tf_latest[tf] = active[0]

    if not per_tf_latest:
        return False, None

    # Overall bias = the most recent active gap across all context TFs.
    overall_latest = max(per_tf_latest.values(), key=lambda g: g.created_at)
    overall_bias = overall_latest.direction
    opposing = (
        Direction.BEARISH
        if overall_bias == Direction.BULLISH
        else Direction.BULLISH
    )

    # Condition 1: price inside an active opposing FVG on any context TF.
    # Only active (unspent, unmitigated) gaps count; spent gaps have already
    # been traded through and no longer represent live trapped order flow.
    all_active = [g for gaps in context_fvgs.values() for g in active_gaps(gaps)]
    for g in all_active:
        if g.direction == opposing and g.contains(price):
            return True, (
                f"price inside {opposing.name.lower()} FVG on {g.timeframe} "
                f"while majority bias is {overall_bias.name.lower()}"
            )

    # Condition 2: price inside both an active bullish and an active bearish FVG.
    inside_bull = any(g.contains(price) for g in all_active if g.direction == Direction.BULLISH)
    inside_bear = any(g.contains(price) for g in all_active if g.direction == Direction.BEARISH)
    if inside_bear and inside_bull:
        return True, "price inside both bullish and bearish FVGs"

    return False, None


class ContextAnalyzer:
    """Assemble higher-timeframe context from a multi-timeframe candle snapshot."""

    def __init__(self) -> None:
        self._gap_tracker = IncrementalGapTracker()

    def analyze(
        self,
        snapshot: dict[str, list[Candle]],
        asset_class: AssetClass,
        style: TradeStyle,
    ) -> dict:
        """Analyze a multi-timeframe snapshot and return a context dictionary.

        Returns:
            {
                "bias": Direction | None,
                "active_pda_fvgs": list[FairValueGap],  # bias-direction, most recent first
                "context_locked": bool,
                "lock_reason": str | None,
                "internal_range": {"top": float | None, "bottom": float | None},
                "external_range_liquidity": {"high": float | None, "low": float | None},
                "midnight": float | None,
                "premium_discount": str | None,
                "operational_context_tf": str | None,
                "allowed_entry_tfs": tuple[str, ...],
            }

        Implements the strategy rules:
          - NO CONTEXT, NO TRADE: no active HTF FVG bias locks the context.
          - PDA FVGs are gathered only from allowed PDA timeframes and are aged
            against price history before use.
          - Internal range is the nearest active PDA FVG zone in the bias direction.
          - External liquidity targets are the nearest swing high/low on the highest
            available context timeframe.
          - Trapped order flow locks the context until the conflicting FVG is closed.
          - The exact timeframe matrix is enforced via operational_context_tf and
            allowed_entry_tfs.
        """
        context_tfs, pda_tfs, entry_tfs = timeframe_options(asset_class, style)

        # Current price: close of the most recent candle across the snapshot.
        all_candles: list[Candle] = []
        for candles in snapshot.values():
            all_candles.extend(candles)
        price = all_candles[-1].close if all_candles else None

        midnight = midnight_open(all_candles) if all_candles else None

        # --- Context FVGs (aged through the prior bar) and directional bias ---
        # A gap is still considered active on the bar that first touches it so
        # the engine can detect the PDA tap / price reaction on that same bar.
        context_fvgs: dict[str, list[FairValueGap]] = {}
        per_tf_bias: dict[str, Direction] = {}
        for tf in context_tfs:
            candles = snapshot.get(tf)
            if not candles:
                continue
            gaps = self._gap_tracker.get_gaps(candles, tf)
            context_fvgs[tf] = gaps
            bias = detect_bias(candles, gaps)
            if bias is not None:
                per_tf_bias[tf] = bias

        bullish_count = sum(1 for b in per_tf_bias.values() if b == Direction.BULLISH)
        bearish_count = sum(1 for b in per_tf_bias.values() if b == Direction.BEARISH)

        bias: Direction | None = None
        if bullish_count > 0 and bearish_count == 0:
            bias = Direction.BULLISH
        elif bearish_count > 0 and bullish_count == 0:
            bias = Direction.BEARISH
        elif bullish_count > 0 and bearish_count > 0:
            # Conflicting context timeframes: keep the majority bias for diagnostics
            # but mark the context locked via trapped_order_flow below.
            bias = (
                Direction.BULLISH
                if bullish_count >= bearish_count
                else Direction.BEARISH
            )

        # --- Operational context timeframe and allowed entry TFs -------------
        # Use the lowest (most zoomed-in) context TF whose latest active FVG
        # aligns with the overall bias. This anchors the core setup matrix row.
        operational_tf: str | None = None
        if bias is not None:
            for tf in reversed(context_tfs):  # D, W, M for forex; H4, D, W, M for index
                if tf not in context_fvgs:
                    continue
                active = active_gaps(context_fvgs[tf])
                if active and active[0].direction == bias:
                    operational_tf = tf
                    break

        allowed_entry_tfs: tuple[str, ...] = ()
        if operational_tf is not None:
            if style == TradeStyle.INTRADAY:
                # Intraday: enforce the exact context->entry matrix row.
                matrix_entries = config.TIMEFRAME_MATRIX.get(operational_tf, ())
                allowed_entry_tfs = tuple(
                    tf for tf in matrix_entries if tf in entry_tfs
                )
            else:
                # Swing: the brief fixes entries at H4/H1 regardless of which
                # context timeframe anchored the bias.
                allowed_entry_tfs = entry_tfs

        # --- PDA FVGs (reaction zones, aged through prior bar) ---------------
        # Only the most recent active FVG per timeframe matters per the strategy.
        active_pda: list[FairValueGap] = []
        for tf in pda_tfs:
            candles = snapshot.get(tf)
            if not candles:
                continue
            gaps = self._gap_tracker.get_gaps(candles, tf)
            tf_active = active_gaps(gaps)
            if tf_active:
                active_pda.append(tf_active[0])
        # Most recent first, then bias-aligned first.
        active_pda.sort(
            key=lambda g: (g.created_at, g.direction == bias),
            reverse=True,
        )

        # --- Internal range (nearest active PDA FVG zone in bias direction) ---
        internal_range = {"top": None, "bottom": None}
        nearest_pda = (
            _nearest_gap_to_price(active_pda, price, bias)
            if price is not None
            else None
        )
        if nearest_pda is not None:
            internal_range["top"] = nearest_pda.top
            internal_range["bottom"] = nearest_pda.bottom

        # --- External liquidity (nearest swing high/low on highest context TF) -
        external_range = {"high": None, "low": None}
        if price is not None:
            highest_context_tf = next(
                (tf for tf in config.TF_ORDER if tf in context_tfs and tf in snapshot),
                None,
            )
            if highest_context_tf is not None:
                swings = find_swing_points(snapshot[highest_context_tf])
                highs = [s.price for s in swings if s.kind == "high" and s.price > price]
                lows = [s.price for s in swings if s.kind == "low" and s.price < price]
                if highs:
                    external_range["high"] = min(highs)
                if lows:
                    external_range["low"] = max(lows)

        # --- Trapped order flow lock ------------------------------------------
        locked, lock_reason = (
            trapped_order_flow(context_fvgs, price)
            if price is not None
            else (False, None)
        )

        # If there is no clear HTF bias at all, the context is locked.
        if bias is None and lock_reason is None:
            locked = True
            lock_reason = "no clear HTF bias"

        # Premium/discount label relative to midnight open.
        pd_label: str | None = None
        if price is not None and midnight is not None:
            pd_label = premium_discount(price, midnight)

        return {
            "bias": bias,
            "active_pda_fvgs": active_pda,
            "context_locked": locked,
            "lock_reason": lock_reason,
            "internal_range": internal_range,
            "external_range_liquidity": external_range,
            "midnight": midnight,
            "premium_discount": pd_label,
            "operational_context_tf": operational_tf,
            "allowed_entry_tfs": allowed_entry_tfs,
        }
