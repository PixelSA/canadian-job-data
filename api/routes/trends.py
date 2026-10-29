from api.deps import SearchKey
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from api.db import get_session

from api.schemas import SearchOut, SkillTrendsOut, SkillOut, SalaryPointOut, SalaryTrendsOut, DemandPointOut, DemandTrendsOut
from pipeline.db import PostingSearch, DailySkillStat, DailySalaryStat, MonthlyDemandStat

from datetime import date, timedelta

SERIES_BREAKS = {
    date(2025, 7, 1): "Job Bank stopped including partner-board postings; counts before and after aren't comparable",
}

router = APIRouter(tags=["trends"])

@router.get("/trends/skills", response_model=SkillTrendsOut)
def top_skills(key: SearchKey, session = Depends(get_session), limit: int = Query(20, ge = 1, le = 100)):
    # Get the most recent skills related to this job
    # TODO: Find latest day in daily_skill_stats for this key
    latest_day = session.scalar(select(func.max(DailySkillStat.day)).where(DailySkillStat.search_key == key))
    if latest_day is None:
        raise HTTPException(
            status_code=404,
            detail = {
                "message": f"No skill data found",
            },
        )

    # TODO: Given the latest day, find that day's top skills

    rows = session.scalars(
        select(DailySkillStat)
        .where(DailySkillStat.search_key == key, DailySkillStat.day == latest_day)
        .order_by(DailySkillStat.active_postings.desc(), DailySkillStat.skill)
        .limit(limit)).all()

    # TODO: Get last week's shares to calculate change
    last_rows = session.scalars(
        select(DailySkillStat)
        .where(DailySkillStat.search_key == key, DailySkillStat.day == latest_day - timedelta(days=7))
        )

    prev_skills = {row.skill : row.share for row in last_rows}

    skills = []

    for row in rows:
        if row.skill in prev_skills:
            change = row.share - prev_skills[row.skill]
        else:
            change = None

        skills.append(SkillOut(
            skill = row.skill,
            category = row.category,
            postings = row.active_postings, 
            share = row.share,
            change = change,
        ))
    
    return SkillTrendsOut(search=SearchOut.from_key(key), day=latest_day, skills=skills)



@router.get("/trends/salaries", response_model=SalaryTrendsOut)
def salary_trends(key: SearchKey, days: int = Query(30, ge = 1, le=365), session = Depends(get_session)):
    since = date.today() - timedelta(days=days)
    rows = session.scalars(
        select(DailySalaryStat)
        .where(DailySalaryStat.search_key == key, DailySalaryStat.day >= since)
        .order_by(DailySalaryStat.day.asc())).all()

    points = [SalaryPointOut(day = row.day, sample_size = row.sample_size, p25 = row.p25, median = row.median, p75=row.p75) for row in rows]


    return SalaryTrendsOut(search=SearchOut.from_key(key), points=points)

@router.get("/trends/demand", response_model = DemandTrendsOut)
def demand_trends(
    key: SearchKey,
    since: date | None = Query(None, description="First month to include; omit for full history"),
    session: Session = Depends(get_session),
):
    query = (
        select(MonthlyDemandStat)
        .where(MonthlyDemandStat.search_key == key, MonthlyDemandStat.source == "jobbank")
        .order_by(MonthlyDemandStat.month)
    )
    if since is not None:
        query = query.where(MonthlyDemandStat.month >= since)

    rows = session.scalars(query).all()

    points = [DemandPointOut(month = row.month, 
                             new_postings= row.new_postings,
                            vacancies = row.vacancies,
                            salary_sample_size= row.salary_sample_size,
                            p25=row.salary_p25,
                            median=row.salary_median,
                            p75=row.salary_p75,
                            note=SERIES_BREAKS.get(row.month)) for row in rows]

    return DemandTrendsOut(search=SearchOut.from_key(key), points=points)
