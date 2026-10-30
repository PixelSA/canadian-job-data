# Job Market Intelligence: data pipeline

Ingestion of job postings, skill extraction, and pre-aggregated trends for the job market
intelligence app (search a role + region, see trending skills, salaries, and demand over time).

## Sources

All sources are free. The ones with quotas run under a request budget stored in the database.

| Source | Role | Cost / limit | Full description? |
|---|---|---|---|
| **JSearch** | Daily market-wide postings (Google for Jobs: LinkedIn, Indeed, Glassdoor...) | 200 req/month, guarded | Yes |
| **Greenhouse, Lever, Ashby, SmartRecruiters** | Daily postings from tracked employers | Unlimited, no key | Yes |
| **Jobven** | Daily postings scraped from employers' own career pages (incl. Workday) | 300 *records*/month, guarded | Yes |
| **Job Bank open data** | Monthly history back to 2023: volume, vacancies, salaries, NOC codes | Unlimited, monthly CSV | No (title only) |
| Jooble, Adzuna | Optional, off unless a key is set | 500 lifetime / ~25 total | Snippets |

## How it works

```
 JSearch ───────┐
 Greenhouse ────┤                                                 ┌─▶ daily_skill_stats
 Lever, Ashby ──┼─▶ raw_postings ─▶ postings ─▶ posting_skills ───┤   daily_salary_stats
 SmartRecruit. ─┘   (exact JSON)    (deduped,    (spaCy matcher,  │
                                     first/last   versioned)      │
 Job Bank CSV (monthly) ───────────▶ seen)  ──────────────────────┴─▶ monthly_demand_stats
```

| Step | Module | Notes |
|---|---|---|
| Fetch | `pipeline/sources/` | Official APIs only; retry with backoff on 429/5xx. |
| Request budgets | `pipeline/budget.py` | Each call to JSearch/Jooble/Adzuna is counted in `api_usage` **before** it is sent, in its own transaction, so the count survives crashes. Monthly or lifetime limits, plus a per-run cap. When the budget runs out the source stops cleanly, the run keeps what it fetched and records a note. Retries count too, because they do against the real quota. Jobven bills per job record instead: a page's size is reserved before the call and the unused part refunded. |
| Store raw | `ingest.store_raw` | Untouched payloads, so improvements can reprocess history without re-calling APIs. (Job Bank rows skip this; the monthly file is already an immutable, re-downloadable raw layer.) |
| Upsert + dedupe | `ingest.upsert_posting` | `(source, source_id)` is unique; a title/company/city **fingerprint** links the same job across sources (JSearch often repeats one job with several apply links). |
| Extract skills | `pipeline/skills/` | ~135-skill YAML taxonomy + spaCy `PhraseMatcher`. Ambiguous names (R, Go, C, Excel, Spark, Swift) need exact case **and** context. |
| Aggregate | `aggregate.py` | **Daily:** skill share + salary p25/median/p75 among *active* postings (deduped, live sources only). **Monthly:** new postings, vacancies, salaries from Job Bank. Job Bank only records a first-posting date, not a close date, so it can't feed "active" counts. |

The extractor version is `v<logic>-<hash of skills.yaml>`: edit the taxonomy and the next run
re-extracts every stored posting.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,api]"
pytest                                   # no network needed
python -m pipeline.run --fixtures        # daily pipeline on saved sample responses -> jobs.db
python -m pipeline.jobbank --file tests/fixtures/jobbank_sample.csv --month 2026-09
```

Live data: copy `.env.example` to `.env`, add your JSearch key and some company boards, then

```bash
python -m pipeline.run              # daily sources
python -m pipeline.run --budgets    # how much quota is left
python -m pipeline.jobbank --latest 45   # backfill all Job Bank history (~3 GB download, one-off)
python -m pipeline.run --rematch    # after editing TRACKED_SEARCHES: reclassify, no API calls
python -m pipeline.jobbank --latest 45 --reload   # then give new searches Job Bank history
```

A posting counts toward a search only if its **title** contains the role's words and its location
is in the region. A `Canada` search matches any province or territory (by name, code such as
`Toronto, ON`, or major city) and rejects US places; Jobven's daily query stays on the tracked
provinces, since its free plan can't cover the whole country. The aggregators' own matching is too loose for stats: on the first live run,
JSearch's "data analyst" results included "Climate Analyst" and "Supply Chain Analyst".

By default the Job Bank loader keeps only rows matching a tracked role in a tracked region
(about 10k Alberta postings a month otherwise); `--all-roles` keeps all of them. Files already
loaded are recorded in `loaded_files` and skipped.

In production `.github/workflows/ingest.yml` runs the daily job and the monthly Job Bank load
against hosted Postgres (`pip install -e ".[postgres]"`).

## API

A read-only FastAPI app (`api/`) serves the aggregated data to the frontend.

```bash
pip install -e ".[dev,api]"
uvicorn api.main:app --reload            # from the project root; docs at http://localhost:8000/docs
```

Every data endpoint takes `role` and `region` (case and spacing don't matter); an unknown
search returns 404 with the list of available ones.

| Endpoint | Returns |
|---|---|
| `GET /searches` | Tracked role + region searches |
| `GET /trends/skills?limit=` | Latest day's top skills: active postings, share, change vs. 7 days earlier |
| `GET /trends/salaries?days=` | Daily salary p25 / median / p75 and sample size |
| `GET /trends/demand?since=` | Monthly Job Bank postings, vacancies and salaries; the July 2025 series break carries a `note` |
| `GET /postings?limit=&offset=` | Active postings, newest first, with `total` for paging |
| `GET /companies?limit=` | Top hiring companies by distinct active jobs |
| `GET /health` | Liveness check |

Data endpoints send `Cache-Control: public, max-age=3600`, since the data changes once a day.

| Variable | Purpose |
|---|---|
| `API_DATABASE_URL` | Read-only connection (role from `sql/api_reader.sql`). Unset falls back to `DATABASE_URL`, for local dev only. |
| `API_CORS_ORIGINS` | Comma-separated browser origins allowed to call the API (default: `localhost:5173`, `localhost:3000`) |

Deploying (e.g. Render): build `pip install ".[api,postgres]"`, start
`uvicorn api.main:app --host 0.0.0.0 --port $PORT`, health check `/health`.

## Known limitations

- Jobven syncs incrementally (oldest-listed first, from the newest listing already stored), capped at `JOBVEN_MAX_PER_RUN` records a day. If Alberta listings for the tracked roles outpace ~10/day, it falls behind rather than skipping jobs. Its own AI-extracted skills are kept in `raw_postings` but not used: stats come from one extractor so every source is measured the same way. Only CAD salaries are used. Its terms forbid redistributing the raw data; check them before listing individual postings publicly.
- Daily skill counts come from JSearch (whole market, capped at ~10 newest postings per search per day on the free plan) and tracked employers' job boards, which skew toward companies on those platforms.
- Job Bank has no employer names or descriptions, so it contributes demand and salary history, not skills.
- **Job Bank series break, July 2025:** tracked-role postings fall about 80%. The file format didn't change; rows from Job Bank's *partner job boards* dropped (Alberta: 6,493 to 3,617 between June and July 2025) while direct employer postings held steady (3,685 to 3,648). Charts should mark this break rather than present it as a collapse in demand.
- Job Bank lists a multi-location posting once per town (one June 2026 posting covered 153 Alberta towns). Rows with the same title, day, pay, occupation code and province count as one job.
- JSearch's base URL/header differ between OpenWebNinja and RapidAPI keys (`JSEARCH_PROVIDER`); confirm against your dashboard's sample request. Also check its terms on storing and displaying results before deploying publicly.
- Dictionary matching only finds skills in the taxonomy; the raw layer + versioning make a later NER model a reprocess, not a re-scrape.
- Schema changes are applied with `create_all` (new tables only). Add Alembic before the schema stabilizes.

Fixture companies and postings in `tests/fixtures/` are fictional.
