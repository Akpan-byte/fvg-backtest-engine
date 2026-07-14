#!/usr/bin/env python3
"""Poll Modal results volume and download new result files."""
import json, os, subprocess, sys, time
from pathlib import Path

res_vol = "fvg-backtest-results"
local_dir = Path("/config/fvg_execution_engine/backtests/results")
local_dir.mkdir(exist_ok=True)

def list_remote():
    try:
        out = subprocess.check_output(["modal", "volume", "ls", res_vol], text=True, timeout=30)
        files = [line.strip() for line in out.splitlines() if line.strip().endswith(".json")]
        return files
    except Exception as e:
        print(f"list error: {e}")
        return []

def download(fname):
    local = local_dir / fname
    if local.exists():
        return False
    try:
        subprocess.run(["modal", "volume", "get", res_vol, f"/{fname}", str(local)],
                       check=True, text=True, timeout=60)
        print(f"Downloaded {fname}")
        return True
    except Exception as e:
        print(f"download error for {fname}: {e}")
        return False

if __name__ == "__main__":
    files = list_remote()
    print(f"Remote files: {files}")
    for f in files:
        download(f)
