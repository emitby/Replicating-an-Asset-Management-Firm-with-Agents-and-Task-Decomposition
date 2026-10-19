"""The digital investment team: schema and validation.

Guardrails:
- Exactly one Portfolio Manager and five analysts.
- Certifications come from a fixed allowlist of real designations.
- Personas are fictional. Past employers may not be well-known real firms, and
  names may not match well-known finance figures. Real universities are
  allowed, because every bio is stamped "AI-generated fictional persona" when
  rendered.
"""

import re
from typing import List, Literal

from datetime import date

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from strategy.guardrails import banned_phrases

CURRENT_YEAR = date.today().year

ALLOWED_CERTIFICATIONS = {"CFA", "CAIA", "FRM", "CMT", "CPA", "CQF", "PRM", "CIPM"}

REAL_FIRMS = {
    "goldman sachs", "jpmorgan", "j.p. morgan", "jp morgan", "morgan stanley", "blackrock", "vanguard",
    "fidelity", "bridgewater", "citadel", "two sigma", "renaissance", "aqr", "pimco", "state street",
    "bank of america", "merrill", "citigroup", "citi", "ubs", "credit suisse", "deutsche bank", "barclays",
    "wells fargo", "schwab", "invesco", "t. rowe", "millennium", "point72", "d. e. shaw", "de shaw",
    "elliott", "man group", "nomura", "hsbc", "bnp paribas", "jane street", "susquehanna", "federal reserve",
}
FAMOUS_NAMES = {
    "warren buffett", "ray dalio", "jim simons", "ken griffin", "cathie wood", "peter lynch",
    "john bogle", "jack bogle", "bill gross", "george soros", "stanley druckenmiller", "howard marks",
    "jamie dimon", "larry fink", "paul tudor jones", "carl icahn", "bill ackman", "david tepper",
    "michael burry", "cliff asness", "benjamin graham", "charlie munger", "seth klarman",
}
FICTIONAL_LABEL = "AI-generated fictional persona"


class Education(BaseModel):
    degree: str = Field(min_length=2, max_length=60)
    field: str = Field(min_length=2, max_length=80)
    institution: str = Field(min_length=3, max_length=100)
    year: int = Field(ge=1970, le=2026)


class Experience(BaseModel):
    firm: str = Field(min_length=3, max_length=80)
    title: str = Field(min_length=3, max_length=80)
    years: str = Field(min_length=4, max_length=20, description="e.g. '2012-2018'")

    @field_validator("firm")
    @classmethod
    def fictional_firm(cls, v):
        low = v.lower()
        hit = next((f for f in REAL_FIRMS if re.search(rf"(?<![a-z]){re.escape(f)}(?![a-z])", low)), None)
        if hit:
            raise ValueError(f"'{v}' looks like a real firm ({hit}); use a fictional firm name")
        return v


class Member(BaseModel):
    name: str = Field(min_length=3, max_length=60)
    role: Literal["Portfolio Manager", "Analyst"]
    title: str = Field(min_length=3, max_length=80)
    focus: str = Field(min_length=3, max_length=120)
    education: List[Education] = Field(min_length=1, max_length=3)
    certifications: List[str] = Field(max_length=4)
    experience: List[Experience] = Field(min_length=1, max_length=4)
    years_experience: int = Field(ge=1, le=45)
    bio: str = Field(min_length=120, max_length=700)

    @model_validator(mode="after")
    def experience_consistent(self):
        """years_experience must match the career dates (within 2 years) as of the current year."""
        starts = [int(m.group()) for e in self.experience if (m := re.match(r"\d{4}", e.years))]
        if starts:
            implied = CURRENT_YEAR - min(starts)
            if abs(self.years_experience - implied) > 2:
                raise ValueError(f"{self.name}: years_experience={self.years_experience} but career starts "
                                 f"{min(starts)}, i.e. about {implied} years as of {CURRENT_YEAR}")
        return self

    @field_validator("bio")
    @classmethod
    def compliant_bio(cls, v):
        hits = banned_phrases(v)
        if hits:
            raise ValueError(f"non-compliant language in bio: {hits}")
        return v

    @field_validator("name")
    @classmethod
    def not_famous(cls, v):
        if v.lower().strip() in FAMOUS_NAMES:
            raise ValueError(f"'{v}' is a well-known real person; invent a name")
        return v

    @field_validator("certifications")
    @classmethod
    def known_certs(cls, v):
        bad = [c for c in v if c not in ALLOWED_CERTIFICATIONS]
        if bad:
            raise ValueError(f"unknown certifications {bad}; allowed: {sorted(ALLOWED_CERTIFICATIONS)}")
        return v


class Team(BaseModel):
    members: List[Member] = Field(min_length=6, max_length=6)

    @field_validator("members")
    @classmethod
    def composition(cls, v):
        pms = [m for m in v if m.role == "Portfolio Manager"]
        if len(pms) != 1:
            raise ValueError(f"need exactly 1 Portfolio Manager, got {len(pms)}")
        names = [m.name.lower() for m in v]
        if len(set(names)) != len(names):
            raise ValueError("member names must be unique")
        focuses = [m.focus.lower() for m in v if m.role == "Analyst"]
        if len(set(focuses)) != 5:
            raise ValueError("each analyst needs a distinct focus")
        return v


def validate_team(members):
    """Return (team_dict, None) or (None, error_text)."""
    try:
        team = Team(members=members)
    except ValidationError as exc:
        errors = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:12])
        return None, f"Team rejected: {errors}"
    data = team.model_dump()
    data["members"].sort(key=lambda m: m["role"] != "Portfolio Manager")
    data["label"] = FICTIONAL_LABEL
    return data, None
