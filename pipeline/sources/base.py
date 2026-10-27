"""Shared types and HTTP helpers for job sources."""

import logging
import time
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

import httpx

from pipeline.budget import RequestBudget

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


@dataclass
class JobRecord:
    """One posting in our normalized shape, plus the untouched payload it came from."""

    source: str
    source_id: str
    title: str
    company: str | None
    location: str | None
    description: str
    url: str | None
    # Untouched payload for the raw layer. None when the source is itself an immutable,
    # re-downloadable file (Job Bank CSVs), so storing every row again would only add bulk.
    raw: dict | None
    description_is_full: bool = True
    salary_min: float | None = None
    salary_max: float | None = None
    salary_is_estimate: bool = False
    posted_at: datetime | None = None
    occupation_code: str | None = None
    vacancies: int | None = None
    # For snapshot sources: the day the posting was observed (instead of the run date).
    seen_on: date | None = None
    # Source-specific identity for deduplication when there's no employer name to fingerprint.
    dedupe_key: str | None = None
    # Searches this record was found by (e.g. Adzuna query). More are added by title/region matching.
    search_keys: list[str] = field(default_factory=list)


# Multipliers to annual pay (2080 h = 40 h x 52 weeks).
ANNUAL_FACTORS = {
    "hour": 2080, "hourly": 2080, "day": 260, "daily": 260, "week": 52, "weekly": 52,
    "bi-weekly": 26, "biweekly": 26, "month": 12, "monthly": 12, "year": 1, "yearly": 1,
    "annual": 1, "annually": 1,
}


def annualize(amount: float | None, period: str | None) -> float | None:
    """Convert a pay amount to yearly; unknown periods return None rather than a guess."""
    if amount is None or not period:
        return None
    key = re.sub(r"^1\s+", "", period.strip().lower())  # Ashby uses "1 YEAR"
    factor = ANNUAL_FACTORS.get(key)
    return round(amount * factor, 2) if factor else None


class Source(Protocol):
    name: str

    def fetch(self) -> Iterator[JobRecord]: ...


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
    headers: dict | None = None,
    attempts: int = 4,
    budget: RequestBudget | None = None,
):
    """HTTP request with exponential backoff on rate limits and server errors.

    With a budget, every attempt (retries included, since they count against the quota)
    is reserved first; BudgetExhausted propagates to the caller.
    """
    delay = 1.0
    for attempt in range(1, attempts + 1):
        if budget is not None:
            budget.spend()
        try:
            resp = client.request(method, url, params=params, json=json, headers=headers)
            if resp.status_code not in RETRY_STATUSES:
                resp.raise_for_status()
                return resp.json()
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
            log.warning("HTTP %s from %s (attempt %d), retrying in %.1fs",
                        resp.status_code, url, attempt, wait)
        except httpx.TransportError as exc:
            wait = delay
            log.warning("%s on %s (attempt %d), retrying in %.1fs", exc, url, attempt, wait)
        if attempt == attempts:
            break
        time.sleep(wait)
        delay *= 2
    raise RuntimeError(f"Giving up on {url} after {attempts} attempts")


def get_json(client: httpx.Client, url: str, params: dict | None = None, **kwargs):
    return request_json(client, "GET", url, params=params, **kwargs)


def default_client() -> httpx.Client:
    return httpx.Client(
        timeout=30,
        headers={"User-Agent": "job-market-intel/0.1 (portfolio project)"},
        follow_redirects=True,
    )
