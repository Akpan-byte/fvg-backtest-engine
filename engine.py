# CHANGE_SUMMARY
# 2026-07-14  kimi-swarm
#   - Created engine.py: stage 1-5 execution state machine for the ICT
#     multi-timeframe FVG strategy.
#   - Updated after audit: uses the context analyzer's exact timeframe matrix
#     (operational_context_tf / allowed_entry_tfs), sizes every trade from the
#     frozen starting balance (fixed-dollar risk), and checks the killzone at the
#     moment the LTF 2nd-leg structure formed.
# WHY: The original engine did not enforce the core setup matrix row and sized
#      risk from the current balance, which violates the fixed-dollar-after-losses
#      rule. It also checked killzone on the pullback bar instead of the variation.
"""Stage 1-5 execution state machine for the ICT FVG strategy.

Public API:
    ExecutionEngine(asset_class, style, balance, risk_mode,
                    enabled_killzones=None, news_events=None)
    on_bar(dt, data_snapshot) -> Signal | None

Stage 1: ContextAnalyzer reads higher-timeframe FVGs for bias + lock + PDAs.
Stage 2: Price taps the single most recent active HTF PDA FVG (single-use).
Stage 3: Price displaces away and creates a NEW FVG/Breaker/CISD on an allowed
         entry timeframe; the trigger is the first pullback into that LTF structure.
Stage 4: Intraday entries must have the LTF structure form inside an enabled
         killzone, on a high-impact news day, and outside the NFP/FOMC/CPI blackout.
Stage 5: Emit Signal with entry = LTF boundary, stop = invalidation/extreme,
         take-profit = exactly 2R.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

try:
    from . import config
    from . import fvg
    from .fvg import IncrementalGapTracker
    from . import risk
    from . import structure
    from . import timefilters
    from .context import ContextAnalyzer
    from .models import (
        AssetClass,
        BreakerBlock,
        Candle,
        CISDEvent,
        Direction,
        FairValueGap,
        GapType,
        RiskMode,
        Signal,
        TradeStyle,
    )
except ImportError:  # module run as top-level (e.g. `python3 -m unittest` from pkg dir)
    import config  # type: ignore[no-redef]
    import fvg  # type: ignore[no-redef]
    from fvg import IncrementalGapTracker  # type: ignore[no-redef]
    import risk  # type: ignore[no-redef]
    import structure  # type: ignore[no-redef]
    import timefilters  # type: ignore[no-redef]
    from context import ContextAnalyzer  # type: ignore[no-redef]
    from models import (  # type: ignore[no-redef]
        AssetClass,
        BreakerBlock,
        Candle,
        CISDEvent,
        Direction,
        FairValueGap,
        GapType,
        RiskMode,
        Signal,
        TradeStyle,
    )


LTFStructure = FairValueGap | BreakerBlock | CISDEvent

# Lookback window for LTF breaker/CISD scans.  The strategy trades only the most
# recent structure, so scanning the whole history is wasteful.  500 bars is more
# than enough context for H4/H1/M15/M5/M1 entry timeframes.
_LTF_STRUCTURE_LOOKBACK = 500


def _gap_key(g: FairValueGap) -> tuple:
    """Stable identity for an FVG so it can be tracked across bars."""
    return (g.timeframe, g.created_at, g.top, g.bottom, g.direction.value)


def _breaker_key(b: BreakerBlock) -> tuple:
    """Stable identity for a breaker block."""
    return (b.timeframe, b.created_at, b.top, b.bottom, b.direction.value)


def _cisd_key(c: CISDEvent) -> tuple:
    """Stable identity for a CISD event."""
    return (c.timeframe, c.ts, c.level, c.direction.value)


def _structure_direction(s: LTFStructure) -> Direction:
    return s.direction


def _structure_timeframe(s: LTFStructure) -> str:
    if isinstance(s, CISDEvent):
        return s.timeframe
    return s.timeframe


def _structure_created_at(s: LTFStructure) -> datetime:
    if isinstance(s, CISDEvent):
        return s.ts
    return s.created_at


def _structure_zone(s: LTFStructure) -> tuple[float, float]:
    """Return (bottom, top) entry zone for an LTF structure.

    For CISD the structure is a single level; we use a zero-width zone.
    """
    if isinstance(s, CISDEvent):
        return (s.level, s.level)
    return (s.bottom, s.top)


def _entry_price_for_structure(s: LTFStructure, direction: Direction) -> float:
    """Entry boundary: the side price reaches first on a pullback.

    Long: price pulls down from above, so the first reachable boundary is top.
    Short: price rallies up from below, so the first reachable boundary is bottom.
    """
    bottom, top = _structure_zone(s)
    if direction == Direction.BULLISH:
        return top
    return bottom


def _stop_price_for_structure(
    s: LTFStructure, direction: Direction, candles: list[Candle]
) -> float:
    """Stop goes behind the LTF structure's far boundary or swing extreme.

    For FVG/breaker the far boundary is used directly. For CISD we fall back to
    the most recent swing extreme on the entry timeframe.
    """
    bottom, top = _structure_zone(s)
    if isinstance(s, CISDEvent):
        swings = structure.find_swing_points(candles)
        if direction == Direction.BULLISH:
            lows = [sw for sw in swings if sw.kind == "low" and sw.ts <= s.ts]
            if lows:
                return max(lows, key=lambda sw: sw.ts).price
        else:
            highs = [sw for sw in swings if sw.kind == "high" and sw.ts <= s.ts]
            if highs:
                return max(highs, key=lambda sw: sw.ts).price
    if direction == Direction.BULLISH:
        return bottom
    return top


class ExecutionEngine:
    """ICT multi-timeframe FVG execution state machine."""

    def __init__(
        self,
        asset_class: AssetClass,
        style: TradeStyle,
        balance: float,
        risk_mode: RiskMode,
        enabled_killzones: Optional[tuple[str, ...]] = None,
        news_events: Optional[list[tuple[datetime, str]]] = None,
    ):
        """Initialize the engine.

        Args:
            asset_class: FOREX (context M/W/D, entries H4/H1) or INDEX
                (context includes H4, LTF entries allowed).
            style: INTRADAY (killzone + news-day required) or SWING.
            balance: Starting account balance used for fixed-dollar risk sizing.
                This value is frozen; risk per trade never changes after losses.
            risk_mode: PASSIVE (balance/20) or AGGRESSIVE (balance/10).
            enabled_killzones: Tuple of killzone names (e.g. ("london", "ny_am"))
                or None for config default.
            news_events: List of (datetime, name) news events for blackout/news-day
                checks. Datetimes may be naive (assumed UTC) or tz-aware.
        """
        self.asset_class = asset_class
        self.style = style
        self.base_balance = balance  # fixed-dollar risk anchor; never updated
        self.risk_mode = risk_mode
        self.enabled_killzones = enabled_killzones
        self.news_events = news_events or []

        self._context_analyzer = ContextAnalyzer()
        self._gap_tracker = IncrementalGapTracker()
        self._context_tfs = self._resolve_context_tfs()

        # State machine
        self._stage = "context"  # context | pda | ltf
        self._context: Optional[dict] = None
        self._pda_gap: Optional[FairValueGap] = None
        self._pda_tap_ts: Optional[datetime] = None
        self._ltf_structure: Optional[LTFStructure] = None
        self._ltf_formed_at: Optional[datetime] = None
        self._spent_pda_keys: set[tuple] = set()
        self._spent_breaker_keys: set[tuple] = set()
        self._spent_cisd_keys: set[tuple] = set()
        self._last_dt: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def _resolve_context_tfs(self) -> tuple[str, ...]:
        """Higher-timeframe context timeframes for this asset class."""
        if self.asset_class == AssetClass.FOREX:
            return config.CONTEXT_TFS_FOREX
        return config.CONTEXT_TFS_INDEX

    def _allowed_entry_tfs(self) -> tuple[str, ...]:
        """Allowed entry timeframes from the context analyzer's matrix row."""
        if self._context is None:
            return ()
        return self._context.get("allowed_entry_tfs", ())

    def _entry_tfs_for_pda(self, pda_gap: FairValueGap) -> tuple[str, ...]:
        """Entry TFs for the 2nd leg, constrained by the exact matrix row.

        BAGs above M5 zoom to the consequent timeframe ONLY if that timeframe is
        allowed by the operational context matrix; otherwise the setup is invalid.
        """
        allowed = self._allowed_entry_tfs()
        if fvg.requires_consequent_zoom(pda_gap):
            consequent = fvg.consequent_timeframe(pda_gap.timeframe)
            if consequent and consequent in allowed:
                return (consequent,)
            return ()
        return allowed

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def on_bar(
        self,
        dt: datetime,
        data_snapshot: dict[str, list[Candle]],
        *,
        trusted_snapshot: bool = False,
    ) -> Optional[Signal]:
        """Process one bar of multi-timeframe data and emit a Signal or None.

        Parameters
        ----------
        dt:
            Timestamp of the bar being processed.
        data_snapshot:
            Mapping from timeframe to chronological candle list.  By default the
            engine defensively trims to ``c.ts <= dt``.  Callers that guarantee
            this (e.g., the deterministic backtest harness) can pass
            ``trusted_snapshot=True`` to skip the expensive copy.
        """
        # Guard against duplicate bars; still recompute context for freshness.
        if self._last_dt is not None and dt <= self._last_dt:
            return None
        self._last_dt = dt

        # A snapshot may contain history beyond `dt`; trim to the current bar so
        # each timeframe's "latest" candle is deterministic and future data does
        # not prematurely spend gaps or create structures.  The backtest harness
        # already maintains this invariant, so it passes trusted_snapshot=True.
        if trusted_snapshot:
            snapshot = data_snapshot
        else:
            snapshot = {
                tf: [c for c in candles if c.ts <= dt]
                for tf, candles in data_snapshot.items()
            }

        # Stage 1: analyze context via ContextAnalyzer, then build engine's own
        # aged FVG view for stage 2/3 logic.
        self._context = self._context_analyzer.analyze(
            snapshot, self.asset_class, self.style
        )
        gaps_by_tf = self._refresh_gaps(snapshot)

        # No context or trapped orderflow -> flat and reset.
        if self._context["bias"] is None or self._context["context_locked"]:
            self._reset()
            self._age_with_latest(snapshot, gaps_by_tf)
            return None

        # Stage 2-5 state transitions.
        result: Optional[Signal] = None
        if self._stage == "context":
            result = self._run_stage_context(dt, snapshot, gaps_by_tf)
        elif self._stage == "pda":
            result = self._run_stage_pda(dt, snapshot, gaps_by_tf)
        elif self._stage == "ltf":
            result = self._run_stage_ltf(dt, snapshot, gaps_by_tf)

        # Finalize the current bar so the next bar starts from a spent-correct state.
        self._age_with_latest(snapshot, gaps_by_tf)
        return result

    # ------------------------------------------------------------------
    # Stage handlers
    # ------------------------------------------------------------------
    def _run_stage_context(
        self,
        dt: datetime,
        data_snapshot: dict[str, list[Candle]],
        gaps_by_tf: dict[str, list[FairValueGap]],
    ) -> Optional[Signal]:
        """Look for a fresh tap of the single most recent active HTF PDA FVG."""
        assert self._context is not None
        bias = self._context["bias"]
        for gap in self._context["active_pda_fvgs"]:
            if _gap_key(gap) in self._spent_pda_keys:
                continue
            if gap.direction != bias:
                continue
            candles = data_snapshot.get(gap.timeframe, [])
            if len(candles) < 2:
                continue
            latest = candles[-1]
            # Detect tap on the latest candle only.
            if self._fresh_overlap(gap, latest, candles):
                self._pda_gap = gap
                self._pda_tap_ts = latest.ts
                self._stage = "pda"
                self._spent_pda_keys.add(_gap_key(gap))
                return None
            # Only the most recent PDA matters; stop after the first candidate.
            break
        return None

    def _run_stage_pda(
        self,
        dt: datetime,
        data_snapshot: dict[str, list[Candle]],
        gaps_by_tf: dict[str, list[FairValueGap]],
    ) -> Optional[Signal]:
        """After a PDA tap, wait for a new LTF structure in the bias direction."""
        if self._pda_gap is None or self._pda_tap_ts is None:
            self._reset()
            return None

        assert self._context is not None
        entry_tfs = self._entry_tfs_for_pda(self._pda_gap)
        if not entry_tfs:
            self._reset()
            return None

        ltf_struct = self._find_new_ltf_structure(
            data_snapshot, gaps_by_tf, entry_tfs, self._context["bias"]
        )
        if ltf_struct is not None:
            self._ltf_structure = ltf_struct
            self._ltf_formed_at = _structure_created_at(ltf_struct)
            self._stage = "ltf"
        return None

    def _run_stage_ltf(
        self,
        dt: datetime,
        data_snapshot: dict[str, list[Candle]],
        gaps_by_tf: dict[str, list[FairValueGap]],
    ) -> Optional[Signal]:
        """Wait for the first pullback into the LTF structure, then emit."""
        if self._ltf_structure is None or self._pda_gap is None:
            self._reset()
            return None

        tf = _structure_timeframe(self._ltf_structure)
        candles = data_snapshot.get(tf, [])
        if not candles:
            return None
        latest = candles[-1]

        # Pullback = latest candle first touches the structure.
        if not self._fresh_overlap_ltf(self._ltf_structure, latest, candles):
            return None

        # Stage 4: timefilters (intraday only) are checked at the moment the
        # LTF structure (the entry variation) formed.
        if not self._timefilters_ok(self._ltf_formed_at or dt):
            self._reset()
            return None

        # Stage 5: emit signal.
        signal = self._build_signal(dt, candles)
        self._mark_ltf_spent(self._ltf_structure)
        self._reset()
        return signal

    # ------------------------------------------------------------------
    # FVG / structure refresh
    # ------------------------------------------------------------------
    def _refresh_gaps(
        self, data_snapshot: dict[str, list[Candle]]
    ) -> dict[str, list[FairValueGap]]:
        """Return active FVGs for each timeframe, aged through the prior bar.

        Uses an incremental tracker so each candle is only processed once per
        timeframe, avoiding the previous O(n²) recomputation.
        """
        gaps_by_tf: dict[str, list[FairValueGap]] = {}
        for tf, candles in data_snapshot.items():
            gaps_by_tf[tf] = self._gap_tracker.get_gaps(candles, tf)
        return gaps_by_tf

    def _age_with_latest(
        self,
        data_snapshot: dict[str, list[Candle]],
        gaps_by_tf: dict[str, list[FairValueGap]],
    ) -> None:
        """Mark any gaps the latest candle touches as spent/mitigated."""
        for tf, candles in data_snapshot.items():
            if not candles:
                continue
            latest = candles[-1]
            for g in gaps_by_tf.get(tf, []):
                if latest.ts > g.created_at and g.overlaps(latest.low, latest.high):
                    g.mitigated = True
                    g.spent = True
                    break

    def _find_new_ltf_structure(
        self,
        data_snapshot: dict[str, list[Candle]],
        gaps_by_tf: dict[str, list[FairValueGap]],
        entry_tfs: tuple[str, ...],
        direction: Direction,
    ) -> Optional[LTFStructure]:
        """Return the newest unspent LTF structure in `direction` after PDA tap."""
        assert self._pda_tap_ts is not None
        cutoff = self._pda_tap_ts
        candidates: list[tuple[datetime, LTFStructure]] = []

        for tf in entry_tfs:
            candles = data_snapshot.get(tf, [])
            if len(candles) < 3:
                continue

            # Plain FVG / BAG.
            for gap in gaps_by_tf.get(tf, []):
                if gap.direction != direction:
                    continue
                if gap.created_at <= cutoff:
                    continue
                if gap.mitigated or gap.spent:
                    continue
                if _gap_key(gap) in self._spent_pda_keys:
                    continue
                candidates.append((gap.created_at, gap))

            # Breaker blocks / CISD — only scan the most recent structure window.
            recent_candles = candles[-_LTF_STRUCTURE_LOOKBACK:]

            # Breaker blocks.
            fvgs = gaps_by_tf.get(tf, [])
            for breaker in structure.find_breakers(recent_candles, tf, fvgs):
                if breaker.direction != direction:
                    continue
                if breaker.created_at <= cutoff:
                    continue
                if _breaker_key(breaker) in self._spent_breaker_keys:
                    continue
                candidates.append((breaker.created_at, breaker))

            # CISD events.
            for cisd in structure.find_cisd(recent_candles, tf):
                if cisd.direction != direction:
                    continue
                if cisd.ts <= cutoff:
                    continue
                if _cisd_key(cisd) in self._spent_cisd_keys:
                    continue
                candidates.append((cisd.ts, cisd))

        if not candidates:
            return None
        candidates.sort(key=lambda t: t[0], reverse=True)
        return candidates[0][1]

    # ------------------------------------------------------------------
    # Overlap / tap detection
    # ------------------------------------------------------------------
    def _fresh_overlap(
        self,
        gap: FairValueGap,
        latest: Candle,
        candles: list[Candle],
    ) -> bool:
        """True when `latest` is the first candle to touch `gap`."""
        if latest.ts <= gap.created_at:
            return False
        if gap.spent or gap.mitigated:
            return False
        return gap.overlaps(latest.low, latest.high)

    def _fresh_overlap_ltf(
        self,
        struct: LTFStructure,
        latest: Candle,
        candles: list[Candle],
    ) -> bool:
        """True when `latest` is the first candle to touch the LTF structure."""
        bottom, top = _structure_zone(struct)
        created_at = _structure_created_at(struct)

        if isinstance(struct, FairValueGap):
            if latest.ts <= created_at:
                return False
            return not struct.spent and struct.overlaps(latest.low, latest.high)

        # Breaker / CISD: manual first-touch check against prior candles.
        for c in candles:
            if c.ts <= created_at:
                continue
            if c.ts >= latest.ts:
                continue
            if self._candle_overlaps_zone(c, bottom, top):
                return False
        return self._candle_overlaps_zone(latest, bottom, top)

    @staticmethod
    def _candle_overlaps_zone(c: Candle, bottom: float, top: float) -> bool:
        return c.low <= top and c.high >= bottom

    # ------------------------------------------------------------------
    # Timefilters
    # ------------------------------------------------------------------
    def _timefilters_ok(self, dt: datetime) -> bool:
        """Intraday entries must pass killzone, blackout and news-day gates."""
        if self.style != TradeStyle.INTRADAY:
            return True
        if not timefilters.in_killzone(dt, enabled=self.enabled_killzones):
            return False
        if timefilters.is_news_blackout(dt, self.news_events):
            return False
        if config.REQUIRE_NEWS_DAY_FOR_INTRADAY:
            if not timefilters.has_high_impact_news_today(dt, self.news_events):
                return False
        return True

    # ------------------------------------------------------------------
    # Signal construction
    # ------------------------------------------------------------------
    def _build_signal(self, dt: datetime, entry_candles: list[Candle]) -> Optional[Signal]:
        """Construct Signal with entry, stop, and exactly 2R take-profit.

        Returns None if the structure is degenerate (entry == stop), enforcing
        a valid risk distance rather than inventing an arbitrary stop.
        """
        assert self._context is not None
        assert self._ltf_structure is not None

        direction = _structure_direction(self._ltf_structure)
        entry = _entry_price_for_structure(self._ltf_structure, direction)
        stop = _stop_price_for_structure(self._ltf_structure, direction, entry_candles)

        if entry == stop:
            return None

        oco = risk.build_oco(direction, entry, stop, self.base_balance, self.risk_mode)

        reason = (
            f"{self.style.value} {direction.name.lower()} from "
            f"{_structure_timeframe(self._ltf_structure)} LTF structure "
            f"into {self._pda_gap.timeframe} PDA"
        )
        return Signal(
            direction=direction,
            style=self.style,
            entry=oco.entry_price,
            stop_loss=oco.stop_loss,
            take_profit=oco.take_profit,
            ts=dt,
            reason=reason,
            context_timeframes=list(self._context_tfs),
        )

    def _mark_ltf_spent(self, struct: LTFStructure) -> None:
        """Ensure the structure that triggered the signal is never reused."""
        if isinstance(struct, FairValueGap):
            struct.spent = True
            struct.mitigated = True
            self._spent_pda_keys.add(_gap_key(struct))
        elif isinstance(struct, BreakerBlock):
            self._spent_breaker_keys.add(_breaker_key(struct))
        elif isinstance(struct, CISDEvent):
            self._spent_cisd_keys.add(_cisd_key(struct))

    # ------------------------------------------------------------------
    # State reset
    # ------------------------------------------------------------------
    def _reset(self) -> None:
        self._stage = "context"
        self._pda_gap = None
        self._pda_tap_ts = None
        self._ltf_structure = None
        self._ltf_formed_at = None
