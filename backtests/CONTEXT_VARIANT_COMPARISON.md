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