# CHANGE_SUMMARY
# 2026-07-14  kilo
#   - Created Beam Cloud batch runner for FVG crypto backtests.
#   - Handler accepts symbol/style/asset/balance/risk as function arguments so
#     they are forwarded to the remote container by the Beam SDK.
#   - Writes a JSON result file back to the fvg-data volume under results/beam/.
# WHY: Offload long-running (~2.5-3h/symbol) BTC/ETH/SOL FVG backtests to Beam
#      CPU workers while keeping strategy logic untouched.

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from beam import Image, Volume, function

VOLUME_MOUNT = "/data"


@function(
    name="fvg-crypto-backtest",
    cpu=4,
    memory="16Gi",
    timeout=-1,  # Disable hard timeout; crypto backtests run ~2.5-3h per symbol.
    headless=True,  # Keep running if the local CLI disconnects.
    image=Image(python_packages=["tzdata"]),
    volumes=[Volume(name="fvg-data", mount_path=VOLUME_MOUNT)],
)
def run_symbol(
    symbol: str = "BTC",
    style: str = "swing",
    asset: str = "index",
    balance: float = 50000.0,
    risk: str = "aggressive",
) -> dict:
    """Run one FVG backtest for the given symbol."""
    symbol = symbol.upper()
    data_dir = Path(VOLUME_MOUNT) / symbol
    results_dir = Path(VOLUME_MOUNT) / "results" / "beam"
    results_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{symbol}] Starting FVG backtest", flush=True)
    print(f"  data_dir={data_dir}", flush=True)
    print(f"  results_dir={results_dir}", flush=True)
    print(f"  style={style} asset={asset} balance={balance} risk={risk}", flush=True)

    try:
        # Local engine modules are available because beam run syncs the working dir.
        from backtest import run_backtest as engine_run_backtest
        from models import AssetClass, RiskMode, TradeStyle

        start = time.monotonic()
        result = engine_run_backtest(
            data_dir=data_dir,
            style=TradeStyle(style),
            asset=AssetClass(asset),
            balance=balance,
            mode=RiskMode(risk),
        )
        elapsed = time.monotonic() - start

        output = {
            "symbol": symbol,
            "style": style,
            "asset": asset,
            "balance": balance,
            "risk": risk,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "stats": result.stats,
            "trades": result.trades,
            "equity_curve": result.equity_curve,
        }

        out_path = results_dir / f"{symbol}.json"
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2, default=str)

        print(f"[{symbol}] Backtest complete in {elapsed:.1f}s", flush=True)
        print(f"[{symbol}] Results written to {out_path}", flush=True)
        print(f"[{symbol}] Stats: {result.stats}", flush=True)
        return output

    except Exception as exc:
        # Write an error artifact so we can diagnose failures without streaming logs.
        error_path = results_dir / f"{symbol}_ERROR.json"
        error_payload = {
            "symbol": symbol,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        with open(error_path, "w") as f:
            json.dump(error_payload, f, indent=2, default=str)
        print(f"[{symbol}] FAILED: {exc}", file=sys.stderr, flush=True)
        traceback.print_exc()
        raise


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--style", default="swing")
    parser.add_argument("--asset", default="index")
    parser.add_argument("--balance", type=float, default=50000.0)
    parser.add_argument("--risk", default="aggressive")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    run_symbol(**vars(args))
