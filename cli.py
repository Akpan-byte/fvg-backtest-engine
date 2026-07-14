# CHANGE_SUMMARY
# 2026-07-14  kimi-swarm
#   - Created cli.py: main entry point with `sample` and `backtest` subcommands.
# WHY: Provides a scriptable interface to generate sample data and run the
#      deterministic backtest from the command line.
"""
Command-line interface for the ICT FVG backtest engine.

Usage:
    python -m cli sample [--dir DIR]
    python -m cli backtest --data DIR --style intraday|swing \
        --asset forex|index --balance N --risk passive|aggressive \
        [--killzones london,ny_am]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import sample_data
from backtest import run_backtest
from models import AssetClass, RiskMode, TradeStyle


def _style(value: str) -> TradeStyle:
    try:
        return TradeStyle(value.lower())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid style: {value!r}") from exc


def _asset(value: str) -> AssetClass:
    try:
        return AssetClass(value.lower())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid asset: {value!r}") from exc


def _risk(value: str) -> RiskMode:
    try:
        return RiskMode(value.lower())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid risk mode: {value!r}") from exc


def _killzones(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fvg_execution_engine",
        description="ICT-style multi-timeframe FVG backtest engine.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sample = sub.add_parser("sample", help="Write synthetic sample CSV data.")
    sample.add_argument(
        "--dir",
        default="sample_data",
        help="Output directory (default: sample_data).",
    )

    bt = sub.add_parser("backtest", help="Run a walk-forward backtest.")
    bt.add_argument("--data", required=True, help="Directory containing timeframe CSVs.")
    bt.add_argument(
        "--style",
        required=True,
        type=_style,
        help="Trading style: intraday or swing.",
    )
    bt.add_argument(
        "--asset",
        required=True,
        type=_asset,
        help="Asset class: forex or index.",
    )
    bt.add_argument(
        "--balance",
        required=True,
        type=float,
        help="Starting account balance.",
    )
    bt.add_argument(
        "--risk",
        required=True,
        type=_risk,
        help="Risk mode: passive (balance/20) or aggressive (balance/10).",
    )
    bt.add_argument(
        "--killzones",
        type=_killzones,
        default=None,
        help="Comma-separated killzone names (default: london,ny_am).",
    )

    return parser


def _print_stats(result) -> None:
    stats = result.stats
    print("--- Backtest Results ---")
    print(f"Trades total : {stats['trades_total']}")
    print(f"Wins         : {stats['wins']}")
    print(f"Losses       : {stats['losses']}")
    print(f"Win rate     : {stats['win_rate']:.2%}")
    print(f"Net profit   : {stats['net_profit']:.2f}")
    print(f"Avg R        : {stats['avg_r']:.2f}")
    print(f"Max loss run : {stats['max_losing_streak']}")
    print(f"Final balance: {result.equity_curve[-1]:.2f}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "sample":
        sample_data.write_sample_data(args.dir)
        print(f"Sample data written to {args.dir}/")
        return 0

    if args.command == "backtest":
        result = run_backtest(
            data_dir=args.data,
            style=args.style,
            asset=args.asset,
            balance=args.balance,
            mode=args.risk,
            killzones=args.killzones,
        )
        _print_stats(result)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
