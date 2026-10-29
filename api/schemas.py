from pydantic import BaseModel, Field
from datetime import date


class SearchOut(BaseModel):
    key: str      # "data analyst|alberta"
    role: str
    region: str

    @classmethod
    def from_key(cls, key: str) -> "SearchOut":
        role, region = key.split("|", 1)
        return cls(key=key, role=role, region=region)

class SkillOut(BaseModel):
    skill: str = Field(examples=["SQL"])
    category: str = Field(examples=["language"])
    postings: int = Field(description="The amount of active postings that mention this skill")
    share: float = Field(description="Fraction of active postings mentioning this skill")
    change: float | None = Field(default = None, description="Change in share currently vs. 7 days earlier, null given no comparison possible")

class SkillTrendsOut(BaseModel):
    search: SearchOut # The search (role and region that form key)
    day: date # Current day for these numbers
    skills: list[SkillOut] # Nested list of skill info, ordered most-mentioned first


class SalaryPointOut(BaseModel):
    day: date
    sample_size: int = Field("Number of postings for this job")
    p25: float | None = Field(default = None, description="Bottom 25th percentile of salaries for this job")
    median: float | None = Field(default = None, description="Median salary for this job")
    p75: float | None = Field(default = None, description="Top 75% percentile of salaries for this job")

class SalaryTrendsOut(BaseModel):
    search: SearchOut
    points: list[SalaryPointOut]

class DemandPointOut(BaseModel):