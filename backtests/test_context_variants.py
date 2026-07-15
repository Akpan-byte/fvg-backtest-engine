#!/usr/bin/env python3
"""Run backtest with custom context timeframe sets for comparison."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add parent to path so we can import the engine modules.
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from backtest import run_backtest
from models import AssetClass, RiskMode, TradeStyle

NY = __import__("zoneinfo").ZoneInfo("America/New_York")


VARIANTS = {
    "H4_only": ("H4",),
    "D_only": ("D",),
    "full_context": ("M", "W", "D", "H4"),
}


def _parse_iso(text: str) -> datetime:
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    return dt.astimezone(NY)


def run_variant(
    symbol: str,
    context_tfs: tuple[str, ...],
    start: str,
    end: str,
    output: Path,
) -> dict[str, Any]:
    """Run a single context-variant backtest and write JSON."""
    original_context = config.CONTEXT_TFS_INDEX
    config.CONTEXT_TFS_INDEX = context_tfs
    try:
        result = run_backtest(
            data_dir=Path(__file__).parent / "data" / symbol,
            style=TradeStyle("swing"),
            asset=AssetClass("index"),
            balance=50_000.0,
            mode=RiskMode("aggressive"),
            start_date=_parse_iso(start),
            end_date=_parse_iso(end),
        )
    finally:
        config.CONTEXT_TFS_INDEX = original_context

    payload = {
        "meta": {
            "symbol": symbol,
            "context_tfs": context_tfs,
            "start": start,
            "end": end,
            "style": "swing",
            "asset": "index",
            "balance": 50_000.0,
            "risk": "aggressive",
        },
        "stats": result.stats,
        "trades": result.trades,
        "equity_curve": result.equity_curve,
    }
    output.write_text(json.dumps(payload, indent=2, default=str))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run context-variant backtest.")
    parser.add_argument("variant", choices=list(VARIANTS.keys()))
    parser.add_argument("--symbol", default="ES", help="Futures symbol (ES, NQ, YM).")
    parser.add_argument("--start", default="2019-03-01T00:00:00", help="ISO start datetime.")
    parser.add_argument("--end", default="2019-09-01T00:00:00", help="ISO end datetime.")
    args = parser.parse_args()

    out_dir = Path(__file__).parent / "results" / "context_variants"
    out_dir.mkdir(parents=True, exist_ok=True)

    context_tfs = VARIANTS[args.variant]
    out_path = out_dir / f"{args.symbol}_{args.variant}_{args.start[:10]}_{args.end[:10]}.json"
    if out_path.exists():
        print(f"Skipping {args.variant} for {args.symbol} (already exists)")
        return 0

    print(f"Running {args.variant} for {args.symbol} with context {context_tfs}...")
    result = run_variant(args.symbol, context_tfs, args.start, args.end, out_path)
    s = result["stats"]
    print(
        f"  {args.variant}: {s['trades_total']} trades, "
        f"{s['win_rate']:.1%} win, ${s['net_profit']:,.0f} net, "
        f"max LS {s['max_losing_streak']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
