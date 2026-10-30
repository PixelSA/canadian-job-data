import logging
import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from pipeline.config import settings

log = logging.getLogger(__name__)


@lru_cache
def get_sessionmaker() -> sessionmaker:
    # The API gets its own read-only connection string (sql/api_reader.sql);
    # falling back to the pipeline's read-write one is only meant for local dev.
    url = (os.getenv("API_DATABASE_URL") or "").strip()
    if not url:
        log.warning("API_DATABASE_URL is not set; using the pipeline's DATABASE_URL "
                    "(read-write). Set it to the api_reader role before deploying.")
        url = settings.database_url
    return sessionmaker(create_engine(url, pool_pre_ping=True))


def get_session() -> Iterator[Session]:
    with get_sessionmaker()() as session:
        yield session
