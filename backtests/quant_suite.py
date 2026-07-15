#!/usr/bin/env python3
"""Full quant suite for FVG backtest results.

Computes risk/return metrics, drawdowns, trade statistics, regression fits,
Probabilistic Sharpe Ratio (PSR), Deflated Sharpe Ratio (DSR), Markov
transition matrix, Bayesian Sharpe, and Brownian motion tests.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from numpy.polynomial import polynomial as P

RESULTS_DIR = Path(__file__).parent / "results" / "github"
REPORT_FILE = Path(__file__).parent / "QUANT_REPORT_FUTURES.md"
CSV_FILE = Path(__file__).parent / "QUANT_METRICS_FUTURES.csv"
START_BALANCE = 50_000.0


def _load(symbol: str) -> dict[str, Any]:
    path = RESULTS_DIR / f"{symbol}_merged_result.json"
    return json.loads(path.read_text())


def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        return dt
    return dt.replace(tzinfo=None)


def _trade_equity(trades: list[dict]) -> list[tuple[datetime, float]]:
    """Build equity curve at each trade close."""
    equity = START_BALANCE
    curve: list[tuple[datetime, float]] = [(START_BALANCE, START_BALANCE)]
    for t in trades:
        equity += t.get("pnl", 0.0)
        curve.append((_parse_ts(t["exit_time"]), equity))
    return curve


def _daily_equity(trades: list[dict]) -> list[tuple[datetime, float]]:
    """Build end-of-day equity curve from closed trades, filling all calendar days.

    Days with no closed trade are recorded as zero PnL (carry forward). This
    produces a daily return series comparable to a buy-and-hold benchmark.
    """
    daily_pnl: dict[datetime, float] = defaultdict(float)
    for t in trades:
        exit_ts = _parse_ts(t["exit_time"])
        day = datetime(exit_ts.year, exit_ts.month, exit_ts.day)
        daily_pnl[day] += t.get("pnl", 0.0)

    if not daily_pnl:
        return []

    start_day = min(daily_pnl.keys())
    end_day = max(daily_pnl.keys())
    equity = START_BALANCE
    curve: list[tuple[datetime, float]] = []
    day = start_day
    while day <= end_day:
        equity += daily_pnl.get(day, 0.0)
        curve.append((day, equity))
        day += timedelta(days=1)
    return curve


def _returns_from_equity(equity: list[tuple[datetime, float]]) -> list[float]:
    if len(equity) < 2:
        return []
    return [(equity[i][1] - equity[i - 1][1]) / equity[i - 1][1] for i in range(1, len(equity))]


def _drawdown_series(equity: list[tuple[datetime, float]]) -> tuple[list[tuple[datetime, float]], list[tuple[datetime, datetime, float, float]]]:
    """Return (dd_series, periods) where each period is (peak_date, trough_date, dd_pct, recovery_value)."""
    if not equity:
        return [], []

    peak = equity[0][1]
    peak_date = equity[0][0]
    min_since_peak = peak
    trough_date = peak_date
    dd_series: list[tuple[datetime, float]] = []
    periods: list[tuple[datetime, datetime, float, float]] = []

    for date, val in equity:
        if val > peak:
            if peak - min_since_peak > 0:
                periods.append((peak_date, trough_date, (peak - min_since_peak) / peak, min_since_peak))
            peak = val
            peak_date = date
            min_since_peak = val
            trough_date = date
        elif val < min_since_peak:
            min_since_peak = val
            trough_date = date
        dd = (peak - val) / peak
        dd_series.append((date, dd))

    # Close last period if in drawdown
    if peak - min_since_peak > 0:
        periods.append((peak_date, trough_date, (peak - min_since_peak) / peak, min_since_peak))

    return dd_series, periods


def _drawdown_stats(equity: list[tuple[datetime, float]]) -> dict[str, Any]:
    dd_series, periods = _drawdown_series(equity)
    if not periods:
        return {
            "max_drawdown": 0.0,
            "max_drawdown_pct": 0.0,
            "max_dd_peak_date": None,
            "max_dd_trough_date": None,
            "max_dd_duration": 0,
            "avg_drawdown": 0.0,
            "avg_drawdown_pct": 0.0,
            "drawdown_count": 0,
        }

    max_period = max(periods, key=lambda p: p[2])
    dds = [p[2] for p in periods]
    durations = [(p[1] - p[0]).days for p in periods]

    return {
        "max_drawdown": max_period[3],
        "max_drawdown_pct": max_period[2] * 100,
        "max_dd_peak_date": max_period[0].date().isoformat(),
        "max_dd_trough_date": max_period[1].date().isoformat(),
        "max_dd_duration": max(durations),
        "avg_drawdown": max_period[3],  # placeholder, see below
        "avg_drawdown_pct": statistics.mean(dds) * 100,
        "drawdown_count": len(periods),
    }


def _start_to_bottom(equity: list[tuple[datetime, float]]) -> dict[str, Any]:
    """Measure worst drop from start-of-period (open) to period low (bottom).

    With daily equity, each point is the close. We treat the previous close as
    the period open and the current close as the period bottom when it is lower.
    """
    if len(equity) < 2:
        return {"worst_start_to_bottom": 0.0, "worst_start_to_bottom_pct": 0.0}

    worst = 0.0
    worst_pct = 0.0
    for i in range(1, len(equity)):
        open_val = equity[i - 1][1]
        low_val = equity[i][1]
        if low_val < open_val:
            drop = open_val - low_val
            drop_pct = drop / open_val
            if drop_pct > worst_pct:
                worst_pct = drop_pct
                worst = drop
    return {"worst_start_to_bottom": worst, "worst_start_to_bottom_pct": worst_pct * 100}


def _sharpe(returns: list[float], risk_free: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    mean = statistics.mean(returns) - risk_free
    std = statistics.stdev(returns)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(252)


def _sortino(returns: list[float], risk_free: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    mean = statistics.mean(returns) - risk_free
    downside = [r for r in returns if r < 0]
    if not downside:
        return float("inf") if mean > 0 else 0.0
    downside_std = math.sqrt(sum((r - statistics.mean(downside)) ** 2 for r in downside) / len(downside))
    if downside_std == 0:
        return 0.0
    return (mean / downside_std) * math.sqrt(252)


def _probabilistic_sharpe_ratio(returns: list[float], benchmark_sr: float = 0.0) -> float:
    """PSR per Bailey & Lopez de Prado (2012)."""
    n = len(returns)
    if n < 4:
        return 0.0
    sr = _sharpe(returns) / math.sqrt(252)  # daily SR
    std = statistics.stdev(returns)
    if std == 0:
        return 0.0
    skew, kurt = _skew_kurt(returns)
    var = (1 - skew * sr + (kurt - 1) / 4 * sr ** 2) / (n - 1)
    if var <= 0:
        return 0.5
    z = (sr - benchmark_sr) * math.sqrt(n - 1) / math.sqrt(var)
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _deflated_sharpe_ratio(returns: list[float], trials: int) -> float:
    """DSR per Lopez de Prado (2019).

    Approximate correction for multiple trials / selection bias.
    """
    n = len(returns)
    if n < 4:
        return 0.0
    sr = _sharpe(returns) / math.sqrt(252)
    skew, kurt = _skew_kurt(returns)
    # Expected max SR under null for N independent trials
    if trials <= 1:
        return sr * math.sqrt(252)
    var0 = (1 - skew * 0 + (kurt - 1) / 4 * 0) / (n - 1)
    if var0 <= 0:
        return sr * math.sqrt(252)
    # Euler-Mascheroni constant
    gamma = 0.5772156649
    expected_max = math.sqrt(var0) * ((1 - gamma) * scipy_norm_ppf(1 - 1 / trials) + gamma * scipy_norm_ppf(1 - 1 / (trials * math.e)))
    z = (sr - expected_max) * math.sqrt(n - 1) / math.sqrt(var0)
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def scipy_norm_ppf(p: float) -> float:
    """Approximate inverse CDF of standard normal (Abramowitz & Stegun)."""
    if p <= 0:
        return -10.0
    if p >= 1:
        return 10.0
    # Rational approximation for inverse error function
    a = -math.sqrt(2) * _inverse_erf(2 * (1 - p))
    return -a if p < 0.5 else math.sqrt(2) * _inverse_erf(2 * p - 1)


def _inverse_erf(x: float) -> float:
    """Approximate inverse error function."""
    sign = 1 if x >= 0 else -1
    x = abs(x)
    a = 8 * (math.pi - 3) / (4 - math.pi)
    y = math.log(1 - x * x)
    z = 2 / (math.pi * a) + y / 2
    return sign * math.sqrt(math.sqrt(z * z - y / a) - z)


def _bayesian_sharpe(returns: list[float]) -> dict[str, float]:
    """Bayesian estimate of Sharpe ratio with posterior mean and 95% CI.

    Uses a simple normal-inverse-gamma posterior for daily returns.
    """
    n = len(returns)
    if n < 4:
        return {"bayesian_sharpe_mean": 0.0, "bayesian_sharpe_lower": 0.0, "bayesian_sharpe_upper": 0.0}
    mean = statistics.mean(returns)
    var = statistics.variance(returns)
    if var == 0:
        return {"bayesian_sharpe_mean": 0.0, "bayesian_sharpe_lower": 0.0, "bayesian_sharpe_upper": 0.0}
    # Posterior for variance ~ Inv-Gamma((n-1)/2, (n-1)*var/2)
    # Posterior predictive standard deviation
    sd_post = math.sqrt(var * (n - 1) / (n - 3))
    # Posterior mean of mu is sample mean; uncertainty in mu
    se_mean = sd_post / math.sqrt(n)
    # 95% CI for daily mean
    t_975 = 1.96 if n > 30 else 2.776 if n > 5 else 3.182
    mean_lower = mean - t_975 * se_mean
    mean_upper = mean + t_975 * se_mean
    sr_mean = (mean / sd_post) * math.sqrt(252)
    sr_lower = (mean_lower / sd_post) * math.sqrt(252)
    sr_upper = (mean_upper / sd_post) * math.sqrt(252)
    return {
        "bayesian_sharpe_mean": sr_mean,
        "bayesian_sharpe_lower": sr_lower,
        "bayesian_sharpe_upper": sr_upper,
    }


def _markov_transition_matrix(returns: list[float]) -> dict[str, Any]:
    """First-order Markov transition matrix for daily returns sign."""
    if len(returns) < 3:
        return {"up_up": 0.0, "up_down": 0.0, "down_up": 0.0, "down_down": 0.0}
    signs = [1 if r >= 0 else 0 for r in returns]
    counts = defaultdict(int)
    for i in range(1, len(signs)):
        counts[(signs[i - 1], signs[i])] += 1

    up_total = counts[(1, 1)] + counts[(1, 0)]
    down_total = counts[(0, 1)] + counts[(0, 0)]
    return {
        "up_up": counts[(1, 1)] / up_total if up_total else 0.0,
        "up_down": counts[(1, 0)] / up_total if up_total else 0.0,
        "down_up": counts[(0, 1)] / down_total if down_total else 0.0,
        "down_down": counts[(0, 0)] / down_total if down_total else 0.0,
    }


def _runs_test(returns: list[float]) -> dict[str, float]:
    """Brownian motion / random walk test via Wald-Wolfowitz runs test."""
    n = len(returns)
    if n < 10:
        return {"runs_statistic": 0.0, "runs_pvalue": 1.0}
    signs = [1 if r >= 0 else 0 for r in returns]
    n1 = sum(signs)
    n0 = n - n1
    if n1 == 0 or n0 == 0:
        return {"runs_statistic": 0.0, "runs_pvalue": 1.0}

    runs = 1
    for i in range(1, n):
        if signs[i] != signs[i - 1]:
            runs += 1

    expected = 1 + 2 * n1 * n0 / n
    var = 2 * n1 * n0 * (2 * n1 * n0 - n) / (n * n * (n - 1))
    if var <= 0:
        return {"runs_statistic": 0.0, "runs_pvalue": 1.0}
    z = (runs - expected) / math.sqrt(var)
    pvalue = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return {"runs_statistic": z, "runs_pvalue": pvalue}


def _var(returns: list[float], level: float = 0.05) -> float:
    if not returns:
        return 0.0
    sorted_r = sorted(returns)
    idx = int(level * len(sorted_r))
    idx = max(0, min(idx, len(sorted_r) - 1))
    return sorted_r[idx]


def _expected_shortfall(returns: list[float], level: float = 0.05) -> float:
    if not returns:
        return 0.0
    var = _var(returns, level)
    tail = [r for r in returns if r <= var]
    if not tail:
        return var
    return statistics.mean(tail)


def _skew_kurt(returns: list[float]) -> tuple[float, float]:
    n = len(returns)
    if n < 3:
        return 0.0, 0.0
    mean = statistics.mean(returns)
    std = statistics.stdev(returns)
    if std == 0:
        return 0.0, 0.0
    skew = (sum((r - mean) ** 3 for r in returns) / n) / (std ** 3)
    kurt = (sum((r - mean) ** 4 for r in returns) / n) / (std ** 4) - 3
    return skew, kurt


def _regressions(equity: list[tuple[datetime, float]]) -> dict[str, Any]:
    """Fit linear, quadratic, cubic, exponential, and polynomial regressions to equity curve."""
    if len(equity) < 5:
        return {}
    x = np.arange(len(equity))
    y = np.array([e[1] for e in equity])

    # Linear
    lin = np.polyfit(x, y, 1)
    lin_pred = np.polyval(lin, x)
    lin_r2 = 1 - np.sum((y - lin_pred) ** 2) / np.sum((y - np.mean(y)) ** 2)

    # Quadratic
    quad = np.polyfit(x, y, 2)
    quad_pred = np.polyval(quad, x)
    quad_r2 = 1 - np.sum((y - quad_pred) ** 2) / np.sum((y - np.mean(y)) ** 2)

    # Cubic
    cubic = np.polyfit(x, y, 3)
    cubic_pred = np.polyval(cubic, x)
    cubic_r2 = 1 - np.sum((y - cubic_pred) ** 2) / np.sum((y - np.mean(y)) ** 2)

    # Exponential: fit y = a * exp(b*x)
    log_y = np.log(y)
    exp_fit = np.polyfit(x, log_y, 1)
    a = math.exp(exp_fit[1])
    b = exp_fit[0]
    exp_pred = a * np.exp(b * x)
    exp_r2 = 1 - np.sum((y - exp_pred) ** 2) / np.sum((y - np.mean(y)) ** 2)

    # Polynomial degree 5
    poly5 = np.polyfit(x, y, 5)
    poly5_pred = np.polyval(poly5, x)
    poly5_r2 = 1 - np.sum((y - poly5_pred) ** 2) / np.sum((y - np.mean(y)) ** 2)

    return {
        "linear_slope": lin[0],
        "linear_intercept": lin[1],
        "linear_r2": lin_r2,
        "quad_a": quad[0],
        "quad_b": quad[1],
        "quad_c": quad[2],
        "quad_r2": quad_r2,
        "cubic_a": cubic[0],
        "cubic_b": cubic[1],
        "cubic_c": cubic[2],
        "cubic_d": cubic[3],
        "cubic_r2": cubic_r2,
        "exp_a": a,
        "exp_b": b,
        "exp_r2": exp_r2,
        "poly5_r2": poly5_r2,
    }


def _trade_durations(trades: list[dict]) -> list[float]:
    durations: list[float] = []
    for t in trades:
        entry = _parse_ts(t["entry_time"])
        exit_ = _parse_ts(t["exit_time"])
        durations.append((exit_ - entry).total_seconds() / 3600.0)
    return durations


def _monthly_returns(trades: list[dict]) -> dict[tuple[int, int], float]:
    monthly_pnl: dict[tuple[int, int], float] = defaultdict(float)
    for t in trades:
        exit_ts = _parse_ts(t["exit_time"])
        monthly_pnl[(exit_ts.year, exit_ts.month)] += t.get("pnl", 0.0)

    months = sorted(monthly_pnl.keys())
    if not months:
        return {}

    start_eq = START_BALANCE
    monthly_ret: dict[tuple[int, int], float] = {}
    for m in months:
        pnl = monthly_pnl[m]
        ret = pnl / start_eq
        monthly_ret[m] = ret
        start_eq += pnl
    return monthly_ret


def analyze_symbol(symbol: str) -> dict[str, Any]:
    data = _load(symbol)
    trades = sorted(data.get("trades", []), key=lambda t: t["entry_time"])

    wins = [t for t in trades if t.get("result") == "win"]
    losses = [t for t in trades if t.get("result") == "loss"]

    total_pnl = sum(t.get("pnl", 0.0) for t in trades)
    gross_profit = sum(t.get("pnl", 0.0) for t in wins)
    gross_loss = abs(sum(t.get("pnl", 0.0) for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss else float("inf")

    avg_trade = total_pnl / len(trades) if trades else 0.0
    avg_win = statistics.mean([t.get("pnl", 0.0) for t in wins]) if wins else 0.0
    avg_loss = statistics.mean([t.get("pnl", 0.0) for t in losses]) if losses else 0.0
    win_loss_ratio = abs(avg_win / avg_loss) if avg_loss else float("inf")

    r_values = [t.get("r_multiple", 0.0) for t in trades]
    avg_r = statistics.mean(r_values) if r_values else 0.0
    r_std = statistics.stdev(r_values) if len(r_values) > 1 else 0.0

    trade_equity = _trade_equity(trades)
    daily_equity = _daily_equity(trades)
    daily_returns = _returns_from_equity(daily_equity)

    dd_stats = _drawdown_stats(daily_equity)
    start_to_bottom = _start_to_bottom(daily_equity)

    sharpe = _sharpe(daily_returns)
    sortino = _sortino(daily_returns)
    vol = statistics.stdev(daily_returns) * math.sqrt(252) if len(daily_returns) > 1 else 0.0
    years = (daily_equity[-1][0] - daily_equity[0][0]).days / 365.25 if len(daily_equity) > 1 else 1.0
    cagr = ((daily_equity[-1][1] / START_BALANCE) ** (1 / years) - 1) if years > 0 and daily_equity else 0.0
    calmar = cagr / (dd_stats["max_drawdown_pct"] / 100) if dd_stats["max_drawdown_pct"] else 0.0

    psr = _probabilistic_sharpe_ratio(daily_returns)
    dsr = _deflated_sharpe_ratio(daily_returns, trials=100)
    bayes = _bayesian_sharpe(daily_returns)
    markov = _markov_transition_matrix(daily_returns)
    runs = _runs_test(daily_returns)

    var95 = _var(daily_returns, 0.05)
    var99 = _var(daily_returns, 0.01)
    es95 = _expected_shortfall(daily_returns, 0.05)
    skew, kurt = _skew_kurt(daily_returns)

    # Trade-level return distribution (PnL / fixed account size).
    trade_returns = [t.get("pnl", 0.0) / START_BALANCE for t in trades]
    trade_sharpe = (statistics.mean(trade_returns) / statistics.stdev(trade_returns) * math.sqrt(len(trade_returns))) if len(trade_returns) > 1 and statistics.stdev(trade_returns) else 0.0
    trade_var95 = _var(trade_returns, 0.05)
    trade_var99 = _var(trade_returns, 0.01)
    trade_es95 = _expected_shortfall(trade_returns, 0.05)
    trade_skew, trade_kurt = _skew_kurt(trade_returns)

    durations = _trade_durations(trades)
    avg_duration = statistics.mean(durations) if durations else 0.0
    median_duration = statistics.median(durations) if durations else 0.0

    max_win = max((t.get("pnl", 0.0) for t in wins), default=0.0)
    max_loss = min((t.get("pnl", 0.0) for t in losses), default=0.0)

    streaks: dict[str, list[int]] = {"win": [], "loss": []}
    current_kind = None
    current_len = 0
    for t in trades:
        kind = t.get("result")
        if kind == current_kind:
            current_len += 1
        else:
            if current_kind and current_len:
                streaks[current_kind].append(current_len)
            current_kind = kind
            current_len = 1
    if current_kind and current_len:
        streaks[current_kind].append(current_len)

    monthly_ret = _monthly_returns(trades)
    positive_months = sum(1 for r in monthly_ret.values() if r > 0)
    negative_months = sum(1 for r in monthly_ret.values() if r < 0)

    regressions = _regressions(daily_equity)

    return {
        "symbol": symbol,
        "trades_total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "net_profit": total_pnl,
        "final_balance": START_BALANCE + total_pnl,
        "cagr": cagr,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "avg_trade": avg_trade,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "win_loss_ratio": win_loss_ratio,
        "avg_r": avg_r,
        "r_std": r_std,
        "sharpe": sharpe,
        "sortino": sortino,
        "volatility_annual": vol,
        "calmar": calmar,
        "psr": psr,
        "dsr": dsr,
        "bayesian_sharpe_mean": bayes["bayesian_sharpe_mean"],
        "bayesian_sharpe_lower": bayes["bayesian_sharpe_lower"],
        "bayesian_sharpe_upper": bayes["bayesian_sharpe_upper"],
        "markov_up_up": markov["up_up"],
        "markov_up_down": markov["up_down"],
        "markov_down_up": markov["down_up"],
        "markov_down_down": markov["down_down"],
        "runs_statistic": runs["runs_statistic"],
        "runs_pvalue": runs["runs_pvalue"],
        "var95": var95,
        "var99": var99,
        "expected_shortfall_95": es95,
        "skewness": skew,
        "kurtosis": kurt,
        "trade_sharpe": trade_sharpe,
        "trade_var95": trade_var95,
        "trade_var99": trade_var99,
        "trade_es95": trade_es95,
        "trade_skewness": trade_skew,
        "trade_kurtosis": trade_kurt,
        **dd_stats,
        **start_to_bottom,
        "avg_trade_duration_hrs": avg_duration,
        "median_trade_duration_hrs": median_duration,
        "max_win": max_win,
        "max_loss": max_loss,
        "avg_win_streak": statistics.mean(streaks["win"]) if streaks["win"] else 0.0,
        "max_win_streak": max(streaks["win"], default=0),
        "avg_loss_streak": statistics.mean(streaks["loss"]) if streaks["loss"] else 0.0,
        "max_loss_streak": max(streaks["loss"], default=0),
        "total_months": len(monthly_ret),
        "positive_months": positive_months,
        "negative_months": negative_months,
        "monthly_win_rate": positive_months / len(monthly_ret) if monthly_ret else 0.0,
        "monthly_returns": monthly_ret,
        **regressions,
    }


def build_report(analyses: list[dict[str, Any]]) -> str:
    lines = [
        "# FVG Futures Quant Suite",
        "",
        "Risk/return analytics for the swing futures backtest (ES, NQ, YM).",
        "",
        "## Performance Summary",
        "",
        "| Metric | ES | NQ | YM |",
        "|--------|----|----|----|",
    ]

    summary_rows = [
        ("Trades", "trades_total", "{:.0f}"),
        ("Win Rate", "win_rate", "{:.2%}"),
        ("Net Profit", "net_profit", "${:,.0f}"),
        ("Final Balance", "final_balance", "${:,.0f}"),
        ("CAGR", "cagr", "{:.2%}"),
        ("Avg Trade", "avg_trade", "${:,.0f}"),
        ("Avg Win", "avg_win", "${:,.0f}"),
        ("Avg Loss", "avg_loss", "${:,.0f}"),
        ("Win/Loss Ratio", "win_loss_ratio", "{:.2f}"),
        ("Profit Factor", "profit_factor", "{:.2f}"),
        ("Avg R", "avg_r", "{:.2f}"),
        ("Max Win", "max_win", "${:,.0f}"),
        ("Max Loss", "max_loss", "${:,.0f}"),
        ("Avg Trade Duration (hrs)", "avg_trade_duration_hrs", "{:.1f}"),
        ("Median Trade Duration (hrs)", "median_trade_duration_hrs", "{:.1f}"),
        ("Total Months", "total_months", "{:.0f}"),
        ("Positive Months", "positive_months", "{:.0f}"),
        ("Monthly Win Rate", "monthly_win_rate", "{:.1%}"),
    ]

    for label, key, fmt in summary_rows:
        cells = [label]
        for a in analyses:
            cells.append(fmt.format(a[key]))
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(["", "## Risk Metrics", ""])
    risk_rows = [
        ("Sharpe (ann.)", "sharpe", "{:.2f}"),
        ("Sortino (ann.)", "sortino", "{:.2f}"),
        ("Volatility (ann.)", "volatility_annual", "{:.2%}"),
        ("Calmar", "calmar", "{:.2f}"),
        ("Probabilistic Sharpe Ratio (PSR)", "psr", "{:.2%}"),
        ("Deflated Sharpe Ratio (DSR)", "dsr", "{:.2%}"),
        ("Bayesian Sharpe Mean", "bayesian_sharpe_mean", "{:.2f}"),
        ("Bayesian Sharpe 95% CI", "bayesian_sharpe_lower", "{:.2f}", "bayesian_sharpe_upper", "{:.2f}"),
        ("VaR 95% (daily)", "var95", "{:.2%}"),
        ("VaR 99% (daily)", "var99", "{:.2%}"),
        ("Expected Shortfall 95%", "expected_shortfall_95", "{:.2%}"),
        ("Skewness", "skewness", "{:.2f}"),
        ("Excess Kurtosis", "kurtosis", "{:.2f}"),
    ]

    for row in risk_rows:
        if len(row) == 3:
            label, key, fmt = row
            cells = [label]
            for a in analyses:
                cells.append(fmt.format(a[key]))
        else:
            label, key1, fmt1, key2, fmt2 = row
            cells = [label]
            for a in analyses:
                cells.append(f"{fmt1.format(a[key1])} - {fmt2.format(a[key2])}")
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(["", "## Trade-Level Return Distribution", "",
                  "Per-trade return = trade PnL / $50,000 fixed account size.", ""])
    lines.append("| Metric | ES | NQ | YM |")
    lines.append("|--------|----|----|----|")
    trade_rows = [
        ("Trade Sharpe", "trade_sharpe", "{:.2f}"),
        ("Trade VaR 95%", "trade_var95", "{:.2%}"),
        ("Trade VaR 99%", "trade_var99", "{:.2%}"),
        ("Trade Expected Shortfall 95%", "trade_es95", "{:.2%}"),
        ("Trade Skewness", "trade_skewness", "{:.2f}"),
        ("Trade Excess Kurtosis", "trade_kurtosis", "{:.2f}"),
    ]
    for label, key, fmt in trade_rows:
        cells = [label]
        for a in analyses:
            cells.append(fmt.format(a[key]))
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(["", "## Drawdown Metrics", ""])
    dd_rows = [
        ("Max Drawdown ($)", "max_drawdown", "${:,.0f}"),
        ("Max Drawdown (%)", "max_drawdown_pct", "{:.2f}%"),
        ("Max DD Peak Date", "max_dd_peak_date", "{}"),
        ("Max DD Trough Date", "max_dd_trough_date", "{}"),
        ("Max DD Duration (days)", "max_dd_duration", "{:.0f}"),
        ("Avg Drawdown (%)", "avg_drawdown_pct", "{:.2f}%"),
        ("Drawdown Count", "drawdown_count", "{:.0f}"),
        ("Worst Start-to-Bottom ($)", "worst_start_to_bottom", "${:,.0f}"),
        ("Worst Start-to-Bottom (%)", "worst_start_to_bottom_pct", "{:.2f}%"),
    ]

    for label, key, fmt in dd_rows:
        cells = [label]
        for a in analyses:
            val = a[key]
            if val is None:
                cells.append("-")
            else:
                cells.append(fmt.format(val))
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(["", "## Markov Transition Matrix (Daily Return Sign)", "",
                  "P(next day | today):", ""])
    lines.append("| Symbol | Up → Up | Up → Down | Down → Up | Down → Down |")
    lines.append("|--------|---------|-----------|-----------|-------------|")
    for a in analyses:
        lines.append(
            f"| {a['symbol']} | {a['markov_up_up']:.2%} | {a['markov_up_down']:.2%} | "
            f"{a['markov_down_up']:.2%} | {a['markov_down_down']:.2%} |"
        )

    lines.extend(["", "## Brownian Motion / Random Walk Test (Runs Test)", "",
                  "H0: returns are random / Brownian. Low p-value rejects randomness.", ""])
    lines.append("| Symbol | Runs Z-Statistic | p-value | Interpretation |")
    lines.append("|--------|------------------|---------|----------------|")
    for a in analyses:
        interp = "Non-random" if a["runs_pvalue"] < 0.05 else "Random"
        lines.append(f"| {a['symbol']} | {a['runs_statistic']:.3f} | {a['runs_pvalue']:.3f} | {interp} |")

    lines.extend(["", "## Regression Fits on Equity Curve", ""])
    lines.append("| Model | Metric | ES | NQ | YM |")
    lines.append("|-------|--------|----|----|----|")
    reg_rows = [
        ("Linear", "linear_r2", "R²", "{:.4f}"),
        ("Linear", "linear_slope", "Slope ($/day)", "${:,.0f}"),
        ("Quadratic", "quad_r2", "R²", "{:.4f}"),
        ("Cubic", "cubic_r2", "R²", "{:.4f}"),
        ("Exponential", "exp_r2", "R²", "{:.4f}"),
        ("Exponential", "exp_b", "Growth rate/day", "{:.4f}"),
        ("Polynomial (deg 5)", "poly5_r2", "R²", "{:.4f}"),
    ]
    for model, key, metric, fmt in reg_rows:
        cells = [model, metric]
        for a in analyses:
            cells.append(fmt.format(a[key]))
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(["", "## Streak Analysis", ""])
    lines.append("| Metric | ES | NQ | YM |")
    lines.append("|--------|----|----|----|")
    streak_rows = [
        ("Avg Win Streak", "avg_win_streak", "{:.1f}"),
        ("Max Win Streak", "max_win_streak", "{:.0f}"),
        ("Avg Loss Streak", "avg_loss_streak", "{:.1f}"),
        ("Max Loss Streak", "max_loss_streak", "{:.0f}"),
    ]
    for label, key, fmt in streak_rows:
        cells = [label]
        for a in analyses:
            cells.append(fmt.format(a[key]))
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(["", "## Monthly Returns", ""])
    for a in analyses:
        lines.append(f"### {a['symbol']}")
        lines.append("")
        lines.append("| Month | Return |")
        lines.append("|-------|--------|")
        for (year, month), ret in sorted(a["monthly_returns"].items()):
            lines.append(f"| {year}-{month:02d} | {ret*100:+.2f}% |")
        lines.append("")

    return "\n".join(lines)


def build_csv(analyses: list[dict[str, Any]]) -> str:
    keys = [
        "symbol", "trades_total", "wins", "losses", "win_rate", "net_profit",
        "final_balance", "cagr", "profit_factor", "avg_trade", "avg_win",
        "avg_loss", "win_loss_ratio", "avg_r", "r_std", "sharpe", "sortino",
        "volatility_annual", "calmar", "psr", "dsr", "bayesian_sharpe_mean",
        "bayesian_sharpe_lower", "bayesian_sharpe_upper", "max_drawdown_pct",
        "max_dd_duration", "avg_drawdown_pct", "drawdown_count",
        "worst_start_to_bottom_pct", "var95", "var99", "expected_shortfall_95",
        "skewness", "kurtosis", "markov_up_up", "markov_up_down",
        "markov_down_up", "markov_down_down", "runs_statistic", "runs_pvalue",
        "linear_r2", "quad_r2", "cubic_r2", "exp_r2", "poly5_r2",
        "avg_trade_duration_hrs", "median_trade_duration_hrs",
        "max_win_streak", "max_loss_streak", "monthly_win_rate",
        "trade_sharpe", "trade_var95", "trade_var99", "trade_es95",
        "trade_skewness", "trade_kurtosis",
    ]
    header = ",".join(keys)
    rows = [header]
    for a in analyses:
        row = []
        for k in keys:
            v = a.get(k, "")
            if isinstance(v, float):
                row.append(f"{v:.6f}")
            else:
                row.append(str(v))
        rows.append(",".join(row))
    return "\n".join(rows)


def main() -> int:
    symbols = ["ES", "NQ", "YM"]
    analyses = [analyze_symbol(sym) for sym in symbols]
    report = build_report(analyses)
    REPORT_FILE.write_text(report)
    CSV_FILE.write_text(build_csv(analyses))
    print(f"Wrote quant report to {REPORT_FILE}")
    print(f"Wrote quant CSV to {CSV_FILE}")
    for a in analyses:
        print(
            f"{a['symbol']}: {a['trades_total']} trades, "
            f"Sharpe={a['sharpe']:.2f}, PSR={a['psr']:.1%}, DSR={a['dsr']:.1%}, "
            f"MaxDD={a['max_drawdown_pct']:.2f}%, Calmar={a['calmar']:.2f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
