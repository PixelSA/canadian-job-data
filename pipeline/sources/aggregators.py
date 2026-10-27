"""Quota-limited job search aggregators: JSearch (primary daily source) and Jooble.

Both run under a RequestBudget, so they stop cleanly before exceeding the plan's quota.
"""

import logging
from collections.abc import Iterator
from datetime import datetime

import httpx

from pipeline.budget import RequestBudget
from pipeline.config import TrackedSearch
from pipeline.normalize import html_to_text, location_in_region
from pipeline.sources.base import JobRecord, annualize, request_json

log = logging.getLogger(__name__)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _join_location(*parts: str | None) -> str | None:
    return ", ".join(p for p in parts if p) or None


class JSearchSource:
    """JSearch: Google-for-Jobs listings (LinkedIn, Indeed, Glassdoor...) with full descriptions.

    One request per tracked search per run. date_posted=3days overlaps consecutive days, so a
    missed run doesn't leave a gap; the overlap is deduplicated on (source, job_id).
    """

    name = "jsearch"
    PROVIDERS = {
        # Base URLs/headers per provider. Check your dashboard's code sample if these change.
        "openwebninja": ("https://api.openwebninja.com/jsearch", "x-api-key"),
        "rapidapi": ("https://jsearch.p.rapidapi.com", "X-RapidAPI-Key"),
    }

    def __init__(
        self,
        client: httpx.Client,
        api_key: str,
        searches: list[TrackedSearch],
        budget: RequestBudget,
        provider: str = "openwebninja",
        country: str = "ca",
        date_posted: str = "3days",
    ):
        self.client = client
        self.searches = searches
        self.budget = budget
        self.country = country
        self.date_posted = date_posted
        self.base_url, key_header = self.PROVIDERS[provider]
        self.headers = {key_header: api_key}
        if provider == "rapidapi":
            self.headers["X-RapidAPI-Host"] = "jsearch.p.rapidapi.com"

    def fetch(self) -> Iterator[JobRecord]:
        for search in self.searches:
            data = request_json(
                self.client, "GET", f"{self.base_url}/search",
                params={
                    "query": f"{search.role} in {search.region}",
                    "page": 1,
                    "num_pages": 1,  # >1 may be billed as several requests
                    "country": self.country,
                    "date_posted": self.date_posted,
                },
                headers=self.headers,
                attempts=2,  # retries cost quota too
                budget=self.budget,
            )
            jobs = data.get("data") or []
            log.info("jsearch %r: %d jobs", search.key, len(jobs))
            for job in jobs:
                yield self._to_record(job, search)

    @staticmethod
    def _to_record(job: dict, search: TrackedSearch) -> JobRecord:
        location = _join_location(job.get("job_city"), job.get("job_state")) \
            or job.get("job_location")
        highlights = job.get("job_highlights") or {}
        description = "\n".join(
            [job.get("job_description") or ""]
            + [f"{section}: " + " ".join(items) for section, items in highlights.items() if items]
        )
        period = job.get("job_salary_period")
        return JobRecord(
            source="jsearch",
            source_id=str(job["job_id"]),
            title=(job.get("job_title") or "").strip(),
            company=job.get("employer_name"),
            location=location,
            description=description.strip(),
            url=job.get("job_apply_link"),
            salary_min=annualize(job.get("job_min_salary"), period),
            salary_max=annualize(job.get("job_max_salary"), period),
            posted_at=_parse_dt(job.get("job_posted_at_datetime_utc")),
            raw=job,
            # JSearch matches loosely ("in Alberta" can return Ontario), so verify the region.
            search_keys=[search.key] if location_in_region(location, search.region) else [],
        )


class JoobleSource:
    """Jooble REST API (POST https://jooble.org/api/<key>). Snippets only; salary is free text."""

    name = "jooble"
    URL = "https://jooble.org/api/{key}"

    def __init__(self, client: httpx.Client, api_key: str, searches: list[TrackedSearch],
                 budget: RequestBudget):
        self.client = client
        self.api_key = api_key
        self.searches = searches
        self.budget = budget

    def fetch(self) -> Iterator[JobRecord]:
        for search in self.searches:
            data = request_json(
                self.client, "POST", self.URL.format(key=self.api_key),
                json={"keywords": search.role, "location": search.region, "page": 1},
                attempts=2,
                budget=self.budget,
            )
            jobs = data.get("jobs") or []
            log.info("jooble %r: %d jobs", search.key, len(jobs))
            for job in jobs:
                location = job.get("location")
                yield JobRecord(
                    source=self.name,
                    source_id=str(job["id"]),
                    title=(job.get("title") or "").strip(),
                    company=job.get("company") or None,
                    location=location,
                    description=html_to_text(job.get("snippet")),
                    description_is_full=False,
                    url=job.get("link"),
                    posted_at=_parse_dt(job.get("updated")),
                    raw=job,
                    search_keys=[search.key] if location_in_region(location, search.region)
                    else [],
                )
