"""Conversational assistant ("What needs my attention?", "Find 30 minutes tomorrow afternoon").

Claude gets read-only tools plus two *proposal* tools. There is no tool that sends,
books, or approves anything: the approval queue is the only way an action happens.
All text going to Claude (history, tool results) is redacted with one Redactor per
request, and the final reply is restored before Monica sees it.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

from . import data_store as ds
from . import features, llm, state
from .calendar_merge import TZ, day_view, free_slots
from .prompts import PERSONA
from .redaction import Redactor, redact_email

MAX_STEPS = 8


def _tool(name, description, props, required=None):
    return {"name": name, "description": description, "strict": True,
            "input_schema": {"type": "object", "properties": props,
                             "required": required if required is not None else list(props),
                             "additionalProperties": False}}


TOOLS = [
    _tool("get_schedule", "Monica's merged schedule for one day (all three calendars): events, free gaps, overlaps.",
          {"date": {"type": "string", "description": "YYYY-MM-DD"}}),
    _tool("find_free_time", "Open slots of at least `minutes` on a day between earliest_hour and latest_hour (24h).",
          {"date": {"type": "string"}, "minutes": {"type": "integer"},
           "earliest_hour": {"type": "integer"}, "latest_hour": {"type": "integer"}}),
    _tool("list_emails", "Inbox emails with their triage category and reason. category 'all' lists everything.",
          {"category": {"type": "string", "enum": ["all", "reply_needed", "scheduling", "fyi", "urgent"]}}),
    _tool("read_email", "Full text of one email (private details hidden).", {"email_id": {"type": "string"}}),
    _tool("list_followups", "Emails Monica still needs to reply to, and sent emails still waiting for an answer.", {}),
    _tool("draft_reply", "Draft a reply to an email. It goes to Monica's approval queue; it is NOT sent.",
          {"email_id": {"type": "string"}, "instructions": {"type": "string"}}),
    _tool("propose_meeting", "Suggest a calendar booking. It goes to Monica's approval queue; it is NOT booked. "
          "Check the time is free first.",
          {"title": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"},
           "start_time": {"type": "string", "description": "HH:MM, 24h"}, "minutes": {"type": "integer"},
           "calendar": {"type": "string", "enum": features.CALENDARS},
           "attendees": {"type": "array", "items": {"type": "string"}}}),
]

CHAT_RULES = """You are chatting with Monica in the app. Answer in a few short sentences or a short list.
Use the tools to look things up; never invent appointments, emails, or free times.
To act, use draft_reply or propose_meeting. These only create suggestions. Tell Monica the suggestion is waiting for \
her approval below the chat. You cannot send, book, or approve anything yourself."""


def _followups() -> dict:
    tri = state.cache_get("triage")
    st = state.load()["followups"]
    need = [{"email_id": e["id"], "from": e["from_name"], "subject": e["subject"], "why": tri[e["id"]]["reason"]}
            for e in ds.emails() if tri.get(e["id"], {}).get("category") == "reply_needed"
            and st.get(e["id"], {}).get("status") != "done"]
    waiting = [{"to": s["to"], "subject": s["subject"], "sent_at": s["sent_at"]}
               for s in ds.sent() if not s["replied"] and st.get(s["id"], {}).get("status") != "done"]
    return {"need_to_reply": need, "waiting_for_response": waiting}


def _run_tool(name: str, args: dict, r: Redactor, proposed: list) -> str:
    if name == "get_schedule":
        v = day_view(ds.merged_events(), date.fromisoformat(args["date"]), now=ds.now())
        slim = {"date": v["date"], "all_day": [e["title"] for e in v["all_day"]],
                "events": [{"title": e["title"], "start": e["start"][11:16], "end": e["end"][11:16],
                            "calendars": e["calendars"], "id": e["id"]} for e in v["events"]],
                "free": [(f["start"][11:16], f["end"][11:16]) for f in v["free_slots"]],
                "overlaps": [(c["a"]["title"], c["b"]["title"]) for c in v["conflicts"]]}
        return r.redact(json.dumps(slim))
    if name == "find_free_time":
        d = date.fromisoformat(args["date"])
        lo, hi = min(max(args["earliest_hour"], 6), 22), min(max(args["latest_hour"], 7), 23)
        slots = free_slots(ds.merged_events(), d, args["minutes"], time(lo), time(max(hi, lo + 1)))
        now = ds.now()
        return json.dumps([(s.strftime("%H:%M"), e.strftime("%H:%M")) for s, e in slots if e > now]) or "[]"
    if name == "list_emails":
        tri = state.cache_get("triage")
        rows = []
        for e in ds.emails():
            t = tri.get(e["id"], {})
            cat = args["category"]
            if cat == "all" or t.get("category") == cat or (cat == "urgent" and t.get("urgent")):
                rows.append({"id": e["id"], "from": e["from_name"], "subject": e["subject"],
                             "category": t.get("category", "not sorted yet"), "urgent": t.get("urgent", False),
                             "reason": t.get("reason", "")})
        return r.redact(json.dumps(rows[:40]))
    if name == "read_email":
        e = ds.email(args["email_id"])
        if not e:
            return "No email with that id."
        return json.dumps(redact_email(e, r)[0])
    if name == "list_followups":
        return r.redact(json.dumps(_followups()))
    if name == "draft_reply":
        if not ds.email(args["email_id"]):
            return "No email with that id."
        a = features.draft_reply(args["email_id"], instructions=r.restore(args["instructions"]) or None)
        proposed.append(a["id"])
        return r.redact(json.dumps({"status": "waiting for Monica's approval", "draft": a["payload"]["body"]}))
    if name == "propose_meeting":
        start = datetime.fromisoformat(f"{args['date']}T{args['start_time']}").replace(tzinfo=TZ)
        minutes = max(10, min(args["minutes"], 240))
        if start <= ds.now():
            return "That time is in the past."
        if not features._within(start, minutes):
            return "Monica is not free then. Pick another time."
        title = r.restore(args["title"])
        a = state.propose("book_meeting", f"Book: {title}",
                          {"title": title, "calendar": args["calendar"], "minutes": minutes,
                           "attendees": [r.restore(x) for x in args["attendees"]],
                           "options": [{"start": start.isoformat(),
                                        "end": (start + timedelta(minutes=minutes)).isoformat(),
                                        "why": "Requested in chat."}]},
                          source="chat")
        proposed.append(a["id"])
        return json.dumps({"status": "waiting for Monica's approval", "action_id": a["id"]})
    return f"Unknown tool {name}"


def chat(message: str, history: list[dict]) -> dict:
    r = Redactor()
    msgs = []
    for h in history[-12:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": r.redact(str(h["content"]))})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    msgs.append({"role": "user", "content": f"(Now: {ds.now():%A %B %d, %Y %I:%M %p})\n{r.redact(message)}"})

    proposed: list[str] = []
    for _ in range(MAX_STEPS):
        resp = llm.create(feature="chat", system=PERSONA + "\n\n" + CHAT_RULES, messages=msgs,
                          tools=TOOLS, effort="medium", max_tokens=12000)
        msgs.append({"role": "assistant", "content": resp.content})  # keep thinking blocks unchanged
        uses = [b for b in resp.content if b.type == "tool_use"]
        if resp.stop_reason != "tool_use" or not uses:
            break
        results = []
        for u in uses:
            try:
                out = _run_tool(u.name, dict(u.input), r, proposed)
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": out})
            except Exception as ex:  # tell Claude, let it recover
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": f"Error: {ex}",
                                "is_error": True})
        msgs.append({"role": "user", "content": results})
    else:
        return {"reply": "Sorry, that took too many steps. Could you ask in a simpler way?",
                "proposed_actions": [state.get_action(i) for i in proposed]}
    reply = r.restore(llm.text_of(resp)).strip() or "Done."
    return {"reply": reply, "proposed_actions": [state.get_action(i) for i in proposed]}
