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
