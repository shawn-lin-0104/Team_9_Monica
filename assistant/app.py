"""HTTP API the website calls. See docs/API.md for the contract.

Run locally:  uvicorn assistant.app:app --reload
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import chat as chat_mod
from . import data_store as ds
from . import features, llm, state
from .calendar_merge import TZ, day_view, events_between, find_conflicts, free_slots
from .prompts import ASSISTANT_NAME
from .redaction import redact_email

app = FastAPI(title="Monica's Assistant API", version="1.0.0")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.exception_handler(llm.AIUnavailable)
def _ai_unavailable(_: Request, exc: llm.AIUnavailable):
    return JSONResponse(status_code=503, content={"error": "ai_unavailable", "message": str(exc)})


@app.exception_handler(llm.AIRefused)
def _ai_refused(_: Request, exc: llm.AIRefused):
    return JSONResponse(status_code=422, content={"error": "ai_refused", "message": str(exc)})


def _email_or_404(email_id: str) -> dict:
    e = ds.email(email_id)
    if not e:
        raise HTTPException(404, "email not found")
    return e


def _action_or_404(action_id: str) -> dict:
    a = state.get_action(action_id)
    if not a:
        raise HTTPException(404, "action not found")
    return a


# ---------------------------------------------------------------- health / usage
@app.get("/api/health")
def health():
    return {"ok": True, "now": ds.now().isoformat(), "assistant_name": ASSISTANT_NAME,
            "ai_available": llm.available(), "model": llm.MODEL}


@app.get("/api/usage")
def usage():
    """Estimated API spend so far (from data/state/usage.jsonl)."""
    return llm.usage_summary()


@app.post("/api/demo/reset")
def demo_reset():
    """Clear approvals, bookings, and follow-up status so a demo starts fresh. AI caches are kept."""
    state.reset()
    return {"ok": True}


# ---------------------------------------------------------------- calendar
@app.get("/api/calendar/events")
def calendar_events(start: date | None = None, end: date | None = None):
    lo = datetime.combine(start or ds.now().date(), time(0), TZ)
    hi = datetime.combine(end, time(0), TZ) + timedelta(days=1) if end else lo + timedelta(days=28)
    return {"events": [e.to_dict() for e in events_between(ds.merged_events(), lo, hi)]}


@app.get("/api/calendar/day")
def calendar_day(day: date | None = Query(None, alias="date")):
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


# ---------------------------------------------------------------- email
@app.get("/api/emails")
def list_emails(category: str | None = None):
    tri = state.cache_get("triage")
    rows = []
    for e in ds.emails():
        t = tri.get(e["id"])
        if category and (not t or (t.get("category") != category and not (category == "urgent" and t.get("urgent")))):
            continue
        rows.append({k: e[k] for k in ("id", "from_name", "from_email", "subject", "received_at")}
                    | {"preview": e["body"][:140], "triage": t})
    return {"emails": rows, "sorted": sum(1 for r in rows if r["triage"]), "total": len(rows)}


@app.get("/api/emails/{email_id}")
def get_email(email_id: str):
    return _email_or_404(email_id) | {"triage": state.cache_get("triage").get(email_id)}


@app.get("/api/emails/{email_id}/privacy")
def email_privacy(email_id: str):
    safe, r = redact_email(_email_or_404(email_id))
    kinds: dict[str, int] = {}
    for ph in r.mapping:
        k = ph.strip("[]").rsplit("_", 1)[0].lower()
        kinds[k] = kinds.get(k, 0) + 1
    return {"email_id": email_id, "hidden_count": len(r.mapping), "hidden_by_type": kinds, "sent_to_ai": safe}


class TriageRun(BaseModel):
    fresh: bool = False


@app.post("/api/triage/run")
def triage_run(req: TriageRun | None = None):
    """Sort every email not sorted yet (results are saved, so this costs money only once)."""
    results = features.triage_all(use_cache=not (req and req.fresh))
    return {"sorted": sum(1 for v in results.values() if "category" in v), "total": len(results)}


@app.post("/api/emails/{email_id}/triage")
def triage_one(email_id: str):
    _email_or_404(email_id)
    return features.triage_email(email_id)


@app.post("/api/emails/{email_id}/summary")
def summarize_email(email_id: str):
    _email_or_404(email_id)
    return {"email_id": email_id} | features.summarize(email_id)


class DraftRequest(BaseModel):
    tone: str | None = None            # "shorter" | "friendlier" | "formal"
    instructions: str | None = None
    previous_action_id: str | None = None  # rewrite this draft instead of starting over


@app.post("/api/emails/{email_id}/draft")
def draft_reply(email_id: str, req: DraftRequest):
    _email_or_404(email_id)
    previous = None
    if req.previous_action_id:
        old = _action_or_404(req.previous_action_id)
        previous = old["payload"].get("body")
        state.reject(old["id"])  # replaced by the new version
    return features.draft_reply(email_id, tone=req.tone, instructions=req.instructions, previous=previous)


@app.post("/api/emails/{email_id}/schedule")
def propose_meeting(email_id: str):
    _email_or_404(email_id)
    return features.propose_meeting(email_id)


# ---------------------------------------------------------------- approval queue
@app.get("/api/actions")
def list_actions(status: str | None = "pending_approval"):
    return {"actions": state.list_actions(None if status == "all" else status)}


class ActionEdit(BaseModel):
    subject: str | None = None
    body: str | None = None


@app.patch("/api/actions/{action_id}")
def edit_action(action_id: str, req: ActionEdit):
    _action_or_404(action_id)
    changes = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        return state.update_payload(action_id, changes)
    except ValueError as ex:
        raise HTTPException(409, str(ex))


class Approve(BaseModel):
    choice: int | None = None  # which suggested time, for book_meeting


@app.post("/api/actions/{action_id}/approve")
def approve_action(action_id: str, req: Approve | None = None):
    """The ONLY way anything is sent or booked. Sending is simulated (goes to /api/outbox)."""
    _action_or_404(action_id)
    try:
        return state.approve(action_id, req.choice if req else None)
    except ValueError as ex:
        raise HTTPException(409, str(ex))


@app.post("/api/actions/{action_id}/reject")
def reject_action(action_id: str):
    _action_or_404(action_id)
    return state.reject(action_id)


@app.get("/api/outbox")
def outbox():
    """Emails Monica approved. Simulated: nothing actually leaves the server."""
    return {"outbox": state.load()["outbox"]}


# ---------------------------------------------------------------- briefing, prep, follow-ups
@app.get("/api/briefing")
def briefing():
    """Counts are computed in plain code (no AI cost)."""
    now = ds.now()
    view = day_view(ds.merged_events(), now.date(), now=now)
    tri = state.cache_get("triage")
    f = chat_mod._followups()
    reply_needed = len(f["need_to_reply"])
    urgent = sum(1 for x in f["need_to_reply"] if tri.get(x["email_id"], {}).get("urgent"))
    pending = len(state.list_actions("pending_approval"))
    n, c = len(view["events"]), len(view["conflicts"])
    parts = [f"{n} appointment{'s' * (n != 1)}"]
    if tri:
        parts.append(f"{reply_needed} email{'s' * (reply_needed != 1)} needing replies"
                     + (f" ({urgent} urgent)" if urgent else ""))
    parts.append(f"{c} scheduling conflict{'s' * (c != 1)}")
    text = "You have " + ", ".join(parts[:-1]) + ", and " + parts[-1] + " today."
    return {"text": text, "counts": {"appointments": n, "reply_needed": reply_needed, "urgent": urgent,
                                     "conflicts": c, "pending_approvals": pending},
            "next_event": view["next_event"], "emails_sorted": bool(tri)}


@app.get("/api/meetings/{event_id}/prep")
def meeting_prep(event_id: str):
    ev = next((e for e in ds.merged_events() if e.id == event_id), None)
    if not ev:
        raise HTTPException(404, "event not found")
    cached = state.cache_get("prep").get(event_id)
    if cached:
        return cached
    out = {"event_id": event_id} | features.meeting_prep(ev.to_dict())
    state.cache_put("prep", event_id, out)
    return out


@app.get("/api/followups")
def followups():
    now = ds.now()
    st = state.load()["followups"]

    def active(item_id):
        s = st.get(item_id, {})
        if s.get("status") == "done":
            return False
        return not (s.get("status") == "snoozed" and s.get("until") and s["until"] > now.isoformat())

    f = chat_mod._followups()
    tri = state.cache_get("triage")
    need = [x | {"urgent": tri.get(x["email_id"], {}).get("urgent", False)} for x in f["need_to_reply"]
            if active(x["email_id"])]
    waiting = [{"id": s["id"], "to": s["to"], "subject": s["subject"], "sent_at": s["sent_at"],
                "days_waiting": (now - datetime.fromisoformat(s["sent_at"])).days}
               for s in ds.sent() if not s["replied"] and active(s["id"])]
    return {"need_to_reply": need, "waiting_for_response": waiting, "emails_sorted": bool(tri)}


class Snooze(BaseModel):
    days: int = 1


@app.post("/api/followups/{item_id}/done")
def followup_done(item_id: str):
    state.set_followup(item_id, "done")
    return {"ok": True}


@app.post("/api/followups/{item_id}/snooze")
def followup_snooze(item_id: str, req: Snooze):
    until = (ds.now() + timedelta(days=max(1, req.days))).isoformat()
    state.set_followup(item_id, "snoozed", until)
    return {"ok": True, "until": until}


# ---------------------------------------------------------------- chat
class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


@app.post("/api/chat")
def chat(req: ChatRequest):
    return chat_mod.chat(req.message, req.history)


# ---------------------------------------------------------------- website
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")
