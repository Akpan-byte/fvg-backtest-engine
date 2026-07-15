# ES Context Variant Comparison

Period: 2019-03-01 to 2019-09-01 (6 months)
Symbol: ES
Style: swing, asset: index, risk: aggressive ($5k/trade)

| Variant | Trades | Win Rate | Net Profit | Max Losing Streak | Avg R |
|---------|--------|----------|------------|-------------------|-------|
| Full Context (M,W,D,H4) | 42 | 83.3% | $305,000 | 2 | 1.45 |
| H4 Only | 36 | 69.4% | $185,000 | 3 | 1.03 |
| D Only | 34 | 76.5% | $210,000 | 2 | 1.24 |

## Observations

- Full context (M/W/D/H4) produced the most trades and the highest win rate on this 6-month sample.
- H4-only context produced fewer trades and a significantly lower win rate (69.4% vs 83.3%).
- D-only context sat in the middle, still underperforming full context.
- Limiting context did **not** increase trade frequency in this period; it removed higher-timeframe bias that was filtering out lower-probability setups.

## Caveat

This is a single 6-month window. A full 10-year comparison across ES/NQ/YM would be needed for a definitive conclusion.