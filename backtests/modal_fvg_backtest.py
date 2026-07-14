#!/usr/bin/env python3
"""Modal serverless offload for long-running FVG backtests (ES/NQ/YM).

Usage:
    source /config/backtest/venv/bin/activate
    modal run /config/fvg_execution_engine/backtests/modal_fvg_backtest.py

Each symbol runs in its own container with 4 CPU / 16 GB RAM and a 6-hour timeout.
Results are written to the modal-fvg-results volume as JSON.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import modal

app = modal.App("fvg-backtest-offload")
data_vol = modal.Volume.from_name("fvg-backtest-data", create_if_missing=True)
res_vol = modal.Volume.from_name("fvg-backtest-results", create_if_missing=True)

LOCAL_ENGINE = Path("/config/fvg_execution_engine")
LOCAL_DATA = Path("/config/fvg_execution_engine/backtests/data")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("pandas", "tzdata")  # tzdata needed for America/New_York
    .add_local_dir(str(LOCAL_ENGINE), remote_path="/root/fvg_engine")
)


@app.function(
    image=image,
    cpu=4.0,
    memory=16384,
    timeout=12 * 3600,
    volumes={"/data": data_vol, "/results": res_vol},
)
def run_symbol(symbol: str, style: str = "swing", asset: str = "index", balance: float = 50000.0, risk: str = "aggressive") -> dict:
    """Run one symbol backtest in a Modal container."""
    import time

    data_dir = Path(f"/data/data/{symbol}")
    if not data_dir.exists():
        return {"symbol": symbol, "error": f"data dir {data_dir} not found"}

    sys.path.insert(0, "/root/fvg_engine")
    from backtest import run_backtest
    from models import AssetClass, RiskMode, TradeStyle

    asset_cls = AssetClass(asset.lower())
    style_cls = TradeStyle(style.lower())
    risk_cls = RiskMode(risk.lower())

    start = time.time()
    result = run_backtest(data_dir, style_cls, asset_cls, balance, risk_cls)
    elapsed = time.time() - start

    out = {
        "symbol": symbol,
        "style": style,
        "asset": asset,
        "balance": balance,
        "risk": risk,
        "elapsed_seconds": elapsed,
        "trades_total": len(result.trades),
        "stats": result.stats,
        "trades": result.trades,
        "equity_curve": result.equity_curve,
    }

    out_path = Path(f"/results/{symbol}_{style}_{asset}_{risk}.json")
    with open(out_path, "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    res_vol.commit()
    return {"symbol": symbol, "elapsed_seconds": elapsed, "trades": len(result.trades), "out_path": str(out_path)}


@app.local_entrypoint()
def main() -> None:
    """Launch ES, NQ, YM backtests in parallel."""
    symbols = ["ES", "NQ", "YM"]
    print(f"Launching Modal backtests for: {symbols}")
    for res in run_symbol.map(symbols):
        print(res)
