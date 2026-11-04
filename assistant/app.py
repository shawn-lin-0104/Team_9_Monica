"""HTTP API the website calls. See docs/API.md for the contract.

Endpoints marked MOCK return realistic example data with "mock": true so the
website team can build against the final shape before the AI part is done.

Run locally:  uvicorn assistant.app:app --reload
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import data_store as ds
from .calendar_merge import TZ, day_view, events_between, find_conflicts, free_slots
from .redaction import redact_email

app = FastAPI(title="Monica's Assistant API", version="0.1.0")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


# ---------------------------------------------------------------- health
@app.get("/api/health")
def health():
    return {"ok": True, "now": ds.now().isoformat()}


# ---------------------------------------------------------------- calendar (real)
@app.get("/api/calendar/events")
def calendar_events(start: date | None = None, end: date | None = None):
    """Merged events across all calendars. Defaults to the 4 weeks from today."""
    lo = datetime.combine(start or ds.now().date(), time(0), TZ)
    hi = datetime.combine(end, time(0), TZ) + timedelta(days=1) if end else lo + timedelta(days=28)
    return {"events": [e.to_dict() for e in events_between(ds.merged_events(), lo, hi)]}


@app.get("/api/calendar/day")
def calendar_day(day: date | None = Query(None, alias="date")):
    """Today's schedule: timeline, next appointment, free gaps, overlaps."""
    return day_view(ds.merged_events(), day or ds.now().date(), now=ds.now())


@app.get("/api/calendar/conflicts")
def calendar_conflicts():
    now = ds.now()
    return {"conflicts": [{"a": a.to_dict(), "b": b.to_dict()}
                          for a, b in find_conflicts(ds.merged_events()) if b.end > now]}


@app.get("/api/calendar/free-slots")
def calendar_free_slots(day: date = Query(..., alias="date"), minutes: int = 30,
                        work_start: time = time(9), work_end: time = time(18)):
    slots = free_slots(ds.merged_events(), day, minutes, work_start, work_end)
    return {"date": day.isoformat(), "minutes": minutes,
            "slots": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in slots]}


# ---------------------------------------------------------------- email (real data, AI fields MOCK)
def _email_summary_row(e: dict) -> dict:
    return {k: e[k] for k in ("id", "from_name", "from_email", "subject", "received_at")} | {
        "preview": e["body"][:140],
        "triage": None,  # filled in once triage is implemented: {"category", "urgent", "reason"}
    }


@app.get("/api/emails")
def list_emails():
    return {"emails": [_email_summary_row(e) for e in ds.emails()]}


@app.get("/api/emails/{email_id}")
def get_email(email_id: str):
    e = ds.email(email_id)
    if not e:
        raise HTTPException(404, "email not found")
    return e


@app.get("/api/emails/{email_id}/privacy")
def email_privacy(email_id: str):
    """Exactly what the AI model would receive for this email, and how many details were hidden.
    Lets the website show e.g. "3 private details hidden before AI processing"."""
    e = ds.email(email_id)
    if not e:
        raise HTTPException(404, "email not found")
    safe, r = redact_email(e)
    kinds: dict[str, int] = {}
    for ph in r.mapping:
        k = ph.strip("[]").rsplit("_", 1)[0].lower()
        kinds[k] = kinds.get(k, 0) + 1
    return {"email_id": email_id, "hidden_count": len(r.mapping), "hidden_by_type": kinds, "sent_to_ai": safe}


# ---------------------------------------------------------------- follow-ups (real)
@app.get("/api/followups")
def followups():
    """'I'm waiting for a response' items (Monica's sent mail with no reply yet)."""
    now = ds.now()
    waiting = [{"id": s["id"], "to": s["to"], "subject": s["subject"], "sent_at": s["sent_at"],
                "days_waiting": (now - datetime.fromisoformat(s["sent_at"])).days}
               for s in ds.sent() if not s["replied"]]
    return {"waiting_for_response": waiting, "need_to_reply": "see /api/emails?category=reply_needed (coming soon)"}


# ---------------------------------------------------------------- MOCK endpoints (AI not wired yet)
class DraftRequest(BaseModel):
    tone: str | None = None  # "shorter" | "friendlier" | "more formal" | None
    instructions: str | None = None


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


@app.post("/api/emails/{email_id}/summary")
def summarize_email(email_id: str):
    return {"mock": True, "email_id": email_id, "main_request": "Approve the back-cover copy.",
            "deadline": "Friday, November 13", "already_agreed": ["Shorten the second paragraph",
                                                                  "Add Dr. Ellis's endorsement"]}


@app.post("/api/emails/{email_id}/draft")
def draft_reply(email_id: str, req: DraftRequest):
    return {"mock": True, "email_id": email_id, "action_id": "act-mock-1",
            "draft": "Hi Priya,\n\nThanks for the updated copy. It looks great. Approved!\n\nBest,\nMonica",
            "status": "pending_approval"}


@app.post("/api/emails/{email_id}/schedule")
def propose_meeting(email_id: str):
    return {"mock": True, "email_id": email_id, "action_id": "act-mock-2",
            "request": {"with": "Priya", "minutes": 45, "window": "next week afternoons, not Wednesday"},
            "options": [{"start": "2026-11-16T14:00:00-05:00", "end": "2026-11-16T14:45:00-05:00", "calendar": "book"},
                        {"start": "2026-11-17T13:00:00-05:00", "end": "2026-11-17T13:45:00-05:00", "calendar": "book"}],
            "status": "pending_approval"}


@app.get("/api/actions")
def list_actions():
    return {"mock": True, "actions": [
        {"id": "act-mock-1", "type": "send_email", "status": "pending_approval",
         "summary": "Reply to Priya: approve back-cover copy", "created_at": ds.now().isoformat()}]}


@app.post("/api/actions/{action_id}/approve")
def approve_action(action_id: str):
    return {"mock": True, "id": action_id, "status": "approved"}


@app.post("/api/actions/{action_id}/reject")
def reject_action(action_id: str):
    return {"mock": True, "id": action_id, "status": "rejected"}


@app.get("/api/briefing")
def briefing():
    return {"mock": True, "text": "You have 5 appointments, 3 emails needing replies, and 1 scheduling conflict.",
            "counts": {"appointments": 5, "reply_needed": 3, "conflicts": 1}}


@app.get("/api/meetings/{event_id}/prep")
def meeting_prep(event_id: str):
    return {"mock": True, "event_id": event_id, "related_emails": ["e042"],
            "open_questions": ["Which title for the grief episode?"]}


@app.post("/api/chat")
def chat(req: ChatRequest):
    return {"mock": True, "reply": "You have a free hour tomorrow from 12:00 to 1:00pm. Want me to hold it?",
            "proposed_actions": []}


# ---------------------------------------------------------------- website (teammates' files)
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")
