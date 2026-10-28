from api.deps import SearchKey
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_session
from api.schemas import SearchOut
from pipeline.db import PostingSearch


router = APIRouter(tags=["trends"])

@router.get("/debug/search-key")
def debug_search_key(key: SearchKey):
    return {"key": key}