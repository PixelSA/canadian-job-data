from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from api.db import get_session
from api.main import app
from pipeline.config import TrackedSearch
from pipeline.db import MonthlyDemandStat, make_session_factory
from pipeline.run import build_sources, fixture_transport, run_pipeline

SEARCHES = [TrackedSearch("data analyst", "Alberta"), TrackedSearch("software developer", "Alberta")]
DA = {"role": "data analyst", "region": "alberta"}


@pytest.fixture
def client(tmp_path):
    factory = make_session_factory(f"sqlite:///{tmp_path / 'api.db'}")
    with httpx.Client(transport=fixture_transport()) as http:
        # Seed as of today: /trends/salaries counts back from date.today().
        run_pipeline(factory, build_sources(http, True, SEARCHES, factory), SEARCHES,
                     today=date.today())
    with factory() as s:
        for month, postings in [(date(2025, 12, 1), 40), (date(2026, 1, 1), 50)]:
            s.add(MonthlyDemandStat(month=month, search_key="data analyst|alberta",
                                    source="jobbank", new_postings=postings, vacancies=postings,
                                    salary_sample_size=0))
        s.commit()

    def session_override():
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = session_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_searches_lists_both_keys(client):
    keys = [s["key"] for s in client.get("/searches").json()]
    assert keys == ["data analyst|alberta", "software developer|alberta"]


def test_top_skills_sorted_by_postings(client):
    body = client.get("/trends/skills", params={**DA, "limit": 5}).json()
    counts = [s["postings"] for s in body["skills"]]
    # Python and SQL tie at 7 postings: ties are broken alphabetically
    assert [s["skill"] for s in body["skills"][:2]] == ["Python", "SQL"]
    assert counts == sorted(counts, reverse=True) and len(counts) == 5


def test_search_input_is_normalized(client):
    assert client.get("/trends/skills", params={"role": "  Data   Analyst", "region": "ALBERTA"}
                      ).status_code == 200


def test_unknown_search_404_lists_available(client):
    r = client.get("/trends/skills", params={"role": "astronaut", "region": "alberta"})
    assert r.status_code == 404
    assert "data analyst|alberta" in r.json()["detail"]["available"]


def test_limit_is_validated(client):
    assert client.get("/trends/skills", params={**DA, "limit": 0}).status_code == 422


def test_salaries_include_today(client):
    points = client.get("/trends/salaries", params=DA).json()["points"]
    assert points[-1]["day"] == date.today().isoformat() and points[-1]["sample_size"] > 0


def test_demand_since_mid_month_includes_that_month(client):
    points = client.get("/trends/demand", params={**DA, "since": "2026-01-15"}).json()["points"]
    assert [p["month"] for p in points] == ["2026-01-01"]


def _ids(postings):
    return [(p["source"], p["title"], p["company"]) for p in postings]


def test_postings_pages_dont_overlap(client):
    first = client.get("/postings", params={**DA, "limit": 2}).json()
    second = client.get("/postings", params={**DA, "limit": 2, "offset": 2}).json()
    assert len(first["postings"]) == 2 and len(second["postings"]) == 2
    assert not set(_ids(first["postings"])) & set(_ids(second["postings"]))
    assert first["total"] == second["total"] > 4


def test_postings_offset_past_end_is_empty(client):
    body = client.get("/postings", params={**DA, "offset": 1000}).json()
    assert body["postings"] == [] and body["total"] > 0


def test_postings_are_live_and_flag_salary_estimates(client):
    postings = client.get("/postings", params={**DA, "limit": 100}).json()["postings"]
    assert all(p["source"] != "jobbank" for p in postings)
    assert "description" not in postings[0]
    assert any(p["salary_is_estimate"] for p in postings)  # Adzuna's predicted pay


def test_companies_sorted_by_postings_and_limited(client):
    companies = client.get("/companies", params={**DA, "limit": 3}).json()["companies"]
    counts = [c["postings"] for c in companies]
    assert len(companies) == 3 and counts == sorted(counts, reverse=True)
