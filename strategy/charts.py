"""Chart rendering (matplotlib, headless), from saved run artifacts only.

Every chart is drawn from a `ChartData` bundle loaded from the run folder
(strategy_returns.csv, research.json, pm.json, analytics.json), never from
live agent state. That is what lets ``build-pdf`` re-render the whole deck,
charts included, after a run, without any agent or API call.

Guardrail: matplotlib keeps a config/font cache in MPLCONFIGDIR. The launchers
(run.ps1 / run.sh) point it at <project>/.cache/matplotlib. Rendering refuses
to run if the cache would live outside the project.
"""

import matplotlib

matplotlib.use("Agg")

from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mtick  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from strategy.analytics import drawdown_series  # noqa: E402
from strategy.paths import PROJECT_DIR, confine  # noqa: E402

FINAL_COLORS = ("#1f4e79", "#2e9e6b", "#7030a0", "#bf9000", "#17becf")
BENCH_COLORS = {"SPY": "#c55a11", "QQQ": "#000000"}
CHART_KINDS = ("growth_final", "drawdowns_final", "round1_heatmap", "rounds_bars", "correlation", "blend")
REQUIRED_CHARTS = ("growth_final", "drawdowns_final", "round1_heatmap", "rounds_bars", "correlation")
# Charts drawn only by code for the pitchbook (not offered to the Presentation Agent).
PITCH_CHARTS = ("pitch_performance",)


class ChartError(ValueError):
    """An unknown chart kind or a cache outside the project."""


@dataclass
class ChartData:
    """Everything the charts need, loaded from one run folder.

    Attributes:
        returns: daily returns over the scored window (strategy ids, SPY, QQQ, rf).
        scores: risk/return table (rows: strategy ids, SPY, QQQ).
        specs: id -> strategy dict (portfolio, sma, lookback_days, signal, label).
        pm: pm.json (top5, proposals, final).
        analytics: analytics.json (portfolio_fit for the correlation and blend charts).
        round1_ids: the round-1 grid ids, in table order.
    """
    returns: pd.DataFrame
    scores: pd.DataFrame
    specs: dict
    pm: dict
    analytics: dict
    round1_ids: list

    @property
    def final(self):
        """The final strategy ids, best total return first."""
        return self.pm["final"]["final"]

    def short(self, sid):
        """Compact legend label, e.g. ``Top 3 | 200d SMA | 180d``."""
        if sid not in self.specs:
            return sid
        s = self.specs[sid]
        return f"{s['portfolio'].replace('Long top 3, short negatives', 'Long/short')} | {s['signal']} | {s['lookback_days']}d"


def assert_cache_confined():
    """Refuse to render if matplotlib's config or cache directory is outside the project."""
    for d in (matplotlib.get_configdir(), matplotlib.get_cachedir()):
        if not Path(d).resolve().is_relative_to(PROJECT_DIR):
            raise ChartError(f"matplotlib cache is outside the project ({d}). Run via run.ps1 / run.sh.")


def _style(ax, title, pct_y=True):
    """Shared axis styling: left title, no top/right spines, light grid, % y-axis by default."""
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color="#222222")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    ax.tick_params(labelsize=9)
    if pct_y:
        ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))


def _save(fig, out_dir, kind):
    """Save a figure as <out_dir>/<kind>.png (confined to the project) and close it."""
    path = confine(Path(out_dir) / f"{kind}.png")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path


def render(kind, out_dir, data):
    """Render one chart.

    Args:
        kind: one of `CHART_KINDS`.
        out_dir: folder for the PNG (inside the project).
        data: a `ChartData` bundle.

    Returns:
        The PNG path.

    Raises:
        ChartError: unknown kind, or matplotlib's cache is outside the project.
    """
    assert_cache_confined()
    if kind not in CHART_KINDS + PITCH_CHARTS:
        raise ChartError(f"Unknown chart {kind!r}. Available: {list(CHART_KINDS)}.")
    fig, ax = plt.subplots(figsize=(9, 6.2))   # matches the slide's chart area, so no dead space
    r = data.returns
    colors = dict(zip(data.final, FINAL_COLORS)) | BENCH_COLORS

    if kind == "growth_final":
        for s in [*data.final, "SPY", "QQQ"]:
            ax.plot((1 + r[s]).cumprod() * 10_000, label=data.short(s) if s in data.specs else f"{s} buy & hold",
                    color=colors[s], lw=1.4 if s in BENCH_COLORS else 2.0, ls="--" if s in BENCH_COLORS else "-")
        ax.set_yscale("log")
        ax.yaxis.set_major_locator(mtick.LogLocator(base=10, subs=(1.0, 2.0, 5.0)))
        ax.yaxis.set_major_formatter(mtick.StrMethodFormatter("${x:,.0f}"))
        ax.yaxis.set_minor_formatter(mtick.NullFormatter())
        _style(ax, "Growth of $10,000: final strategies vs SPY and QQQ (log scale)", pct_y=False)
        ax.legend(fontsize=8.5, frameon=False, loc="upper left")
        ax.set_xlabel("Hypothetical backtest; no trading costs", fontsize=8.5, color="#595959")

    elif kind == "drawdowns_final":
        fig.set_size_inches(9, 6.2)
        for s in [*data.final, "SPY"]:
            dd = drawdown_series(r[s])
            ax.plot(dd, color=colors[s], lw=1.2 if s != "SPY" else 2.2, alpha=0.85 if s != "SPY" else 1.0,
                    label=data.short(s) if s in data.specs else "SPY buy & hold", zorder=3 if s == "SPY" else 2)
        _style(ax, "Drawdown from peak: final strategies vs SPY")
        # Legend below the plot: inside, it covered the deepest troughs (visual review).
        ax.legend(fontsize=8.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.07), ncol=3)

    elif kind == "round1_heatmap":
        specs = [data.specs[i] for i in data.round1_ids]
        rows = list(dict.fromkeys((s["portfolio"], s["signal"]) for s in specs))
        cols = sorted({s["lookback_days"] for s in specs})
        grid = np.full((len(rows), len(cols)), np.nan)
        for sid, s in zip(data.round1_ids, specs):
            grid[rows.index((s["portfolio"], s["signal"])), cols.index(s["lookback_days"])] = data.scores.at[sid, "excess_vs_spy"]
        lim = np.nanmax(np.abs(grid))
        im = ax.imshow(grid, cmap="RdBu", vmin=-lim, vmax=lim, aspect="auto")
        for i in range(len(rows)):
            for j in range(len(cols)):
                v = grid[i, j]
                ax.text(j, i, f"{v * 100:+.0f}%", ha="center", va="center", fontsize=7.5,
                        color="white" if abs(v) > lim * 0.6 else "#222222")
        ax.set_xticks(range(len(cols)), [f"{c}d" for c in cols])
        ax.set_yticks(range(len(rows)), [f"{p.replace('Long top 3, short negatives', 'Long/short')} | {sig}" for p, sig in rows],
                      fontsize=8)
        ax.set_xlabel("Trailing lookback (calendar days)", fontsize=9)
        ax.set_title(f"Round 1: total return minus SPY's, all {len(specs)} strategies", loc="left",
                     fontsize=13, fontweight="bold", color="#222222")
        fig.colorbar(im, ax=ax, format=mtick.PercentFormatter(1.0, decimals=0), shrink=0.8)

    elif kind == "rounds_bars":
        top = [p["id"] for p in data.pm["top5"]]
        props = [p["id"] for p in data.pm["proposals"]]
        ids = [*top, *props]
        vals = [data.scores.at[i, "total_return"] for i in ids]
        bar_colors = ["#1f4e79"] * len(top) + ["#c55a11"] * len(props)
        y = np.arange(len(ids))[::-1]
        ax.barh(y, vals, color=bar_colors)
        ax.set_yticks(y, [f"{data.short(i)}{'  (final)' if i in data.final else ''}" for i in ids], fontsize=8.5)
        for b, c in (("SPY", BENCH_COLORS["SPY"]), ("QQQ", BENCH_COLORS["QQQ"])):
            ax.axvline(data.scores.at[b, "total_return"], color=c, ls="--", lw=1.4, label=f"{b} buy & hold")
        ax.xaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="x", alpha=0.25)
        ax.set_title("Total return: round-1 top 5 (blue) and PM proposals (orange)", loc="left", fontsize=13,
                     fontweight="bold", color="#222222")
        ax.legend(fontsize=8.5, frameon=False, loc="lower right")

    elif kind == "correlation":
        corr = data.analytics["portfolio_fit"]["correlation"]
        assets = list(next(iter(corr.values())))
        width = 0.8 / len(data.final)
        for i, sid in enumerate(data.final):
            ax.bar(np.arange(len(assets)) + (i - (len(data.final) - 1) / 2) * width,
                   [corr[sid][a] for a in assets], width, color=colors[sid], label=data.short(sid))
        ax.set_xticks(range(len(assets)), assets)
        ax.axhline(0, color="#888888", lw=0.8)
        ax.set_ylim(-1, 1)
        _style(ax, "Correlation of daily returns with core asset classes", pct_y=False)
        ax.legend(fontsize=8.5, frameon=False, loc="upper right")

    elif kind == "blend":
        fit = data.analytics["portfolio_fit"]
        w = round(fit["blend_weight"] * 100)
        names = ["SPY alone", *[data.short(s) for s in data.final]]
        metrics = [fit["spy"], *[fit["blends"][s] for s in data.final]]
        x = np.arange(len(names))
        ax.bar(x - 0.2, [m["cagr"] for m in metrics], 0.4, color="#1f4e79", label="Annual return")
        ax.bar(x + 0.2, [m["max_drawdown"] for m in metrics], 0.4, color="#c55a11", label="Max drawdown")
        ax.set_xticks(x, names, rotation=20, ha="right", fontsize=8)
        ax.axhline(0, color="#888888", lw=0.8)
        _style(ax, f"{100 - w}% SPY + {w}% strategy vs SPY alone (rebalanced daily)")
        ax.legend(fontsize=8.5, frameon=False)

    elif kind == "pitch_performance":
        # The top strategy, the SPY + strategy blend, and the two benchmarks (pitchbook page 3).
        top = data.final[0]
        w = data.analytics["portfolio_fit"]["blend_weight"]
        blend = (1 - w) * r["SPY"] + w * r[top]      # rebalanced daily, as in analytics.portfolio_fit
        series = [(r[top], data.short(top), FINAL_COLORS[0], 2.4, "-"),
                  (blend, f"{100 - round(w * 100)}% SPY + {round(w * 100)}% strategy", "#2e9e6b", 2.0, "-"),
                  (r["SPY"], "SPY buy & hold", BENCH_COLORS["SPY"], 1.5, "--"),
                  (r["QQQ"], "QQQ buy & hold", BENCH_COLORS["QQQ"], 1.5, "--")]
        for s, label, color, lw, ls in series:
            ax.plot((1 + s).cumprod() * 10_000, label=label, color=color, lw=lw, ls=ls)
        ax.set_yscale("log")
        ax.yaxis.set_major_locator(mtick.LogLocator(base=10, subs=(1.0, 2.0, 5.0)))
        ax.yaxis.set_major_formatter(mtick.StrMethodFormatter("${x:,.0f}"))
        ax.yaxis.set_minor_formatter(mtick.NullFormatter())
        _style(ax, "Growth of $10,000: top strategy, SPY blend, SPY and QQQ (log scale)", pct_y=False)
        ax.legend(fontsize=9, frameon=False, loc="upper left")
        ax.set_xlabel("Hypothetical backtest; no trading costs", fontsize=8.5, color="#595959")

    return _save(fig, out_dir, kind)
