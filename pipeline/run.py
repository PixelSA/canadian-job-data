"""Daily pipeline: fetch -> store raw -> upsert/dedupe -> extract skills -> aggregate.

    python -m pipeline.run                     # live sources configured in .env
    python -m pipeline.run --fixtures          # offline, using tests/fixtures
    python -m pipeline.run --fixtures --day 2026-10-20
    python -m pipeline.run --budgets           # show quota usage for JSearch/Jooble/Adzuna/Jobven
    python -m pipeline.run --rematch           # after editing TRACKED_SEARCHES; no API calls
"""

import argparse
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

from pipeline.aggregate import aggregate_day, aggregate_month
from pipeline.budget import RequestBudget
from pipeline.config import ROOT, TrackedSearch, settings
from pipeline.db import IngestionRun, MonthlyDemandStat, make_session_factory
from pipeline.ingest import extract_pending, ingest_source, reclean_companies, rematch_all
from pipeline.jobbank import refingerprint
from pipeline.skills import SkillExtractor, get_extractor
from pipeline.sources import (
    AdzunaSource,
    AshbySource,
    GreenhouseSource,
    JobvenSource,
    JoobleSource,
    JSearchSource,
    LeverSource,
    SmartRecruitersSource,
    Source,
)
from pipeline.sources.base import default_client
from pipeline.sources.jobven import last_listed_at

log = logging.getLogger("pipeline")

FIXTURES_DIR = ROOT / "tests" / "fixtures"


def run_pipeline(
    session_factory,
    sources: list[Source],
    searches: list[TrackedSearch],
    today: date | None = None,
    extractor: SkillExtractor | None = None,
) -> IngestionRun:
    today = today or date.today()
    extractor = extractor or get_extractor()

    with session_factory() as session:
        run = IngestionRun(errors=[], notes=[])
        session.add(run)
        session.commit()

        failed_sources = sum(
            not ingest_source(session, source, run, today, searches) for source in sources
        )

        extracted = extract_pending(session, extractor)
        log.info("extracted skills for %d postings (extractor %s)", extracted, extractor.version)
        aggregate_day(session, today, [s.key for s in searches])

        run.finished_at = datetime.now(timezone.utc)
        if failed_sources == 0:
            run.status = "success"
        elif failed_sources < len(sources):
            run.status = "partial"
        else:
            run.status = "failed"
        session.commit()
        return run


# ---------------------------------------------------------------- source wiring


def _slug(text: str) -> str:
    return text.lower().strip().replace(" ", "-")


def fixture_transport(fixtures_dir: Path = FIXTURES_DIR) -> httpx.MockTransport:
    """Serves saved API responses so the pipeline runs offline (and in tests)."""

    def load(name: str, default=None):
        file = fixtures_dir / name
        if file.exists():
            return httpx.Response(200, json=json.loads(file.read_text(encoding="utf-8")))
        return httpx.Response(200, json=default) if default is not None else httpx.Response(404)

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path.strip("/").split("/")
        params = request.url.params
        if host == "api.adzuna.com":
            return load(f"adzuna_{_slug(params.get('what', ''))}_page{path[-1]}.json",
                        {"results": []})
        if host in ("api.openwebninja.com", "jsearch.p.rapidapi.com"):
            role = params.get("query", "").split(" in ")[0]
            return load(f"jsearch_{_slug(role)}.json", {"status": "OK", "data": []})
        if host == "api.jobven.com":
            return load("jobven_jobs.json", {"data": [], "meta": {"hasMore": False}})
        if host == "jooble.org":
            role = json.loads(request.content).get("keywords", "")
            return load(f"jooble_{_slug(role)}.json", {"totalCount": 0, "jobs": []})
        if host == "boards-api.greenhouse.io":
            return load(f"greenhouse_{path[2]}.json")
        if host == "api.lever.co":
            return load(f"lever_{path[2]}.json")
        if host == "api.ashbyhq.com":
            return load(f"ashby_{path[-1]}.json")
        if host == "api.smartrecruiters.com":
            company = path[2]
            if len(path) > 4:  # /v1/companies/{c}/postings/{id}
                return load(f"smartrecruiters_{company}_{path[4]}.json")
            return load(f"smartrecruiters_{company}.json")
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def make_budgets(session_factory) -> dict[str, RequestBudget]:
    s = settings
    return {
        "jsearch": RequestBudget(session_factory, "jsearch", s.jsearch_monthly_limit, "month",
                                 max_per_run=s.jsearch_max_per_run),
        "jooble": RequestBudget(session_factory, "jooble", s.jooble_lifetime_limit, "lifetime",
                                max_per_run=s.jooble_max_per_run),
        "adzuna": RequestBudget(session_factory, "adzuna", s.adzuna_lifetime_limit, "lifetime",
                                max_per_run=s.adzuna_max_per_run),
        "jobven": RequestBudget(session_factory, "jobven", s.jobven_monthly_limit, "month",
                                max_per_run=s.jobven_max_per_run, unit="records"),
    }


def build_sources(
    client: httpx.Client, use_fixtures: bool, searches: list[TrackedSearch], session_factory
) -> list[Source]:
    budgets = make_budgets(session_factory)
    if use_fixtures:
        return [
            JSearchSource(client, "fixture", searches, budgets["jsearch"]),
            JoobleSource(client, "fixture", searches, budgets["jooble"]),
            JobvenSource(client, "fixture", searches, budgets["jobven"]),
            AdzunaSource(client, "fixture", "fixture", searches, page_delay=0,
                         budget=budgets["adzuna"]),
            GreenhouseSource(client, ["examplecorp"]),
            LeverSource(client, ["examplestartup"]),
            AshbySource(client, ["examplehealth"]),
            SmartRecruitersSource(client, ["ExampleRetail"], searches, detail_delay=0),
        ]

    s = settings
    sources: list[Source] = []
    # Quota-limited APIs are opt-in: they only run when their key is configured.
    if s.jsearch_api_key:
        sources.append(JSearchSource(client, s.jsearch_api_key, searches, budgets["jsearch"],
                                     s.jsearch_provider, s.jsearch_country, s.jsearch_date_posted))
    if s.jooble_api_key:
        sources.append(JoobleSource(client, s.jooble_api_key, searches, budgets["jooble"]))
    if s.jobven_api_key:
        sources.append(JobvenSource(client, s.jobven_api_key, searches, budgets["jobven"],
                                    last_listed_at(session_factory), s.jobven_country,
                                    s.jobven_lookback_days))
    if s.adzuna_app_id and s.adzuna_app_key:
        sources.append(AdzunaSource(client, s.adzuna_app_id, s.adzuna_app_key, searches,
                                    s.adzuna_country, max_pages=1, budget=budgets["adzuna"]))
    if s.greenhouse_boards:
        sources.append(GreenhouseSource(client, s.greenhouse_boards))
    if s.lever_companies:
        sources.append(LeverSource(client, s.lever_companies))
    if s.ashby_boards:
        sources.append(AshbySource(client, s.ashby_boards))
    if s.smartrecruiters_companies:
        sources.append(SmartRecruitersSource(client, s.smartrecruiters_companies, searches))
    if not sources:
        log.warning("No sources configured; set JSEARCH_API_KEY and/or company boards in .env")
    return sources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixtures", action="store_true", help="use saved responses, no network")
    parser.add_argument("--day", type=date.fromisoformat, help="pretend today is YYYY-MM-DD")
    parser.add_argument("--db", default=settings.database_url, help="SQLAlchemy database URL")
    parser.add_argument("--budgets", action="store_true", help="print API quota usage and exit")
    parser.add_argument("--rematch", action="store_true",
                        help="recompute which searches stored postings belong to, tidy stored "
                             "company names, re-aggregate (no API calls), and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    session_factory = make_session_factory(args.db)

    if args.budgets:
        for name, b in make_budgets(session_factory).items():
            print(f"{name:8} {b.used():>4} / {b.limit} {b.unit} used ({b.period_key})")
        return
    if args.rematch:
        keys = [s.key for s in settings.searches]
        with session_factory() as session:
            refingerprint(session)
            recleaned = reclean_companies(session)
            changed = rematch_all(session, settings.searches)
            aggregate_day(session, args.day or date.today(), keys)
            months = session.scalars(select(MonthlyDemandStat.month).distinct()).all()
            for month in months:
                aggregate_month(session, month, keys)
        print(f"rematched {changed} postings, cleaned {recleaned} company names; "
              f"re-aggregated today and {len(months)} months")
        return

    client = (httpx.Client(transport=fixture_transport()) if args.fixtures else default_client())
    with client:
        sources = build_sources(client, args.fixtures, settings.searches, session_factory)
        run = run_pipeline(session_factory, sources, settings.searches, today=args.day)
    print(f"run {run.id}: {run.status} | fetched={run.fetched} new={run.new_postings} "
          f"updated={run.updated_postings} errors={len(run.errors)} notes={run.notes}")
    if run.status == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
