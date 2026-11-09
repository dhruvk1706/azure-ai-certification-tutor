"""Database session for the API. Ingestion manages its own engine."""

import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session


@lru_cache
def get_engine() -> Engine:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return create_engine(url, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    # Routes commit explicitly, so a failed commit reaches the client as an error.
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session
