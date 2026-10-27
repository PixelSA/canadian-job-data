"""Database schema.

Four layers, each derived from the one before it:

  raw_postings       exact API payloads, never modified (lets us reprocess history)
  postings           deduplicated, normalized jobs with first_seen / last_seen
  posting_searches   which tracked role/region searches each posting belongs to
  posting_skills     skills found in each posting, tagged with extractor_version
  daily_skill_stats  pre-aggregated counts the API/frontend reads
  daily_salary_stats
  monthly_demand_stats  long-run history from monthly snapshot files (Job Bank)

plus bookkeeping: ingestion_runs (log of every run), api_usage (request budgets for
quota-limited APIs), loaded_files (bulk files already imported).
"""

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class RawPosting(Base):
    __tablename__ = "raw_postings"
    __table_args__ = (UniqueConstraint("source", "source_id", "payload_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    source_id: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"))


class Posting(Base):
    __tablename__ = "postings"
    __table_args__ = (UniqueConstraint("source", "source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(128))
    # Same job seen via two sources shares a fingerprint; aggregates count fingerprints, not rows.
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)

    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str | None] = mapped_column(String(200), index=True)
    location: Mapped[str | None] = mapped_column(String(200))
    # Canadian NOC 2021 occupation code (Job Bank); groups "BI analyst", "data analyst", ...
    occupation_code: Mapped[str | None] = mapped_column(String(10), index=True)
    vacancies: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text, default="")
    description_is_full: Mapped[bool] = mapped_column(default=True)
    url: Mapped[str | None] = mapped_column(String(1000))
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_is_estimate: Mapped[bool] = mapped_column(default=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    first_seen: Mapped[date] = mapped_column(Date, index=True)
    last_seen: Mapped[date] = mapped_column(Date, index=True)
    # None means "needs (re)extraction"; set when skills are written.
    extractor_version: Mapped[str | None] = mapped_column(String(32))

    skills: Mapped[list["PostingSkill"]] = relationship(
        back_populates="posting", cascade="all, delete-orphan"
    )
    searches: Mapped[list["PostingSearch"]] = relationship(
        back_populates="posting", cascade="all, delete-orphan"
    )


class PostingSearch(Base):
    """Which tracked searches (e.g. 'data analyst|alberta') a posting belongs to."""

    __tablename__ = "posting_searches"
    __table_args__ = (UniqueConstraint("posting_id", "search_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    posting_id: Mapped[int] = mapped_column(ForeignKey("postings.id", ondelete="CASCADE"))
    search_key: Mapped[str] = mapped_column(String(200), index=True)

    posting: Mapped[Posting] = relationship(back_populates="searches")


class PostingSkill(Base):
    __tablename__ = "posting_skills"
    __table_args__ = (UniqueConstraint("posting_id", "skill"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    posting_id: Mapped[int] = mapped_column(ForeignKey("postings.id", ondelete="CASCADE"))
    skill: Mapped[str] = mapped_column(String(100), index=True)
    category: Mapped[str] = mapped_column(String(50))
    extractor_version: Mapped[str] = mapped_column(String(32))

    posting: Mapped[Posting] = relationship(back_populates="skills")


class DailySkillStat(Base):
    __tablename__ = "daily_skill_stats"
    __table_args__ = (UniqueConstraint("day", "search_key", "skill"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    search_key: Mapped[str] = mapped_column(String(200), index=True)
    skill: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50))
    active_postings: Mapped[int] = mapped_column(Integer)  # postings mentioning skill still live
    share: Mapped[float] = mapped_column(Float)  # active_postings / all active postings


class DailySalaryStat(Base):
    __tablename__ = "daily_salary_stats"
    __table_args__ = (UniqueConstraint("day", "search_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    search_key: Mapped[str] = mapped_column(String(200), index=True)
    sample_size: Mapped[int] = mapped_column(Integer)
    p25: Mapped[float | None] = mapped_column(Float)
    median: Mapped[float | None] = mapped_column(Float)
    p75: Mapped[float | None] = mapped_column(Float)


class MonthlyDemandStat(Base):
    """New postings per month from snapshot sources (Job Bank): long-run demand + salary history."""

    __tablename__ = "monthly_demand_stats"
    __table_args__ = (UniqueConstraint("month", "search_key", "source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[date] = mapped_column(Date, index=True)  # first day of the month
    search_key: Mapped[str] = mapped_column(String(200), index=True)
    source: Mapped[str] = mapped_column(String(32))
    new_postings: Mapped[int] = mapped_column(Integer)
    vacancies: Mapped[int] = mapped_column(Integer)
    salary_sample_size: Mapped[int] = mapped_column(Integer)
    salary_p25: Mapped[float | None] = mapped_column(Float)
    salary_median: Mapped[float | None] = mapped_column(Float)
    salary_p75: Mapped[float | None] = mapped_column(Float)


class ApiUsage(Base):
    """Calls made to quota-limited APIs, per billing period ('2026-10' or 'lifetime')."""

    __tablename__ = "api_usage"
    __table_args__ = (UniqueConstraint("source", "period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    period: Mapped[str] = mapped_column(String(16))
    calls: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow,
                                                 onupdate=utcnow)


class LoadedFile(Base):
    """Bulk files already ingested (Job Bank monthly CSVs), so reruns skip them."""

    __tablename__ = "loaded_files"
    __table_args__ = (UniqueConstraint("source", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(1000))
    rows_loaded: Mapped[int] = mapped_column(Integer, default=0)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    new_postings: Mapped[int] = mapped_column(Integer, default=0)
    updated_postings: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[list] = mapped_column(JSON, default=list)  # e.g. "jsearch: monthly budget used"


def make_session_factory(database_url: str):
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
