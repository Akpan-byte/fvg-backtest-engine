#!/usr/bin/env python3
"""Quick Modal smoke test for one symbol."""
import modal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from modal_fvg_backtest import app, run_symbol

@app.local_entrypoint()
def test():
    print(run_symbol.remote("SI"))
