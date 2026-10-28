from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_session
from api.schemas import SearchOut
from pipeline.db import PostingSearch

router = APIRouter(tags=["searches"])


@router.get("/searches", response_model=list[SearchOut])
def list_searches(session: Session = Depends(get_session)):
    keys = session.scalars(
        select(PostingSearch.search_key).distinct().order_by(PostingSearch.search_key)
    )
    return [SearchOut.from_key(k) for k in keys]