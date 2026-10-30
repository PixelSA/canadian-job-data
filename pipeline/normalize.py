"""Text cleanup, deduplication fingerprints, and role/region matching."""

import hashlib
import html
import json
import re

from pipeline.config import TrackedSearch

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_PARENS_RE = re.compile(r"\([^)]*\)")
_NON_WORD_RE = re.compile(r"[^a-z0-9+#]+")
_COMPANY_SUFFIXES = {"inc", "ltd", "llc", "corp", "corporation", "co", "limited", "ulc", "lp"}

# Lets "Alberta" match postings whose location only names a city.
REGION_ALIASES: dict[str, set[str]] = {
    "alberta": {"alberta", "ab", "calgary", "edmonton", "red deer", "lethbridge",
                "medicine hat", "airdrie", "st. albert", "grande prairie", "fort mcmurray"},
    "british columbia": {"british columbia", "bc", "vancouver", "victoria", "burnaby",
                         "surrey", "kelowna", "richmond"},
    "ontario": {"ontario", "on", "toronto", "ottawa", "waterloo", "mississauga",
                "hamilton", "london", "markham", "kitchener"},
    "canada": {"canada"},
}


def html_to_text(raw: str | None) -> str:
    """Greenhouse sends entity-escaped HTML; Lever sends HTML lists. Flatten both to text."""
    if not raw:
        return ""
    text = html.unescape(html.unescape(raw))  # Greenhouse double-escapes
    text = re.sub(r"<\s*(br|/p|/li|/h\d|/div)\s*/?>", "\n", text, flags=re.I)
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _norm(s: str | None) -> str:
    s = _PARENS_RE.sub(" ", (s or "").lower())
    return _WS_RE.sub(" ", _NON_WORD_RE.sub(" ", s)).strip()


_QUOTES = "\"'“”‘’`"


def clean_display_name(name: str | None) -> str | None:
    """Tidy a name for display: sources send stray padding ('TD ') and quoting
    ('"Total Life, Inc."'), which would otherwise split one company into several."""
    cleaned = _WS_RE.sub(" ", (name or "")).strip().strip(_QUOTES).strip()
    return cleaned or None


def normalize_company(name: str | None) -> str:
    return " ".join(w for w in _norm(name).split() if w not in _COMPANY_SUFFIXES)


def fingerprint(title: str, company: str | None, location: str | None) -> str:
    """Stable ID for 'the same job', so one role posted on two sources is counted once."""
    city = _norm((location or "").split(",")[0])
    key = f"{_norm(title)}|{normalize_company(company)}|{city}"
    return hashlib.sha256(key.encode()).hexdigest()


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def location_in_region(location: str | None, region: str) -> bool:
    loc = f" {_norm(location)} "
    names = REGION_ALIASES.get(region.lower(), {region.lower()})
    return any(f" {_norm(n)} " in loc for n in names)


def title_matches_role(title: str, role: str) -> bool:
    """Every word of the role appears in the title ('data analyst' ~ 'Senior Data Analyst II')."""
    words = set(_norm(title).split())
    return all(w in words for w in _norm(role).split())


def matching_searches(
    title: str, location: str | None, searches: list[TrackedSearch]
) -> list[str]:
    return [
        s.key
        for s in searches
        if title_matches_role(title, s.role) and location_in_region(location, s.region)
    ]
