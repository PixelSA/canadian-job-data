from fastapi import Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_session
from pipeline.db import PostingSearch

from typing import Annotated

import string



def normalize(text: str) -> str:
    # TODO: lowercase, trim, and collapse repeated spaces ("Data   Analyst " -> "data analyst")
    ...
    return " ".join(text.lower().split())



def search_key(
    role: str = Query(..., min_length=2, examples=["data analyst"]),
    region: str = Query(..., min_length=2, examples=["Alberta"]),
    session: Session = Depends(get_session),
) -> str:
    key = f"{normalize(role)}|{normalize(region)}"  

    # TODO: check the key exists in posting_searches.
    #   Query just the search_key column, filtered to this key, with .limit(1),
    #   and use session.scalar(...), which returns None when there's no row.
    exists = session.scalar(
        select(PostingSearch.search_key) 
        .where(PostingSearch.search_key == key) # WHERE search_key == key
        .limit(1) # at least 1
    )


    # TODO: if it doesn't exist, raise HTTPException(status_code=404, detail=...)
    #   Make the error useful: include the searches that DO exist (the same query
    #   /searches uses). `detail` can be a dict, e.g. {"message": ..., "available": [...]}
    if exists is None:
        available = session.scalars(
            select(PostingSearch.search_key).distinct().order_by(PostingSearch.search_key)
        ).all()
        raise HTTPException(
            status_code=404,
            detail = {
                "message": f"No job data for role = {role!r} in region = {region!r}",
                "available": available,
            },
        )

    return key

SearchKey = Annotated[str, Depends(search_key)]