from datetime import datetime, timezone

import httpx
import pytest

from pipeline.budget import BudgetExhausted, RequestBudget
from pipeline.db import make_session_factory
from pipeline.sources.base import get_json


@pytest.fixture
def factory(tmp_path):
    return make_session_factory(f"sqlite:///{tmp_path / 'b.db'}")


def clock_at(year, month):
    return lambda: datetime(year, month, 15, tzinfo=timezone.utc)


def test_monthly_limit_and_reset(factory):
    oct_budget = RequestBudget(factory, "jsearch", limit=3, clock=clock_at(2026, 10))
    for _ in range(3):
        oct_budget.spend()
    with pytest.raises(BudgetExhausted):
        oct_budget.spend()
    assert oct_budget.used() == 3

    nov_budget = RequestBudget(factory, "jsearch", limit=3, clock=clock_at(2026, 11))
    assert nov_budget.remaining() == 3
    nov_budget.spend()
    assert nov_budget.used() == 1


def test_usage_persists_across_runs(factory):
    RequestBudget(factory, "jooble", limit=5, period="lifetime").spend()
    RequestBudget(factory, "jooble", limit=5, period="lifetime").spend()
    assert RequestBudget(factory, "jooble", limit=5, period="lifetime").remaining() == 3


def test_lifetime_budget_never_resets(factory):
    RequestBudget(factory, "adzuna", 1, "lifetime", clock=clock_at(2026, 1)).spend()
    with pytest.raises(BudgetExhausted):
        RequestBudget(factory, "adzuna", 1, "lifetime", clock=clock_at(2027, 6)).spend()


def test_per_run_cap(factory):
    budget = RequestBudget(factory, "jsearch", limit=200, max_per_run=2)
    budget.spend()
    budget.spend()
    with pytest.raises(BudgetExhausted, match="per-run"):
        budget.spend()
    assert budget.used() == 2


def test_retries_are_charged(factory):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) == 1 else 200, json={"ok": True})

    budget = RequestBudget(factory, "jsearch", limit=10)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client, \
            pytest.MonkeyPatch.context() as mp:
        mp.setattr("pipeline.sources.base.time.sleep", lambda s: None)
        assert get_json(client, "https://api.example.com/x", budget=budget) == {"ok": True}
    assert len(calls) == 2 and budget.used() == 2


def test_exhausted_budget_blocks_request_before_sending(factory):
    sent = []
    budget = RequestBudget(factory, "jsearch", limit=0)
    with httpx.Client(transport=httpx.MockTransport(lambda r: sent.append(r))) as client:
        with pytest.raises(BudgetExhausted):
            get_json(client, "https://api.example.com/x", budget=budget)
    assert sent == []


def test_spend_and_refund_in_units(factory):
    # Per-record billing (Jobven): reserve a page, give back what didn't come.
    budget = RequestBudget(factory, "jobven", limit=30, max_per_run=25, unit="records")
    budget.spend(25)
    budget.refund(22)
    assert budget.used() == 3 and budget.remaining() == 22
    with pytest.raises(BudgetExhausted, match="per-run"):
        budget.spend(23)
    uncapped = RequestBudget(factory, "jobven", limit=30, unit="records")
    with pytest.raises(BudgetExhausted, match="limit of 30"):
        uncapped.spend(28)  # 3 already used + 28 > 30
    assert uncapped.used() == 3
