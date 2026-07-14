# CHANGE_SUMMARY
# 2026-07-14  kimi-swarm
#   - Created sample_data.py: deterministic synthetic H4/M15 candles plus a
#     matching news event, designed to contain exactly one clean bullish
#     2nd-leg setup and a noisy no-signal region.
# WHY: Gives backtest.py and cli.py a reproducible dataset for tests and
#      demos without requiring real market data.
"""
Synthetic CSV data generator for the ICT FVG backtest.

The generated dataset contains:
- H4 bullish FVG at 08:00 NY on 2026-07-14 (context + PDA).
- An M15 tap of that H4 zone around 09:00 NY.
- A fresh M15 bullish FVG created at 09:30 NY.
- A pullback entry at 09:45 NY inside the M15 FVG.
- A 2R win on the next two M15 bars.
- A high-impact news event (CPI) later that day so intraday mode passes the
  news-day filter without being inside the 30-minute blackout window.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import config

NY = ZoneInfo(config.NY_TZ)


def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 14, hour, minute, tzinfo=NY)


def _m15_rows() -> list[dict]:
    """Hand-built M15 series that aggregates to the H4 plan."""
    rows: list[dict] = []

    def add(h: int, mi: int, o: float, hi: float, lo: float, c: float) -> None:
        rows.append(
            {
                "ts": (_ts(h, mi)).isoformat(),
                "open": o,
                "high": hi,
                "low": lo,
                "close": c,
                "volume": 1000.0,
            }
        )

    # --- H4 00:00 bucket (00:00-03:45): noisy, no FVG ------------------------
    # All bars overlap [99.5, 100.0] so no M15 FVG forms here.
    for m in range(0, 4 * 60, 15):
        add(m // 60, m % 60, 99.8, 100.0, 99.5, 99.8)

    # --- H4 04:00 bucket (04:00-07:45): slow overlapping rise, still no FVG --
    # Aggregate: open ~99.8, high 102.0, low 99.5, close 101.0.
    for m in range(0, 4 * 60, 15):
        add(4 + m // 60, m % 60, 99.8, 102.0, 99.5, 100.0 + (m / 15) * 0.05)

    # --- H4 08:00 bucket (08:00-11:45): the 2nd-leg setup --------------------
    add(8, 0, 101.0, 101.6, 101.0, 101.1)
    add(8, 15, 101.1, 101.6, 101.0, 101.2)
    add(8, 30, 101.2, 101.6, 101.0, 101.3)
    add(8, 45, 101.3, 101.6, 101.0, 101.5)

    # 09:00 taps the H4 FVG [100.0, 101.5].
    add(9, 0, 101.6, 101.7, 100.5, 100.8)
    add(9, 15, 100.9, 101.1, 100.8, 101.0)

    # 09:30 displacement creates M15 bullish FVG [101.7, 102.0].
    add(9, 30, 101.1, 102.2, 102.0, 102.1)

    # 09:45 pullback into the new M15 FVG -> signal bar.
    # Low stays above the 101.7 stop so the trade is not stopped out instantly.
    add(9, 45, 102.1, 102.1, 101.8, 101.9)

    # 10:00 fills the limit entry at 102.0.
    add(10, 0, 101.9, 102.2, 101.8, 102.0)

    # 10:15 hits the 2R target (102.0 + 2*0.3 = 102.6).
    add(10, 15, 102.0, 102.6, 101.9, 102.5)

    # Post-setup noise: drifts back toward the H4 close of 101.8.
    for m in range(30, 4 * 60, 15):
        add(10 + m // 60, m % 60, 102.0, 102.2, 101.7, 101.8)

    # --- H4 12:00 bucket (12:00-15:45): continuation, no new entry signal ----
    for m in range(0, 4 * 60, 15):
        add(12 + m // 60, m % 60, 101.8, 102.5, 101.7, 102.2)

    # --- H4 16:00 bucket (16:00-19:45) ---------------------------------------
    for m in range(0, 4 * 60, 15):
        add(16 + m // 60, m % 60, 102.2, 102.8, 102.0, 102.5)

    # --- H4 20:00 bucket (20:00-23:45) ---------------------------------------
    for m in range(0, 4 * 60, 15):
        add(20 + m // 60, m % 60, 102.5, 103.0, 102.3, 102.8)

    return rows


def _m_rows() -> list[dict]:
    """Monthly candle that provides the highest timeframe bullish context."""
    return [
        {
            "ts": datetime(2026, 6, 1, 0, 0, tzinfo=NY).isoformat(),
            "open": 98.0,
            "high": 99.0,
            "low": 97.0,
            "close": 98.0,
            "volume": 10000.0,
        },
        {
            "ts": datetime(2026, 7, 1, 0, 0, tzinfo=NY).isoformat(),
            "open": 98.0,
            "high": 104.0,
            "low": 97.0,
            "close": 103.0,
            "volume": 10000.0,
        },
    ]


def _w_rows() -> list[dict]:
    """Weekly candles that provide bullish context."""
    return [
        {
            "ts": datetime(2026, 7, 5, 0, 0, tzinfo=NY).isoformat(),
            "open": 98.0,
            "high": 99.0,
            "low": 97.0,
            "close": 98.0,
            "volume": 8000.0,
        },
        {
            "ts": datetime(2026, 7, 12, 0, 0, tzinfo=NY).isoformat(),
            "open": 98.0,
            "high": 104.0,
            "low": 97.0,
            "close": 103.0,
            "volume": 8000.0,
        },
    ]


def _d_rows() -> list[dict]:
    """Daily candles that provide the bullish context FVG."""
    return [
        {
            "ts": datetime(2026, 7, 10, 0, 0, tzinfo=NY).isoformat(),
            "open": 100.0,
            "high": 100.0,
            "low": 99.0,
            "close": 99.0,
            "volume": 5000.0,
        },
        {
            "ts": datetime(2026, 7, 11, 0, 0, tzinfo=NY).isoformat(),
            "open": 99.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 5000.0,
        },
        {
            # Bullish FVG [100.0, 101.0] formed on Jul 12.
            "ts": datetime(2026, 7, 12, 0, 0, tzinfo=NY).isoformat(),
            "open": 100.0,
            "high": 103.0,
            "low": 101.0,
            "close": 103.0,
            "volume": 5000.0,
        },
        {
            "ts": datetime(2026, 7, 13, 0, 0, tzinfo=NY).isoformat(),
            "open": 103.0,
            "high": 104.0,
            "low": 102.0,
            "close": 104.0,
            "volume": 5000.0,
        },
        {
            "ts": datetime(2026, 7, 14, 0, 0, tzinfo=NY).isoformat(),
            "open": 104.0,
            "high": 105.0,
            "low": 104.0,
            "close": 105.0,
            "volume": 5000.0,
        },
    ]


def _h4_rows() -> list[dict]:
    """HTF candles that provide the bullish PDA FVG.

    FVG [100.0, 101.0] is created at 04:00 and tapped at 08:00 so the M15
    2nd leg can form during the NY AM killzone.
    """
    return [
        {
            "ts": datetime(2026, 7, 13, 20, 0, tzinfo=NY).isoformat(),
            "open": 100.0,
            "high": 100.0,
            "low": 99.5,
            "close": 99.8,
            "volume": 5000.0,
        },
        {
            "ts": _ts(0, 0).isoformat(),
            "open": 99.8,
            "high": 101.0,
            "low": 99.5,
            "close": 100.0,
            "volume": 5000.0,
        },
        {
            # Bullish FVG [100.0, 101.0] formed at 04:00 (plain FVG, not a BAG,
            # so the engine uses the operational-context entry set M15/M5).
            "ts": _ts(4, 0).isoformat(),
            "open": 100.0,
            "high": 102.0,
            "low": 101.0,
            "close": 101.0,
            "volume": 5000.0,
        },
        {
            # Tap of the H4 FVG at 08:00.
            "ts": _ts(8, 0).isoformat(),
            "open": 102.0,
            "high": 102.0,
            "low": 100.5,
            "close": 101.0,
            "volume": 5000.0,
        },
        {
            "ts": _ts(12, 0).isoformat(),
            "open": 101.0,
            "high": 102.5,
            "low": 101.0,
            "close": 102.2,
            "volume": 5000.0,
        },
        {
            "ts": _ts(16, 0).isoformat(),
            "open": 102.2,
            "high": 102.8,
            "low": 102.0,
            "close": 102.5,
            "volume": 5000.0,
        },
        {
            "ts": _ts(20, 0).isoformat(),
            "open": 102.5,
            "high": 103.0,
            "low": 102.3,
            "close": 102.8,
            "volume": 5000.0,
        },
    ]


def _news_rows() -> list[dict]:
    """One high-impact event on the sample day, outside the entry window."""
    return [
        {
            "datetime": _ts(11, 0).isoformat(),
            "name": "CPI m/m",
        }
    ]


def write_sample_data(directory: str | Path) -> None:
    """Write H4.csv, M15.csv and news.csv into `directory`."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    for name, rows in [
        ("M.csv", _m_rows()),
        ("W.csv", _w_rows()),
        ("D.csv", _d_rows()),
        ("H4.csv", _h4_rows()),
        ("M15.csv", _m15_rows()),
    ]:
        path = directory / name
        with path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["ts", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerows(rows)

    news_path = directory / "news.csv"
    with news_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["datetime", "name"])
        writer.writeheader()
        writer.writerows(_news_rows())


if __name__ == "__main__":
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "sample_data"
    write_sample_data(out)
    print(f"Sample data written to {out}/")
