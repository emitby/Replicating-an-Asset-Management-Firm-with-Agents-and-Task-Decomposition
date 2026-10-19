"""Independent cross-check of the momentum sub-strategies (v2: top-3 weighted 50/30/20).

Deliberately does NOT import strategy.momentum. It re-derives every month's weights and
monthly return from prices.csv with plain month-end arithmetic:
    - rank the six ETFs by trailing return over the lookback
    - 50/30/20 to the top three; a slot whose ETF has a negative trailing return is cash (0%)
    - all six negative -> 100% cash for 3 months, then re-evaluate
    - monthly return = Σ weight × ETF month-over-month return (monthly rebalancing)
and compares them with the saved momentum.json and returns.csv.

    .venv\\Scripts\\python.exe evals\\crosscheck_momentum.py runs\\<id>
"""

import json
import sys
from pathlib import Path

import pandas as pd

UNIVERSE = ["SPY", "QQQ", "TLT", "GLD", "IWM", "IEF"]
SLOTS = [0.5, 0.3, 0.2]


def derive(prices, lookback, start="2011-01", cash_months=3):
    m = prices[UNIVERSE].groupby(prices.index.to_period("M")).last()   # month-end (or latest) closes
    weights, lock = {}, 0
    for month in [p for p in m.index if p >= pd.Period(start)]:
        decided = month - 1
        trailing = {a: m.loc[decided, a] / m.loc[decided - lookback, a] - 1 for a in UNIVERSE}
        if lock:
            weights[month], lock = {"CASH": 1.0}, lock - 1
        elif all(v < 0 for v in trailing.values()):
            weights[month], lock = {"CASH": 1.0}, cash_months - 1
        else:
            ranked = sorted(UNIVERSE, key=lambda a: (-trailing[a], UNIVERSE.index(a)))
            w = {}
            for a, slot in zip(ranked, SLOTS):
                key = a if trailing[a] >= 0 else "CASH"
                w[key] = round(w.get(key, 0.0) + slot, 10)
            weights[month] = w
    monthly_ret = {mo: sum(wt * (m.loc[mo, a] / m.loc[mo - 1, a] - 1) for a, wt in w.items() if a != "CASH")
                   for mo, w in weights.items()}
    return weights, monthly_ret


def main(run_dir):
    run = Path(run_dir)
    prices = pd.read_csv(run / "prices.csv", index_col=0, parse_dates=True)
    returns = pd.read_csv(run / "returns.csv", index_col=0, parse_dates=True)
    saved = json.loads((run / "momentum.json").read_text(encoding="utf-8"))["sub_strategies"]
    ok = True
    for name in saved:
        L = int(name[3:])
        weights, mret = derive(prices, L)
        hist = {pd.Period(h["month"]): h["weights"] for h in saved[name]["history"]}
        mismatch = [str(mo) for mo in weights if hist.get(mo) != weights[mo]]
        daily = returns[name].dropna()
        by_month = (1 + daily).groupby(daily.index.to_period("M")).prod() - 1
        worst = max(abs(by_month[mo] - r) for mo, r in mret.items())
        total_indep = 1.0
        for r in mret.values():
            total_indep *= 1 + r
        total_saved = float((1 + daily).prod())
        good = not mismatch and worst < 1e-9 and abs(total_indep - total_saved) < 1e-9
        ok &= good
        print(f"{name:<5}  months={len(weights)}  weight mismatches={len(mismatch)}  max monthly diff={worst:.1e}  "
              f"total {total_indep - 1:.4%} vs {total_saved - 1:.4%}  {'OK' if good else 'MISMATCH ' + str(mismatch[:5])}")
    print("INDEPENDENT CROSS-CHECK PASSED" if ok else "INDEPENDENT CROSS-CHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
