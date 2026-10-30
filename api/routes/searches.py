from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.db import get_session
from api.deps import list_search_keys
from api.schemas import SearchOut

router = APIRouter(tags=["searches"])


@router.get("/searches", response_model=list[SearchOut])
def list_searches(session: Session = Depends(get_session)):
    return [SearchOut.from_key(k) for k in list_search_keys(session)]
