# CHANGE_SUMMARY
# 2026-07-14  kimi-swarm
#   - Created backtest.py: CSV loading, deterministic multi-timeframe replay,
#     signal generation via ExecutionEngine, trade simulation, and stats.
#   - Updated after audit: the replay now routes every bar through the real
#     ExecutionEngine so all context / PDA / 2nd-leg / killzone / news / 2R
#     rules are enforced.  Position sizing uses the frozen starting balance.
# 2026-07-14  kilo
#   - Hardened _parse_timestamp to accept -0400 style UTC offsets (no colon),
#     which is the format used by the crypto CSVs and required by Python 3.10's
#     datetime.fromisoformat. No strategy logic changed.
# WHY: Beam Cloud containers run Python 3.10; without this normalization the
#      crypto data files fail to load. This is a parser compatibility fix only.
"""
Deterministic walk-forward backtest for the ICT multi-timeframe FVG engine.

Public API:
- load_candles(csv_path) -> list[Candle]
- BacktestResult dataclass
- run_backtest(...) -> BacktestResult

Design notes:
- CSVs are loaded per timeframe from a directory (e.g. D.csv, H4.csv, M15.csv).
- Bars are replayed in chronological order; only data up to the current
  timestamp is visible to the strategy logic.
- The ExecutionEngine is called on every event with the full historical
  snapshot.  It enforces context, PDA tap, 2nd-leg formation, killzone,
  news, and 2R rules.
- Trades are sized from the frozen starting balance (fixed-dollar risk), so
  a losing streak does not shrink the dollar risk of subsequent trades.
"""
from __future__ import annotations

import csv
import gzip
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

import config
import risk
import timefilters
from engine import ExecutionEngine
from models import AssetClass, Candle, Direction, RiskMode, Signal, TradeStyle

__all__ = ["load_candles", "BacktestResult", "run_backtest"]


NY = ZoneInfo(config.NY_TZ)


@dataclass
class BacktestResult:
    """Container for backtest output."""

    trades: list[dict] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _parse_timestamp(text: str) -> datetime:
    """Parse a CSV timestamp into a tz-aware America/New_York datetime.

    Supports ISO-like strings, common slash/dash formats, and AM/PM.
    Naive inputs are localized to NY; aware inputs are converted to NY.
    """
    s = text.strip()

    # fromisoformat does not accept a trailing 'Z' in Python 3.12 without
    # an explicit offset, so normalize it first.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    # Python 3.10's fromisoformat also requires a colon in the UTC offset
    # (e.g. -04:00), but the crypto CSVs supply -0400. Normalize that too.
    if len(s) >= 5 and s[-5] in "+-" and s[-4:].isdigit():
        s = s[:-2] + ":" + s[-2:]

    dt: Optional[datetime] = None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        pass

    if dt is None:
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%m/%d/%Y %H:%M:%S",
            "%m/%d/%Y %H:%M",
            "%m/%d/%y %H:%M:%S",
            "%m/%d/%y %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%d-%m-%Y %H:%M:%S",
            "%d-%m-%Y %H:%M",
            "%m-%d-%Y %H:%M:%S",
            "%m-%d-%Y %H:%M",
            "%m/%d/%Y %I:%M:%S %p",
            "%m/%d/%Y %I:%M %p",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue

    if dt is None:
        raise ValueError(f"Unable to parse timestamp: {text!r}")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    else:
        dt = dt.astimezone(NY)
    return dt


def _is_header_row(row: list[str]) -> bool:
    """Heuristic: first cell is a known column name."""
    if not row:
        return False
    first = row[0].strip().lower()
    names = {"ts", "time", "timestamp", "datetime", "date", "open", "high", "low", "close", "volume"}
    return first in names


def load_candles(csv_path: str | Path) -> list[Candle]:
    """Load candles from a CSV file.

    Expected columns (header optional): ts, open, high, low, close, volume.
    Timestamps are parsed flexibly and normalized to America/New_York.
    Returns candles sorted by timestamp.

    Supports plain ``*.csv`` and gzip-compressed ``*.csv.gz`` files.
    """
    path = Path(csv_path)
    candles: list[Candle] = []
    opener = gzip.open if path.suffixes and path.suffixes[-1] == ".gz" else open
    with opener(path, "rt", newline="") as fh:
        reader = csv.reader(fh)
        first = next(reader, None)
        if first is None:
            return []
        start = 1 if _is_header_row(first) else 0
        if start == 0:
            row = first
            candles.append(
                Candle(
                    ts=_parse_timestamp(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]) if len(row) > 5 else 0.0,
                )
            )
        for row in reader:
            if not row:
                continue
            candles.append(
                Candle(
                    ts=_parse_timestamp(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]) if len(row) > 5 else 0.0,
                )
            )
    candles.sort(key=lambda c: c.ts)
    return candles


def _tf_rank(tf: str) -> int:
    """Position in config.TF_ORDER (lower index = higher timeframe)."""
    try:
        return config.TF_ORDER.index(tf)
    except ValueError:
        return len(config.TF_ORDER)


def _load_timeframe_csvs(data_dir: str | Path) -> dict[str, list[Candle]]:
    """Load every {timeframe}.csv or {timeframe}.csv.gz in data_dir."""
    data_dir = Path(data_dir)
    by_tf: dict[str, list[Candle]] = {}
    for path in sorted(data_dir.glob("*.csv*")):
        # Handle both M1.csv and M1.csv.gz.
        tf = path.stem.upper().removesuffix(".CSV")
        if tf not in config.TF_ORDER:
            continue
        by_tf[tf] = load_candles(path)
    return by_tf


def _load_news_events(data_dir: str | Path) -> list[timefilters.NewsEvent]:
    """Load optional news.csv or news.csv.gz (datetime,name) from data_dir."""
    data_dir = Path(data_dir)
    news_path = data_dir / "news.csv"
    if not news_path.exists():
        news_path = data_dir / "news.csv.gz"
    events: list[timefilters.NewsEvent] = []
    if not news_path.exists():
        return events
    opener = gzip.open if news_path.suffix == ".gz" else open
    with opener(news_path, "rt", newline="") as fh:
        reader = csv.reader(fh)
        first = next(reader, None)
        if first is None:
            return events
        start = 1 if _is_header_row(first) else 0
        if start == 0:
            events.append((_parse_timestamp(first[0]), first[1]))
        for row in reader:
            if not row:
                continue
            events.append((_parse_timestamp(row[0]), row[1]))
    return events


def _close_trade(
    trade: dict,
    exit_price: float,
    exit_time: datetime,
    balance: float,
) -> tuple[dict, float]:
    """Close an open trade and return (closed_trade, new_balance)."""
    direction = trade["direction"]
    qty = trade["quantity"]
    entry = trade["entry"]
    risk_amount = trade["risk_amount"]
    pnl = direction.value * qty * (exit_price - entry)
    balance += pnl
    result = "win" if pnl > 0 else "loss"
    r_multiple = pnl / risk_amount if risk_amount else 0.0
    trade.update(
        {
            "exit_time": exit_time,
            "exit_price": exit_price,
            "pnl": pnl,
            "result": result,
            "balance_after": balance,
            "r_multiple": r_multiple,
        }
    )
    return trade, balance


def run_backtest(
    data_dir: str | Path,
    style: TradeStyle,
    asset: AssetClass,
    balance: float,
    mode: RiskMode,
    *,
    killzones: Optional[Sequence[str]] = None,
    news_events: Optional[Sequence[timefilters.NewsEvent]] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> BacktestResult:
    """Run a deterministic walk-forward backtest over timeframe CSVs in data_dir.

    Parameters
    ----------
    data_dir:
        Directory containing {timeframe}.csv files. An optional news.csv with
        columns (datetime, name) may also be present.
    style:
        TradeStyle.INTRADAY or TradeStyle.SWING.
    asset:
        AssetClass.FOREX or AssetClass.INDEX.
    balance:
        Starting account balance (frozen for fixed-dollar risk sizing).
    mode:
        RiskMode.PASSIVE (balance/20) or RiskMode.AGGRESSIVE (balance/10).
    killzones:
        Optional sequence of killzone names (e.g. ["london", "ny_am"]).
        Defaults to config.DEFAULT_ENABLED_KILLZONES.
    news_events:
        Optional explicit news events. If omitted, loaded from news.csv.
    start_date:
        If provided, ignore candles and trades before this datetime (inclusive).
    end_date:
        If provided, ignore candles and trades after this datetime (inclusive).
    """
    data_dir = Path(data_dir)
    candles_by_tf = _load_timeframe_csvs(data_dir)

    # Optional date-range chunking for long-running backtests (e.g. splitting
    # 10-year futures data into chunks that fit under CI timeouts).  Filtering
    # here reduces the event stream size while preserving strategy fidelity
    # inside the requested window.
    if start_date is not None or end_date is not None:
        for tf, candles in candles_by_tf.items():
            candles_by_tf[tf] = [
                c
                for c in candles
                if (start_date is None or c.ts >= start_date)
                and (end_date is None or c.ts <= end_date)
            ]

    initial_balance = balance
    equity_curve = [balance]
    closed_trades: list[dict] = []

    if not candles_by_tf:
        return BacktestResult(
            trades=[],
            equity_curve=equity_curve,
            stats=_compute_stats([], initial_balance),
        )

    if news_events is None:
        news_events = _load_news_events(data_dir)
    if killzones is None:
        killzones = config.DEFAULT_ENABLED_KILLZONES

    engine = ExecutionEngine(
        asset_class=asset,
        style=style,
        balance=initial_balance,
        risk_mode=mode,
        enabled_killzones=tuple(killzones),
        news_events=list(news_events),
    )

    # Build a globally sorted event stream. Ties are resolved by processing
    # higher timeframes first, so lower-timeframe bars can react to HTF closes.
    events: list[tuple[datetime, int, str, Candle]] = []
    for tf, candles in candles_by_tf.items():
        rank = _tf_rank(tf)
        for candle in candles:
            events.append((candle.ts, rank, tf, candle))
    events.sort(key=lambda e: (e[0], e[1]))

    history: dict[str, list[Candle]] = {tf: [] for tf in candles_by_tf}
    open_trade: Optional[dict] = None
    pending_signal: Optional[Signal] = None

    for dt, _rank, tf, candle in events:
        history[tf].append(candle)

        # Update / fill a pending signal first (limit order from prior bar).
        if pending_signal is not None and open_trade is None:
            if pending_signal.entry <= candle.high and pending_signal.entry >= candle.low:
                oco = risk.build_oco(
                    pending_signal.direction,
                    pending_signal.entry,
                    pending_signal.stop_loss,
                    initial_balance,
                    mode,
                )
                open_trade = {
                    "direction": pending_signal.direction,
                    "entry": oco.entry_price,
                    "stop_loss": oco.stop_loss,
                    "take_profit": oco.take_profit,
                    "quantity": oco.quantity,
                    "risk_amount": oco.risk_amount,
                    "entry_time": candle.ts,
                    "timeframe": tf,
                    "reason": pending_signal.reason,
                }
            pending_signal = None

        # Check an open trade against this bar.
        if open_trade is not None:
            direction = open_trade["direction"]
            tp = open_trade["take_profit"]
            stop = open_trade["stop_loss"]
            exit_price: Optional[float] = None
            if direction == Direction.BULLISH:
                if candle.high >= tp:
                    exit_price = tp
                elif candle.low <= stop:
                    exit_price = stop
            else:
                if candle.low <= tp:
                    exit_price = tp
                elif candle.high >= stop:
                    exit_price = stop

            if exit_price is not None:
                closed, balance = _close_trade(open_trade, exit_price, candle.ts, balance)
                closed_trades.append(closed)
                open_trade = None
                equity_curve.append(balance)

        # Always route the bar through the engine so its internal state advances,
        # but only act on a signal when we are flat.  History is already
        # chronological and trimmed to dt by construction, so pass it directly
        # without copying to avoid O(n²) list duplication.
        signal = engine.on_bar(dt, history, trusted_snapshot=True)
        if signal is not None and open_trade is None:
            # Fill immediately if the current bar touches the entry; otherwise
            # leave as a pending limit order for the next bar.
            if signal.entry <= candle.high and signal.entry >= candle.low:
                oco = risk.build_oco(
                    signal.direction,
                    signal.entry,
                    signal.stop_loss,
                    initial_balance,
                    mode,
                )
                open_trade = {
                    "direction": signal.direction,
                    "entry": oco.entry_price,
                    "stop_loss": oco.stop_loss,
                    "take_profit": oco.take_profit,
                    "quantity": oco.quantity,
                    "risk_amount": oco.risk_amount,
                    "entry_time": candle.ts,
                    "timeframe": tf,
                    "reason": signal.reason,
                }
            else:
                pending_signal = signal

        equity_curve.append(balance)

    # Close any remaining trade at the last available close.
    if open_trade is not None:
        tf = open_trade["timeframe"]
        last_close = (
            history[tf][-1].close
            if tf in history and history[tf]
            else open_trade["entry"]
        )
        closed, balance = _close_trade(open_trade, last_close, history[tf][-1].ts, balance)
        closed_trades.append(closed)
        equity_curve.append(balance)

    closed_trades.sort(key=lambda t: t["entry_time"])
    stats = _compute_stats(closed_trades, initial_balance)
    return BacktestResult(trades=closed_trades, equity_curve=equity_curve, stats=stats)


def _compute_stats(trades: list[dict], initial_balance: float) -> dict:
    """Compute the strategy summary statistics required by the brief."""
    total = len(trades)
    wins = sum(1 for t in trades if t.get("result") == "win")
    losses = total - wins
    net_profit = trades[-1]["balance_after"] - initial_balance if trades else 0.0
    win_rate = wins / total if total else 0.0
    r_values = [t.get("r_multiple", 0.0) for t in trades]
    avg_r = sum(r_values) / total if total else 0.0

    max_streak = 0
    current = 0
    for t in trades:
        if t.get("result") == "loss":
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0

    return {
        "net_profit": net_profit,
        "win_rate": win_rate,
        "avg_r": avg_r,
        "max_losing_streak": max_streak,
        "trades_total": total,
        "wins": wins,
        "losses": losses,
    }
