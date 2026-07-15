# FVG Strategy Backtest Report

Generated: 2026-07-15 20:57 UTC

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
| ES | 549 | 386 | 163 | 70.3% | $2,940,000 | $2,990,000 | 4 | 1.07 |
| NQ | 522 | 374 | 148 | 71.6% | $2,965,000 | $3,015,000 | 4 | 1.14 |
| YM | 564 | 389 | 175 | 69.0% | $2,920,000 | $2,970,000 | 4 | 1.04 |
| GC | 192 | 110 | 82 | 57.3% | $635,000 | $685,000 | 10 | 0.66 |
| SI | 80 | 43 | 37 | 53.8% | $230,000 | $280,000 | 5 | 0.57 |
| BTC | 120 | 88 | 32 | 73.3% | $705,000 | $755,000 | 4 | 1.18 |
| ETH | 137 | 95 | 42 | 69.3% | $725,000 | $775,000 | 3 | 1.06 |
| SOL | 135 | 97 | 38 | 71.9% | $780,000 | $830,000 | 3 | 1.16 |
| **TOTAL** | **2,299** | | | | **$11,900,000** | | | |

## Symbol Notes

- **Futures (ES, NQ, YM)**: ~10 years of data (May 2016 – May 2026). Split into 3 date-range chunks per symbol on GitHub Actions to fit within the 6-hour job timeout, then audited with overlapping 6-month bridge chunks across each boundary to recover trades that spanned chunk cuts.
- **Commodities (GC, SI)**: ~10 years of data. Completed in single runs.
- **Crypto (BTC, ETH, SOL)**: ~2 years of data (June 2024 – June 2026). Single runs.

## Key Observations

- Every symbol was profitable.
- Win rates ranged from 53.8% (SI) to 73.3% (BTC).
- Avg R multiples were positive across the board, with futures and crypto clustering around 1.0–1.2R.
- Max losing streaks were 4–10 trades; the aggressive $5k risk model survived all of them.

## Boundary Audit / Caveats

- **Futures bridge re-test**: Overlapping 6-month bridge chunks were run across the two chunk boundaries per futures symbol (2019-06-01 and 2022-12-01). The bridge runs recovered additional boundary-spanning trades:
  - ES: +27 trades, +$195,000
  - NQ: +18 trades, +$70,000
  - YM: +33 trades, +$225,000
  - Total futures net profit increased from $8,335,000 to $8,825,000.
- **ETH discrepancy**: Two additional ETH runs produced different trade counts:
  - Modal ETH: 137 trades, 69.3% win, +$725k (same as GitHub Actions).
  - Beam ETH: 175 trades, 64.0% win, +$775k.
  The GitHub Actions ETH result is used as the canonical result because the entire matrix was run with identical code and environment.
- Crypto data only spans ~2 years, so those results are not directly comparable to the 10-year futures/commodity backtests.

## Compute Used

- Modal: initial runs (stopped at 83% credit usage).
- Lightning AI: attempted but failed due to studio auto-stop/sleep issues.
- Beam Cloud: completed ETH before credits ran out.
- GitHub Actions: final matrix used for the canonical results above; bridge chunks used to audit futures boundaries.
