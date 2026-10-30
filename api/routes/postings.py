from api.deps import SearchKey
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from api.db import get_session

from api.schemas import PostingsPage, SearchOut, PostingOut, CompaniesOut, CompanyOut
from pipeline.db import PostingSearch, Posting
from pipeline.aggregate import GRACE_DAYS, SNAPSHOT_SOURCES

from datetime import date, timedelta

router = APIRouter(tags=["postings"])


def active_conditions(key: str) -> list:
    # Active postings for this search, by the same rule the pipeline's daily stats use
    return [
        PostingSearch.search_key == key,
        Posting.source.not_in(SNAPSHOT_SOURCES),
        Posting.last_seen >= date.today() - timedelta(days=GRACE_DAYS),
    ]


@router.get("/postings", response_model=PostingsPage)
def list_postings(
    key: SearchKey,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    """Active postings for a search, newest first.

    Lists rows, not distinct jobs: the same job found through two sources appears twice,
    so `total` can be higher than the job counts in /companies and /trends/skills.
    """
    conditions = active_conditions(key)

    page = select(Posting).join(PostingSearch).where(*conditions).order_by(Posting.first_seen.desc(), Posting.id).limit(limit).offset(offset)

    total_query = (select(func.count()).select_from(Posting).join(PostingSearch).where(*conditions))

    rows = session.scalars(page).all() # Lists all posting objects for this page

    total = session.scalar(total_query) 

    return PostingsPage(
        search = SearchOut.from_key(key),
        total = total,
        limit = limit,
        offset = offset,
        postings = [PostingOut.model_validate(row) for row in rows]
    )

@router.get("/companies", response_model=CompaniesOut)
def list_companies(key: SearchKey,
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session)):
    """Top companies by number of active postings for a search."""
    conditions = active_conditions(key)

    count = func.count(func.distinct(Posting.fingerprint)).label("postings")
    rows = session.execute(
        select(Posting.company, count)
        .join(PostingSearch)
        .where(*conditions, Posting.company.is_not(None))
        .group_by(Posting.company)
        .order_by(count.desc(), Posting.company)
        .limit(limit)
    ).all()

    company_counts = [CompanyOut(company=row.company, postings=row.postings) for row in rows]

    return CompaniesOut(
        search = SearchOut.from_key(key),
        companies = company_counts
    )
