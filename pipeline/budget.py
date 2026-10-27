"""Request budgets for quota-limited APIs (JSearch, Jooble, Adzuna).

Every call is counted in the api_usage table *before* it is made, in its own transaction,
so the count survives crashes and rolled-back ingestion. Once the period's limit (or the
per-run cap) is reached, spend() raises BudgetExhausted and the source stops cleanly.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from pipeline.db import ApiUsage

log = logging.getLogger(__name__)


class BudgetExhausted(Exception):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RequestBudget:
    def __init__(
        self,
        session_factory: sessionmaker,
        source: str,
        limit: int,
        period: str = "month",  # "month" resets on the 1st (UTC); "lifetime" never resets
        max_per_run: int | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ):
        if period not in {"month", "lifetime"}:
            raise ValueError(f"unknown budget period {period!r}")
        self.session_factory = session_factory
        self.source = source
        self.limit = limit
        self.period = period
        self.max_per_run = max_per_run
        self.clock = clock
        self.spent_this_run = 0

    @property
    def period_key(self) -> str:
        return self.clock().strftime("%Y-%m") if self.period == "month" else "lifetime"

    def used(self) -> int:
        with self.session_factory() as s:
            row = s.scalar(select(ApiUsage).where(ApiUsage.source == self.source,
                                                  ApiUsage.period == self.period_key))
            return row.calls if row else 0

    def remaining(self) -> int:
        left = self.limit - self.used()
        if self.max_per_run is not None:
            left = min(left, self.max_per_run - self.spent_this_run)
        return max(left, 0)

    def start_run(self) -> None:
        self.spent_this_run = 0

    def spend(self) -> None:
        """Reserve one call, or raise BudgetExhausted."""
        if self.max_per_run is not None and self.spent_this_run >= self.max_per_run:
            raise BudgetExhausted(f"{self.source}: per-run cap of {self.max_per_run} reached")
        key = self.period_key
        with self.session_factory() as s:
            row = s.scalar(
                select(ApiUsage)
                .where(ApiUsage.source == self.source, ApiUsage.period == key)
                .with_for_update()  # row lock on Postgres; no-op on SQLite
            )
            if row is None:
                row = ApiUsage(source=self.source, period=key, calls=0)
                s.add(row)
            if row.calls >= self.limit:
                raise BudgetExhausted(
                    f"{self.source}: {self.period} limit of {self.limit} reached ({key})")
            row.calls += 1
            s.commit()
            used = row.calls
        self.spent_this_run += 1
        if used >= self.limit * 0.8:
            log.warning("%s has used %d of %d calls for %s", self.source, used, self.limit, key)
