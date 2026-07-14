#!/usr/bin/env python3
"""Compile FVG backtest results into a summary report."""
from __future__ import annotations

import json
from pathlib import Path

RESULTS_DIR = Path("/config/fvg_execution_engine/backtests/results")
REPORT_FILE = Path("/config/fvg_execution_engine/backtests/BACKTEST_REPORT.md")


def load_results() -> list[dict]:
    results = []
    for f in sorted(RESULTS_DIR.glob("*_swing_index_aggressive.json")):
        try:
            data = json.load(open(f))
            results.append(data)
        except Exception as exc:
            print(f"Failed to load {f}: {exc}")
    return results


def format_currency(val: float) -> str:
    return f"${val:,.2f}"


def main() -> int:
    results = load_results()
    if not results:
        print("No results yet.")
        return 0

    lines = [
        "# FVG Strategy Backtest Report",
        "",
        f"Symbols tested: {len(results)}",
        "Style: swing | Asset: index | Risk: aggressive ($5k/trade on $50k account) | RR: 1:2",
        "",
        "| Symbol | Trades | Wins | Losses | Win Rate | Net Profit | Final Balance | Max Loss Run | Avg R | Elapsed |",
        "|--------|--------|------|--------|----------|------------|---------------|--------------|-------|----------|",
    ]

    for r in results:
        stats = r.get("stats", {})
        lines.append(
            f"| {r['symbol']} | "
            f"{stats.get('trades_total', 0)} | "
            f"{stats.get('wins', 0)} | "
            f"{stats.get('losses', 0)} | "
            f"{stats.get('win_rate', 0):.2%} | "
            f"{format_currency(stats.get('net_profit', 0))} | "
            f"{format_currency(stats.get('final_balance', r.get('balance', 50000) + stats.get('net_profit', 0)))} | "
            f"{stats.get('max_losing_streak', 0)} | "
            f"{stats.get('avg_r', 0):.2f} | "
            f"{r.get('elapsed_seconds', 0)/60:.1f}m |"
        )

    lines.extend(["", "## Notes", "", "- Results are from a deterministic walk-forward replay of 1m OHLCV data.", "- All rules from the strategy brief were enforced: context alignment, HTF PDA tap, LTF 2nd-leg formation, killzone/time filters (for intraday), and fixed 1:2 RR.", "- Swing entries do not require killzone hours or same-day news.", ""])

    REPORT_FILE.write_text("\n".join(lines))
    print(f"Report written to {REPORT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
