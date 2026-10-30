"""Field mapping for each source, run against the fixture transport."""

import httpx
import pytest

from pipeline.budget import RequestBudget
from pipeline.config import TrackedSearch
from pipeline.db import make_session_factory
from pipeline.run import fixture_transport
from pipeline.sources import AshbySource, JoobleSource, JSearchSource, SmartRecruitersSource
from pipeline.sources.base import annualize

SEARCHES = [TrackedSearch("data analyst", "Alberta"), TrackedSearch("software developer", "Alberta")]


@pytest.fixture
def client():
    with httpx.Client(transport=fixture_transport()) as c:
        yield c


@pytest.fixture
def budget(tmp_path):
    return RequestBudget(make_session_factory(f"sqlite:///{tmp_path / 's.db'}"), "test", 100)


@pytest.mark.parametrize("amount, period, expected", [
    (30, "HOUR", 62400), (90000, "1 YEAR", 90000), (5000, "month", 60000),
    (2000, "Bi-weekly", 52000), (100, "fortnightly-ish", None), (None, "YEAR", None),
])
def test_annualize(amount, period, expected):
    assert annualize(amount, period) == expected


def test_jsearch_mapping(client, budget):
    records = list(JSearchSource(client, "k", SEARCHES, budget).fetch())
    assert len(records) == 4 and budget.used() == 2  # one request per search

    bow = next(r for r in records if r.source_id == "js-da-0001")
    assert bow.location == "Calgary, AB"
    assert (bow.salary_min, bow.salary_max) == (62400, 79040)  # hourly -> yearly
    assert "Azure Data Factory" in bow.description  # highlights are appended
    assert bow.search_keys == ["data analyst|alberta"]

    toronto = next(r for r in records if r.source_id == "js-da-0003")
    assert toronto.search_keys == []  # JSearch returned it for "Alberta", but it's in Ontario


def test_jsearch_rapidapi_headers(budget):
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, json={"data": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        list(JSearchSource(c, "secret", SEARCHES[:1], budget, provider="rapidapi").fetch())
    assert seen["x-rapidapi-key"] == "secret"
    assert seen["x-rapidapi-host"] == "jsearch.p.rapidapi.com"


def test_jooble_mapping(client, budget):
    [rec] = list(JoobleSource(client, "k", SEARCHES[:1], budget).fetch())
    assert rec.company == "Central Alberta Co-op"
    assert rec.description_is_full is False
    assert "SQL" in rec.description and "<b>" not in rec.description
    assert rec.search_keys == ["data analyst|alberta"]


def test_ashby_mapping_skips_unlisted(client):
    [rec] = list(AshbySource(client, ["examplehealth"]).fetch())
    assert rec.title == "Senior Data Analyst"
    assert rec.location == "Calgary, Alberta"
    assert (rec.salary_min, rec.salary_max) == (90000, 110000)


def test_smartrecruiters_fetches_details_only_for_tracked_roles(client):
    requested = []
    transport = fixture_transport()

    def spy(request):
        requested.append(request.url.path)
        return transport.handle_request(request)

    with httpx.Client(transport=httpx.MockTransport(spy)) as c:
        [rec] = list(SmartRecruitersSource(c, ["ExampleRetail"], SEARCHES, detail_delay=0).fetch())
    assert rec.title == "Data Analyst, Merchandising"
    assert rec.location == "Edmonton, AB"
    assert "Power BI" in rec.description
    assert not any(p.endswith("744000002") for p in requested)  # Store Manager: no detail call


def test_jobven_mapping_and_record_budget(client, budget):
    from pipeline.sources import JobvenSource

    records = list(JobvenSource(client, "k", SEARCHES, budget, listed_after=1793300000).fetch())
    assert len(records) == 3
    assert budget.used() == 3  # 25 reserved, 22 refunded: billed per record returned

    energy, northwind, coop = records
    assert (energy.company, energy.location) == ("Prairie Example Energy", "Calgary, Alberta")
    assert (energy.salary_min, energy.salary_max) == (75000, 90000)
    assert "Power BI" in energy.description
    assert northwind.location == "Edmonton, Alberta"  # the Canadian office, not Seattle
    assert northwind.salary_min is None  # USD pay isn't mixed into Canadian stats
    assert (coop.salary_min, coop.salary_max) == (62400, 70720)  # hourly CAD, annualized
    assert coop.posted_at is None


def _jobven_pages(pages, seen):
    def handler(request):
        seen.append(dict(request.url.params))
        if pages and isinstance(pages[0], int):
            return httpx.Response(pages.pop(0))
        jobs = pages.pop(0)
        return httpx.Response(200, json={
            "data": [{"id": j, "title": "Data Analyst", "listedAt": 1} for j in jobs],
            "meta": {"hasMore": bool(pages), "nextCursor": "next" if pages else None},
        })
    return httpx.MockTransport(handler)


def test_jobven_query_and_capped_run_stops_cleanly(tmp_path):
    from pipeline.sources import JobvenSource

    budget = RequestBudget(make_session_factory(f"sqlite:///{tmp_path / 'j.db'}"), "jobven",
                           limit=300, max_per_run=4, unit="records")
    seen = []
    pages = [["a", "b", "c", "d"], ["e"]]
    with httpx.Client(transport=_jobven_pages(pages, seen)) as c:
        records = list(JobvenSource(c, "k", SEARCHES, budget, listed_after=1_000_000).fetch())

    assert [r.source_id for r in records] == ["a", "b", "c", "d"]
    assert len(seen) == 1 and budget.used() == 4  # cap reached: no second page, no error
    params = seen[0]
    assert params["q"] == '"data analyst" OR "software developer"'
    assert params["state"] == "alberta" and params["country"] == "ca"
    assert params["listedAfter"] == str(1_000_000 - 600)  # small overlap with the last sync
    assert (params["sortBy"], params["order"], params["limit"]) == ("listedAt", "ASC", "4")


def test_jobven_follows_cursor_within_budget(tmp_path):
    from pipeline.sources import JobvenSource

    budget = RequestBudget(make_session_factory(f"sqlite:///{tmp_path / 'j.db'}"), "jobven", 300)
    seen = []
    with httpx.Client(transport=_jobven_pages([["a", "b"], ["c"]], seen)) as c:
        records = list(JobvenSource(c, "k", SEARCHES, budget, listed_after=1, page_size=2).fetch())
    assert [r.source_id for r in records] == ["a", "b", "c"]
    assert seen[1]["cursor"] == "next" and budget.used() == 3


def test_jobven_failed_request_is_refunded_and_exhausted_budget_raises(tmp_path):
    from pipeline.budget import BudgetExhausted
    from pipeline.sources import JobvenSource

    factory = make_session_factory(f"sqlite:///{tmp_path / 'j.db'}")
    budget = RequestBudget(factory, "jobven", 300)
    with httpx.Client(transport=_jobven_pages([401], [])) as c:
        with pytest.raises(httpx.HTTPStatusError):
            list(JobvenSource(c, "k", SEARCHES, budget, listed_after=1).fetch())
    assert budget.used() == 0  # Jobven doesn't bill failed requests

    spent = RequestBudget(factory, "jobven", 0)
    with httpx.Client(transport=_jobven_pages([], [])) as c:
        with pytest.raises(BudgetExhausted):
            list(JobvenSource(c, "k", SEARCHES, spent, listed_after=1).fetch())


def test_jobven_first_sync_and_canada_wide_search(budget):
    from datetime import datetime, timezone

    from pipeline.sources import JobvenSource

    now = datetime(2026, 10, 29, tzinfo=timezone.utc)
    src = JobvenSource(None, "k", [TrackedSearch("data analyst", "Canada")], budget,
                       lookback_days=7, clock=lambda: now)
    params = src.params()
    assert params["listedAfter"] == int(now.timestamp()) - 7 * 86400
    assert "state" not in params  # no province filter for a Canada-wide search


def test_jobven_prefers_the_tracked_region_site(budget):
    from pipeline.sources import JobvenSource

    # Real case: Questrade listed North York first, Calgary second.
    job = {"id": "q1", "title": "Software Engineer", "locations": [
        {"addressLocality": "North York", "addressRegion": "Ontario", "addressCountry": "CA"},
        {"addressLocality": "Calgary", "addressRegion": "Alberta", "addressCountry": "CA"}]}
    rec = JobvenSource(None, "k", SEARCHES, budget, listed_after=1)._to_record(job)
    assert rec.location == "Calgary, Alberta"


def test_jobven_query_override_and_page_delay(tmp_path, monkeypatch):
    from pipeline.sources import JobvenSource

    sleeps = []
    monkeypatch.setattr("pipeline.sources.jobven.time.sleep", sleeps.append)
    budget = RequestBudget(make_session_factory(f"sqlite:///{tmp_path / 'j.db'}"), "jobven", 300)
    seen = []
    with httpx.Client(transport=_jobven_pages([["a", "b"], ["c"]], seen)) as c:
        list(JobvenSource(c, "k", SEARCHES, budget, listed_after=1, page_size=2,
                          query="analyst OR engineer", page_delay=1.5).fetch())
    assert seen[0]["q"] == "analyst OR engineer" and seen[0]["state"] == "alberta"
    assert sleeps == [1.5]  # between pages, not before the first


def test_jobven_canada_search_keeps_the_province_filter(budget):
    from pipeline.sources import JobvenSource

    searches = [*SEARCHES, TrackedSearch("data analyst", "Canada")]
    params = JobvenSource(None, "k", searches, budget, listed_after=1).params()
    assert params["state"] == "alberta"  # 10 records/day can't cover the whole country
