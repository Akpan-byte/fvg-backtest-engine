#!/usr/bin/env python3
"""Convert a single 1-minute OHLCV CSV into the FVG engine's per-timeframe CSVs.

Usage:
    source /config/backtest/venv/bin/activate
    python3 convert_1m_to_engine.py <input_1m.csv> <output_dir>

Outputs: M.csv, W.csv, D.csv, H4.csv, H1.csv, M15.csv, M5.csv, M1.csv
with columns: ts,open,high,low,close,volume
"""
from __future__ import annotations

import argparse
import gzip
import os
import sys
from pathlib import Path

import pandas as pd

TIMEFRAMES = {
    "M": "ME",   # month end
    "W": "W-SUN",  # weekly Sunday-aligned
    "D": "D",
    "H4": "4h",
    "H1": "1h",
    "M15": "15min",
    "M5": "5min",
    "M1": "1min",
}


def read_1m(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Normalize column names
    df.columns = [c.strip().lower() for c in df.columns]
    # Parse timestamp
    ts_col = "timestamp" if "timestamp" in df.columns else "ts"
    df["ts"] = pd.to_datetime(df[ts_col], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    df = df[["ts", "open", "high", "low", "close", "volume"]]
    return df


def resample_to(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample 1m OHLCV to a higher timeframe, dropping empty periods."""
    df = df.set_index("ts")
    res = df.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })
    res = res.dropna(subset=["open", "high", "low", "close"])
    res = res.reset_index()
    return res


def write_csv(df: pd.DataFrame, path: Path) -> None:
    # Write in NY timezone if tz-aware; otherwise keep as UTC-aware ISO.
    out = df.copy()
    if isinstance(out["ts"].dtype, pd.DatetimeTZDtype):
        out["ts"] = out["ts"].dt.tz_convert("America/New_York")
    out["ts"] = out["ts"].dt.strftime("%Y-%m-%d %H:%M:%S%z")
    gz_path = path.with_suffix(path.suffix + ".gz")
    with gzip.open(gz_path, "wt", newline="") as fh:
        out.to_csv(fh, index=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert 1m OHLCV CSV to FVG engine format")
    parser.add_argument("input", type=Path, help="Input 1m CSV path")
    parser.add_argument("output_dir", type=Path, help="Output directory")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Reading {args.input} ...")
    df = read_1m(args.input)
    print(f"  rows: {len(df)}, range: {df['ts'].min()} -> {df['ts'].max()}")

    for tf, rule in TIMEFRAMES.items():
        if tf == "M1":
            res = df.copy()
        else:
            res = resample_to(df, rule)
        out_path = args.output_dir / f"{tf}.csv"
        write_csv(res, out_path)
        print(f"  {tf}: {len(res)} bars -> {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
