"""Loads the simulated data. Ground-truth labels are never loaded here,
so they can't leak into what the website or the AI model sees."""
from __future__ import annotations

import json
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .calendar_merge import TZ, MergedEvent, merge_calendars

DATA_DIR = Path(os.environ.get("ASSISTANT_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))


def _load(rel: str) -> dict:
    return json.loads((DATA_DIR / rel).read_text())


@lru_cache
def raw_calendars() -> dict[str, list[dict]]:
    out = {}
    for f in sorted((DATA_DIR / "calendars").glob("*.json")):
        d = json.loads(f.read_text())
        out[d["calendar"]] = d["events"]
    return out


@lru_cache
def merged_events() -> list[MergedEvent]:
    return merge_calendars(raw_calendars())


@lru_cache
def emails() -> list[dict]:
    return _load("emails.json")["emails"]


def email(email_id: str) -> dict | None:
    return next((e for e in emails() if e["id"] == email_id), None)


@lru_cache
def sent() -> list[dict]:
    return _load("sent.json")["sent"]


def now() -> datetime:
    """The demo's 'current time'. Set ASSISTANT_NOW to override; defaults to the dataset's date."""
    value = os.environ.get("ASSISTANT_NOW") or _load("emails.json")["now"]
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)
