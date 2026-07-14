# CHANGE_SUMMARY
# 2026-07-14  kimi-swarm
#   - Created risk.py: fixed-dollar risk sizing, OCO cluster builder,
#     breakeven win-rate math, and losing-streak survivability.
# WHY: Implements the account-preservation protocol — fixed fractional risk
#      (balance/20 passive, balance/10 aggressive), exactly 2R targets, and
#      strictly no martingale, scaling, or trailing after wins or losses.
"""
Account-preservation protocol for the FVG execution engine.

Strategy rules implemented here:
- Fixed dollar risk per trade, identical every trade regardless of prior
  wins or losses: passive = balance / 20, aggressive = balance / 10
  (config.RISK_DIVISORS). No martingale, no scaling.
- Take profit is always exactly 1:2 RR (config.RR). No trailing, no partials.
"""
from __future__ import annotations

import config
from models import Direction, OrderCluster, RiskMode


def risk_amount(balance: float, mode: RiskMode) -> float:
    """Fixed dollar risk for a single trade: balance / config.RISK_DIVISORS.

    Strategy rule: risk is a fixed dollar amount every single trade —
    passive = balance / 20, aggressive = balance / 10 — and never changes
    in response to prior wins or losses (no martingale, no scaling).
    """
    return balance / config.RISK_DIVISORS[mode.value]


def size_position(
    balance: float, mode: RiskMode, entry: float, stop: float
) -> tuple[float, float]:
    """Fixed-fractional position size for one trade.

    Returns (quantity, risk_dollars). risk_dollars is exactly
    risk_amount(balance, mode) — identical every trade regardless of
    win/loss history. quantity = risk_dollars / abs(entry - stop), so a
    wider stop simply means a smaller position at the same dollar risk.

    Raises ValueError if entry == stop: a zero-width stop would imply
    infinite position size and zero room for the trade to breathe.
    """
    distance = abs(entry - stop)
    if distance == 0:
        raise ValueError("entry and stop must differ (zero-width stop)")
    dollars = risk_amount(balance, mode)
    return dollars / distance, dollars


def build_oco(
    direction: Direction,
    entry: float,
    stop: float,
    balance: float,
    mode: RiskMode,
) -> OrderCluster:
    """Build the OCO order cluster (limit entry + stop + fixed 2R target).

    Strategy rule: take_profit = entry + direction.value * config.RR *
    abs(entry - stop) — exactly 1:2 RR, no trailing, no partials. Quantity
    and risk_amount come from size_position, so dollar risk is identical
    every trade.
    """
    quantity, dollars = size_position(balance, mode, entry, stop)
    take_profit = entry + direction.value * config.RR * abs(entry - stop)
    return OrderCluster(
        side=direction,
        quantity=quantity,
        entry_price=entry,
        stop_loss=stop,
        take_profit=take_profit,
        risk_amount=dollars,
        rr=config.RR,
    )


def breakeven_winrate(rr: float) -> float:
    """Win rate required to break even at a given risk:reward: 1 / (1 + rr).

    At the strategy's fixed 2R target (config.RR) this is 1/3 ≈ 0.3333 —
    the system needs only about a 34% win rate to break even.
    """
    return 1.0 / (1.0 + rr)


def max_consecutive_losses_survivable(mode: RiskMode) -> int:
    """Losing-streak cushion for a risk mode: 20 passive, 10 aggressive.

    Directly config.RISK_DIVISORS[mode]: at balance / N fixed risk per
    trade, N consecutive full losses would just exhaust the account, so N
    is the maximum streak the sizing is designed to survive.
    """
    return config.RISK_DIVISORS[mode.value]
