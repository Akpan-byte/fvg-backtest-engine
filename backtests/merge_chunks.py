#!/usr/bin/env python3
"""Merge chunked and bridge backtest results into a single per-symbol result.

Combines non-overlapping chunks with overlapping boundary bridges, then
deduplicates trades by entry_time so boundary-spanning setups are counted once.
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


def _bridge_sort_key(path: Path) -> tuple:
    """Sort bridge files by bridge number."""
    m = re.search(r"_bridge(\d+)_result\.json$", path.name)
    if not m:
        return (999,)
    return (int(m.group(1)),)


def _trade_key(trade: dict) -> str:
    """Stable identity for a trade: symbol + entry_time rounded to the minute."""
    ts = trade.get("entry_time", "")
    # Strip seconds/sub-minute precision so the same entry triggered in two
    # overlapping chunks is deduplicated to a single trade.
    if ts:
        ts = ts[:16]  # "YYYY-MM-DDTHH:MM"
    return f"{trade.get('direction','')}|{ts}|{trade.get('entry','')}"


def merge_symbol_results(result_dir: Path, symbol: str) -> dict | None:
    """Merge chunk + bridge results for a symbol and deduplicate trades."""
    chunk_files = sorted(
        result_dir.glob(f"{symbol}_chunk*_result.json"),
        key=_chunk_sort_key,
    )
    bridge_files = sorted(
        result_dir.glob(f"{symbol}_bridge*_result.json"),
        key=_bridge_sort_key,
    )
    all_files = chunk_files + bridge_files

    # If subchunks for chunk1 exist (1a, 1b, 1c), drop the parent chunk1.
    subchunks = [p for p in chunk_files if re.search(r"_chunk1[a-z]_result\.json$", p.name)]
    if subchunks:
        all_files = [p for p in all_files if not re.search(r"_chunk1_result\.json$", p.name)]

    if not all_files:
        return None

    meta: dict | None = None
    seen: set[str] = set()
    deduped_trades: list[dict] = []

    for p in all_files:
        data = _load(p)
        if meta is None:
            meta = data.get("meta", {})
        for trade in data.get("trades", []):
            key = _trade_key(trade)
            if key in seen:
                continue
            seen.add(key)
            deduped_trades.append(trade)

    deduped_trades.sort(key=lambda t: t["entry_time"])

    total = len(deduped_trades)
    wins = sum(1 for t in deduped_trades if t.get("result") == "win")
    losses = total - wins
    win_rate = wins / total if total else 0.0
    r_values = [t.get("r_multiple", 0.0) for t in deduped_trades]
    avg_r = sum(r_values) / total if total else 0.0

    max_streak = 0
    current = 0
    for t in deduped_trades:
        if t.get("result") == "loss":
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0

    start_balance = meta.get("balance", 50000.0) if meta else 50000.0
    # With fixed-dollar risk and identical sizing, net profit is the sum of
    # individual trade PnLs from the deduplicated trade list.
    net_profit = sum(t.get("pnl", 0.0) for t in deduped_trades)
    final_balance = start_balance + net_profit

    stats = {
        "trades_total": total,
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
        "trades": deduped_trades,
        "equity_curve": [start_balance, final_balance],
    }


def main() -> int:
    result_dir = Path(__file__).parent / "results" / "github"
    out_dir = result_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    symbols = ["ES", "NQ", "YM"]
    for sym in symbols:
        merged = merge_symbol_results(result_dir, sym)
        if merged is None:
            print(f"{sym}: no results found")
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
