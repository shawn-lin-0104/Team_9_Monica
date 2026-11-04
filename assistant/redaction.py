"""Privacy guardrail: hide identifying details BEFORE any text reaches an AI model.

Runs entirely on this server (regular expressions plus spaCy's local name
recogniser). Each detail is replaced with a numbered placeholder such as
[PHONE_1]. The mapping stays here, so text the model writes back (e.g. a draft
reply that mentions [NAME_1]) can be restored before Monica sees it.

First names alone are allowed by the project scope, so "Quinn Hargrove"
becomes "Quinn [LAST_NAME_1]".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

MONTHS = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
STREET = r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Way|Ct|Court|Pl|Place|Ter|Terrace|Pkwy)"

# Order matters: more specific patterns first.
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("SSN", re.compile(r"\b\d{3}[ -]\d{2}[ -]\d{4}\b")),
    ("PHONE", re.compile(r"(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\b\d{3}[\s.-])\d{3}[\s.-]\d{4}\b")),
    ("ADDRESS", re.compile(rf"\b\d{{1,6}}\s+(?:[A-Z][\w'-]*\s+){{1,3}}{STREET}\.?"
                           r"(?:,?\s+(?:Apt|Unit|#)\s*\w+)?"
                           r"(?:,\s*[A-Z][a-zA-Z .]+)?(?:,\s*[A-Z]{2})?(?:\s+\d{5}(?:-\d{4})?)?")),
    # Full dates with a year (HIPAA treats dates tied to a person as identifiers; deadlines
    # without a year, like "November 13", are kept so the assistant stays useful).
    ("DATE", re.compile(rf"\b(?:\d{{1,2}}/\d{{1,2}}/\d{{2,4}}|{MONTHS}\.? \d{{1,2}}(?:st|nd|rd|th)?,? \d{{4}}|\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}(?:st|nd|rd|th)? of {MONTHS},? \d{{4}})\b")),
    ("ID", re.compile(r"\b(?:MRN|Member ID|ID|Account|Acct|Policy)[:#\s]*([A-Z]{0,4}[\s-]?\d[\d\s-]{3,}\d)\b", re.I)),
    ("ID", re.compile(r"\b[A-Z]{2,4}\d{6,}\b")),
    ("ID", re.compile(r"\b\d{7,}\b")),
    ("ZIP", re.compile(r"\b(?:PA|OH|NY|WV)\s+\d{5}\b")),
]

# Capitalised words that start "First Last"-looking pairs but are not people.
NOT_NAMES = {
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December", "Dear", "Hi", "Hello", "Hey", "Thanks", "Thank", "Best", "Warmly",
    "Clinical", "Operations", "Claims", "Department", "Provider", "Riverstone", "Books", "Harborlight",
    "Press", "Thriving", "Together", "Thriveworks", "Squirrel", "Hill", "South", "Hills", "Adult",
    "Programs", "Events", "Team", "Pittsburgh", "Magazine", "Grief", "Waves", "Loss", "When", "The",
    "Holding", "Space", "Anxiety", "Night", "Episode", "Library", "Society", "Social", "Work", "Calendar",
    "Google", "Workspace", "Zoom", "Canva", "Coach", "Rabbi", "Back", "Cover", "Final", "New", "Your",
    "Payment", "Member", "Date", "Recap", "Question", "Quick", "Need", "Records", "Action", "Prep",
    "Primary", "Care", "Learning", "Dr", "Ms", "Mr", "Mrs", "Mx", "Line", "Up", "Straight", "Shows",
}
ALLOWED_FULL_NAMES: set[str] = set()  # e.g. public figures Monica is happy to share

SURNAME = r"(?:O'|Mc|Mac)?[A-Z][a-z]+(?:-[A-Z][a-z]+)?"
NAME_PAIR = re.compile(rf"\b([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\s+({SURNAME})\b")
LAST_FIRST = re.compile(rf"(?<!Hi )(?<!Hey )(?<!Dear )(?<!Hello )\b({SURNAME}),[ \t]+([A-Z][a-z]+)\b")
MY_NAME_IS = re.compile(r"(?i)\b(?:my name is|name:)\s+[a-z]+(?:\s+([a-z'-]+))")
TITLE_SURNAME = re.compile(r"\b(Mr|Ms|Mrs|Mx)\.?\s+([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b")


@lru_cache
def _nlp():
    try:
        import spacy
        return spacy.load("en_core_web_sm", disable=["lemmatizer", "parser"])
    except Exception:  # spaCy is optional; the pattern rules still run
        return None


@dataclass
class Redaction:
    text: str
    mapping: dict[str, str] = field(default_factory=dict)  # placeholder -> original

    def restore(self, text: str) -> str:
        for ph, original in sorted(self.mapping.items(), key=lambda kv: -len(kv[0])):
            text = text.replace(ph, original)
        return text

    @property
    def count(self) -> int:
        return len(self.mapping)


class Redactor:
    """Use one Redactor per conversation so the same detail always gets the same placeholder."""

    def __init__(self) -> None:
        self.mapping: dict[str, str] = {}
        self._reverse: dict[str, str] = {}
        self._counts: dict[str, int] = {}

    def _placeholder(self, kind: str, original: str) -> str:
        if original in self._reverse:
            return self._reverse[original]
        self._counts[kind] = self._counts.get(kind, 0) + 1
        ph = f"[{kind}_{self._counts[kind]}]"
        self.mapping[ph] = original
        self._reverse[original] = ph
        return ph

    def _name_spans(self, text: str) -> list[tuple[int, int]]:
        """Spans of surnames to hide (first names are allowed)."""
        spans = []
        nlp = _nlp()
        candidates = []
        if nlp is not None:
            for ent in nlp(text).ents:
                if ent.label_ in ("PERSON", "ORG") and " " in ent.text.strip():
                    candidates.append((ent.start_char, ent.end_char))
        for m in NAME_PAIR.finditer(text):
            candidates.append((m.start(), m.end()))
        for start, end in candidates:
            chunk = text[start:end]
            words = re.findall(SURNAME, chunk)
            if len(words) < 2 or chunk in ALLOWED_FULL_NAMES:
                continue
            if any(w in NOT_NAMES for w in words):
                continue
            # hide everything after the first name
            last = text.find(words[1], start)
            spans.append((last, last + len(words[-1]) + (text.find(words[-1], last) - last)))
        for m in TITLE_SURNAME.finditer(text):
            spans.append((m.start(2), m.end(2)))
        for m in LAST_FIRST.finditer(text):
            if m.group(1) not in NOT_NAMES and m.group(2) not in NOT_NAMES:
                spans.append((m.start(1), m.end(1)))
        for m in MY_NAME_IS.finditer(text):
            if m.group(1):
                spans.append((m.start(1), m.end(1)))
        return spans

    def redact(self, text: str) -> str:
        spans: list[tuple[int, int, str]] = []
        for kind, pat in PATTERNS:
            for m in pat.finditer(text):
                s, e = (m.start(1), m.end(1)) if pat.groups else (m.start(), m.end())
                spans.append((s, e, kind))
        spans += [(s, e, "LAST_NAME") for s, e in self._name_spans(text)]
        # Keep the earliest, longest non-overlapping spans.
        spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
        chosen, cursor = [], -1
        for s, e, kind in spans:
            if s >= cursor:
                chosen.append((s, e, kind))
                cursor = e
        out, pos = [], 0
        for s, e, kind in chosen:
            out.append(text[pos:s])
            out.append(self._placeholder(kind, text[s:e]))
            pos = e
        out.append(text[pos:])
        return "".join(out)

    def restore(self, text: str) -> str:
        return Redaction("", self.mapping).restore(text)


def redact(text: str) -> Redaction:
    r = Redactor()
    return Redaction(r.redact(text), r.mapping)


def redact_email(email: dict, redactor: Redactor | None = None) -> tuple[dict, Redactor]:
    """Redact every field of an email that would be sent to the model."""
    r = redactor or Redactor()
    safe = {
        "id": email["id"],
        "from_name": r.redact(email["from_name"]),
        "from_email": r.redact(email["from_email"]),
        "subject": r.redact(email["subject"]),
        "received_at": email["received_at"],
        "body": r.redact(email["body"]),
        "history": [{"from": r.redact(h["from"]), "date": h["date"], "body": r.redact(h["body"])}
                    for h in email.get("history", [])],
    }
    return safe, r
