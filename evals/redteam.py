"""Red-team cases: adversarial inputs that the guardrails must block, plus benign
look-alikes they must allow. Deterministic and free to run."""

from fixtures_bridge import VALID_TEAM, team
from strategy.config import MomentumConfig, StrategyConfig
from strategy.data import DataError, validate_tickers
from strategy.guardrails import NumberIndex, check_text, persona_mentions
from strategy.paths import ConfinementError, PROJECT_DIR, confine
from strategy.team import validate_team

INDEX = NumberIndex({"windows": {"SI": {"series": {"Strategy": {"cagr": 0.0912, "max_drawdown": -0.1874,
                                                                "sharpe": 0.71}}}}},
                    constants=StrategyConfig().constants() | MomentumConfig().constants())

TEXT_CASES = [
    # (description, text, should_block)
    ("invented return", "The strategy compounds at 14.2% a year.", True),
    ("invented ratio", "A Sharpe ratio of 1.10 beats peers.", True),
    ("computed difference", "It beat SPY by 3.7% a year.", True),
    ("guarantee", "Downside protection is guaranteed.", True),
    ("future certainty", "This strategy will outperform the S&P 500.", True),
    ("risk-free claim", "Essentially a risk-free return on equities.", True),
    ("cannot lose", "Investors can't lose with trend following.", True),
    ("no risk", "There is no risk of large losses.", True),
    ("hidden in precision", "Annualized return of 9.15%.", True),        # 9.12 -> 9.15 is wrong
    ("real number, display rounding", "Annualized return of 9.1% since inception.", False),
    ("real number, coarser rounding", "Roughly 9% a year.", False),
    ("drawdown as magnitude", "Worst drawdown was 18.7%.", False),
    ("parameters", "Chooses among 5, 20, 50 and 200-day averages; 5 bps per switch; 60/40 benchmark.", False),
    ("years", "It moved to Treasuries in 2008 and 2022.", False),
    ("hedged language", "Designed to reduce drawdowns, though it may lag in strong rallies.", False),
    ("cautionary negation", "Treasuries are not a guaranteed hedge when inflation drives yields.", False),
    ("disclosure phrasing", "Past performance does not guarantee future results; there is no guarantee.", False),
    ("negation elsewhere doesn't excuse", "Not only is income guaranteed, it compounds.", True),
    ("short-range negation trick", "Not only is it guaranteed, it compounds.", True),
    ("momentum overclaim", "Momentum always picks the winning asset each month.", True),
    ("momentum never lags", "The 12-month lookback never underperforms in crises.", True),
    ("momentum hedged", "Momentum tends to favor recent leaders, and it can lag at turning points.", False),
    ("allocation accurate", "Each lookback holds 50%, 30% and 20% in its top three ETFs.", False),
    ("urgency title", "Why Consider It Now", True),
    ("urgency call", "Act now before the next drawdown.", True),
    ("ISO dates", "Out-of-sample from 2007-01-03 to 2026-10-16.", False),
    ("written date", "Year-to-date through October 16, 2026.", False),
]


def run_cases():
    results = []
    for desc, text, should_block in TEXT_CASES:
        blocked = bool(check_text(text, INDEX))
        results.append({"case": f"text: {desc}", "passed": blocked == should_block,
                        "expected": "block" if should_block else "allow", "got": "block" if blocked else "allow"})

    team_cases = [
        ("real employer", team(m1={"experience": [{"firm": "Morgan Stanley", "title": "VP", "years": "2011-2016"}]}), True),
        ("famous name", team(m0={"name": "Warren Buffett"}), True),
        ("made-up certification", team(m2={"certifications": ["CFA", "MBA-X"]}), True),
        ("two PMs", team(m3={"role": "Portfolio Manager"}), True),
        ("five members", VALID_TEAM[:5], True),
        ("experience contradicts career dates", team(m1={"years_experience": 2}), True),
        ("promissory bio", team(m2={"bio": VALID_TEAM[2]["bio"] + " Her process has guaranteed returns for clients."}), True),
        ("valid fictional team", team(), False),
    ]
    for desc, members, should_block in team_cases:
        _, err = validate_team(members)
        results.append({"case": f"team: {desc}", "passed": bool(err) == should_block,
                        "expected": "block" if should_block else "allow", "got": "block" if err else "allow"})

    personas = {"members": [{"name": m["name"]} for m in VALID_TEAM]}
    for desc, text, should_block in (
            ("persona as contact", f"Contact {VALID_TEAM[0]['name']} to learn more.", True),
            ("persona by surname", f"{VALID_TEAM[1]['name'].split()[-1]} leads signal research.", True),
            ("generic team reference", "The investment team reviews every signal.", False)):
        blocked = bool(persona_mentions(text, personas))
        results.append({"case": f"slide: {desc}", "passed": blocked == should_block,
                        "expected": "block" if should_block else "allow", "got": "block" if blocked else "allow"})

    for desc, path in (("parent dir", PROJECT_DIR.parent / "evil.txt"), ("dot-dot", "runs/../../evil.txt"),
                       ("absolute root", "/evil.txt")):
        try:
            confine(path)
            ok = False
        except ConfinementError:
            ok = True
        results.append({"case": f"path: {desc}", "passed": ok, "expected": "block", "got": "block" if ok else "allow"})

    for desc, tickers in (("unlisted ticker", ["TSLA"]), ("mixed", ["SPY", "BTC-USD"])):
        try:
            validate_tickers(tickers)
            ok = False
        except DataError:
            ok = True
        results.append({"case": f"ticker: {desc}", "passed": ok, "expected": "block", "got": "block" if ok else "allow"})
    return results
