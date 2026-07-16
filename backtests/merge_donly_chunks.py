#!/usr/bin/env python3
"""Merge overlapping D-only context chunks into per-symbol results.

Chunks overlap by ~3 months so boundary-spanning trades are captured by at
least one chunk. Trades are deduplicated by entry_time (rounded to the
minute) so each setup is counted once.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _trade_key(trade: dict) -> str:
    """Stable identity for a trade: direction + entry_time minute + entry price."""
    ts = trade.get("entry_time", "")
    if ts:
        ts = ts[:16]  # "YYYY-MM-DDTHH:MM"
    return f"{trade.get('direction', '')}|{ts}|{trade.get('entry', '')}"


def merge_symbol_donly(result_dir: Path, symbol: str) -> dict | None:
    """Merge D-only chunk results for a symbol and deduplicate trades."""
    all_files = sorted(result_dir.glob(f"{symbol}_Donly_chunk*_result.json"))
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
    result_dir = Path(__file__).parent / "results" / "context_variants"
    out_dir = result_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    symbols = ["ES", "NQ", "YM"]
    for sym in symbols:
        merged = merge_symbol_donly(result_dir, sym)
        if merged is None:
            print(f"{sym}: no D-only chunks found")
            continue
        out_path = out_dir / f"{sym}_Donly_merged_result.json"
        out_path.write_text(json.dumps(merged, indent=2, default=str))
        s = merged["stats"]
        print(
            f"{sym}: wrote {out_path.name} — "
            f"trades={s['trades_total']} win={s['win_rate']:.1%} net=${s['net_profit']:,.0f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
