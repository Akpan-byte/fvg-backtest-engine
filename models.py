# CHANGE_SUMMARY
# 2026-07-14  kimi-swarm
#   - Created shared data model contract for the FVG/Breaker execution engine.
# WHY: All modules (fvg, structure, context, engine, risk, backtest) must
#      exchange identical dataclasses so independently-built parts interlock.
"""
Shared data models for the ICT multi-timeframe FVG execution engine.

Strategy rules encoded here:
- Everything is anchored to New York time (America/New_York).
- An FVG/BAG is single-use: once price taps it, it is spent forever.
- Signals always carry entry / stop / 2R take-profit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Direction(Enum):
    BULLISH = 1
    BEARISH = -1


class GapType(Enum):
    FVG = "fvg"  # plain fair value gap
    BAG = "bag"  # breakaway gap (high-momentum FVG)


class TradeStyle(Enum):
    INTRADAY = "intraday"  # needs killzone + news-day, entry M15/M5/M1
    SWING = "swing"        # no killzone/news requirement, entry H4/H1


class AssetClass(Enum):
    FOREX = "forex"  # context M/W/D only; entries H4/H1 only
    INDEX = "index"  # indices & gold: H4 allowed as context; LTF entries ok


class RiskMode(Enum):
    PASSIVE = "passive"      # balance / 20  (20-trade losing streak cushion)
    AGGRESSIVE = "aggressive"  # balance / 10 (10-trade losing streak cushion)


@dataclass
class Candle:
    ts: datetime  # tz-aware, America/New_York
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass
class FairValueGap:
    direction: Direction
    gap_type: GapType
    top: float            # upper boundary of the gap zone
    bottom: float         # lower boundary of the gap zone
    created_at: datetime
    timeframe: str        # e.g. "D", "H4", "M15"
    mitigated: bool = False  # price has traded into the zone
    spent: bool = False      # single-use: consumed by first touch

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top

    def overlaps(self, low: float, high: float) -> bool:
        return low <= self.top and high >= self.bottom


@dataclass
class SwingPoint:
    ts: datetime
    price: float
    kind: str  # "high" or "low"


@dataclass
class BreakerBlock:
    direction: Direction
    top: float
    bottom: float
    created_at: datetime
    timeframe: str
    has_fvg_overlap: bool = False  # True  =>  "Unicorn" model


@dataclass
class CISDEvent:
    direction: Direction
    level: float          # the body level that was closed through
    ts: datetime
    timeframe: str


@dataclass
class Signal:
    direction: Direction
    style: TradeStyle
    entry: float
    stop_loss: float
    take_profit: float    # always exactly 2R from entry
    ts: datetime
    reason: str
    context_timeframes: list = field(default_factory=list)


@dataclass
class OrderCluster:
    """OCO payload: limit entry + stop + fixed 2R target."""
    side: Direction
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_amount: float    # fixed $ risk, identical every trade
    rr: float = 2.0
