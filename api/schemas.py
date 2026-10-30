from pydantic import BaseModel, Field, ConfigDict
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
    day: date | None # Current day for these numbers; null when the search has no daily stats yet
    skills: list[SkillOut] # Nested list of skill info, ordered most-mentioned first


class SalaryPointOut(BaseModel):
    day: date
    sample_size: int = Field(description="Number of postings for this job")
    p25: float | None = Field(default = None, description="Bottom 25th percentile of salaries for this job")
    median: float | None = Field(default = None, description="Median salary for this job")
    p75: float | None = Field(default = None, description="Top 75% percentile of salaries for this job")

class SalaryTrendsOut(BaseModel):
    search: SearchOut
    points: list[SalaryPointOut]

class DemandPointOut(BaseModel):
    month: date
    new_postings: int
    vacancies: int
    salary_sample_size: int
    p25: float | None = None
    median: float | None = None
    p75: float | None = None
    note: str | None = None

class DemandTrendsOut(BaseModel):
    search: SearchOut
    points: list[DemandPointOut]


class PostingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    title: str
    company: str | None
    location: str | None
    url: str | None
    salary_min: float | None
    salary_max: float | None
    salary_is_estimate: bool  # Adzuna's predicted pay, not stated by the employer
    source: str
    first_seen: date

class PostingsPage(BaseModel):
    search: SearchOut
    total: int
    limit: int
    offset: int
    postings: list[PostingOut]


class CompanyOut(BaseModel):
    company: str
    postings: int

class CompaniesOut(BaseModel):
    search: SearchOut
    companies: list[CompanyOut]