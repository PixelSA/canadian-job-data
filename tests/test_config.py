import importlib

import pytest

import pipeline.config


@pytest.fixture
def load_settings(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)  # ignore the local .env

    def load(**env):
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        return importlib.reload(pipeline.config).Settings()

    yield load
    monkeypatch.undo()
    importlib.reload(pipeline.config)


def test_blank_values_fall_back_to_defaults(load_settings):
    # What GitHub Actions passes for a secret/variable that was never created.
    s = load_settings(DATABASE_URL="", TRACKED_SEARCHES="", JSEARCH_PROVIDER="",
                      JSEARCH_MONTHLY_LIMIT="", JSEARCH_API_KEY="", GREENHOUSE_BOARDS="")
    assert s.database_url.startswith("sqlite:///")
    assert [x.key for x in s.searches][0] == "data analyst|alberta"
    assert s.jsearch_provider == "openwebninja"
    assert s.jsearch_monthly_limit == 200
    assert s.jsearch_api_key is None
    assert s.greenhouse_boards == []


def test_pasted_whitespace_is_trimmed(load_settings):
    s = load_settings(DATABASE_URL="  postgresql+psycopg://u:p@h/db?sslmode=require\n",
                      ASHBY_BOARDS=" jobber, benevity ,")
    assert s.database_url == "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert s.ashby_boards == ["jobber", "benevity"]
