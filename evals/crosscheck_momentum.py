"""Independent cross-check of the momentum sub-strategies.

Deliberately does NOT import strategy.momentum. It re-derives every month's pick and
monthly return from prices.csv with plain month-end arithmetic and compares them with
the saved momentum.json and returns.csv.

    .venv\\Scripts\\python.exe evals\\crosscheck_momentum.py runs\\<id>
"""

import json
import sys
from pathlib import Path

import pandas as pd

UNIVERSE = ["SPY", "QQQ", "TLT", "GLD", "IWM", "IEF"]


def derive(prices, lookback, start="2011-01", cash_months=3):
    m = prices[UNIVERSE].groupby(prices.index.to_period("M")).last()   # month-end (or latest) closes
    picks, cash_left = {}, 0
    months = [p for p in m.index if p >= pd.Period(start)]
    for month in months:
        decided = month - 1
        trailing = m.loc[decided] / m.loc[decided - lookback] - 1
        if cash_left:
            picks[month], cash_left = "CASH", cash_left - 1
        elif (trailing < 0).all():
            picks[month], cash_left = "CASH", cash_months - 1
        else:
            picks[month] = trailing.idxmax()
    monthly_ret = {mo: 0.0 if p == "CASH" else m.loc[mo, p] / m.loc[mo - 1, p] - 1 for mo, p in picks.items()}
    return picks, monthly_ret


def main(run_dir):
    run = Path(run_dir)
    prices = pd.read_csv(run / "prices.csv", index_col=0, parse_dates=True)
    returns = pd.read_csv(run / "returns.csv", index_col=0, parse_dates=True)
    saved = json.loads((run / "momentum.json").read_text(encoding="utf-8"))["sub_strategies"]
    ok = True
    for L in (3, 6, 12, 24):
        picks, mret = derive(prices, L)
        hist = {pd.Period(h["month"]): h["pick"] for h in saved[f"MOM{L}"]["history"]}
        pick_mismatch = [str(mo) for mo in picks if hist.get(mo) != picks[mo]]
        daily = returns[f"MOM{L}"].dropna()
        by_month = (1 + daily).groupby(daily.index.to_period("M")).prod() - 1
        worst = max(abs(by_month[mo] - r) for mo, r in mret.items())
        total_indep = 1.0
        for r in mret.values():
            total_indep *= 1 + r
        total_saved = float((1 + daily).prod())
        good = not pick_mismatch and worst < 1e-9 and abs(total_indep - total_saved) < 1e-9
        ok &= good
        print(f"MOM{L:<2}  months={len(picks)}  pick mismatches={len(pick_mismatch)}  "
              f"max monthly diff={worst:.1e}  total {total_indep - 1:.4%} vs {total_saved - 1:.4%}  "
              f"{'OK' if good else 'MISMATCH ' + str(pick_mismatch[:5])}")
    print("INDEPENDENT CROSS-CHECK PASSED" if ok else "INDEPENDENT CROSS-CHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
