#!/usr/bin/env python3
"""Launch a single symbol backtest on Modal (use with modal run --detach)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from modal_fvg_backtest import app, run_symbol


@app.local_entrypoint()
def run_one(symbol: str):
    # Use .spawn() so the local entrypoint returns immediately; the remote
    # function continues executing inside the detached app.
    call = run_symbol.spawn(symbol)
    print(f"Spawned {symbol}: {call.object_id}")
