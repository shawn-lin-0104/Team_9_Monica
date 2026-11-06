"""AI features: triage, summaries, reply drafts, scheduling, meeting prep.

Pattern for every feature:  redact -> Claude (structured JSON) -> restore placeholders -> propose (never execute).
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta

from . import data_store as ds
from . import llm, state
from .calendar_merge import TZ, free_slots
from .prompts import PERSONA, TRIAGE_RULES
from .redaction import Redactor, redact_email

CALENDARS = ["thriveworks", "book", "podcast"]


def _email_prompt(safe: dict) -> str:
    hist = "".join(f"\n--- Earlier message from {h['from']} ({h['date']}) ---\n{h['body']}\n" for h in safe["history"])
    return (f"Today is {ds.now():%A, %B %d, %Y, %I:%M %p}.\n\n"
            f"From: {safe['from_name']} <{safe['from_email']}>\nReceived: {safe['received_at']}\n"
            f"Subject: {safe['subject']}\n\n{safe['body']}\n{hist}")


def _obj(props: dict, required: list | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


# ------------------------------------------------------------------ triage
TRIAGE_SCHEMA = _obj({
    "category": {"type": "string", "enum": ["reply_needed", "scheduling", "fyi"]},
    "urgent": {"type": "boolean"},
    "reason": {"type": "string"},
})


def triage_email(email_id: str, use_cache: bool = True) -> dict:
    cached = state.cache_get("triage").get(email_id)
    if use_cache and cached:
        return cached
    e = ds.email(email_id)
    safe, r = redact_email(e)
    out = llm.create_json(
        feature="triage", schema=TRIAGE_SCHEMA, effort="low", max_tokens=4000,
        system=PERSONA + "\n\n" + TRIAGE_RULES,
        messages=[{"role": "user", "content": "Sort this email.\n\n" + _email_prompt(safe)}],
    )
    out["reason"] = r.restore(out["reason"])
    state.cache_put("triage", email_id, out)
    return out


def triage_all(use_cache: bool = True, workers: int = 6) -> dict:
    ids = [e["id"] for e in ds.emails()]
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda i: (i, _safe(triage_email, i, use_cache)), ids))
    return dict(results)


def _safe(fn, *args):
    try:
        return fn(*args)
    except llm.AIRefused as ex:
        return {"error": str(ex)}


# ------------------------------------------------------------------ summary
SUMMARY_SCHEMA = _obj({
    "main_request": {"type": "string"},
    "deadline": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    "already_agreed": {"type": "array", "items": {"type": "string"}},
    "suggested_next_step": {"type": "string"},
})


def summarize(email_id: str) -> dict:
    cached = state.cache_get("summary_reader_v2").get(email_id)
    if cached:
        return cached
    safe, r = redact_email(ds.email(email_id))
    out = llm.create_json(
        feature="summary", schema=SUMMARY_SCHEMA, effort="low", max_tokens=4000, system=PERSONA,
        messages=[{"role": "user", "content":
                   "Summarize this email thread for Monica in plain language. main_request: one sentence. "
                   "deadline: the relevant date/time in words, or null. already_agreed: decisions already made "
                   "in the thread (empty if none). suggested_next_step: one short sentence.\n\n" + _email_prompt(safe)}],
    )
    out = json.loads(r.restore(json.dumps(out)))
    state.cache_put("summary_reader_v2", email_id, out)
    return out


# ------------------------------------------------------------------ reply drafts
DRAFT_SCHEMA = _obj({"subject": {"type": "string"}, "body": {"type": "string"}})
TONES = {
    "shorter": "Make it noticeably shorter (2-4 sentences).",
    "friendlier": "Make it warmer and more friendly, still professional.",
    "formal": "Make it more formal and polished.",
}


def draft_reply(email_id: str, tone: str | None = None, instructions: str | None = None,
                previous: str | None = None) -> dict:
    """Write a reply and put it in the approval queue. Returns the pending action."""
    e = ds.email(email_id)
    safe, r = redact_email(e)
    asks = ["Write a reply from Monica to this email. Keep it short and natural."]
    if previous:
        asks.append("Rewrite this earlier draft rather than starting over:\n" + r.redact(previous))
    if tone in TONES:
        asks.append(TONES[tone])
    if instructions:
        asks.append("Monica's instructions: " + r.redact(instructions))
    if (state.cache_get("triage").get(email_id) or {}).get("category") == "scheduling":
        asks.append("If the sender asked for times, do not invent availability; say in first person that you will confirm a time shortly.")
    out = llm.create_json(
        feature="draft", schema=DRAFT_SCHEMA, effort="low", max_tokens=6000, system=PERSONA,
        messages=[{"role": "user", "content": "\n".join(asks) + "\n\n" + _email_prompt(safe)}],
    )
    subject = r.restore(out["subject"]) or f"Re: {e['subject']}"
    body = r.restore(out["body"])
    return state.propose("send_email", f"Reply to {e['from_name']}: {e['subject']}",
                         {"email_id": email_id, "to": e["from_email"], "subject": subject, "body": body},
                         source=f"email:{email_id}")


# ------------------------------------------------------------------ scheduling
MEETING_SCHEMA = _obj({
    "is_meeting_request": {"type": "boolean"},
    "title": {"type": "string"},
    "with_whom": {"type": "string"},
    "duration_minutes": {"type": "integer"},
    "calendar": {"type": "string", "enum": CALENDARS},
    "specific_times": {"type": "array", "items": {"type": "string"},
                       "description": "Exact start times the sender proposed, as YYYY-MM-DDTHH:MM (24h, local)."},
    "candidate_dates": {"type": "array", "items": {"type": "string"},
                        "description": "Dates (YYYY-MM-DD) that fit the request, at most 5, none in the past."},
    "earliest_hour": {"type": "integer"},
    "latest_hour": {"type": "integer"},
})


def _within(start: datetime, minutes: int) -> bool:
    end = start + timedelta(minutes=minutes)
    return all(not (ev.start < end and ev.end > start) for ev in ds.merged_events() if not ev.all_day)


def find_options(req: dict, limit: int = 3) -> list[dict]:
    """Plain code: turn an extracted request into real free times on Monica's merged calendar."""
    minutes = max(15, min(req["duration_minutes"] or 30, 240))
    now = ds.now()
    options = []
    for t in req.get("specific_times", []):
        try:
            start = datetime.fromisoformat(t).replace(tzinfo=TZ)
        except ValueError:
            continue
        if start > now and _within(start, minutes):
            options.append({"start": start.isoformat(), "end": (start + timedelta(minutes=minutes)).isoformat(),
                            "why": "One of the times they offered, and you're free."})
    lo_h = min(max(req.get("earliest_hour") or 9, 7), 20)
    hi_h = max(min(req.get("latest_hour") or 18, 21), lo_h + 1)
    days = []
    for d in req.get("candidate_dates", [])[:5]:
        try:
            days.append(date.fromisoformat(d))
        except ValueError:
            pass
    if not days:  # default: next 5 weekdays
        d = now.date()
        while len(days) < 5:
            d += timedelta(days=1)
            if d.weekday() < 5:
                days.append(d)
    for d in days:
        if len(options) >= limit:
            break
        if d < now.date():
            continue
        for s, e in free_slots(ds.merged_events(), d, minutes, time(lo_h), time(hi_h)):
            start = max(s, now)
            # round up to the next quarter hour
            start += timedelta(minutes=(-start.minute) % 15, seconds=-start.second)
            if start + timedelta(minutes=minutes) <= e:
                options.append({"start": start.isoformat(),
                                "end": (start + timedelta(minutes=minutes)).isoformat(),
                                "why": "You're free then."})
                break  # one option per day, so choices are spread out
    seen, out = set(), []
    for o in options:
        if o["start"] not in seen:
            seen.add(o["start"])
            out.append(o)
    return out[:limit]


def propose_meeting(email_id: str) -> dict:
    e = ds.email(email_id)
    safe, r = redact_email(e)
    req = llm.create_json(
        feature="schedule", schema=MEETING_SCHEMA, effort="low", max_tokens=4000, system=PERSONA,
        messages=[{"role": "user", "content":
                   "Extract the meeting request from this email. Use Monica's local time. If no duration is given, "
                   "use 50 for a therapy session, 60 for a podcast recording, otherwise 30. Pick the calendar the "
                   "meeting belongs to. earliest_hour/latest_hour: the window in 24h hours (default 9 and 18).\n\n"
                   + _email_prompt(safe)}],
    )
    if not req["is_meeting_request"]:
        return {"is_meeting_request": False, "message": "This email doesn't look like a meeting request."}
    options = find_options(req)
    title = r.restore(req["title"]) or f"Meeting with {e['from_name']}"
    action = state.propose("book_meeting", f"Book: {title}",
                           {"email_id": email_id, "title": title, "calendar": req["calendar"],
                            "attendees": [r.restore(req["with_whom"])] if req["with_whom"] else [],
                            "minutes": req["duration_minutes"], "options": options},
                           source=f"email:{email_id}")
    return {"is_meeting_request": True, "action": action}


# ------------------------------------------------------------------ meeting prep
PREP_SCHEMA = _obj({"summary": {"type": "string"}, "follow_up_actions": {"type": "array", "items": {"type": "string"}}})
_STOP = {"with", "the", "and", "for", "call", "meeting", "session", "podcast", "review", "prep"}


def related_emails(event: dict, limit: int = 4) -> list[dict]:
    people = {a.lower() for a in event.get("attendees", [])}
    words = {w for w in re.findall(r"[a-z]{4,}", event["title"].lower()) if w not in _STOP}
    scored = []
    for e in ds.emails():
        score = 2 * (e["from_name"].lower() in people)
        score += len(words & set(re.findall(r"[a-z]{4,}", (e["subject"] + " " + e["body"]).lower())))
        if score:
            scored.append((score, e["received_at"], e))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [e for _, _, e in scored[:limit]]


def meeting_prep(event: dict) -> dict:
    emails = related_emails(event)
    if not emails:
        return {"summary": "No related emails found.", "follow_up_actions": [], "related_emails": []}
    r = Redactor()
    blocks = [_email_prompt(redact_email(e, r)[0]) for e in emails]
    out = llm.create_json(
        feature="prep", schema=PREP_SCHEMA, effort="low", max_tokens=4000, system=PERSONA,
        messages=[{"role": "user", "content":
                   f"Monica has this meeting coming up: {event['title']} at {event['start']} "
                   f"with {', '.join(event.get('attendees', [])) or 'no listed attendees'}.\n"
                   "Write directly to the reader using you/your, never Monica/she/her. "
                   "From the related emails below, write a concise summary (at most two sentences) of what you need to know. "
                   "follow_up_actions: at most three specific, unfinished next steps grounded in those emails. "
                   "Start each with a verb, e.g. 'Confirm a new time with Carla.' Use short sentences, not questions. "
                   "Only include actions explicitly requested or necessary to resolve the request in the related emails. "
                   "Never add notifications to supervisors or other people merely mentioned in your background persona. "
                   "Do not pad the list with optional tasks such as inform someone if necessary. One action is enough. "
                   "Do not invent tasks, deadlines, or availability, or imply a suggestion is already completed. "
                   "Use an empty list when nothing needs following up. Do not repeat the actions in the summary.\n\n" + "\n\n=====\n\n".join(blocks)}],
    )
    out = json.loads(r.restore(json.dumps(out)))
    out["related_emails"] = [{"id": e["id"], "from_name": e["from_name"], "subject": e["subject"]} for e in emails]
    return out
