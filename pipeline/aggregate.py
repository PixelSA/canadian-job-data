"""Roll postings up into the small daily tables the API serves.

A posting counts as "active" on a day if it was first seen on/before that day and last seen
within GRACE_DAYS of it (sources occasionally miss a posting for a day).
Duplicates across sources (same fingerprint) count once; their skills are unioned, so a
full Greenhouse description can fill in for a truncated Adzuna snippet of the same job.

Snapshot sources (Job Bank monthly files) only say when a posting first appeared, not when
it closed, so they are kept out of the daily "active" stats and rolled up monthly instead.
"""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from pipeline.db import (
    DailySalaryStat,
    DailySkillStat,
    MonthlyDemandStat,
    Posting,
    PostingSearch,
)

GRACE_DAYS = 2
SNAPSHOT_SOURCES = ("jobbank",)


def percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0, 1]."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def _salary_point(p: Posting) -> float | None:
    if p.salary_is_estimate:
        return None
    values = [v for v in (p.salary_min, p.salary_max) if v]
    return sum(values) / len(values) if values else None


def aggregate_day(session: Session, day: date, search_keys: list[str]) -> None:
    for key in search_keys:
        postings = session.scalars(
            select(Posting)
            .join(PostingSearch)
            .where(
                PostingSearch.search_key == key,
                Posting.source.not_in(SNAPSHOT_SOURCES),
                Posting.first_seen <= day,
                Posting.last_seen >= day - timedelta(days=GRACE_DAYS),
            )
            .options(selectinload(Posting.skills))
        ).all()

        jobs: dict[str, list[Posting]] = defaultdict(list)
        for p in postings:
            jobs[p.fingerprint].append(p)

        skill_jobs: dict[str, set[str]] = defaultdict(set)
        categories: dict[str, str] = {}
        salaries: list[float] = []
        for fp, group in jobs.items():
            for p in group:
                for s in p.skills:
                    skill_jobs[s.skill].add(fp)
                    categories[s.skill] = s.category
            points = [x for x in map(_salary_point, group) if x]
            if points:
                salaries.append(max(points))

        session.execute(
            delete(DailySkillStat).where(DailySkillStat.day == day, DailySkillStat.search_key == key)
        )
        session.execute(
            delete(DailySalaryStat).where(
                DailySalaryStat.day == day, DailySalaryStat.search_key == key
            )
        )
        total = len(jobs)
        for skill, fps in skill_jobs.items():
            session.add(DailySkillStat(
                day=day, search_key=key, skill=skill, category=categories[skill],
                active_postings=len(fps), share=len(fps) / total,
            ))
        salaries.sort()
        session.add(DailySalaryStat(
            day=day, search_key=key, sample_size=len(salaries),
            p25=percentile(salaries, 0.25) if salaries else None,
            median=percentile(salaries, 0.5) if salaries else None,
            p75=percentile(salaries, 0.75) if salaries else None,
        ))
    session.commit()


def _next_month(month: date) -> date:
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


def aggregate_month(
    session: Session, month: date, search_keys: list[str], source: str = "jobbank"
) -> None:
    """New postings, vacancies and salary range for one month of a snapshot source."""
    month = month.replace(day=1)
    for key in search_keys:
        postings = session.scalars(
            select(Posting)
            .join(PostingSearch)
            .where(
                PostingSearch.search_key == key,
                Posting.source == source,
                Posting.first_seen >= month,
                Posting.first_seen < _next_month(month),
            )
        ).all()
        # One job listed in many towns shares a fingerprint: count it once, and take its
        # largest per-town vacancy count rather than summing across towns.
        jobs: dict[str, Posting] = {}
        for p in postings:
            best = jobs.get(p.fingerprint)
            if best is None or (p.vacancies or 1) > (best.vacancies or 1):
                jobs[p.fingerprint] = p
        postings = list(jobs.values())
        salaries = sorted(x for x in map(_salary_point, postings) if x)

        session.execute(delete(MonthlyDemandStat).where(
            MonthlyDemandStat.month == month, MonthlyDemandStat.search_key == key,
            MonthlyDemandStat.source == source,
        ))
        session.add(MonthlyDemandStat(
            month=month, search_key=key, source=source,
            new_postings=len(postings),
            vacancies=sum(p.vacancies or 1 for p in postings),
            salary_sample_size=len(salaries),
            salary_p25=percentile(salaries, 0.25) if salaries else None,
            salary_median=percentile(salaries, 0.5) if salaries else None,
            salary_p75=percentile(salaries, 0.75) if salaries else None,
        ))
    session.commit()
