from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from pipeline.config import TrackedSearch
from pipeline.db import (
    DailySkillStat,
    LoadedFile,
    MonthlyDemandStat,
    Posting,
    RawPosting,
    make_session_factory,
)
from pipeline.jobbank import iter_rows, list_files, load_file, load_latest
from pipeline.run import run_pipeline

FIXTURE = Path(__file__).parent / "fixtures" / "jobbank_sample.csv"
SEARCHES = [TrackedSearch("data analyst", "Alberta"), TrackedSearch("software developer", "Alberta")]
SEPT = date(2026, 9, 1)


@pytest.fixture
def factory(tmp_path):
    return make_session_factory(f"sqlite:///{tmp_path / 'jb.db'}")


def test_reads_utf16_tab_separated_and_utf8_comma(tmp_path):
    rows = list(iter_rows(FIXTURE))
    assert rows[0]["Job Title"] == "data analyst" and len(rows) == 6

    plain = tmp_path / "plain.csv"
    plain.write_text("Job Title,City\ndata analyst,Calgary\n", encoding="utf-8")
    assert list(iter_rows(plain)) == [{"Job Title": "data analyst", "City": "Calgary"}]


def test_load_file_filters_and_aggregates_monthly(factory):
    run = load_file(factory, FIXTURE, "sept", SEPT, SEARCHES)
    assert run.status == "success"
    assert run.fetched == 3  # 2 Alberta data analysts + 1 Alberta developer

    with factory() as s:
        postings = {p.source_id: p for p in s.scalars(select(Posting))}
        assert set(postings) == {"90000001", "90000002", "90000005"}  # not Ontario/cook/blank
        p = postings["90000002"]
        assert p.first_seen == date(2026, 9, 15)  # posting date, not load date
        assert (p.salary_min, p.salary_max) == (62400, 72800)  # hourly -> yearly
        assert p.occupation_code == "21223" and p.vacancies == 2
        assert s.scalars(select(RawPosting)).first() is None  # the file is the raw layer

        stat = s.scalar(select(MonthlyDemandStat).where(
            MonthlyDemandStat.search_key == "data analyst|alberta"))
        assert (stat.month, stat.new_postings, stat.vacancies) == (SEPT, 2, 3)
        assert stat.salary_median == pytest.approx((70000 + 67600) / 2)


def test_all_roles_keeps_every_posting_in_region(factory):
    run = load_file(factory, FIXTURE, "sept", SEPT, SEARCHES, all_roles=True)
    assert run.fetched == 4  # adds the Alberta cook


def test_job_bank_postings_stay_out_of_daily_stats(factory):
    load_file(factory, FIXTURE, "sept", SEPT, SEARCHES)
    run_pipeline(factory, [], SEARCHES, today=date(2026, 9, 15))
    with factory() as s:
        assert s.scalars(select(DailySkillStat)).first() is None


def test_load_latest_skips_files_already_loaded(factory):
    package = {"result": {"resources": [
        {"name": "September 2026 Job Postings Advertised on Canada's National Job Bank Website",
         "format": "CSV", "language": ["en"], "url": "https://files.example/sept-en.csv"},
        {"name": "September 2026 Job Postings Advertised on Canada's National Job Bank Website",
         "format": "CSV", "language": ["fr"], "url": "https://files.example/sept-fr.csv"},
        {"name": "August 2026 Job Postings Advertised on Canada's National Job Bank Website",
         "format": "CSV", "language": ["en"], "url": "https://files.example/aug-en.csv"},
    ]}}
    downloads = []

    def handler(request):
        if "package_show" in str(request.url):
            return httpx.Response(200, json=package)
        downloads.append(str(request.url))
        return httpx.Response(200, content=FIXTURE.read_bytes())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        files = list_files(client)
        assert [f.month for f in files] == [date(2026, 9, 1), date(2026, 8, 1)]

        load_latest(factory, client, SEARCHES, latest=2)
        load_latest(factory, client, SEARCHES, latest=2)  # second run: nothing new

    assert downloads == ["https://files.example/aug-en.csv", "https://files.example/sept-en.csv"]
    with factory() as s:
        assert len(s.scalars(select(LoadedFile)).all()) == 2


def test_both_date_formats_and_bad_dates_skip_the_row_not_the_file():
    from pipeline.jobbank import parse_date, row_to_record

    assert parse_date("2026/09/02") == date(2026, 9, 2)
    assert parse_date("2024-06-04") == date(2024, 6, 4)  # Jun-Sep 2024 files
    base = {"WIC Job Location Snapshot ID": "1", "Job Title": "data analyst",
            "Province/Territory": "Alberta", "City": "Calgary"}
    assert row_to_record({**base, "First Posting Date": "2024-06-04"}, SEARCHES) is not None
    assert row_to_record({**base, "First Posting Date": "June 4th"}, SEARCHES) is None


def test_one_posting_listed_in_many_towns_counts_once(factory, tmp_path):
    import csv as _csv
    cols = ["WIC Job Location Snapshot ID", "Job Title", "First Posting Date", "Vacancy Count",
            "Province/Territory", "City", "Salary Per", "Salary Minimum", "Salary Maximum",
            "NOC21 Code"]
    towns = ["Camrose", "Cold Lake", "Fort McMurray", "Calgary"]
    path = tmp_path / "multi.csv"
    with path.open("w", encoding="utf-16", newline="") as fh:
        w = _csv.writer(fh, delimiter="\t")
        w.writerow(cols)
        for i, town in enumerate(towns):  # same job, one row per town (as seen June 2026)
            w.writerow([f"7{i}", "software developer", "2026/06/22", "1", "Alberta", town,
                        "Year", "80000", "90000", "21232"])
        w.writerow(["99", "software developer", "2026/06/23", "1", "Alberta", "Edmonton",
                    "Year", "95000", "99000", "21232"])  # a genuinely different posting

    load_file(factory, path, "multi", date(2026, 6, 1), SEARCHES)
    with factory() as s:
        stat = s.scalar(select(MonthlyDemandStat).where(
            MonthlyDemandStat.search_key == "software developer|alberta"))
        assert (stat.new_postings, stat.vacancies) == (2, 2)


def test_mid_2024_export_without_id_column(factory, tmp_path):
    """Jun-Sep 2024: UTF-8, commas, no 'WIC Job Location Snapshot ID', dashed dates."""
    path = tmp_path / "june2024.csv"
    path.write_text(
        "Job Title,First Posting Date,Vacancy Count,Province/Territory,City,Salary Per,"
        "Salary Minimum,Salary Maximum,NOC21 Code\n"
        "data analyst,2024-06-07,1,Alberta,Calgary,Year,60000,70000,21223\n"
        "data analyst,2024-06-09,1,Alberta,Edmonton,Year,62000,72000,21223\n",
        encoding="utf-8-sig")
    run = load_file(factory, path, "june2024", date(2024, 6, 1), SEARCHES)
    assert (run.status, run.fetched) == ("success", 2)
    load_file(factory, path, "june2024-again", date(2024, 6, 1), SEARCHES)
    with factory() as s:
        ids = [p.source_id for p in s.scalars(select(Posting))]
        assert len(ids) == 2 and all(i.startswith("h:") for i in ids)  # stable across reloads


def test_canada_search_keeps_rows_from_every_province(factory):
    canada = [*SEARCHES, TrackedSearch("data analyst", "Canada")]
    load_file(factory, FIXTURE, "sept", SEPT, canada)
    with factory() as s:
        toronto = s.scalar(select(Posting).where(Posting.source_id == "90000003"))
        assert {x.search_key for x in toronto.searches} == {"data analyst|canada"}
        stat = s.scalar(select(MonthlyDemandStat).where(
            MonthlyDemandStat.search_key == "data analyst|canada"))
        assert stat.new_postings == 3  # Calgary, Alberta (no city) and Toronto


def test_reload_reprocesses_loaded_months_for_new_searches(factory):
    package = {"result": {"resources": [
        {"name": "September 2026 Job Postings Advertised on Canada's National Job Bank Website",
         "format": "CSV", "language": ["en"], "url": "https://files.example/sept-en.csv"},
    ]}}

    def handler(request):
        if "package_show" in str(request.url):
            return httpx.Response(200, json=package)
        return httpx.Response(200, content=FIXTURE.read_bytes())

    canada = [*SEARCHES, TrackedSearch("data analyst", "Canada")]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        load_latest(factory, client, SEARCHES)
        assert load_latest(factory, client, canada) == []  # already loaded: skipped
        [run] = load_latest(factory, client, canada, reload=True)
    assert run.status == "success"
    with factory() as s:
        assert s.scalar(select(Posting).where(Posting.source_id == "90000003")) is not None
        assert len(s.scalars(select(LoadedFile)).all()) == 1  # replaced, not duplicated
