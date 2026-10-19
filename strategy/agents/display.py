"""Rounded, display-ready views of computed metrics for agents to quote.

Agents see percentages to 1 decimal and ratios to 2. The guardrails accept
exactly these roundings, or coarser ones, of the stored full-precision values.
"""

PCT_KEYS = {"total_return", "cagr", "volatility", "max_drawdown", "hit_rate", "best_day", "worst_day",
            "up_capture", "down_capture", "pct_time_in_spy", "current_allocation_spy",
            "pct_periods_beating_spy", "worst_1y_strategy", "worst_1y_spy", "best_1y_strategy", "best_1y_spy",
            "median_1y_excess"}
RATIO_KEYS = {"sharpe", "sortino", "calmar", "beta", "correlation"}


def show(value, key):
    if value is None or value != value:
        return None
    if key in PCT_KEYS:
        return f"{value * 100:.1f}%"
    if key in RATIO_KEYS:
        return round(value, 2)
    if isinstance(value, float):
        return round(value, 2)
    return value


def display(obj, key=None):
    if isinstance(obj, dict):
        return {k: display(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [display(v, key) for v in obj]
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        return show(obj, key)
    return obj
