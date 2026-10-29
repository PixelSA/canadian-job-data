from pipeline.db import Posting, RawPosting


def test_columns_from_external_apis_are_unbounded():
    # SQLite ignores String(n), so a too-small limit only fails on Postgres (it broke JSearch).
    columns = [RawPosting.source_id, Posting.source_id, Posting.title, Posting.company,
               Posting.location, Posting.url]
    assert [c.key for c in columns if getattr(c.type, "length", None)] == []
