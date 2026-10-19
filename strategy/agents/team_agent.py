"""Team Agent: creates the fictional digital investment team (1 PM + 5 analysts)."""

from strategy.agents.runtime import Agent, Tool, ToolError, schema
from strategy.paths import write_json
from strategy.team import ALLOWED_CERTIFICATIONS, CURRENT_YEAR, validate_team

PROMPT = """You are the Team Agent. You create a "digital investment team" of AI personas who will present two systematic strategies to investors: a SPY/IEF moving-average trend rotation, and a monthly multi-asset momentum strategy across SPY, QQQ, TLT, GLD, IWM and IEF. The team is explicitly fictional, and the final document labels every member as an AI-generated fictional persona.

Create exactly 6 members: 1 Portfolio Manager and 5 Analysts. Each analyst has a distinct focus that clearly matters to this strategy, such as quantitative research and signal design, risk management, macro and interest rates (the IEF side), market data engineering and backtest integrity, and trading and execution or investor communications.

For each member provide:
- a realistic but invented full name, and a title
- education (1-3 entries): degree, field, institution and graduation year. Real universities are fine.
- certifications drawn only from: {certs}. An empty list is fine for some people.
- 1-4 past roles at FICTIONAL firms. Invent plausible names such as "Harborview Capital Partners", and never use real banks, asset managers, hedge funds or regulators.
- years_experience equal to the current year minus the start year of their earliest role, within 2 years. The current year is {year}.
- a 60-110 word third-person bio: background, what they own on this team, and one distinctive strength

Make the team credible and varied: a mix of seniority, educational paths and backgrounds, with the PM the most senior. Don't use famous people's names. Don't include performance claims or numbers about the strategy in the bios.

Submit the team with submit_team. If validation rejects it, fix exactly what's reported and resubmit. When it's accepted, reply with a one-line summary."""

MEMBER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["name", "role", "title", "focus", "education", "certifications", "experience",
                 "years_experience", "bio"],
    "properties": {
        "name": {"type": "string"},
        "role": {"type": "string", "enum": ["Portfolio Manager", "Analyst"]},
        "title": {"type": "string"}, "focus": {"type": "string"},
        "education": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                      "required": ["degree", "field", "institution", "year"],
                      "properties": {"degree": {"type": "string"}, "field": {"type": "string"},
                                     "institution": {"type": "string"}, "year": {"type": "integer"}}}},
        "certifications": {"type": "array", "items": {"type": "string", "enum": sorted(ALLOWED_CERTIFICATIONS)}},
        "experience": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                       "required": ["firm", "title", "years"],
                       "properties": {"firm": {"type": "string"}, "title": {"type": "string"},
                                      "years": {"type": "string"}}}},
        "years_experience": {"type": "integer"},
        "bio": {"type": "string"},
    },
}


def build(ctx):
    def submit(members):
        ctx.record("submit_team", n=len(members))
        team, error = validate_team(members)
        if error:
            raise ToolError(error)
        ctx.team = team
        write_json(ctx.path("team.json"), team)
        return {"accepted": True, "members": [f"{m['name']} ({m['title']})" for m in team["members"]]}

    tools = [Tool("submit_team", "Submit the 6-member team for validation and saving.",
                  schema({"members": {"type": "array", "items": MEMBER_SCHEMA, "minItems": 6, "maxItems": 6}},
                         ["members"]), submit)]
    prompt = PROMPT.format(certs=", ".join(sorted(ALLOWED_CERTIFICATIONS)), year=CURRENT_YEAR)
    return Agent(ctx.client, "Team Agent", prompt, tools, ctx.trace, effort="low",
                 max_turns=8, token_budget=ctx.cfg.token_budget, model=ctx.cfg.model)


def task(ctx):
    return "Create the digital investment team for the trend rotation and multi-asset momentum strategies."
