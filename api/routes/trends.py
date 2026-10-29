from api.deps import SearchKey
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from api.db import get_session
from api.schemas import SearchOut, SkillTrendsOut, SkillOut
from pipeline.db import PostingSearch, DailySkillStat

from datetime import date, timedelta


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
