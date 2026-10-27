from pipeline.config import TrackedSearch
from pipeline.normalize import (
    fingerprint,
    html_to_text,
    location_in_region,
    matching_searches,
    title_matches_role,
)


def test_fingerprint_ignores_company_suffix_case_and_province_format():
    a = fingerprint("Data Analyst", "ExampleCorp Inc.", "Calgary, Alberta")
    b = fingerprint("data analyst", "examplecorp", "Calgary, AB")
    assert a == b


def test_fingerprint_differs_by_city():
    assert fingerprint("Data Analyst", "X", "Calgary, AB") != fingerprint("Data Analyst", "X", "Edmonton, AB")


def test_html_to_text_unescapes_greenhouse_content():
    raw = "&lt;ul&gt;&lt;li&gt;SQL &amp;amp; Python&lt;/li&gt;&lt;/ul&gt;"
    assert html_to_text(raw) == "SQL & Python"


def test_region_matching_uses_city_aliases():
    assert location_in_region("Red Deer, AB", "Alberta")
    assert location_in_region("Edmonton", "alberta")
    assert not location_in_region("Toronto, ON", "Alberta")
    # "on" alias for Ontario must match as a whole word, not inside "Edmonton"
    assert not location_in_region("Edmonton, Alberta", "Ontario")


def test_title_matching():
    assert title_matches_role("Senior Data Analyst II", "data analyst")
    assert title_matches_role("Data Analyst, Supply Chain", "Data Analyst")
    assert not title_matches_role("Data Engineer", "data analyst")


def test_matching_searches():
    searches = [TrackedSearch("data analyst", "Alberta"), TrackedSearch("data analyst", "Ontario")]
    assert matching_searches("Data Analyst", "Calgary, AB", searches) == ["data analyst|alberta"]
