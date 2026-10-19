"""Chart rendering (matplotlib, headless).

Guardrail: matplotlib keeps a config/font cache in MPLCONFIGDIR. The launchers
(run.ps1 / run.sh) point it at <project>/.cache/matplotlib. Rendering refuses
to run if the cache would live outside the project.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mtick  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from pathlib import Path  # noqa: E402

from strategy.analytics import drawdown_series  # noqa: E402
from strategy.paths import PROJECT_DIR, confine  # noqa: E402

COLORS = {"Strategy": "#1f4e79", "SPY": "#c55a11", "60/40": "#7f7f7f", "MA Strategy": "#1f4e79",
          "MOM3": "#9dc3e6", "MOM6": "#2e9e6b", "MOM12": "#7030a0", "MOM24": "#bf9000"}
# Distinct hues per asset (an earlier palette made SPY/QQQ/GLD look alike); cash is light grey and hatched.
ASSET_COLORS = {"SPY": "#d62728", "QQQ": "#9467bd", "IWM": "#2ca02c", "TLT": "#1f3a93", "IEF": "#17becf",
                "GLD": "#ffbf00", "CASH": "#d9d9d9"}
CHART_KINDS = ("equity_vs_spy", "drawdowns", "rolling_1y", "allocation", "window_returns",
               "ma_selection", "calendar_years",
               "momentum_vs_spy", "momentum_drawdowns", "momentum_holdings", "comparison_returns")
MOM_SERIES = ("MOM3", "MOM6", "MOM12", "MOM24")


class ChartError(ValueError):
    pass


def assert_cache_confined():
    for d in (matplotlib.get_configdir(), matplotlib.get_cachedir()):
        if not Path(d).resolve().is_relative_to(PROJECT_DIR):
            raise ChartError(f"matplotlib cache is outside the project ({d}). Run via run.ps1 / run.sh.")


def _style(ax, title, pct_y=True):
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color="#222222")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    ax.tick_params(labelsize=9)
    if pct_y:
        ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))


def _save(fig, out_dir, kind):
    path = confine(Path(out_dir) / f"{kind}.png")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path


def render(kind, out_dir, returns, analytics=None, history=None):
    assert_cache_confined()
    if kind not in CHART_KINDS:
        raise ChartError(f"Unknown chart {kind!r}. Available: {list(CHART_KINDS)}.")
    fig, ax = plt.subplots(figsize=(9, 6.2))   # matches the slide's chart area, so no dead space
    series = ["Strategy", "SPY", "60/40"]

    if kind == "equity_vs_spy":
        for s in series:
            ax.plot((1 + returns[s]).cumprod() * 10_000, label=s, color=COLORS[s],
                    lw=2.2 if s == "Strategy" else 1.4)
        ax.set_yscale("log")
        ax.yaxis.set_major_locator(mtick.LogLocator(base=10, subs=(1.0, 2.0, 5.0)))
        ax.yaxis.set_major_formatter(mtick.StrMethodFormatter("${x:,.0f}"))
        ax.yaxis.set_minor_formatter(mtick.NullFormatter())
        _style(ax, "Growth of $10,000 (log scale, walk-forward out-of-sample)", pct_y=False)
        ax.legend(frameon=False)
    elif kind == "drawdowns":
        spy_dd, strat_dd = drawdown_series(returns["SPY"]), drawdown_series(returns["Strategy"])
        ax.fill_between(spy_dd.index, spy_dd, 0, color=COLORS["SPY"], alpha=0.18, lw=0)
        ax.plot(spy_dd, color=COLORS["SPY"], lw=1.0, label="SPY")
        ax.plot(strat_dd, color=COLORS["Strategy"], lw=1.6, label="Strategy")
        _style(ax, "Drawdown from peak")
        ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.08), ncols=2)
    elif kind == "rolling_1y":
        roll = (1 + returns[["Strategy", "SPY"]]).rolling(252).apply(lambda x: x.prod(), raw=True) - 1
        for s in ("Strategy", "SPY"):
            ax.plot(roll[s], label=s, color=COLORS[s], lw=1.6)
        ax.axhline(0, color="#999999", lw=0.8)
        _style(ax, "Rolling 1-year return")
        ax.legend(frameon=False)
    elif kind == "allocation":
        w = returns["w_spy"]
        ax.fill_between(w.index, w, 0, step="post", color=COLORS["SPY"], alpha=0.75, label="SPY")
        ax.fill_between(w.index, w, 1, step="post", color="#5b9bd5", alpha=0.75, label="IEF")
        ax.set_ylim(0, 1)
        _style(ax, "Allocation over time (SPY vs IEF)")
        ax.legend(frameon=False, loc="lower left", ncols=2)
    elif kind == "window_returns":
        if not analytics:
            raise ChartError("window_returns needs analytics.")
        labels = [w for w in ("3M", "1Y", "3Y", "5Y") if w in analytics["windows"]]
        width = 0.26
        for i, s in enumerate(series):
            vals = []
            for w in labels:
                m = analytics["windows"][w]["series"][s]
                vals.append(m.get("cagr", m["total_return"]))
            xs = [x + (i - 1) * width for x in range(len(labels))]
            bars = ax.bar(xs, vals, width, label=s, color=COLORS[s])
            ax.bar_label(bars, labels=[f"{v:.1%}" for v in vals], fontsize=8, padding=2)
        ax.set_xticks(range(len(labels)), [f"{w}{' (ann.)' if analytics['windows'][w]['annualized'] else ''}" for w in labels])
        ax.axhline(0, color="#999999", lw=0.8)
        _style(ax, "Trailing returns: 3M total, 1Y/3Y/5Y annualized")
        ax.legend(frameon=False)
    elif kind == "ma_selection":
        if not history:
            raise ChartError("ma_selection needs the selection history.")
        years = [h["year"] for h in history]
        chosen = [h["chosen_ma"] for h in history]
        ax.step(years, chosen, where="mid", color=COLORS["Strategy"], lw=2)
        ax.scatter(years, chosen, color=COLORS["Strategy"], zorder=3)
        ax.set_yscale("log")
        ax.set_yticks([5, 20, 50, 200], ["5-day", "20-day", "50-day", "200-day"])
        ax.minorticks_off()
        ax.xaxis.set_major_locator(mtick.MaxNLocator(integer=True))
        _style(ax, "Moving average chosen each year (walk-forward, prior data only)", pct_y=False)
    elif kind == "calendar_years":
        yearly = (1 + returns[["Strategy", "SPY"]]).groupby(returns.index.year).prod() - 1
        xs = range(len(yearly))
        ax.bar([x - 0.2 for x in xs], yearly["Strategy"], 0.4, label="Strategy", color=COLORS["Strategy"])
        ax.bar([x + 0.2 for x in xs], yearly["SPY"], 0.4, label="SPY", color=COLORS["SPY"])
        end = returns.index.max()
        labels = [f"{y} YTD" if (y == end.year and (end.month, end.day) < (12, 24)) else str(y) for y in yearly.index]
        ax.set_xticks(list(xs), labels, rotation=45, fontsize=8)
        ax.axhline(0, color="#999999", lw=0.8)
        _style(ax, "Calendar-year returns (final year is year-to-date)" if "YTD" in labels[-1] else "Calendar-year returns")
        ax.legend(frameon=False)
    elif kind in ("momentum_vs_spy", "momentum_drawdowns", "momentum_holdings", "comparison_returns"):
        _momentum_chart(kind, ax, fig, returns, analytics)
    return _save(fig, out_dir, kind)


def _momentum_frame(returns):
    missing = [c for c in MOM_SERIES if c not in returns.columns]
    if missing:
        raise ChartError(f"Momentum returns missing: {missing}.")
    df = returns.dropna(subset=list(MOM_SERIES))
    return df.rename(columns={"Strategy": "MA Strategy"})


def _momentum_chart(kind, ax, fig, returns, analytics):
    df = _momentum_frame(returns)
    lines = [*MOM_SERIES, "MA Strategy", "SPY"]
    if kind == "momentum_vs_spy":
        for s in lines:
            ax.plot((1 + df[s]).cumprod() * 10_000, label=s, color=COLORS[s],
                    lw=2.0 if s in ("SPY", "MA Strategy") else 1.5, ls="--" if s == "MA Strategy" else "-")
        ax.set_yscale("log")
        ax.yaxis.set_major_locator(mtick.LogLocator(base=10, subs=(1.0, 2.0, 5.0)))
        ax.yaxis.set_major_formatter(mtick.StrMethodFormatter("${x:,.0f}"))
        ax.yaxis.set_minor_formatter(mtick.NullFormatter())
        _style(ax, f"Growth of $10,000 since {df.index.min():%b %Y} (log scale)", pct_y=False)
        ax.legend(frameon=False, ncols=3, loc="upper left")
    elif kind == "momentum_drawdowns":
        spy_dd = drawdown_series(df["SPY"])
        ax.fill_between(spy_dd.index, spy_dd, 0, color=COLORS["SPY"], alpha=0.15, lw=0)
        for s in lines:
            ax.plot(drawdown_series(df[s]), label=s, color=COLORS[s], lw=1.2,
                    ls="--" if s == "MA Strategy" else "-")
        _style(ax, f"Drawdown from peak since {df.index.min():%b %Y}")
        ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.08), ncols=6, fontsize=8)
    elif kind == "momentum_holdings":
        assets = list(ASSET_COLORS)
        rows = []
        for s in MOM_SERIES:
            hold = df[f"hold_{s}"]
            monthly = hold.groupby(hold.index.to_period("M")).first()
            rows.append([assets.index(a) for a in monthly])
        months = monthly.index
        grid = np.array(rows)
        ax.imshow(grid, aspect="auto", interpolation="nearest",
                  cmap=ListedColormap([ASSET_COLORS[a] for a in assets]), vmin=0, vmax=len(assets) - 1)
        cash = assets.index("CASH")
        for r, row in enumerate(grid):           # hatch cash cells so they can't be mistaken for background
            for col in np.flatnonzero(row == cash):
                ax.add_patch(plt.Rectangle((col - 0.5, r - 0.5), 1, 1, fill=False, hatch="////",
                                           edgecolor="#595959", lw=0))
        ax.set_yticks(range(len(MOM_SERIES)), [f"{s[3:]}-month" for s in MOM_SERIES])
        ax.set_yticks(np.arange(-0.5, len(MOM_SERIES)), minor=True)
        ax.grid(which="minor", axis="y", color="white", lw=3)
        ax.tick_params(which="minor", length=0)
        ticks = [i for i, m in enumerate(months) if m.month == 1]
        ax.set_xticks(ticks, [str(months[i].year) for i in ticks], fontsize=8, rotation=45)
        ax.set_title("Monthly holding by lookback (hatched grey = cash)", loc="left", fontsize=13, fontweight="bold")
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.legend(handles=[Patch(facecolor=ASSET_COLORS[a], edgecolor="#595959", label=a,
                                 hatch="////" if a == "CASH" else None) for a in assets],
                  frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncols=7, fontsize=9)
    elif kind == "comparison_returns":
        comp = (analytics or {}).get("comparison", {}).get("windows")
        if not comp:
            raise ChartError("comparison_returns needs the comparison analytics.")
        wins = [w for w in ("3M", "1Y", "3Y", "5Y", "S2011") if w in comp]
        width = 0.13
        for i, s in enumerate(lines):
            vals = [comp[w]["series"][s].get("cagr", comp[w]["series"][s]["total_return"]) for w in wins]
            xs = [x + (i - 2.5) * width for x in range(len(wins))]
            ax.bar(xs, vals, width, label=s, color=COLORS[s], edgecolor="white", lw=0.4,
                   hatch="//" if s == "MA Strategy" else None)
        labels = {"S2011": "Since 2011"}
        ax.set_xticks(range(len(wins)), [f"{labels.get(w, w)}{' (ann.)' if comp[w]['annualized'] else ''}" for w in wins])
        ax.axhline(0, color="#999999", lw=0.8)
        _style(ax, "Returns by period: momentum lookbacks vs MA strategy and SPY")
        ax.legend(frameon=False, ncols=6, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.08))
