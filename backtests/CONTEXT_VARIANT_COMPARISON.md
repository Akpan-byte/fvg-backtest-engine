# Context Variant Comparison: ES / NQ / YM

Tests compare three context-timeframe configurations across futures symbols.

## 6-Month Window (Mar–Sep 2019) — ES Only

| Variant | Trades | Win Rate | Net Profit | Max Losing Streak | Avg R |
|---------|--------|----------|------------|-------------------|-------|
| Full Context (M,W,D,H4) | 42 | 83.3% | $305,000 | 2 | 1.45 |
| D Only | 34 | 76.5% | $210,000 | 2 | 1.24 |
| H4 Only | 36 | 69.4% | $185,000 | 3 | 1.03 |

**Observation:** Full context dominated this period. Stripping higher timeframes reduced trade count and quality.

## 1-Year Window (2022) — ES / NQ / YM

### ES

| Variant | Trades | Win Rate | Net Profit | Max Losing Streak | Avg R |
|---------|--------|----------|------------|-------------------|-------|
| Full Context (M,W,D,H4) | 83 | 67.5% | $425,000 | 2 | 1.02 |
| D Only | 71 | 73.2% | $410,000 | 2 | 1.15 |
| H4 Only | 85 | 70.6% | $470,000 | 2 | 1.11 |

### NQ

| Variant | Trades | Win Rate | Net Profit | Max Losing Streak | Avg R |
|---------|--------|----------|------------|-------------------|-------|
| Full Context (M,W,D,H4) | 58 | 70.7% | $320,000 | 2 | 1.10 |
| D Only | 71 | 67.6% | $360,000 | 3 | 1.01 |
| H4 Only | 80 | 62.5% | $350,000 | 5 | 0.88 |

### YM

| Variant | Trades | Win Rate | Net Profit | Max Losing Streak | Avg R |
|---------|--------|----------|------------|-------------------|-------|
| Full Context (M,W,D,H4) | 71 | 74.6% | $430,000 | 4 | 1.21 |
| D Only | 52 | 76.9% | $330,000 | 2 | 1.27 |
| H4 Only | 78 | 69.2% | $405,000 | 4 | 1.04 |

### Combined ES + NQ + YM

| Variant | Total Trades | Total Profit | Avg Win Rate |
|---------|--------------|--------------|--------------|
| Full Context (M,W,D,H4) | 212 | $1,175,000 | 70.9% |
| D Only | 194 | $1,100,000 | 72.6% |
| H4 Only | 243 | $1,225,000 | 67.4% |

**Observation (2022):**
- H4 Only produced the most trades (243) and the highest total profit ($1,225,000).
- However, H4 Only had the lowest win rate (67.4%) and the longest losing streak (5 on NQ).
- Full Context gave a strong balance: 212 trades, $1,175,000 profit, 70.9% win rate.
- D Only had the highest win rate (72.6%) but the fewest trades and lowest total profit.

## 1-Year Window (2024) — Bull Year — ES / NQ / YM

### ES (2024)

| Variant | Trades | Win Rate | Net Profit | Max Losing Streak | Avg R |
|---------|--------|----------|------------|-------------------|-------|
| Full Context (M,W,D,H4) | 84 | 52.4% | $235,000 | 8 | 0.56 |
| D Only | 80 | 63.7% | $350,000 | 4 | 0.88 |
| H4 Only | 76 | 63.2% | $325,000 | 8 | 0.86 |

### NQ (2024)

| Variant | Trades | Win Rate | Net Profit | Max Losing Streak | Avg R |
|---------|--------|----------|------------|-------------------|-------|
| Full Context (M,W,D,H4) | 48 | 64.6% | $220,000 | 3 | 0.92 |
| D Only | 79 | 65.8% | $375,000 | 3 | 0.95 |
| H4 Only | 76 | 63.2% | $340,000 | 3 | 0.89 |

### YM (2024)

| Variant | Trades | Win Rate | Net Profit | Max Losing Streak | Avg R |
|---------|--------|----------|------------|-------------------|-------|
| Full Context (M,W,D,H4) | 54 | 68.5% | $280,000 | 2 | 1.04 |
| D Only | 54 | 72.2% | $300,000 | 2 | 1.11 |
| H4 Only | 69 | 65.2% | $320,000 | 3 | 0.93 |

### Combined ES + NQ + YM (2024)

| Variant | Total Trades | Total Profit | Avg Win Rate |
|---------|--------------|--------------|--------------|
| Full Context (M,W,D,H4) | 186 | $735,000 | 61.8% |
| D Only | 213 | $1,025,000 | 67.3% |
| H4 Only | 221 | $985,000 | 63.8% |

**Observation (2024 bull year):**
- D Only was the strongest overall: 213 trades, $1,025,000 profit, 67.3% win rate.
- H4 Only had the most trades (221) and nearly matched D Only in profit ($985,000).
- Full Context significantly underperformed: only 186 trades, $735,000 profit, and a rough 8-loss streak on ES.
- In a strong bull market, requiring Monthly/Weekly alignment appears to filter out too many valid trending setups.

## Regime Comparison Summary

| Year | Regime | Best Variant | Total Trades | Total Profit | Avg Win Rate |
|------|--------|--------------|--------------|--------------|--------------|
| 2022 | Bear/Volatile | H4 Only | 243 | $1,225,000 | 67.4% |
| 2024 | Bull | D Only | 213 | $1,025,000 | 67.3% |

## Implications for Prop Firm Trading

If the priority is **consistency and passing drawdown rules**, Full Context or D Only are safer:
- Higher win rates
- Shorter losing streaks
- More predictable daily PnL

If the priority is **raw trade frequency and total profit**, H4 Only wins on this 2022 sample,
but at the cost of more volatility and deeper losing streaks.

## Caveats

- 2022 was a bearish, volatile year for equity indices; results may differ in bull or chop regimes.
- Only one 1-year period was tested. A multi-year scan would strengthen conclusions.
- All tests used aggressive sizing ($5k risk on $50k account). Prop-firm sizing (1–2% risk) would scale profits and drawdowns proportionally.