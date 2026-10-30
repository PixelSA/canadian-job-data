from fastapi import Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_session
from pipeline.db import PostingSearch

from typing import Annotated


def normalize(text: str) -> str:
    # Lowercase, trim, and collapse repeated spaces ("Data   Analyst " -> "data analyst")
    return " ".join(text.lower().split())


def list_search_keys(session: Session) -> list[str]:
    # Every search that has postings; shared by /searches and the 404 below.
    return session.scalars(
        select(PostingSearch.search_key).distinct().order_by(PostingSearch.search_key)
    ).all()


def search_key(
    role: str = Query(..., min_length=2, examples=["data analyst"]),
    region: str = Query(..., min_length=2, examples=["Alberta"]),
    session: Session = Depends(get_session),
) -> str:
    key = f"{normalize(role)}|{normalize(region)}"

    exists = session.scalar(
        select(PostingSearch.search_key)
        .where(PostingSearch.search_key == key) # WHERE search_key == key
        .limit(1) # at least 1
    )

    if exists is None:
        raise HTTPException(
            status_code=404,
            detail = {
                "message": f"No job data for role = {role!r} in region = {region!r}",
                "available": list_search_keys(session),
            },
        )

    return key

SearchKey = Annotated[str, Depends(search_key)]
