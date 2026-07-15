#!/usr/bin/env python3
"""Merge chunked backtest results into a single per-symbol result.

Chunks are expected to be ordered by date range and non-overlapping.
Trades, equity curve, and stats are aggregated.

Subchunk support: if chunk1a/b/c exist, they replace chunk1 so that a
partial/failed chunk1 can be superseded by smaller successful subchunks.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _chunk_sort_key(path: Path) -> tuple:
    """Sort chunk files: chunk1 < chunk1a < chunk1b < chunk2 < chunk3."""
    m = re.search(r"_chunk(\d+)([a-z]?)_result\.json$", path.name)
    if not m:
        return (999, "")
    return (int(m.group(1)), m.group(2) or "_")


def merge_symbol_chunks(result_dir: Path, symbol: str) -> dict | None:
    all_files = list(result_dir.glob(f"{symbol}_chunk*_result.json"))
    if not all_files:
        return None

    # If subchunks for chunk1 exist (1a, 1b, 1c), drop the parent chunk1.
    subchunks = [p for p in all_files if re.search(r"_chunk1[a-z]_result\.json$", p.name)]
    if subchunks:
        all_files = [p for p in all_files if not re.search(r"_chunk1_result\.json$", p.name)]

    chunks = sorted(all_files, key=_chunk_sort_key)

    all_trades: list[dict] = []
    meta: dict | None = None

    for p in chunks:
        data = _load(p)
        all_trades.extend(data.get("trades", []))
        if meta is None:
            meta = data.get("meta", {})

    all_trades.sort(key=lambda t: t["entry_time"])

    wins = sum(1 for t in all_trades if t.get("result") == "win")
    losses = len(all_trades) - wins
    win_rate = wins / len(all_trades) if all_trades else 0.0
    r_values = [t.get("r_multiple", 0.0) for t in all_trades]
    avg_r = sum(r_values) / len(all_trades) if all_trades else 0.0

    max_streak = 0
    current = 0
    for t in all_trades:
        if t.get("result") == "loss":
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0

    start_balance = meta.get("balance", 50000.0) if meta else 50000.0
    # Each chunk backtest starts from the same initial balance, so total PnL is
    # the sum of per-chunk net profits.
    net_profit = sum(
        _load(p).get("stats", {}).get("net_profit", 0.0) for p in chunks
    )
    final_balance = start_balance + net_profit

    stats = {
        "trades_total": len(all_trades),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_r": avg_r,
        "max_losing_streak": max_streak,
        "net_profit": net_profit,
    }

    return {
        "meta": meta,
        "stats": stats,
        "trades": all_trades,
        "equity_curve": [start_balance, final_balance],
    }


def main() -> int:
    result_dir = Path(__file__).parent / "results" / "github"
    out_dir = result_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    symbols = ["ES", "NQ", "YM"]
    for sym in symbols:
        merged = merge_symbol_chunks(result_dir, sym)
        if merged is None:
            print(f"{sym}: no chunks found")
            continue
        out_path = out_dir / f"{sym}_merged_result.json"
        out_path.write_text(json.dumps(merged, indent=2, default=str))
        s = merged["stats"]
        print(
            f"{sym}: wrote {out_path.name} — "
            f"trades={s['trades_total']} win={s['win_rate']:.1%} net=${s['net_profit']:,.0f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
