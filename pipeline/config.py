"""Runtime configuration, read from environment variables (or a .env file)."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class TrackedSearch:
    """A role + region pair the pipeline pulls every day."""

    role: str
    region: str

    @property
    def key(self) -> str:
        return f"{self.role.lower()}|{self.region.lower()}"


def _parse_searches(raw: str) -> list[TrackedSearch]:
    # Format: "data analyst@Alberta;software developer@Calgary"
    out = []
    for chunk in filter(None, (c.strip() for c in raw.split(";"))):
        role, _, region = chunk.partition("@")
        out.append(TrackedSearch(role.strip(), region.strip() or "Canada"))
    return out


def _env(name: str, default: str | None = None) -> str | None:
    """Read a setting, treating blank as unset. GitHub Actions passes an empty string for a
    secret or variable that was never created, and that must not override the default."""
    value = (os.getenv(name) or "").strip()
    return value or default


def _list(name: str) -> list[str]:
    return [v.strip() for v in (_env(name) or "").split(",") if v.strip()]


def _int(name: str, default: int) -> int:
    return int(_env(name) or default)


@dataclass(frozen=True)
class Settings:
    database_url: str = _env("DATABASE_URL", f"sqlite:///{ROOT / 'jobs.db'}")
    searches: list[TrackedSearch] = field(
        default_factory=lambda: _parse_searches(
            _env("TRACKED_SEARCHES",
                 "data analyst@Alberta;software developer@Alberta;software engineer@Alberta;"
                 "data analyst@Canada;software developer@Canada")
        )
    )

    # --- Quota-limited APIs. Each is enabled only when its key is set. ---
    # JSearch: 200 requests/month on the free plan; one request per search per run.
    jsearch_api_key: str | None = _env("JSEARCH_API_KEY")
    jsearch_provider: str = _env("JSEARCH_PROVIDER", "openwebninja")  # or "rapidapi"
    jsearch_monthly_limit: int = _int("JSEARCH_MONTHLY_LIMIT", 200)
    jsearch_max_per_run: int = _int("JSEARCH_MAX_PER_RUN", 5)  # one per tracked search
    jsearch_country: str = _env("JSEARCH_COUNTRY", "ca")
    jsearch_date_posted: str = _env("JSEARCH_DATE_POSTED", "3days")
    # Jooble: 500 requests for the key's lifetime.
    jooble_api_key: str | None = _env("JOOBLE_API_KEY")
    jooble_lifetime_limit: int = _int("JOOBLE_LIFETIME_LIMIT", 500)
    jooble_max_per_run: int = _int("JOOBLE_MAX_PER_RUN", 2)
    # Adzuna: ~25 free calls in total.
    adzuna_app_id: str | None = _env("ADZUNA_APP_ID")
    adzuna_app_key: str | None = _env("ADZUNA_APP_KEY")
    adzuna_country: str = _env("ADZUNA_COUNTRY", "ca")
    adzuna_lifetime_limit: int = _int("ADZUNA_LIFETIME_LIMIT", 25)
    adzuna_max_per_run: int = _int("ADZUNA_MAX_PER_RUN", 2)
    # Jobven: billed per job *record* returned (free plan: 300/month), not per request.
    jobven_api_key: str | None = _env("JOBVEN_API_KEY")
    jobven_monthly_limit: int = _int("JOBVEN_MONTHLY_LIMIT", 300)
    jobven_max_per_run: int = _int("JOBVEN_MAX_PER_RUN", 10)  # ~300/month at one run a day
    jobven_country: str = _env("JOBVEN_COUNTRY", "ca")
    jobven_lookback_days: int = _int("JOBVEN_LOOKBACK_DAYS", 7)  # first sync only

    # --- Unlimited public company job boards ---
    greenhouse_boards: list[str] = field(default_factory=lambda: _list("GREENHOUSE_BOARDS"))
    lever_companies: list[str] = field(default_factory=lambda: _list("LEVER_COMPANIES"))
    ashby_boards: list[str] = field(default_factory=lambda: _list("ASHBY_BOARDS"))
    smartrecruiters_companies: list[str] = field(
        default_factory=lambda: _list("SMARTRECRUITERS_COMPANIES"))


settings = Settings()
