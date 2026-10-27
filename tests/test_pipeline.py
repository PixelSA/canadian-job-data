"""End-to-end run against the saved fixtures, using a throwaway SQLite database."""

from datetime import date

import httpx
import pytest
from sqlalchemy import func, select

from pipeline.config import TrackedSearch
from pipeline.db import (
    DailySalaryStat,
    DailySkillStat,
    Posting,
    RawPosting,
    make_session_factory,
)
from pipeline.run import build_sources, fixture_transport, run_pipeline

SEARCHES = [TrackedSearch("data analyst", "Alberta"), TrackedSearch("software developer", "Alberta")]
DA = "data analyst|alberta"
SD = "software developer|alberta"
DAY1 = date(2026, 10, 26)


ORIGINAL = {"adzuna", "greenhouse", "lever"}


@pytest.fixture
def all_sources(tmp_path):
    factory = make_session_factory(f"sqlite:///{tmp_path / 'test.db'}")
    client = httpx.Client(transport=fixture_transport())
    yield factory, build_sources(client, True, SEARCHES, factory)
    client.close()


@pytest.fixture
def env(all_sources):
    """Just Adzuna + Greenhouse + Lever, which the exact-count assertions below are based on."""
    factory, sources = all_sources
    return factory, [s for s in sources if s.name in ORIGINAL]


def skill_stats(session, key, day=DAY1):
    rows = session.scalars(
        select(DailySkillStat).where(DailySkillStat.search_key == key, DailySkillStat.day == day)
    )
    return {r.skill: r.active_postings for r in rows}


def test_first_run_ingests_dedupes_and_aggregates(env):
    factory, sources = env
    run = run_pipeline(factory, sources, SEARCHES, today=DAY1)

    assert run.status == "success", run.errors
    assert run.fetched == 9  # 4 adzuna + 3 greenhouse + 2 lever
    assert run.new_postings == 9

    with factory() as s:
        da = skill_stats(s, DA)
        # 6 data analyst rows, but the Adzuna + Greenhouse ExampleCorp copies are one job,
        # so SQL is counted for ExampleCorp, Chinook (via SQL Server) and ExampleStartup.
        assert da["SQL"] == 3
        assert da["Python"] == 3
        # Skills from the full Greenhouse description count for the deduped job
        assert da["Airflow"] == 1
        assert "Go" not in da  # "Go above and beyond" is not a skill

        sd = skill_stats(s, SD)
        assert sd["Go"] == 1 and sd["C"] == 1 and sd["AWS"] == 2

        salary = s.scalar(select(DailySalaryStat).where(DailySalaryStat.search_key == DA))
        # The predicted Adzuna salary is excluded; Lever hourly wage is annualized.
        assert salary.sample_size == 4
        assert salary.median == pytest.approx(77500)


def test_rerun_is_idempotent_and_updates_last_seen(env):
    factory, sources = env
    run_pipeline(factory, sources, SEARCHES, today=DAY1)
    run2 = run_pipeline(factory, sources, SEARCHES, today=date(2026, 10, 27))

    assert run2.new_postings == 0 and run2.updated_postings == 0
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Posting)) == 9
        assert s.scalar(select(func.count()).select_from(RawPosting)) == 9  # same payloads
        assert {p.last_seen for p in s.scalars(select(Posting))} == {date(2026, 10, 27)}
        assert {p.first_seen for p in s.scalars(select(Posting))} == {DAY1}


def test_changed_extractor_version_triggers_reextraction(env):
    factory, sources = env
    run_pipeline(factory, sources, SEARCHES, today=DAY1)
    with factory() as s:
        for p in s.scalars(select(Posting)):
            p.extractor_version = "v0-old"
        s.commit()

    run_pipeline(factory, sources, SEARCHES, today=DAY1)
    with factory() as s:
        versions = {p.extractor_version for p in s.scalars(select(Posting))}
        assert "v0-old" not in versions


def test_failing_source_marks_run_partial(env):
    factory, sources = env

    class Broken:
        name = "broken"

        def fetch(self):
            raise RuntimeError("API down")
            yield

    run = run_pipeline(factory, [*sources, Broken()], SEARCHES, today=DAY1)
    assert run.status == "partial"
    assert run.errors == ["broken: API down"]
    assert run.new_postings == 9


def test_all_fixture_sources_together(all_sources):
    factory, sources = all_sources
    run = run_pipeline(factory, sources, SEARCHES, today=DAY1)
    assert run.status == "success", run.errors

    with factory() as s:
        da = skill_stats(s, DA)
        # ExampleCorp's Data Analyst now arrives via Adzuna, Greenhouse *and* JSearch: still 1 job.
        # SQL jobs: ExampleCorp, Chinook, ExampleStartup, Bow River, Co-op (Jooble),
        # ExampleRetail (SmartRecruiters) = 6. Lakeshore (Toronto) isn't in the Alberta search.
        assert da["SQL"] == 6
        assert da["Azure Data Factory"] == 1  # from JSearch highlights
        assert da["Looker"] == 3  # Lethbridge (Adzuna), ExampleStartup, ExampleHealth (Ashby)


def test_budget_exhaustion_keeps_partial_results(tmp_path):
    from pipeline.budget import RequestBudget
    from pipeline.sources import JSearchSource

    factory = make_session_factory(f"sqlite:///{tmp_path / 'b.db'}")
    budget = RequestBudget(factory, "jsearch", limit=1, period="month")
    with httpx.Client(transport=fixture_transport()) as client:
        run = run_pipeline(factory, [JSearchSource(client, "k", SEARCHES, budget)], SEARCHES,
                           today=DAY1)

    assert run.status == "success"  # running out of quota is expected, not a failure
    assert run.fetched == 3  # the first search's results were kept
    assert any("limit of 1 reached" in n for n in run.notes)
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Posting)) == 3


def _rec(title, location, search_keys=(), source="jsearch", source_id="x1"):
    from pipeline.sources import JobRecord
    return JobRecord(source=source, source_id=source_id, title=title, company="Acme",
                     location=location, description="", url=None, raw={},
                     search_keys=list(search_keys))


def test_aggregator_search_needs_title_match():
    from pipeline.ingest import search_keys_for

    # Real examples from a live JSearch/Adzuna run: loose matches must not count.
    assert search_keys_for(_rec("Climate Analyst", "Calgary, AB", [DA]), SEARCHES) == set()
    assert search_keys_for(
        _rec("Hiring .NET and Java Developers to work in USA", "Onefour", [DA]), SEARCHES) == set()
    assert search_keys_for(_rec("Senior Data Analyst", "Calgary, AB", [DA]), SEARCHES) == {DA}
    # A source's own search may vouch for an obscure Alberta location, if the title fits.
    assert search_keys_for(_rec("Data Analyst", "Onefour", [DA]), SEARCHES) == {DA}


def test_rematch_reclassifies_without_refetching(tmp_path):
    from pipeline.ingest import rematch_all, upsert_posting

    factory = make_session_factory(f"sqlite:///{tmp_path / 'r.db'}")
    with factory() as s:
        upsert_posting(s, _rec("Software Engineer", "Calgary, AB"), DAY1, SEARCHES)
        s.commit()
        assert {x.search_key for x in s.scalar(select(Posting)).searches} == set()

        engineer = TrackedSearch("software engineer", "Alberta")
        assert rematch_all(s, [*SEARCHES, engineer]) == 1
        assert {x.search_key for x in s.scalar(select(Posting)).searches} == {engineer.key}


def test_rematch_replaces_existing_links(tmp_path):
    from pipeline.ingest import rematch_all, upsert_posting

    factory = make_session_factory(f"sqlite:///{tmp_path / 'r2.db'}")
    wide = [*SEARCHES, TrackedSearch("data analyst", "Canada")]
    with factory() as s:
        upsert_posting(s, _rec("Data Analyst", "Calgary, AB"), DAY1, SEARCHES)
        s.commit()
        rematch_all(s, list(reversed(wide)))  # keeps one link, adds one
        rematch_all(s, SEARCHES)  # drops one
        assert {x.search_key for x in s.scalar(select(Posting)).searches} == {DA}
