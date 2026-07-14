# CHANGE_SUMMARY
# 2026-07-14  kilo
#   - Created download_lightning_results.py: polls the three Lightning AI
#     backtest jobs and downloads their JSON results once they complete.
# WHY: The jobs run for ~8-10 hours each, so a reusable downloader avoids
#      hand-copying files from the Lightning Studio after they finish.

#!/usr/bin/env python3
"""Poll Lightning AI jobs and download FVG backtest results when complete.

Usage:
    source /config/backtest/venv/bin/activate
    LIGHTNING_USER_ID=720edfd1-7894-4713-a8c2-f03edd57a2da \
    LIGHTNING_API_KEY=b9c2d04e-7980-476d-81e1-21908d22a1db \
    LIGHTNING_USERNAME=theakpanobong \
    python3 /config/fvg_execution_engine/download_lightning_results.py

The script polls the three jobs launched for ES/NQ/YM, downloads their JSON
result files once they succeed, and writes them to:
    /config/fvg_execution_engine/backtests/results/lightning/
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from lightning_sdk import Job, Studio, User

TEAMSPACE = "theakpanobong/deploy-model-project"
STUDIO_NAME = "fvg-backtest-studio"
RESULTS_REMOTE = "fvg_execution_engine/backtests/results/lightning"
RESULTS_LOCAL = Path("/config/fvg_execution_engine/backtests/results/lightning")
JOBS = {
    "ES": "fvg-bt-es-20260714",
    "NQ": "fvg-bt-nq-20260714",
    "YM": "fvg-bt-ym-20260714",
}
POLL_INTERVAL_SECONDS = 300  # 5 minutes


def main() -> int:
    user = User()
    teamspace = next(t for t in user.teamspaces if t.name == "deploy-model-project")
    studio = Studio(name=STUDIO_NAME, teamspace=teamspace, create_ok=False)
    RESULTS_LOCAL.mkdir(parents=True, exist_ok=True)

    pending = dict(JOBS)
    print(f"Polling {len(pending)} jobs every {POLL_INTERVAL_SECONDS // 60} minutes...")

    while pending:
        for sym, name in list(pending.items()):
            job = Job(name=name, teamspace=teamspace, _fetch_job=True)
            print(f"{name}: {job.status}")

            if str(job.status).lower() in {"succeeded", "success", "completed"}:
                remote_file = f"{RESULTS_REMOTE}/{sym}_result.json"
                local_file = RESULTS_LOCAL / f"{sym}_result.json"
                print(f"  -> Downloading {remote_file} to {local_file}")
                studio.download_file(remote_file, str(local_file))
                pending.pop(sym)
            elif str(job.status).lower() in {"failed", "stopped", "canceled"}:
                print(f"  -> Job {name} ended with status {job.status}; not downloading.")
                pending.pop(sym)

        if pending:
            time.sleep(POLL_INTERVAL_SECONDS)

    print("Done. Downloaded results:")
    for f in sorted(RESULTS_LOCAL.glob("*_result.json")):
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
