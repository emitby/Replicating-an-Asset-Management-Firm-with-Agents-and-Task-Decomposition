"""Chart: tools vs tokens, from a run's token_profile.json (see evals/token_profile.py).

    run.ps1-style:  MPLCONFIGDIR=.cache/matplotlib .venv\\Scripts\\python.exe -m evals.token_chart runs\\<id> docs\\images\\tool-tokens.png

Two panels on separate axes (never a dual axis): tokens each tool's DEFINITION adds to every model
call of its agent, and tokens its RESULTS added over the whole run. Color identifies the agent
(categorical slots 1-5 of the dataviz reference palette, in fixed pipeline order); every bar also
carries a value label in text ink and the y-axis groups tools by agent, so identity is never color-alone.
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from strategy.charts import assert_cache_confined  # noqa: E402
from strategy.paths import confine  # noqa: E402

AGENT_ORDER = ["Data Agent", "Backtest Agent", "Analytics Agent", "Team Agent", "Presentation Agent"]
AGENT_COLORS = {"Data Agent": "#2a78d6", "Backtest Agent": "#eb6834", "Analytics Agent": "#1baf7a",
                "Team Agent": "#eda100", "Presentation Agent": "#e87ba4"}
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"


def main(run_dir, out_png):
    assert_cache_confined()
    report = json.loads((confine(run_dir) / "token_profile.json").read_text(encoding="utf-8"))
    tools = sorted(report["tools"], key=lambda t: (AGENT_ORDER.index(t["agent"]), -t["result_tokens_total"]))
    labels = [f"{t['tool']}" for t in tools]
    colors = [AGENT_COLORS[t["agent"]] for t in tools]
    y = list(range(len(tools)))[::-1]

    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 7.2), sharey=True, facecolor=SURFACE,
                                      gridspec_kw={"width_ratios": [1, 1.35], "wspace": 0.08})
    panels = ((left, "definition_tokens", "Definition tokens\n(every model call; cached)"),
              (right, "result_tokens_total", "Result tokens\n(total over the run)"))
    for ax, key, title in panels:
        vals = [t[key] for t in tools]
        ax.set_facecolor(SURFACE)
        ax.barh(y, vals, height=0.62, color=colors, edgecolor=SURFACE, linewidth=2)   # 2px surface gap
        vmax = max(vals)
        for yi, v, t in zip(y, vals, tools):
            extra = f"  ({t['calls']} calls)" if key == "result_tokens_total" and t["calls"] != 1 else ""
            ax.text(v + vmax * 0.012, yi, f"{v:,}{extra}", va="center", ha="left", fontsize=8.5, color=INK2)
        ax.set_xlim(0, vmax * 1.32)
        ax.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold")
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(colors=INK2, labelsize=9, length=0)
        ax.xaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
        for spine in ax.spines.values():
            spine.set_visible(False)
    left.set_yticks(y, labels, fontsize=9, color=INK)
    handles = [plt.Rectangle((0, 0), 1, 1, color=AGENT_COLORS[a]) for a in AGENT_ORDER]
    fig.legend(handles, AGENT_ORDER, loc="lower center", ncols=5, frameon=False, fontsize=9.5,
               labelcolor=INK, bbox_to_anchor=(0.5, -0.005))
    fig.suptitle(f"Agent tools vs tokens (exact counts, claude-opus-5-5 tokenizer, run {report['run']})",
                 x=0.01, ha="left", fontsize=13, fontweight="bold", color=INK)
    fig.subplots_adjust(left=0.17, right=0.98, top=0.86, bottom=0.1)
    out = confine(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160, facecolor=SURFACE)
    print(out)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
