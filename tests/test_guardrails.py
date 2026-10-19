import pytest

from strategy.guardrails import NumberIndex, banned_phrases, check_text, unsupported_numbers

ANALYTICS = {"windows": {"1Y": {"series": {"Strategy": {"cagr": 0.12345, "max_drawdown": -0.0832, "sharpe": 1.234}}}},
             "growth_of_10000": {"Strategy": 48213.7}}
INDEX = NumberIndex(ANALYTICS, constants={5, 20, 50, 200, 60, 40, 10000})


@pytest.mark.parametrize("text", [
    "The strategy returned 12.3% over one year.",          # 12.345 -> 12.3
    "Returned 12% annualized.",                             # coarser rounding is fine
    "Max drawdown was 8.3%, versus a deeper fall for SPY.",  # abs value of -0.0832
    "Max drawdown was -8.3%.",
    "Sharpe ratio of 1.23.",
    "$10,000 grew to $48,214.",
    "Uses the 50-day and 200-day moving averages, MA200 too, and a 60/40 benchmark.",
    "In 2008 and 2022 the strategy rotated into Treasuries.",  # years are ignored
])
def test_supported_numbers_pass(text):
    assert unsupported_numbers(text, INDEX) == []


@pytest.mark.parametrize("text, bad", [
    ("The strategy returned 15.2% over one year.", "15.2%"),
    ("Sharpe ratio of 1.5.", "1.5"),
    ("Outperformed by 4.1% per year.", "4.1%"),
    ("Growth to $52,000.", "$52,000"),
])
def test_invented_numbers_fail(text, bad):
    assert bad in unsupported_numbers(text, INDEX)


def test_precision_must_match_rounding():
    assert unsupported_numbers("12.35%", INDEX) == []      # 12.345 to 2dp (half-up tolerance)
    assert unsupported_numbers("12.4%", INDEX) == ["12.4%"]


@pytest.mark.parametrize("text", [
    "Returns are guaranteed.", "A risk-free return.", "You can't lose.", "This will outperform SPY.",
    "It is certain to beat the market.", "There is no risk.",
])
def test_banned_phrases(text):
    assert banned_phrases(text)
    assert check_text(text, INDEX)


@pytest.mark.parametrize("text", [
    "Out-of-sample period: 2007-01-03 to 2026-10-16.",
    "2026 YTD (through October 16, 2026) and 10/16/2026.",
])
def test_dates_are_not_numbers(text):
    assert unsupported_numbers(text, INDEX) == []


@pytest.mark.parametrize("text, blocked", [
    ("Treasuries are not a guaranteed hedge.", False),          # regression: flagged in a live bio
    ("Past performance does not guarantee future results.", False),
    ("There is no guarantee of profit.", False),
    ("Not only is it guaranteed, it compounds.", True),
    ("Income is guaranteed.", True),
])
def test_guarantee_negation(text, blocked):
    assert bool(banned_phrases(text)) == blocked


def test_urgency_language_blocked():
    assert banned_phrases("Why Consider It Now") and banned_phrases("Act now to protect gains.")


def test_persona_mentions():
    from strategy.guardrails import persona_mentions
    team = {"members": [{"name": "Elena Vasquez-Park"}, {"name": "Daniel Okafor"}]}
    assert persona_mentions("Contact Elena Vasquez-Park to learn more.", team) == ["Elena Vasquez-Park"]
    assert persona_mentions("Okafor leads research.", team) == ["Daniel Okafor"]
    assert persona_mentions("Our investment team reviews signals.", team) == []


def test_clean_text_passes():
    assert check_text("Designed to reduce drawdowns; it may lag in strong rallies.", INDEX) == []
