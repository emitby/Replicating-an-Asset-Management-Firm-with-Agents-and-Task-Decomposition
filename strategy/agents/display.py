"""Rounded, display-ready views of computed metrics for agents to quote.

Agents see percentages to 1 decimal and ratios to 2. The guardrails accept
exactly these roundings, or coarser ones, of the stored full-precision values.
"""

PCT_KEYS = {"total_return", "excess_vs_spy", "median_total_return", "cagr", "volatility", "max_drawdown",
            "hit_rate", "best_day", "worst_day", "up_capture", "down_capture", "added_total_return",
            "removed_total_return", "blend_weight", "worst_year", "best_year"}
RATIO_KEYS = {"sharpe", "sortino", "calmar", "beta", "correlation", "corr_spy"}


def show(value, key):
    if value is None or value != value:
        return None
    if key in PCT_KEYS:
        s = f"{value * 100:.1f}"
        return (s[1:] if s == "-0.0" else s) + "%"           # never "-0.0%", matching pdf.pct
    if key in RATIO_KEYS:
        # A string with exactly 2 decimals: as a float, 1.10 became "1.1" on a slide (reviewer catch).
        s = f"{value:.2f}"
        return s[1:] if s == "-0.00" else s
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
