"""Merge Monica's calendars into one view. Plain code, no AI.

Why no AI: the scope requires "no duplicates or omissions", which must hold
every time. Deterministic code is exact and easy to test.

Two events are treated as the same meeting when either
  * they share the same calendar invite id (``uid``), or
  * they have the same normalised title, start, and end
    (e.g. Monica copied an event onto a second calendar by hand).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")


@dataclass
class MergedEvent:
    id: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    calendars: list[str]
    source_ids: list[str]
    location: str = ""
    attendees: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict:
        fmt = (lambda d: d.date().isoformat()) if self.all_day else (lambda d: d.isoformat())
        return {
            "id": self.id, "title": self.title, "start": fmt(self.start), "end": fmt(self.end),
            "all_day": self.all_day, "calendars": self.calendars, "source_ids": self.source_ids,
            "location": self.location, "attendees": self.attendees, "description": self.description,
        }


def _parse(value: str, all_day: bool) -> datetime:
    if all_day:
        return datetime.combine(date.fromisoformat(value), time(0), TZ)
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


def _norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", t.lower())).strip()


def merge_calendars(calendars: dict[str, list[dict]]) -> list[MergedEvent]:
    """calendars: {calendar_name: [raw event dicts]} -> sorted, de-duplicated events."""
    raw = []
    for cal, events in calendars.items():
        for ev in events:
            raw.append((cal, ev))

    # Union-find over raw events: anything sharing a uid or (title, start, end) key is one meeting.
    parent = list(range(len(raw)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen: dict[tuple, int] = {}
    for i, (cal, ev) in enumerate(raw):
        keys = [("uid", ev.get("uid"))] if ev.get("uid") else []
        keys.append(("tse", _norm_title(ev["title"]), ev["start"], ev["end"]))
        for k in keys:
            if k in seen:
                parent[find(i)] = find(seen[k])
            else:
                seen[k] = i

    groups: dict[int, list[int]] = {}
    for i in range(len(raw)):
        groups.setdefault(find(i), []).append(i)

    merged = []
    for members in groups.values():
        cal0, ev0 = raw[members[0]]
        all_day = bool(ev0.get("all_day"))
        cals, sources, attendees = [], [], []
        location, description = "", ""
        for i in members:
            cal, ev = raw[i]
            if cal not in cals:
                cals.append(cal)
            sources.append(f"{cal}/{ev['id']}")
            for a in ev.get("attendees", []):
                if a not in attendees:
                    attendees.append(a)
            location = location or ev.get("location", "")
            description = description or ev.get("description", "")
        merged.append(MergedEvent(
            id="m-" + "+".join(sorted(sources)).replace("/", "_"),
            title=ev0["title"], start=_parse(ev0["start"], all_day), end=_parse(ev0["end"], all_day),
            all_day=all_day, calendars=cals, source_ids=sorted(sources), location=location,
            attendees=attendees, description=description,
        ))
    merged.sort(key=lambda e: (e.start, not e.all_day, e.title))
    return merged


def find_conflicts(events: list[MergedEvent]) -> list[tuple[MergedEvent, MergedEvent]]:
    """Pairs of different (already de-duplicated) timed events that overlap."""
    timed = sorted((e for e in events if not e.all_day), key=lambda e: e.start)
    out = []
    for i, a in enumerate(timed):
        for b in timed[i + 1:]:
            if b.start >= a.end:
                break
            out.append((a, b))
    return out


def events_between(events: list[MergedEvent], start: datetime, end: datetime) -> list[MergedEvent]:
    return [e for e in events if e.start < end and e.end > start]


def free_slots(events: list[MergedEvent], day: date, duration_min: int = 30,
               work_start: time = time(9), work_end: time = time(18)) -> list[tuple[datetime, datetime]]:
    """Gaps of at least ``duration_min`` within working hours on ``day``. All-day items don't block time."""
    lo = datetime.combine(day, work_start, TZ)
    hi = datetime.combine(day, work_end, TZ)
    busy = sorted((max(e.start, lo), min(e.end, hi))
                  for e in events_between(events, lo, hi) if not e.all_day)
    gaps, cursor = [], lo
    for s, e in busy:
        if s > cursor:
            gaps.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < hi:
        gaps.append((cursor, hi))
    need = timedelta(minutes=duration_min)
    return [(s, e) for s, e in gaps if e - s >= need]


def day_view(events: list[MergedEvent], day: date, now: datetime | None = None) -> dict:
    """Everything 'Today's schedule' needs: timeline, next appointment, gaps, overlaps."""
    lo = datetime.combine(day, time(0), TZ)
    todays = events_between(events, lo, lo + timedelta(days=1))
    timed = [e for e in todays if not e.all_day]
    nxt = next((e for e in timed if now is None or e.start >= now), None)
    return {
        "date": day.isoformat(),
        "all_day": [e.to_dict() for e in todays if e.all_day],
        "events": [e.to_dict() for e in timed],
        "next_event": nxt.to_dict() if nxt else None,
        "free_slots": [{"start": s.isoformat(), "end": e.isoformat(),
                        "minutes": int((e - s).total_seconds() // 60)}
                       for s, e in free_slots(events, day, duration_min=15)],
        "conflicts": [{"a": a.to_dict(), "b": b.to_dict()} for a, b in find_conflicts(timed)],
    }
