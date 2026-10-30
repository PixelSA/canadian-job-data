"""Shared ingestion steps: store raw -> upsert/dedupe -> extract skills.

Used by both the daily run (pipeline.run) and the monthly Job Bank loader (pipeline.jobbank).
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from pipeline.budget import BudgetExhausted
from pipeline.config import TrackedSearch
from pipeline.db import IngestionRun, Posting, PostingSearch, PostingSkill, RawPosting
from pipeline.normalize import clean_display_name, fingerprint, matching_searches, payload_hash, title_matches_role
from pipeline.skills import SkillExtractor
from pipeline.sources import JobRecord, Source

log = logging.getLogger("pipeline")


@dataclass
class UpsertResult:
    created: bool
    changed: bool


def store_raw(session: Session, rec: JobRecord, run_id: int) -> None:
    if rec.raw is None:
        return
    h = payload_hash(rec.raw)
    exists = session.scalar(
        select(RawPosting.id).where(
            RawPosting.source == rec.source,
            RawPosting.source_id == rec.source_id,
            RawPosting.payload_hash == h,
        )
    )
    if not exists:
        session.add(RawPosting(source=rec.source, source_id=rec.source_id, payload_hash=h,
                               payload=rec.raw, run_id=run_id))


def dedupe_fingerprint(source: str, key: str) -> str:
    return hashlib.sha256(f"{source}:{key}".encode()).hexdigest()


def _fingerprint(rec: JobRecord) -> str:
    if rec.company:
        return fingerprint(rec.title, rec.company, rec.location)
    if rec.dedupe_key:
        return dedupe_fingerprint(rec.source, rec.dedupe_key)
    # Without an employer, "data analyst in Alberta" would merge unrelated jobs; keep it unique.
    return dedupe_fingerprint(rec.source, rec.source_id)


def upsert_posting(
    session: Session, rec: JobRecord, today: date, searches: list[TrackedSearch]
) -> UpsertResult:
    seen = rec.seen_on or today
    posting = session.scalar(
        select(Posting)
        .where(Posting.source == rec.source, Posting.source_id == rec.source_id)
        .options(selectinload(Posting.searches))
    )
    created = posting is None
    if created:
        posting = Posting(source=rec.source, source_id=rec.source_id, first_seen=seen,
                          last_seen=seen, searches=[])
        session.add(posting)

    changed = not created and posting.description != rec.description
    posting.fingerprint = _fingerprint(rec)
    posting.title = rec.title
    posting.company = clean_display_name(rec.company)
    posting.location = rec.location
    posting.occupation_code = rec.occupation_code
    posting.vacancies = rec.vacancies
    posting.description = rec.description
    posting.description_is_full = rec.description_is_full
    posting.url = rec.url
    posting.salary_min = rec.salary_min
    posting.salary_max = rec.salary_max
    posting.salary_is_estimate = rec.salary_is_estimate
    posting.posted_at = rec.posted_at
    posting.first_seen = min(posting.first_seen, seen)
    posting.last_seen = max(posting.last_seen, seen)
    if created or changed:
        posting.extractor_version = None  # queue for (re)extraction

    set_searches(posting, search_keys_for(rec, searches))
    return UpsertResult(created=created, changed=changed)


def search_keys_for(rec: JobRecord, searches: list[TrackedSearch]) -> set[str]:
    """Searches a posting counts toward. The title must match the role, whatever the source:
    aggregators match loosely (JSearch's "data analyst" returns "Climate Analyst"). A source's
    own search can vouch for the region, since Adzuna locations like "Onefour" are obscure."""
    keys = set(matching_searches(rec.title, rec.location, searches))
    by_key = {s.key: s for s in searches}
    keys |= {k for k in rec.search_keys
             if k in by_key and title_matches_role(rec.title, by_key[k].role)}
    return keys


def set_searches(posting: Posting, keys: set[str]) -> None:
    have = {s.search_key for s in posting.searches}
    for key in sorted(keys - have):
        posting.searches.append(PostingSearch(search_key=key))


def reclean_companies(session: Session) -> int:
    """Re-apply clean_display_name to stored company names (for rows ingested before it)."""
    changed = 0
    for p in session.scalars(select(Posting).where(Posting.company.is_not(None))):
        cleaned = clean_display_name(p.company)
        if cleaned != p.company:
            p.company = cleaned
            changed += 1
    session.commit()
    return changed


def rematch_all(session: Session, searches: list[TrackedSearch]) -> int:
    """Recompute search membership for stored postings (after changing TRACKED_SEARCHES or
    matching rules) without refetching anything. Returns the number of postings changed."""
    changed = 0
    for posting in session.scalars(select(Posting).options(selectinload(Posting.searches))):
        new = set(matching_searches(posting.title, posting.location, searches))
        have = {s.search_key for s in posting.searches}
        if new != have:
            # Remove first: a unique (posting, search) row can't be re-inserted before the
            # old one is deleted, which is the order a plain collection swap would flush in.
            for link in [s for s in posting.searches if s.search_key not in new]:
                posting.searches.remove(link)
            session.flush()
            set_searches(posting, new)
            changed += 1
    session.commit()
    return changed


def ingest_source(
    session: Session, source: Source, run: IngestionRun, today: date,
    searches: list[TrackedSearch],
) -> bool:
    """Pull one source into the DB. Returns False if it failed (the run carries on).

    Budgeted sources write their call counter in a separate transaction before each request.
    SQLite allows a single writer, so we must not hold an open write transaction while the
    source fetches its next page: commit after every record for those sources. Upserts are
    idempotent, so partially ingested sources are safe to re-run.
    """
    budget = getattr(source, "budget", None)
    if budget:
        budget.start_run()
    commit_every = 1 if budget else 500
    try:
        for i, rec in enumerate(source.fetch(), start=1):
            run.fetched += 1
            store_raw(session, rec, run.id)
            result = upsert_posting(session, rec, today, searches)
            run.new_postings += result.created
            run.updated_postings += result.changed
            if i % commit_every == 0:
                session.commit()
            else:
                session.flush()
        session.commit()
        return True
    except BudgetExhausted as exc:
        # Expected for quota-limited APIs: keep everything fetched before the limit.
        log.warning("%s", exc)
        run.notes = [*run.notes, str(exc)]
        session.commit()
        return True
    except Exception as exc:  # one bad source shouldn't sink the run
        session.rollback()
        log.exception("source %s failed", source.name)
        run.errors = [*run.errors, f"{source.name}: {exc}"]
        session.commit()
        return False


def extract_pending(session: Session, extractor: SkillExtractor, batch_size: int = 500) -> int:
    """(Re)extract skills for postings that are new, changed, or from an older extractor."""
    done = 0
    while True:
        batch = session.scalars(
            select(Posting)
            .where(or_(Posting.extractor_version.is_(None),
                       Posting.extractor_version != extractor.version))
            .options(selectinload(Posting.skills))
            .limit(batch_size)
        ).all()
        if not batch:
            return done
        for p in batch:
            p.skills.clear()
        session.flush()  # delete old rows before inserting new ones (unique posting+skill)
        for p in batch:
            p.skills = [
                PostingSkill(skill=s.name, category=s.category, extractor_version=extractor.version)
                for s in extractor.extract(f"{p.title}. {p.description}")
            ]
            p.extractor_version = extractor.version
        session.commit()
        done += len(batch)
