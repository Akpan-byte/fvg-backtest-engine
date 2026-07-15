import re
#!/usr/bin/env python3
"""Merge chunked backtest results into a single per-symbol result.

Chunks are expected to be ordered by date range and non-overlapping.
Trades, equity curve, and stats are aggregated."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def merge_symbol_chunks(result_dir: Path, symbol: str) -> dict | None:
    chunks = sorted([x for x in result_dir.glob(f"{symbol}_chunk*_result.json") if not x.name.startswith(f"{symbol}_chunk1") or re.match(rf"^{symbol}_chunk1[a-z]?_result\.json$", x.name)])
    if not chunks:
        return None

    all_trades: list[dict] = []
    final_balance = 0.0
    meta: dict | None = None

    for p in chunks:
        data = _load(p)
        trades = data.get("trades", [])
        all_trades.extend(trades)
        if data.get("equity_curve"):
            final_balance = data["equity_curve"][-1]
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
    # the sum of per-chunk net profits, not final equity curve delta.
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
