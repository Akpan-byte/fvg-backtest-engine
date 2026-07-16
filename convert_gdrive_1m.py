#!/usr/bin/env python3
"""Convert gdrive 1-minute CSVs into FVG engine multi-timeframe format.

Reads files like backtests/data/gdrive_raw/{SYMBOL}_1min.csv,
parses timestamps (UTC-aware or naive-NY), converts everything to
America/New_York, then resamples to M/W/D/H4/H1/M15/M5/M1 candles
and writes gzip CSVs into backtests/data/{SYMBOL}/.
"""
from __future__ import annotations

import gzip
import sys
from pathlib import Path

import pandas as pd
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

TIME_FRAMES = {
    "M": "ME",      # month end
    "W": "W-SUN",   # weekly ending Sunday
    "D": "D",
    "H4": "4h",
    "H1": "1h",
    "M15": "15min",
    "M5": "5min",
    "M1": "1min",
}

# For weekly/monthly we want the bar timestamp to represent the start or a
# stable anchor.  Using "left" label with closed="left" keeps bars aligned.
RESAMPLE_RULES = {
    "M": "ME",
    "W": "W-SUN",
    "D": "D",
    "H4": "4h",
    "H1": "1h",
    "M15": "15min",
    "M5": "5min",
    "M1": "1min",
}


def read_1m_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.rename(columns={c: c.lower().strip() for c in df.columns})
    # Accept either 'timestamp' or 'ts' column.
    ts_col = "timestamp" if "timestamp" in df.columns else "ts"
    df[ts_col] = df[ts_col].astype(str).str.strip()
    # Parse; if a row has an offset pandas handles it, naive ones become NY.
    df["ts"] = pd.to_datetime(df[ts_col], utc=True)
    df = df.set_index("ts").sort_index()
    # Drop duplicate timestamps, keep first.
    df = df[~df.index.duplicated(keep="first")]
    return df


def resample_to(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample 1m OHLCV to a higher timeframe."""
    resampled = pd.DataFrame(
        {
            "open": df["open"].resample(rule, label="left", closed="left").first(),
            "high": df["high"].resample(rule, label="left", closed="left").max(),
            "low": df["low"].resample(rule, label="left", closed="left").min(),
            "close": df["close"].resample(rule, label="left", closed="left").last(),
            "volume": df["volume"].resample(rule, label="left", closed="left").sum(),
        }
    )
    resampled = resampled.dropna()
    return resampled


def write_csv(df: pd.DataFrame, path: Path) -> None:
    """Write DataFrame as gzip CSV with NY-local ISO timestamps."""
    df = df.copy()
    # Convert UTC index to NY and format with offset.
    df.index = df.index.tz_convert(NY)
    df.index.name = "ts"
    # Reset index so ts becomes a column; format ISO with offset.
    df_out = df.reset_index()
    df_out["ts"] = df_out["ts"].apply(lambda x: x.isoformat())
    with gzip.open(path, "wt", newline="") as fh:
        df_out.to_csv(fh, index=False)


def convert_symbol(raw_dir: Path, symbol: str, out_dir: Path) -> None:
    in_path = raw_dir / f"{symbol}_1min.csv"
    if not in_path.exists():
        print(f"Skipping {symbol}: {in_path} not found")
        return
    print(f"Converting {symbol} ...")
    df = read_1m_csv(in_path)
    print(f"  1m rows: {len(df)}, range: {df.index[0]} to {df.index[-1]} UTC")

    symbol_out = out_dir / symbol
    symbol_out.mkdir(parents=True, exist_ok=True)

    for tf, rule in RESAMPLE_RULES.items():
        rdf = resample_to(df, rule)
        out_path = symbol_out / f"{tf}.csv.gz"
        write_csv(rdf, out_path)
        print(f"  {tf}: {len(rdf)} rows -> {out_path}")


def main() -> int:
    repo_root = Path(__file__).parent
    raw_dir = repo_root / "backtests" / "data" / "gdrive_raw"
    out_dir = repo_root / "backtests" / "data"

    if not raw_dir.exists():
        print(f"Raw directory not found: {raw_dir}")
        return 1

    symbols = [
        p.stem.replace("_1min", "")
        for p in raw_dir.glob("*_1min.csv")
    ]
    symbols.sort()
    print(f"Found symbols: {symbols}")

    for sym in symbols:
        try:
            convert_symbol(raw_dir, sym, out_dir)
        except Exception as e:
            print(f"ERROR converting {sym}: {e}")
            import traceback
            traceback.print_exc()

    return 0


if __name__ == "__main__":
    sys.exit(main())
