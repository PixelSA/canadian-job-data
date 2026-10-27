"""Public applicant-tracking-system job boards (Greenhouse, Lever, Ashby, SmartRecruiters).

No API key or quota, and they return full descriptions, which is what skill extraction needs.
Each company's board is fetched whole; postings are matched to tracked searches afterwards.

Greenhouse:      https://developers.greenhouse.io/job-board.html
Lever:           https://github.com/lever/postings-api
Ashby:           https://developers.ashbyhq.com/docs/public-job-posting-api
SmartRecruiters: https://developers.smartrecruiters.com/docs/posting-api
"""

import logging
import time
from collections.abc import Iterator
from datetime import datetime, timezone

import httpx

from pipeline.config import TrackedSearch
from pipeline.normalize import html_to_text, title_matches_role
from pipeline.sources.base import JobRecord, annualize, get_json

log = logging.getLogger(__name__)

HOURS_PER_YEAR = 2080


class GreenhouseSource:
    name = "greenhouse"
    URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"

    def __init__(self, client: httpx.Client, boards: list[str]):
        self.client = client
        self.boards = boards

    def fetch(self) -> Iterator[JobRecord]:
        for board in self.boards:
            data = get_json(self.client, self.URL.format(board=board), params={"content": "true"})
            jobs = data.get("jobs", [])
            log.info("greenhouse %s: %d jobs", board, len(jobs))
            for job in jobs:
                updated = job.get("updated_at")
                yield JobRecord(
                    source=self.name,
                    source_id=f"{board}:{job['id']}",
                    title=job.get("title", "").strip(),
                    company=job.get("company_name") or board,
                    location=(job.get("location") or {}).get("name"),
                    description=html_to_text(job.get("content")),
                    url=job.get("absolute_url"),
                    posted_at=datetime.fromisoformat(updated) if updated else None,
                    raw=job,
                )


class LeverSource:
    name = "lever"
    URL = "https://api.lever.co/v0/postings/{company}"

    def __init__(self, client: httpx.Client, companies: list[str]):
        self.client = client
        self.companies = companies

    def fetch(self) -> Iterator[JobRecord]:
        for company in self.companies:
            jobs = get_json(self.client, self.URL.format(company=company), params={"mode": "json"})
            log.info("lever %s: %d jobs", company, len(jobs))
            for job in jobs:
                yield self._to_record(company, job)

    def _to_record(self, company: str, job: dict) -> JobRecord:
        parts = [job.get("descriptionPlain") or html_to_text(job.get("description"))]
        for section in job.get("lists", []):
            parts.append(section.get("text", ""))
            parts.append(html_to_text(section.get("content")))
        parts.append(job.get("additionalPlain") or "")

        salary_min = salary_max = None
        if rng := job.get("salaryRange"):
            factor = HOURS_PER_YEAR if rng.get("interval") == "per-hour-wage" else 1
            salary_min = rng.get("min") and rng["min"] * factor
            salary_max = rng.get("max") and rng["max"] * factor

        created_ms = job.get("createdAt")
        return JobRecord(
            source=self.name,
            source_id=f"{company}:{job['id']}",
            title=job.get("text", "").strip(),
            company=company,
            location=(job.get("categories") or {}).get("location"),
            description=" ".join(p for p in parts if p).strip(),
            url=job.get("hostedUrl"),
            salary_min=salary_min,
            salary_max=salary_max,
            posted_at=(datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)
                       if created_ms else None),
            raw=job,
        )


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class AshbySource:
    name = "ashby"
    URL = "https://api.ashbyhq.com/posting-api/job-board/{board}"

    def __init__(self, client: httpx.Client, boards: list[str]):
        self.client = client
        self.boards = boards

    def fetch(self) -> Iterator[JobRecord]:
        for board in self.boards:
            data = get_json(self.client, self.URL.format(board=board),
                            params={"includeCompensation": "true"})
            jobs = data.get("jobs", [])
            log.info("ashby %s: %d jobs", board, len(jobs))
            for job in jobs:
                if job.get("isListed") is False:
                    continue
                yield self._to_record(board, job)

    def _to_record(self, board: str, job: dict) -> JobRecord:
        address = (job.get("address") or {}).get("postalAddress") or {}
        location = ", ".join(
            p for p in (address.get("addressLocality"), address.get("addressRegion")) if p
        ) or job.get("location")

        salary_min = salary_max = None
        for comp in (job.get("compensation") or {}).get("summaryComponents") or []:
            if comp.get("compensationType") == "Salary":
                salary_min = annualize(comp.get("minValue"), comp.get("interval"))
                salary_max = annualize(comp.get("maxValue"), comp.get("interval"))
                break

        return JobRecord(
            source=self.name,
            source_id=f"{board}:{job['id']}",
            title=(job.get("title") or "").strip(),
            company=board,
            location=location,
            description=job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml")),
            url=job.get("jobUrl"),
            salary_min=salary_min,
            salary_max=salary_max,
            posted_at=_parse_iso(job.get("publishedAt")),
            raw=job,
        )


class SmartRecruitersSource:
    """The list endpoint has no descriptions, so each relevant posting costs a detail request.

    To stay polite, details are fetched only for titles matching a tracked role; other
    postings at the company are skipped entirely.
    """

    name = "smartrecruiters"
    BASE = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
    PAGE_SIZE = 100

    def __init__(self, client: httpx.Client, companies: list[str],
                 searches: list[TrackedSearch], detail_delay: float = 0.5):
        self.client = client
        self.companies = companies
        self.searches = searches
        self.detail_delay = detail_delay

    def fetch(self) -> Iterator[JobRecord]:
        for company in self.companies:
            base = self.BASE.format(company=company)
            offset, matched = 0, 0
            while True:
                page = get_json(self.client, base,
                                params={"limit": self.PAGE_SIZE, "offset": offset})
                content = page.get("content", [])
                for summary in content:
                    if not any(title_matches_role(summary.get("name", ""), s.role)
                               for s in self.searches):
                        continue
                    detail = get_json(self.client, f"{base}/{summary['id']}")
                    matched += 1
                    yield self._to_record(company, detail)
                    time.sleep(self.detail_delay)
                offset += len(content)
                if not content or offset >= page.get("totalFound", 0):
                    break
            log.info("smartrecruiters %s: %d of %d postings matched tracked roles",
                     company, matched, offset)

    def _to_record(self, company: str, job: dict) -> JobRecord:
        loc = job.get("location") or {}
        sections = ((job.get("jobAd") or {}).get("sections") or {})
        description = " ".join(
            html_to_text((sections.get(key) or {}).get("text"))
            for key in ("jobDescription", "qualifications", "additionalInformation",
                        "companyDescription")
        )
        return JobRecord(
            source=self.name,
            source_id=f"{company}:{job['id']}",
            title=(job.get("name") or "").strip(),
            company=(job.get("company") or {}).get("name") or company,
            location=", ".join(p for p in (loc.get("city"), loc.get("region")) if p) or None,
            description=description.strip(),
            url=job.get("postingUrl") or job.get("applyUrl"),
            posted_at=_parse_iso(job.get("releasedDate")),
            raw=job,
        )
