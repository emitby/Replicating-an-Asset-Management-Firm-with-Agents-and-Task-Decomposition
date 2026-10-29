"""Tests for the month-end ranking engine (strategy.ranking)."""

import pandas as pd
import pytest

from evals.crosscheck_ranking import notebook_returns
from strategy.config import RankingConfig
from strategy.ranking import (RankingError, StrategySpec, apply_replacement, common_start, grid, month_ends, run_strategy,
                              score, daily_rf, top_n, trailing_change, validate_proposal)

CFG = RankingConfig()


@pytest.fixture(scope="module")
def px(prices):
    return prices[list(CFG.universe)]


def test_grid_is_84_strategies_in_table_order():
    g = grid(CFG)
    assert len(g) == 84 == CFG.grid_size
    assert g[0].id == "T1-CLOSE-15d" and g[-1].id == "LS-SMA200-180d"
    assert len({s.id for s in g}) == 84


def test_spec_id_round_trip():
    for s in grid(CFG):
        assert StrategySpec.from_id(s.id) == s
    with pytest.raises(RankingError):
        StrategySpec.from_id("XX-SMA20-15d")


def test_month_ends_exclude_the_current_month(px):
    ends = month_ends(px)
    assert ends[-1] < px.index[-1]
    assert ends[-1].to_period("M") < px.index[-1].to_period("M") or px.index[-1] not in ends
    # every month end is the last trading day of its month
    assert all(px.index[px.index.to_period("M") == e.to_period("M")].max() == e for e in ends)


def test_trailing_change_uses_last_value_on_or_before(px):
    ends = month_ends(px)
    tc = trailing_change(px, 30, ends)
    d = tc.index[5]
    past = px.loc[:d - pd.Timedelta(days=30)].iloc[-1]
    assert tc.loc[d].to_dict() == pytest.approx((px.loc[d] / past - 1).to_dict())


def test_top1_holds_the_leader_for_the_month(px):
    rets, picks = run_strategy(px, StrategySpec("Top 1", 0, 30))
    start, nxt = picks.index[3], picks.index[4]
    leader = picks.loc[start, 0]
    expected = px.loc[start:nxt, leader].pct_change().iloc[1:]
    assert rets.loc[expected.index].to_numpy() == pytest.approx(expected.to_numpy())


def test_top3_mix_drifts_within_the_month(px):
    rets, picks = run_strategy(px, StrategySpec("Top 3 mix", 50, 60))
    start, nxt = picks.index[2], picks.index[3]
    held = list(picks.loc[start])
    path = px.loc[start:nxt, held]
    value = (path / path.iloc[0]).mul([0.5, 0.3, 0.2]).sum(axis=1)
    # The return dated `start` belongs to the previous holding period; this one runs after it to `nxt`.
    held_rets = rets[(rets.index > start) & (rets.index <= nxt)]
    assert (1 + held_rets).prod() == pytest.approx(value.iloc[-1])


def test_long_short_never_shorts_a_long_holding(px):
    _, picks = run_strategy(px, StrategySpec("Long top 3, short negatives", 20, 90))
    for _, row in picks.iterrows():
        assert not set(row["shorts"]) & {row[0], row[1], row[2]}


def test_no_look_ahead(px):
    """Changing prices after a date can't change returns on or before it."""
    spec = StrategySpec("Top 3 mix", 20, 30)
    base, _ = run_strategy(px, spec)
    cut = px.index[len(px) // 2]
    shocked = px.copy()
    shocked.loc[shocked.index > cut, "USO"] *= 3
    after, _ = run_strategy(shocked, spec)
    # The month containing `cut` was decided at the previous month end, so returns up to `cut` match.
    assert after.loc[:cut].to_numpy() == pytest.approx(base.loc[:cut].to_numpy())


@pytest.mark.parametrize("sid", ["T1-CLOSE-15d", "T3-SMA200-180d", "LS-SMA50-60d", "T1-SMA20-10d"])
def test_matches_the_notebook_implementation(px, sid):
    ours, _ = run_strategy(px, StrategySpec.from_id(sid))
    ref = notebook_returns(px, sid)
    assert (ours - ref.reindex(ours.index)).abs().max() < 1e-12


def test_score_common_window_and_excess(px, prices):
    rets = {s.id: run_strategy(px, s)[0] for s in grid(CFG)[:8]}
    start = common_start(rets)
    sc = score(rets, prices, start, daily_rf(prices))
    assert sc.at["SPY", "excess_vs_spy"] == 0
    sid = next(iter(rets))
    assert sc.at[sid, "excess_vs_spy"] == pytest.approx(sc.at[sid, "total_return"] - sc.at["SPY", "total_return"])
    assert sc.at[sid, "total_return"] == pytest.approx((1 + rets[sid].loc[start:]).prod() - 1)
    spy = prices["SPY"].pct_change().loc[start:]
    assert sc.at["SPY", "corr_spy"] == pytest.approx(1.0)
    assert sc.at[sid, "corr_spy"] == pytest.approx(rets[sid].loc[start:].corr(spy))


def test_score_rejects_a_strategy_missing_dates(px, prices):
    short = run_strategy(px, StrategySpec("Top 1", 0, 15))[0]
    late = short.iloc[300:]
    with pytest.raises(RankingError, match="insufficient history"):
        score({"a": short, "b": late}, prices, short.index[0], daily_rf(prices))


def test_top_n_ignores_benchmarks_and_breaks_ties_by_id():
    sc = pd.DataFrame({"total_return": [9.0, 1.0, 1.0, 0.5]}, index=["SPY", "b", "a", "c"])
    assert top_n(sc, 2) == ["a", "b"]


def test_replacement_rule():
    sc = pd.DataFrame({"total_return": [5, 4, 3, 2, 1, 4.5, 2.5, 0.1]}, index=list("ABCDE") + ["N1", "N2", "N3"])
    out = apply_replacement(sc, list("ABCDE"), ["N1", "N2", "N3"])
    assert out["final"] == ["A", "N1", "B", "C", "N2"]
    assert [(r["added"], r["removed"]) for r in out["replacements"]] == [("N1", "E"), ("N2", "D")]
    # no new strategy good enough: nothing changes
    assert apply_replacement(sc, list("ABCDE"), ["N3"]) == {"final": list("ABCDE"), "replacements": []}


@pytest.mark.parametrize("spec, match", [
    (StrategySpec("Top 1", 20, 15), "already run"),
    (StrategySpec("Top 1", 3, 15), "SMA window"),
    (StrategySpec("Top 1", 20, 400), "Lookback"),
    (StrategySpec("Top 5", 20, 15), "Portfolio"),
])
def test_invalid_proposals(spec, match):
    with pytest.raises(RankingError, match=match):
        validate_proposal(spec, CFG, {"T1-SMA20-15d"})
