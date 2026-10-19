"""Shared test data: a valid fictional team."""

import copy

from strategy.team import CURRENT_YEAR


def member(name, role, title, focus, certs=("CFA",), years=12):
    start = CURRENT_YEAR - years
    return {
        "name": name, "role": role, "title": title, "focus": focus,
        "education": [{"degree": "MS", "field": "Financial Engineering", "institution": "Columbia University", "year": start - 1}],
        "certifications": list(certs),
        "experience": [{"firm": "Harborview Capital Partners", "title": "Associate", "years": f"{start}-{start + 5}"}],
        "years_experience": years,
        "bio": (f"{name} brings a disciplined, research-driven approach to {focus.lower()}. "
                "Earlier roles at fictional firms built deep experience in systematic investing, and "
                "the team relies on this member for careful, well-documented decisions."),
    }


VALID_TEAM = [
    member("Elena Marchetti", "Portfolio Manager", "Portfolio Manager", "Strategy oversight and allocation", ("CFA", "CAIA"), 22),
    member("Daniel Okafor", "Analyst", "Quantitative Research Analyst", "Signal design and walk-forward testing", ("CQF",)),
    member("Priya Raman", "Analyst", "Risk Analyst", "Drawdown and risk management", ("FRM",)),
    member("Marcus Lindqvist", "Analyst", "Macro & Rates Analyst", "Interest rates and Treasury duration", ("CFA",)),
    member("Sofia Alvarez", "Analyst", "Data Engineer", "Market data and backtest integrity", ()),
    member("James Whitfield", "Analyst", "Trading Analyst", "Execution and rebalancing", ("CMT",)),
]


def team(**changes):
    t = copy.deepcopy(VALID_TEAM)
    for idx, fields in changes.items():
        t[int(idx.strip("m"))].update(fields)
    return t
