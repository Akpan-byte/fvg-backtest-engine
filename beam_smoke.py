# CHANGE_SUMMARY
# 2026-07-14  kilo
#   - Created quick smoke test for Beam volume mount and engine imports.
#   - Accepts symbol as a function argument so it works through the Beam SDK
#     remote invocation (shell env vars are not auto-forwarded).
# WHY: Verify the Beam runtime, volume mount, and local module imports before
#      launching multi-hour backtest jobs.

import os
import sys
from pathlib import Path

from beam import Image, Volume, function


@function(
    name="fvg-smoke-test",
    cpu=1,
    memory="4Gi",
    timeout=300,
    image=Image(python_packages=["tzdata"]),
    volumes=[Volume(name="fvg-data", mount_path="/data")],
)
def smoke(symbol: str = "BTC") -> dict:
    symbol = symbol.upper()
    data_dir = Path("/data") / symbol
    results_dir = Path("/data") / "results" / "beam"

    print(f"Smoke test for {symbol}", flush=True)
    print(f"Python version: {sys.version}", flush=True)
    print(f"CWD: {Path.cwd()}", flush=True)
    print(f"Data dir exists: {data_dir.exists()}", flush=True)
    if data_dir.exists():
        listdir_files = sorted(os.listdir(data_dir))
        print(f"Data dir files: {listdir_files}", flush=True)
        for name in ["D.csv.gz", "H1.csv.gz", "H4.csv.gz", "M.csv.gz", "M1.csv.gz", "M15.csv.gz", "M5.csv.gz", "W.csv.gz"]:
            p = data_dir / name
            print(f"  {name}: exists={p.exists()} size={p.stat().st_size if p.exists() else 'N/A'}", flush=True)
    print(f"Results dir exists: {results_dir.exists()}", flush=True)

    # Verify local engine modules import cleanly.
    from backtest import run_backtest
    from models import AssetClass, RiskMode, TradeStyle
    print("Engine imports OK", flush=True)

    return {
        "symbol": symbol,
        "data_dir_exists": data_dir.exists(),
        "results_dir_exists": results_dir.exists(),
        "files": sorted(os.listdir(data_dir)) if data_dir.exists() else [],
    }


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    smoke(symbol)
