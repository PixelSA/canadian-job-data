"""Dictionary-based skill extraction with spaCy's PhraseMatcher.

Unambiguous skills ("PostgreSQL", "power bi") match case-insensitively anywhere.
Ambiguous ones ("R", "Go", "Excel", "Spark") must match with exact capitalization and pass
a context check, so "excel in a fast-paced role" or "go above and beyond" don't count.
"""

import hashlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import spacy
import yaml
from spacy.matcher import PhraseMatcher
from spacy.tokens import Doc, Span
from spacy.util import filter_spans

TAXONOMY_PATH = Path(__file__).with_name("skills.yaml")
# Bump when the matching *logic* changes; taxonomy edits are picked up via the file hash.
LOGIC_VERSION = 1
CONTEXT_WINDOW = 8  # tokens either side to look for a corroborating skill


@dataclass(frozen=True)
class Skill:
    name: str
    category: str
    aliases: tuple[str, ...] = ()
    implies: tuple[str, ...] = ()
    ambiguous: bool = False
    cues: frozenset[str] = field(default_factory=frozenset)
    reject_prev: frozenset[str] = field(default_factory=frozenset)
    reject_next: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ExtractedSkill:
    name: str
    category: str


def load_taxonomy(path: Path = TAXONOMY_PATH) -> dict[str, Skill]:
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))
    skills = {}
    for e in entries:
        lower = lambda key: frozenset(str(w).lower() for w in e.get(key, []))  # noqa: E731
        skills[e["name"]] = Skill(
            name=e["name"],
            category=e["category"],
            aliases=tuple(str(a) for a in e.get("aliases", [])),
            implies=tuple(e.get("implies", [])),
            ambiguous=e.get("ambiguous", False),
            cues=lower("cues"),
            reject_prev=lower("reject_prev"),
            reject_next=lower("reject_next"),
        )
    unknown = {i for s in skills.values() for i in s.implies} - skills.keys()
    if unknown:
        raise ValueError(f"'implies' refers to unknown skills: {sorted(unknown)}")
    return skills


class SkillExtractor:
    def __init__(self, taxonomy_path: Path = TAXONOMY_PATH):
        self.skills = load_taxonomy(taxonomy_path)
        taxonomy_hash = hashlib.sha256(taxonomy_path.read_bytes()).hexdigest()[:8]
        self.version = f"v{LOGIC_VERSION}-{taxonomy_hash}"

        # Tokenizer only; no model download needed.
        self.nlp = spacy.blank("en")
        self.loose = PhraseMatcher(self.nlp.vocab, attr="LOWER")
        self.strict = PhraseMatcher(self.nlp.vocab, attr="ORTH")
        for skill in self.skills.values():
            if skill.ambiguous:
                # Canonical name is case-sensitive; multi-word aliases ("r programming",
                # "apache spark") are specific enough to match loosely.
                self.strict.add(skill.name, [self.nlp.make_doc(skill.name)])
                loose_aliases = [a for a in skill.aliases if len(a) > 2]
            else:
                loose_aliases = [skill.name, *skill.aliases]
            if loose_aliases:
                self.loose.add(skill.name, [self.nlp.make_doc(a) for a in loose_aliases])

    def extract(self, text: str) -> list[ExtractedSkill]:
        if not text:
            return []
        doc = self.nlp.make_doc(text)
        sure = [Span(doc, s, e, label=m) for m, s, e in self.loose(doc)]
        candidates = [Span(doc, s, e, label=m) for m, s, e in self.strict(doc)]
        confirmed = [span for span in candidates if self._context_ok(doc, span, sure)]

        found: set[str] = set()
        for span in filter_spans(sure + confirmed):  # longest wins: "C++" beats "C"
            name = self.nlp.vocab.strings[span.label]
            found.add(name)
            found.update(self.skills[name].implies)
        return sorted(
            (ExtractedSkill(n, self.skills[n].category) for n in found), key=lambda s: s.name
        )

    def _context_ok(self, doc: Doc, span: Span, sure: list[Span]) -> bool:
        skill = self.skills[self.nlp.vocab.strings[span.label]]
        prev = doc[span.start - 1].lower_ if span.start > 0 else ""
        nxt = doc[span.end].lower_ if span.end < len(doc) else ""
        if prev in skill.reject_prev or nxt in skill.reject_next:
            return False
        if prev in skill.cues or nxt in skill.cues:
            return True
        # Otherwise require a list-like context: another confident skill close by.
        return any(
            abs(other.start - span.start) <= CONTEXT_WINDOW
            and not (other.start <= span.start < other.end)  # not the span that contains us
            for other in sure
        )


@lru_cache(maxsize=1)
def get_extractor() -> SkillExtractor:
    return SkillExtractor()
