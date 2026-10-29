"""Content guardrails for anything an agent writes that reaches the PDF.

1. Numeric faithfulness: every number in agent-written text must match a
   computed result (analytics, backtest, data report) or a configured constant,
   within the rounding the text uses. Agents can't introduce numbers.
2. Compliance language: phrases that promise returns or deny risk are blocked.

Violations go back to the agent as tool errors so it can rewrite. The harness
runs the same checks again before the PDF is built, and the evals run them a
third time on the final PDF.
"""

import math
import re

from strategy.config import TRADING_DAYS

BANNED_PATTERNS = [
    r"\bguarantee(d|s)?\b", r"\brisk[- ]free (return|profit|investment)", r"\bcan(no|')t lose\b",
    r"\bcannot lose\b", r"\bno risk\b", r"\bwithout risk\b", r"\brisk-?less\b", r"\bsure thing\b",
    r"\bnever lose", r"\bwill (outperform|beat|deliver|return|generate)\b", r"\bcertain(ly)? to\b",
    r"\bproven to (beat|outperform)\b", r"\bfree money\b",
    # sales urgency / market-timing calls
    r"\bact now\b", r"\bdon'?t miss\b", r"\bnow is the (time|moment)\b", r"\bwhy .{0,20}\bnow\b",
    r"\blimited time\b",
    # overclaiming certainty about a rules-based selection
    r"\balways (picks|wins|beats|outperforms|chooses the (winner|best))\b", r"\bnever (misses|underperforms)\b",
    # marketing overclaims about diversification (the deck has a positive portfolio-fit section)
    r"\beliminat\w* (all |the )?(risk|losses|drawdowns)\b",
    r"\b(protects?|shields?|insulates?) (you |investors |portfolios? )?(from|against) (all )?"
    r"(losses|drawdowns|downturns|crashes)\b",
]


def persona_mentions(text, team):
    """Names of fictional team members in agent-written slide text. Personas may
    appear only on the code-rendered team pages, which carry the fictional label."""
    if not team:
        return []
    hits = []
    for m in team.get("members", []):
        parts = m["name"].split()
        if m["name"] in text or (len(parts) > 1 and re.search(rf"\b{re.escape(parts[-1])}\b", text)):
            hits.append(m["name"])
    return hits
_BANNED = [re.compile(p, re.IGNORECASE) for p in BANNED_PATTERNS]

# A number not preceded by a letter (skips "MA200", "Q3"), with optional $, sign, commas, decimals, %.
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9.^])([-−+]?)\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s?(%|x\b|bps\b)?")
WORD_CONSTANTS = {1, 3, 5, 6, 12, 36, 60, TRADING_DAYS}   # window lengths in years/months, team size


_GUARANTEE = _BANNED[0]
# The negation must directly qualify the word: "not guaranteed", "not a guaranteed", "no guarantee",
# "does not guarantee". "Not only is it guaranteed" doesn't qualify.
_NEGATION_BEFORE = re.compile(r"(\b(not|no|never|without|nor)\b|n't)\s+((a|an|any|be|been|always)\s+)?$",
                              re.IGNORECASE)


def banned_phrases(text):
    hits = set()
    for p in _BANNED:
        for m in p.finditer(text):
            # "does not guarantee", "no guarantee", "not a guaranteed hedge" are cautionary, not promises.
            if p is _GUARANTEE and _NEGATION_BEFORE.search(text[max(0, m.start() - 25):m.start()]):
                continue
            hits.add(m.group(0))
    return sorted(hits)


def _numeric_leaves(obj):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        if math.isfinite(obj):
            yield float(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _numeric_leaves(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _numeric_leaves(v)


class NumberIndex:
    """All values agents may cite, in raw and percent form."""

    def __init__(self, *sources, constants=(), years=(1990, 2100)):
        vals = set()
        for src in sources:
            for v in _numeric_leaves(src):
                vals.update({v, abs(v), v * 100, abs(v) * 100})
        vals.update(float(c) for c in constants)
        vals.update(float(c) for c in WORD_CONSTANTS)
        self.values = sorted(vals)
        self.years = years

    def matches(self, number, decimals):
        tol = 0.5 * 10 ** (-decimals) + 1e-9
        # values are sorted: binary-search the window [number - tol, number + tol]
        lo, hi = 0, len(self.values)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.values[mid] < number - tol:
                lo = mid + 1
            else:
                hi = mid
        return lo < len(self.values) and self.values[lo] <= number + tol


MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
DATE_RES = [re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),                       # 2026-10-16
            re.compile(rf"\b{MONTHS}\s+\d{{1,2}},?\s+\d{{4}}\b"),        # October 16, 2026
            re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")]                  # 10/16/2026


def extract_numbers(text):
    """Yield (value, decimals, raw_text, unit) for each number in prose. Dates are skipped."""
    for date_re in DATE_RES:
        text = date_re.sub(" ", text)
    for m in NUMBER_RE.finditer(text):
        sign, whole, frac, unit = m.groups()
        value = float(whole.replace(",", "") + (frac or ""))
        if sign in ("-", "−"):
            value = -value
        yield value, len(frac) - 1 if frac else 0, m.group(0).strip(), unit


def unsupported_numbers(text, index):
    bad = []
    for value, decimals, raw, unit in extract_numbers(text):
        if decimals == 0 and unit is None and index.years[0] <= value <= index.years[1]:
            continue  # a calendar year
        if not (index.matches(value, decimals) or index.matches(abs(value), decimals)):
            bad.append(raw)
    return bad


def check_text(text, index):
    """List of human-readable violations (empty = OK)."""
    problems = []
    phrases = banned_phrases(text)
    if phrases:
        problems.append(f"Non-compliant language: {phrases}. Don't promise returns or deny risk.")
    nums = unsupported_numbers(text, index)
    if nums:
        problems.append(f"Numbers not found in the computed results: {nums}. Use only values from "
                        f"the tools, rounded as given (percentages to 1 decimal, ratios to 2).")
    return problems
