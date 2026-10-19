import pytest

from fixtures import VALID_TEAM, team
from strategy.team import FICTIONAL_LABEL, validate_team


def test_valid_team_accepted_pm_first():
    data, err = validate_team(team())
    assert err is None
    assert data["members"][0]["role"] == "Portfolio Manager"
    assert data["label"] == FICTIONAL_LABEL


@pytest.mark.parametrize("changes, expected", [
    ({"m1": {"experience": [{"firm": "Goldman Sachs Asset Management", "title": "VP", "years": "2010-2015"}]}}, "real firm"),
    ({"m2": {"name": "Ray Dalio"}}, "well-known"),
    ({"m3": {"certifications": ["CFP"]}}, "unknown certifications"),
    ({"m4": {"role": "Portfolio Manager"}}, "exactly 1 Portfolio Manager"),
    ({"m5": {"focus": "Signal design and walk-forward testing"}}, "distinct focus"),
    ({"m1": {"bio": "Too short."}}, "bio"),
])
def test_invalid_teams_rejected(changes, expected):
    data, err = validate_team(team(**changes))
    assert data is None and expected in err


def test_experience_years_must_match_career_dates():
    """Regression: a persona whose career began in 1997 was shown with 26 years' experience."""
    _, err = validate_team(team(m1={"years_experience": 3}))
    assert err and "years_experience" in err


def test_wrong_size_rejected():
    _, err = validate_team(VALID_TEAM[:5])
    assert err and "members" in err


def test_fictional_firm_with_similar_word_allowed():
    data, err = validate_team(team(m1={"experience": [{"firm": "Citizens Ridge Partners", "title": "Analyst", "years": "2012-2016"}]}))
    assert err is None
