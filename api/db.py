import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from pipeline.config import settings


@lru_cache
def get_sessionmaker() -> sessionmaker:
    # The API gets its own (read-only) connection string; fall back to the pipeline's locally.
    url = (os.getenv("API_DATABASE_URL") or "").strip() or settings.database_url
    return sessionmaker(create_engine(url, pool_pre_ping=True))


def get_session() -> Iterator[Session]:
    with get_sessionmaker()() as session:
        yield session