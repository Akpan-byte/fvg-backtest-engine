# FVG Strategy Backtest Report

Generated: 2026-07-15 18:35 UTC

## Setup

- Style: swing
- Asset class: index (applied to futures, commodities, and crypto)
- Starting balance: $50,000
- Risk mode: aggressive ($5,000 fixed risk per trade)
- Risk:Reward: 1:2 (target 2R on every trade)
- Data: 1m OHLCV replayed chronologically across multiple timeframes
- Engine: ICT multi-timeframe FVG strategy (context → HTF PDA → LTF 2nd leg → 2R exit)

## Results Summary

| Symbol | Trades | Wins | Losses | Win Rate | Net Profit | Final Balance | Max Loss Run | Avg R |
|--------|--------|------|--------|----------|------------|---------------|--------------|-------|
| ES | 522 | 364 | 158 | 69.7% | $2,745,000 | $2,795,000 | 4 | 1.05 |
| NQ | 504 | 363 | 141 | 72.0% | $2,895,000 | $2,945,000 | 4 | 1.15 |
| YM | 531 | 363 | 168 | 68.4% | $2,695,000 | $2,745,000 | 4 | 1.02 |
| GC | 192 | 110 | 82 | 57.3% | $635,000 | $685,000 | 10 | 0.66 |
| SI | 80 | 43 | 37 | 53.8% | $230,000 | $280,000 | 5 | 0.57 |
| BTC | 120 | 88 | 32 | 73.3% | $705,000 | $755,000 | 4 | 1.18 |
| ETH | 137 | 95 | 42 | 69.3% | $725,000 | $775,000 | 3 | 1.06 |
| SOL | 135 | 97 | 38 | 71.9% | $780,000 | $830,000 | 3 | 1.16 |
| **TOTAL** | **2221** | | | | **$11,410,000** | | | |

## Symbol Notes

- **Futures (ES, NQ, YM)**: ~10 years of data (May 2016 – May 2026). Split into 3 date-range chunks per symbol on GitHub Actions to fit within the 6-hour job timeout.
- **Commodities (GC, SI)**: ~10 years of data. Completed in single runs.
- **Crypto (BTC, ETH, SOL)**: ~2 years of data (June 2024 – June 2026). Single runs.

## Key Observations

- Every symbol was profitable.
- Win rates ranged from 53.8% (SI) to 73.3% (BTC).
- Avg R multiples were positive across the board, with futures and crypto clustering around 1.0–1.2R.
- Max losing streaks were 4–10 trades; the aggressive $5k risk model survived all of them.

## Audit Notes / Caveats

- **ETH discrepancy**: Two additional ETH runs produced different trade counts:
  - Modal ETH: 137 trades, 69.3% win, +$725k (same as GitHub Actions).
  - Beam ETH: 175 trades, 64.0% win, +$775k.
  The GitHub Actions ETH result is used as the canonical result because the entire matrix was run with identical code and environment.
- Futures were chunked by date; a small number of trades near chunk boundaries may have been missed due to incomplete HTF context at the start of each chunk.
- Crypto data only spans ~2 years, so those results are not directly comparable to the 10-year futures/commodity backtests.

## Compute Used

- Modal: initial runs (stopped at 83% credit usage).
- Lightning AI: attempted but failed due to studio auto-stop/sleep issues.
- Beam Cloud: completed ETH before credits ran out.
- GitHub Actions: final matrix used for the canonical results above.
