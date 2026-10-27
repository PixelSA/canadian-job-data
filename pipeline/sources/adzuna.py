"""Adzuna search API: broad coverage + salaries. Descriptions are truncated snippets.

Opt-in only (the free plan is ~25 calls), and always run under a RequestBudget.
Docs: https://developer.adzuna.com/docs/search
"""

import logging
import time
from collections.abc import Iterator
from datetime import datetime

import httpx

from pipeline.budget import RequestBudget
from pipeline.config import TrackedSearch
from pipeline.normalize import html_to_text
from pipeline.sources.base import JobRecord, get_json

log = logging.getLogger(__name__)

BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
RESULTS_PER_PAGE = 50


class AdzunaSource:
    name = "adzuna"

    def __init__(
        self,
        client: httpx.Client,
        app_id: str,
        app_key: str,
        searches: list[TrackedSearch],
        country: str = "ca",
        max_pages: int = 5,
        max_days_old: int = 3,
        page_delay: float = 1.0,
        budget: RequestBudget | None = None,
    ):
        self.client = client
        self.app_id = app_id
        self.app_key = app_key
        self.searches = searches
        self.country = country
        self.max_pages = max_pages
        self.max_days_old = max_days_old  # daily run only needs recent postings
        self.page_delay = page_delay
        self.budget = budget

    def fetch(self) -> Iterator[JobRecord]:
        for search in self.searches:
            for page in range(1, self.max_pages + 1):
                data = get_json(
                    self.client,
                    BASE_URL.format(country=self.country, page=page),
                    params={
                        "app_id": self.app_id,
                        "app_key": self.app_key,
                        "what": search.role,
                        "where": search.region,
                        "results_per_page": RESULTS_PER_PAGE,
                        "max_days_old": self.max_days_old,
                        "content-type": "application/json",
                    },
                    attempts=2 if self.budget else 4,
                    budget=self.budget,
                )
                results = data.get("results", [])
                log.info("adzuna %r page %d: %d results", search.key, page, len(results))
                for item in results:
                    yield self._to_record(item, search)
                if len(results) < RESULTS_PER_PAGE:
                    break
                time.sleep(self.page_delay)

    @staticmethod
    def _to_record(item: dict, search: TrackedSearch) -> JobRecord:
        created = item.get("created")
        return JobRecord(
            source="adzuna",
            source_id=str(item["id"]),
            title=item.get("title", "").strip(),
            company=(item.get("company") or {}).get("display_name"),
            location=(item.get("location") or {}).get("display_name"),
            description=html_to_text(item.get("description")),
            description_is_full=False,
            url=item.get("redirect_url"),
            salary_min=item.get("salary_min"),
            salary_max=item.get("salary_max"),
            salary_is_estimate=str(item.get("salary_is_predicted", "0")) == "1",
            posted_at=datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None,
            raw=item,
            search_keys=[search.key],
        )
