# CHANGE_SUMMARY
# 2026-07-14  kilo
#   - Created backtest_json.py: thin JSON-serializing wrapper around
#     backtest.run_backtest so Lightning AI jobs can write machine-readable
#     results to disk without touching strategy logic.
# WHY: The cli.py backtest command only prints human-readable stats; remote
#      batch jobs need deterministic JSON output for downstream aggregation.

#!/usr/bin/env python3
"""Serialize FVG backtest results to JSON.

This is a thin wrapper around the engine's deterministic backtest so that
remote jobs can write machine-readable results to disk. It does not modify
strategy logic.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from backtest import run_backtest
from models import AssetClass, RiskMode, TradeStyle


def _serialize(obj: Any) -> Any:
    """Recursively convert enums, datetimes, and other non-JSON types."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "value"):
        return obj.value
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    if isinstance(obj, tuple):
        return [_serialize(v) for v in obj]
    return obj


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run FVG backtest and write results to JSON."
    )
    parser.add_argument("--data", required=True, help="Directory containing timeframe CSVs.")
    parser.add_argument(
        "--style", required=True, type=lambda s: TradeStyle(s.lower()), help="intraday or swing"
    )
    parser.add_argument(
        "--asset", required=True, type=lambda s: AssetClass(s.lower()), help="forex or index"
    )
    parser.add_argument("--balance", required=True, type=float, help="Starting balance.")
    parser.add_argument(
        "--risk", required=True, type=lambda s: RiskMode(s.lower()), help="passive or aggressive"
    )
    parser.add_argument("--output", required=True, help="Path to write the JSON result file.")
    parser.add_argument(
        "--start-date",
        dest="start_date",
        type=lambda s: datetime.fromisoformat(s),
        default=None,
        help="ISO datetime. Ignore candles/trades before this date.",
    )
    parser.add_argument(
        "--end-date",
        dest="end_date",
        type=lambda s: datetime.fromisoformat(s),
        default=None,
        help="ISO datetime. Ignore candles/trades after this date.",
    )
    args = parser.parse_args(argv)

    result = run_backtest(
        data_dir=args.data,
        style=args.style,
        asset=args.asset,
        balance=args.balance,
        mode=args.risk,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    payload = {
        "meta": {
            "data_dir": str(args.data),
            "style": args.style.value,
            "asset": args.asset.value,
            "balance": args.balance,
            "risk": args.risk.value,
            "final_balance": result.equity_curve[-1] if result.equity_curve else args.balance,
        },
        "stats": _serialize(result.stats),
        "trades": _serialize(result.trades),
        "equity_curve": _serialize(result.equity_curve),
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(payload, fh, indent=2)

    print(f"Wrote backtest result to {out_path}")
    print(json.dumps(payload["stats"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
