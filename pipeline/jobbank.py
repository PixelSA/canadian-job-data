"""Monthly loader for Job Bank open data (Government of Canada, Open Government Licence).

Dataset: https://open.canada.ca/data/en/dataset/ea639e28-c0fc-48bf-b5dd-b8899bd43072
One CSV per month, back to 2023. Format quirks handled here:
  * UTF-16 with a BOM, tab-separated (despite the .csv name)
  * missing values are the string "NA"
  * Jun-Sep 2024 are a different export: UTF-8, comma-separated, no snapshot ID column,
    dates as 2024-06-04 (elsewhere 2026/09/02)
  * from July 2025, rows from partner job boards ("External Indicator" = 1) drop sharply
    while direct employer postings hold steady; treat it as a break in the series
  * a multi-location posting gets one row (and ID) per town; one June 2026 posting appeared
    in 153 Alberta towns, so rows are deduplicated into one job (see jobbank_dedupe_key)
  * no employer name, URL or description: useful for volume, salary and NOC codes, not skills

    python -m pipeline.jobbank                    # load the newest month not loaded yet
    python -m pipeline.jobbank --latest 12        # backfill up to 12 months
    python -m pipeline.jobbank --latest 45 --reload   # reprocess history for new searches
    python -m pipeline.jobbank --file tests/fixtures/jobbank_sample.csv --month 2026-09
"""

import argparse
import codecs
import csv
import hashlib
import io
import logging
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import httpx
from sqlalchemy import select

from pipeline.aggregate import aggregate_month
from pipeline.config import TrackedSearch, settings
from pipeline.db import IngestionRun, LoadedFile, make_session_factory
from pipeline.ingest import extract_pending, ingest_source
from pipeline.normalize import location_in_region, title_matches_role
from pipeline.skills import get_extractor
from pipeline.sources.base import JobRecord, annualize, default_client, get_json

log = logging.getLogger("pipeline.jobbank")

SOURCE = "jobbank"
PACKAGE_URL = ("https://open.canada.ca/data/api/action/package_show"
               "?id=ea639e28-c0fc-48bf-b5dd-b8899bd43072")


@dataclass(frozen=True)
class MonthlyFile:
    month: date
    name: str
    url: str


def list_files(client: httpx.Client) -> list[MonthlyFile]:
    """English monthly CSVs, newest first, from the open.canada.ca catalogue API."""
    resources = get_json(client, PACKAGE_URL)["result"]["resources"]
    files = []
    for r in resources:
        if r.get("format") != "CSV" or "en" not in (r.get("language") or []):
            continue
        m = re.match(r"([A-Za-z]+) (\d{4})", r.get("name", ""))
        if not m:
            continue
        try:
            month = datetime.strptime(f"{m[1]} {m[2]}", "%B %Y").date()
        except ValueError:
            continue
        files.append(MonthlyFile(month, r["name"], r["url"]))
    return sorted(files, key=lambda f: f.month, reverse=True)


def iter_rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open("rb") as fh:
        head = fh.read(4)
        fh.seek(0)
        if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            encoding = "utf-16"
        else:
            encoding = "utf-8-sig"
        text = io.TextIOWrapper(fh, encoding=encoding, errors="replace", newline="")
        first = text.readline()
        delimiter = "\t" if "\t" in first else ","
        text.seek(0)
        yield from csv.DictReader(text, delimiter=delimiter)


def _val(row: dict, col: str) -> str | None:
    v = (row.get(col) or "").strip()
    return None if v in ("", "NA", "*No data") else v


def _num(row: dict, col: str) -> float | None:
    v = _val(row, col)
    try:
        return float(v.replace(",", "")) if v else None
    except ValueError:
        return None


DATE_FORMATS = ("%Y/%m/%d", "%Y-%m-%d")


def _row_hash(row: dict) -> str:
    """Stable ID for files without a snapshot ID column (Jun-Sep 2024)."""
    content = "\x1f".join(f"{k}={v}" for k, v in sorted(row.items()) if k)
    return "h:" + hashlib.sha1(content.encode()).hexdigest()


def parse_date(value: str | None) -> date | None:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value or "", fmt).date()
        except ValueError:
            continue
    return None


def jobbank_dedupe_key(title: str, posted: date, salary_min: float | None,
                       salary_max: float | None, noc: str | None, province: str) -> str:
    """Same title, day, pay and occupation in one province = one posting listed in many towns."""
    return f"{title.lower()}|{posted}|{salary_min}|{salary_max}|{noc}|{province.lower()}"


def row_to_record(row: dict, searches: list[TrackedSearch],
                  all_roles: bool = False) -> JobRecord | None:
    """Map a CSV row, or None if it's outside the tracked regions (or roles) or unusable."""
    title = _val(row, "Job Title") or _val(row, "Original Job Title")
    province, city = _val(row, "Province/Territory"), _val(row, "City")
    seen = parse_date(_val(row, "First Posting Date"))
    if not title or not province or not seen:
        return None
    location = f"{city}, {province}" if city else province
    relevant = [s for s in searches if location_in_region(location, s.region)]
    if not all_roles:
        relevant = [s for s in relevant if title_matches_role(title, s.role)]
    if not relevant:
        return None

    period = _val(row, "Salary Per")
    vacancies = _num(row, "Vacancy Count")
    salary_min = annualize(_num(row, "Salary Minimum"), period)
    salary_max = annualize(_num(row, "Salary Maximum"), period)
    noc = _val(row, "NOC21 Code")
    return JobRecord(
        source=SOURCE,
        source_id=_val(row, "WIC Job Location Snapshot ID") or _row_hash(row),
        title=title,
        company=None,  # not published in the open data
        location=location,
        description="",
        description_is_full=False,
        url=None,
        raw=None,  # the monthly file itself is the immutable raw layer
        salary_min=salary_min,
        salary_max=salary_max,
        posted_at=datetime.combine(seen, datetime.min.time()),
        seen_on=seen,
        occupation_code=noc,
        vacancies=int(vacancies) if vacancies else None,
        dedupe_key=jobbank_dedupe_key(title, seen, salary_min, salary_max, noc, province),
    )


def refingerprint(session) -> int:
    """Re-apply jobbank_dedupe_key to stored rows (for data loaded before it existed)."""
    from sqlalchemy import select as _select

    from pipeline.db import Posting
    from pipeline.ingest import dedupe_fingerprint

    changed = 0
    for p in session.scalars(_select(Posting).where(Posting.source == SOURCE)):
        province = (p.location or "").split(",")[-1].strip()
        fp = dedupe_fingerprint(SOURCE, jobbank_dedupe_key(
            p.title, p.first_seen, p.salary_min, p.salary_max, p.occupation_code, province))
        if fp != p.fingerprint:
            p.fingerprint = fp
            changed += 1
    session.commit()
    return changed


class CsvSource:
    """Adapts a downloaded monthly file to the Source interface used by ingest_source."""

    name = SOURCE

    def __init__(self, path: Path, searches: list[TrackedSearch], all_roles: bool = False):
        self.path, self.searches, self.all_roles = path, searches, all_roles
        self.rows_read = 0

    def fetch(self) -> Iterator[JobRecord]:
        for row in iter_rows(self.path):
            self.rows_read += 1
            rec = row_to_record(row, self.searches, self.all_roles)
            if rec:
                yield rec


def load_file(session_factory, path: Path, name: str, month: date,
              searches: list[TrackedSearch], url: str | None = None,
              all_roles: bool = False) -> IngestionRun:
    source = CsvSource(path, searches, all_roles)
    with session_factory() as session:
        run = IngestionRun(errors=[], notes=[f"jobbank file: {name}"])
        session.add(run)
        session.commit()

        ok = ingest_source(session, source, run, month, searches)
        extract_pending(session, get_extractor())  # titles only; still catches "SQL developer"
        aggregate_month(session, month, [s.key for s in searches])
        if ok:
            # A --reload replaces the earlier record of the same file
            session.query(LoadedFile).filter_by(source=SOURCE, name=name).delete()
            session.add(LoadedFile(source=SOURCE, name=name, url=url, rows_loaded=run.fetched))
        run.status = "success" if ok else "failed"
        run.finished_at = datetime.now().astimezone()
        session.commit()
        log.info("%s: %d rows read, %d kept", name, source.rows_read, run.fetched)
        return run


def download(client: httpx.Client, url: str, dest: Path) -> None:
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in resp.iter_bytes(1 << 20):
                fh.write(chunk)


def load_latest(session_factory, client: httpx.Client, searches: list[TrackedSearch],
                latest: int = 1, all_roles: bool = False,
                reload: bool = False) -> list[IngestionRun]:
    with session_factory() as s:
        done = set() if reload else set(
            s.scalars(select(LoadedFile.name).where(LoadedFile.source == SOURCE)))
    todo = [f for f in list_files(client)[:latest] if f.name not in done]
    if not todo:
        log.info("Job Bank: nothing new to load")
    runs = []
    for f in reversed(todo):  # oldest first, so history fills in order
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobbank.csv"
            log.info("downloading %s", f.name)
            download(client, f.url, path)
            runs.append(load_file(session_factory, path, f.name, f.month, searches, f.url,
                                  all_roles))
    return runs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--latest", type=int, default=1, help="consider the newest N months")
    parser.add_argument("--file", type=Path, help="load a local file instead of downloading")
    parser.add_argument("--month", help="YYYY-MM of --file")
    parser.add_argument("--all-roles", action="store_true",
                        help="keep every posting in tracked regions, not just tracked roles")
    parser.add_argument("--reload", action="store_true",
                        help="reprocess months already loaded, e.g. after adding a tracked "
                             "search (Canada) whose rows earlier loads skipped")
    parser.add_argument("--db", default=settings.database_url)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    factory = make_session_factory(args.db)
    if args.file:
        if not args.month:
            parser.error("--file needs --month YYYY-MM")
        month = datetime.strptime(args.month, "%Y-%m").date()
        runs = [load_file(factory, args.file, args.file.name, month, settings.searches,
                          all_roles=args.all_roles)]
    else:
        with default_client() as client:
            runs = load_latest(factory, client, settings.searches, args.latest, args.all_roles,
                               args.reload)
    for run in runs:
        print(f"run {run.id}: {run.status} | kept={run.fetched} new={run.new_postings}")
    if any(r.status == "failed" for r in runs):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
