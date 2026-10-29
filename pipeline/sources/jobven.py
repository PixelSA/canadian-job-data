"""Jobven: postings collected from employers' own career pages (Workday, iCIMS, custom
sites...), which reaches employers our Greenhouse/Lever/Ashby/SmartRecruiters boards don't.

Jobven bills per job record returned, not per request (free plan: 300 records/month, 25
per request), so the budget counts records. One run makes one combined query for every
tracked role ("data analyst" OR "software developer" ...) in the tracked provinces, and
syncs incrementally: oldest-listed first from just before the newest listing we already
hold, so a run capped at a few records picks up where the last one stopped instead of
skipping jobs. Title/region matching in ingest assigns each job to its searches.

One-off backfill with a wider query (e.g. the free plan's 2,500-record first week):

    python -m pipeline.sources.jobven --query "analyst OR developer OR engineer" --max 1000

Postings whose titles match no tracked search are stored but don't affect stats, so a
later --rematch can fill a newly tracked role from them without API calls.
"""

import argparse
import logging
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from pipeline.budget import RequestBudget
from pipeline.config import TrackedSearch
from pipeline.db import RawPosting
from pipeline.normalize import REGION_ALIASES, location_in_region
from pipeline.sources.base import JobRecord, annualize, request_json

log = logging.getLogger(__name__)

# Re-request a little before the newest listing we hold: listings that share a timestamp
# with it (or arrive slightly out of order) aren't missed. The overlap costs a record or two.
SYNC_OVERLAP = timedelta(minutes=10)


def last_listed_at(session_factory: sessionmaker) -> int | None:
    """Newest Jobven `listedAt` already stored, read from the raw layer (Unix seconds)."""
    with session_factory() as s:
        payloads = s.scalars(
            select(RawPosting.payload)
            .where(RawPosting.source == JobvenSource.name)
            .order_by(RawPosting.fetched_at.desc())
            .limit(500)  # only the latest runs matter; listings arrive in listedAt order
        )
        listed = [p.get("listedAt") for p in payloads if isinstance(p, dict)]
    return max((t for t in listed if t), default=None)


class JobvenSource:
    name = "jobven"
    URL = "https://api.jobven.com/v1/public/jobs"

    def __init__(
        self,
        client: httpx.Client,
        api_key: str,
        searches: list[TrackedSearch],
        budget: RequestBudget,
        listed_after: int | None = None,
        country: str = "ca",
        lookback_days: int = 7,
        page_size: int = 25,  # free plan maximum
        query: str | None = None,  # title search; default: the tracked roles
        page_delay: float = 0,  # seconds between pages (the free plan rate-limits bursts)
        clock=lambda: datetime.now(timezone.utc),
    ):
        self.client = client
        self.headers = {"X-API-Key": api_key}
        self.searches = searches
        self.budget = budget
        self.country = country
        if listed_after is None:  # first sync: start a few days back
            listed_after = int((clock() - timedelta(days=lookback_days)).timestamp())
        else:
            listed_after -= int(SYNC_OVERLAP.total_seconds())
        self.listed_after = listed_after
        self.page_size = page_size
        self.query = query
        self.page_delay = page_delay

    def params(self) -> dict:
        roles = sorted({s.role.lower() for s in self.searches})
        params = {
            "q": self.query or " OR ".join(f'"{r}"' for r in roles),
            "country": self.country,
            "listedAfter": self.listed_after,
            "sortBy": "listedAt",
            "order": "ASC",
            "descriptionFormat": "plain",
        }
        # Provinces narrow the query; a Canada-wide search (or an unknown region) can't.
        regions = {s.region.lower() for s in self.searches}
        if regions <= REGION_ALIASES.keys() - {"canada"}:
            params["state"] = ",".join(sorted(regions))
        return params

    def fetch(self) -> Iterator[JobRecord]:
        params, cursor, first = self.params(), None, True
        while True:
            left = self.budget.remaining()
            if not left and not first:
                # Normal end of a capped daily run; the next run continues from here.
                log.info("jobven: record cap reached, more listings left for the next run")
                return
            # With nothing left before the first page, reserving 1 raises BudgetExhausted
            # with the reason (monthly limit), which ends up in the run's notes.
            size = max(min(self.page_size, left), 1)
            if not first:
                time.sleep(self.page_delay)
            first = False
            self.budget.spend(size)
            try:
                data = request_json(
                    self.client, "GET", self.URL,
                    params={**params, "limit": size, **({"cursor": cursor} if cursor else {})},
                    headers=self.headers,
                    attempts=4,  # failed requests (incl. 429s) aren't billed, so retry freely
                )
            except Exception:
                self.budget.refund(size)  # failed requests aren't billed
                raise
            jobs = data.get("data") or []
            self.budget.refund(size - len(jobs))  # billed per record actually returned
            log.info("jobven: %d jobs", len(jobs))
            for job in jobs:
                yield self._to_record(job)

            meta = data.get("meta") or {}
            cursor = meta.get("nextCursor")
            if not (meta.get("hasMore") and cursor and jobs):
                return

    def _to_record(self, job: dict) -> JobRecord:
        # A multi-site posting ("North York; Calgary", "Seattle; Edmonton") is one record:
        # keep the site in a tracked region, else a Canadian one, else the first.
        sites = [(", ".join(p for p in (l.get("addressLocality"), l.get("addressRegion")) if p),
                  l.get("addressCountry")) for l in job.get("locations") or []]
        regions = {s.region for s in self.searches}
        location = next((name for name, _ in sites
                         if any(location_in_region(name, r) for r in regions)), None)             or next((name for name, country in sites if country == "CA"), None)             or (sites[0][0] if sites else None)

        salary = job.get("salary") or {}
        # Only CAD pay is comparable with the rest of our Canadian salary stats.
        cad = (salary.get("currency") or "").upper() == "CAD"

        def pay(annual_key: str, raw_key: str) -> float | None:
            if not cad:
                return None
            if salary.get(annual_key) is not None:
                return float(salary[annual_key])
            return annualize(salary.get(raw_key), salary.get("period"))

        companies = job.get("companies") or []
        posted = job.get("postedAt")
        return JobRecord(
            source=self.name,
            source_id=str(job["id"]),
            title=(job.get("title") or "").strip(),
            company=companies[0].get("name") if companies else None,
            location=location or None,
            description=(job.get("descriptionPlain") or "").strip(),
            url=job.get("applyUrl"),
            salary_min=pay("annualMin", "min"),
            salary_max=pay("annualMax", "max"),
            posted_at=datetime.fromtimestamp(posted, timezone.utc) if posted else None,
            # Jobven's own AI-extracted `skills` stay in the raw payload: stats use our
            # versioned extractor so every source is measured the same way.
            raw=job,
        )


def main() -> None:
    from pipeline.config import settings
    from pipeline.db import IngestionRun, make_session_factory
    from pipeline.run import run_pipeline
    from pipeline.sources.base import default_client

    parser = argparse.ArgumentParser(description="One-off Jobven backfill with a custom query")
    parser.add_argument("--query", required=True, help='Jobven title search, e.g. "analyst OR engineer"')
    parser.add_argument("--max", type=int, required=True, help="most records to spend")
    parser.add_argument("--days", type=int, default=3650, help="only listings from the last N days")
    args = parser.parse_args()
    if not settings.jobven_api_key:
        raise SystemExit("JOBVEN_API_KEY is not set")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    factory = make_session_factory(settings.database_url)
    # Counted in api_usage like daily runs, but allowed past the monthly limit by --max:
    # the free plan's first week allows more than the monthly 300.
    probe = RequestBudget(factory, JobvenSource.name, settings.jobven_monthly_limit)
    budget = RequestBudget(factory, JobvenSource.name, probe.used() + args.max, "month",
                           max_per_run=args.max, unit="records")
    with default_client() as client:
        source = JobvenSource(client, settings.jobven_api_key, settings.searches, budget,
                              country=settings.jobven_country, lookback_days=args.days,
                              query=args.query, page_delay=1.5)
        run = run_pipeline(factory, [source], settings.searches)
    with factory() as s:  # mark the run, so a jump in that day's counts can be explained
        stored = s.get(IngestionRun, run.id)
        stored.notes = [*stored.notes, f"jobven backfill: q={args.query!r}, max={args.max}"]
        s.commit()
    print(f"run {run.id}: {run.status} fetched={run.fetched} new={run.new_postings} "
          f"errors={run.errors} | jobven {budget.used()} records used this month")


if __name__ == "__main__":
    main()
