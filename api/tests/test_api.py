from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from api.db import get_session
from api.main import app
from pipeline.config import TrackedSearch
from pipeline.db import make_session_factory
from pipeline.run import build_sources, fixture_transport, run_pipeline

SEARCHES = [TrackedSearch("data analyst", "Alberta"), TrackedSearch("software developer", "Alberta")]


@pytest.fixture
def client(tmp_path):
    factory = make_session_factory(f"sqlite:///{tmp_path / 'api.db'}")
    with httpx.Client(transport=fixture_transport()) as http:
        run_pipeline(factory, build_sources(http, True, SEARCHES, factory), SEARCHES,
                     today=date(2026, 10, 26))

    def session_override():
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = session_override
    yield TestClient(app)
    app.dependency_overrides.clear()