"""Checks the scope objective: all events from the three calendars appear in
one view with no duplicates or omissions. Compared against ground truth
written by scripts/generate_data.py."""
import json
from datetime import date
from pathlib import Path

from assistant import data_store
from assistant.calendar_merge import day_view, find_conflicts, free_slots

TRUTH = json.loads((Path(__file__).resolve().parent.parent / "data/ground_truth/calendar_truth.json").read_text())


def test_no_duplicates_or_omissions():
    merged = data_store.merged_events()
    assert len(merged) == TRUTH["expected_merged_events"]
    # Every raw event appears in exactly one merged event (no omissions, nothing counted twice).
    covered = [s for e in merged for s in e.source_ids]
    raw = [f"{cal}/{ev['id']}" for cal, evs in data_store.raw_calendars().items() for ev in evs]
    assert sorted(covered) == sorted(raw)


def test_planted_duplicates_are_merged_with_both_labels():
    by_source = {s: e for e in data_store.merged_events() for s in e.source_ids}
    for group in TRUTH["duplicate_groups"]:
        events = {id(by_source[s]) for s in group}
        assert len(events) == 1, f"duplicate group not merged: {group}"
        assert len(by_source[group[0]].calendars) == 2


def test_conflicts_match_planted():
    found = sorted(sorted(a.source_ids + b.source_ids) for a, b in find_conflicts(data_store.merged_events()))
    assert found == sorted(sorted(c) for c in TRUTH["planted_conflicts"])


def test_free_slots_do_not_overlap_events():
    events = data_store.merged_events()
    for d in range(9, 30):
        day = date(2026, 11, d)
        for s, e in free_slots(events, day, 30):
            assert all(not (ev.start < e and ev.end > s) for ev in events if not ev.all_day)


def test_day_view_shape():
    v = day_view(data_store.merged_events(), date(2026, 11, 10), now=data_store.now())
    assert v["events"] and v["next_event"] and v["free_slots"]
    assert len(v["conflicts"]) == 1  # planted Grace session vs sponsor call
