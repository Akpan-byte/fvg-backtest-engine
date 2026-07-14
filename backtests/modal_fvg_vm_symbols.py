#!/usr/bin/env python3
"""Launch BTC, ETH, SOL, GC on Modal to free up the VM."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from modal_fvg_backtest import app, run_symbol


@app.local_entrypoint()
def vm_symbols():
    symbols = ["BTC", "ETH", "SOL", "GC"]
    print(f"Launching Modal backtests for VM symbols: {symbols}")
    for res in run_symbol.map(symbols):
        print(res)
