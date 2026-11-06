"""AI features tested with a fake Claude client (no API key, no cost).

Checks the two scope guarantees that don't depend on model quality:
  1. 100% of actions require approval: nothing is sent or booked until /approve.
  2. Planted identifiers never appear in anything sent to the model.
"""
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from assistant import llm, state
from assistant.app import app

ROOT = Path(__file__).resolve().parent.parent
IDENTIFIERS = json.loads((ROOT / "data/ground_truth/identifiers.json").read_text())


class FakeClient:
    """Records every request; answers with plausible JSON for each schema."""

    def __init__(self, script=None):
        self.requests = []
        self.script = list(script or [])
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.requests.append(kw)
        usage = NS(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        if self.script:
            content, stop = self.script.pop(0)
            return NS(content=content, stop_reason=stop, usage=usage)
        props = kw["output_config"]["format"]["schema"]["properties"]
        if "category" in props:
            out = {"category": "reply_needed", "urgent": False, "reason": "Asks you a question."}
        elif "main_request" in props:
            out = {"main_request": "Approve the copy.", "deadline": "Friday", "already_agreed": [],
                   "suggested_next_step": "Reply."}
        elif "is_meeting_request" in props:
            out = {"is_meeting_request": True, "title": "Call with Priya", "with_whom": "Priya",
                   "duration_minutes": 45, "calendar": "book", "specific_times": [],
                   "candidate_dates": ["2026-11-16", "2026-11-17"], "earliest_hour": 13, "latest_hour": 17}
        elif "follow_up_actions" in props:
            out = {"summary": "Talk about launch.", "follow_up_actions": ["Confirm the launch date."]}
        else:
            out = {"subject": "Re: hello", "body": "Hi, thanks! I'll call you at [PHONE_1].\n\nMonica"}
        return NS(content=[NS(type="text", text=json.dumps(out))], stop_reason="end_turn", usage=usage)


@pytest.fixture
def fake():
    state.reset()
    f = FakeClient()
    llm.set_client(f)
    yield f
    llm.set_client(None)
    state.reset()


@pytest.fixture
def api():
    return TestClient(app)


def _sent_text(fake) -> str:
    return json.dumps([{k: r.get(k) for k in ("system", "messages")} for r in fake.requests], default=str)


def test_no_planted_identifier_reaches_the_model(fake, api):
    for eid in IDENTIFIERS:
        api.post(f"/api/emails/{eid}/triage")
        api.post(f"/api/emails/{eid}/summary")
        api.post(f"/api/emails/{eid}/draft", json={})
    sent = _sent_text(fake)
    leaked = [i["value"] for items in IDENTIFIERS.values() for i in items if i["value"] in sent]
    assert leaked == []


def test_draft_is_not_sent_until_approved(fake, api):
    eid = next(k for k, v in IDENTIFIERS.items() if any(i["type"] == "phone" for i in v))
    a = api.post(f"/api/emails/{eid}/draft", json={"tone": "shorter"}).json()
    assert a["status"] == "pending_approval"
    assert api.get("/api/outbox").json()["outbox"] == []
    # placeholders are restored for Monica, so she sees the real phone number
    assert "[PHONE_1]" not in a["payload"]["body"]
    api.patch(f"/api/actions/{a['id']}", json={"body": "Edited by Monica"})
    done = api.post(f"/api/actions/{a['id']}/approve").json()
    assert done["status"] == "approved"
    out = api.get("/api/outbox").json()["outbox"]
    assert len(out) == 1 and out[0]["body"] == "Edited by Monica"
    # approving twice is refused
    assert api.post(f"/api/actions/{a['id']}/approve").status_code == 409


def test_rejected_action_never_executes(fake, api):
    a = api.post("/api/emails/e001/draft", json={}).json()
    api.post(f"/api/actions/{a['id']}/reject")
    assert api.post(f"/api/actions/{a['id']}/approve").status_code == 409
    assert api.get("/api/outbox").json()["outbox"] == []


def test_meeting_is_booked_only_after_approval_and_only_in_free_time(fake, api):
    before = len(api.get("/api/calendar/events").json()["events"])
    res = api.post("/api/emails/e001/schedule").json()
    a = res["action"]
    assert a["status"] == "pending_approval" and a["payload"]["options"]
    assert len(api.get("/api/calendar/events").json()["events"]) == before
    for o in a["payload"]["options"]:  # every suggestion is genuinely free
        day = api.get(f"/api/calendar/day?date={o['start'][:10]}").json()
        assert all(not (e["start"] < o["end"] and e["end"] > o["start"]) for e in day["events"])
    api.post(f"/api/actions/{a['id']}/approve", json={"choice": 0})
    assert len(api.get("/api/calendar/events").json()["events"]) == before + 1


def test_chat_can_only_propose(fake, api):
    tool = NS(type="tool_use", id="tu1", name="propose_meeting",
              input={"title": "Writing time", "date": "2026-11-10", "start_time": "11:00", "minutes": 30,
                     "calendar": "book", "attendees": []})
    fake.script = [([tool], "tool_use"), ([NS(type="text", text="I've suggested 11:00. Approve it below.")], "end_turn")]
    r = api.post("/api/chat", json={"message": "Find 30 minutes tomorrow morning", "history": []}).json()
    assert r["proposed_actions"] and r["proposed_actions"][0]["status"] == "pending_approval"
    assert "Writing time" not in json.dumps(api.get("/api/calendar/day?date=2026-11-10").json())
    assert not any(t["name"] in ("approve", "send_email", "book_meeting") for t in fake.requests[0]["tools"])


def test_chat_refuses_busy_time(fake, api):
    tool = NS(type="tool_use", id="tu1", name="propose_meeting",
              input={"title": "x", "date": "2026-11-10", "start_time": "09:00", "minutes": 30,
                     "calendar": "book", "attendees": []})
    fake.script = [([tool], "tool_use"), ([NS(type="text", text="That time is taken.")], "end_turn")]
    r = api.post("/api/chat", json={"message": "book 9am tomorrow", "history": []}).json()
    assert r["proposed_actions"] == []
    assert "not free" in json.dumps(fake.requests[1]["messages"], default=str)


def test_refusal_and_missing_key_are_friendly(api):
    llm.set_client(None)
    assert api.post("/api/emails/e001/summary").status_code == 503
    f = FakeClient(script=[([], "refusal")])
    llm.set_client(f)
    try:
        r = api.post("/api/emails/e002/draft", json={})
        assert r.status_code == 422 and "handle it directly" in r.json()["message"]
    finally:
        llm.set_client(None)


def test_requests_use_sonnet_with_fallback(fake, api):
    api.post("/api/emails/e003/triage")
    req = fake.requests[0]
    assert req["model"] == "claude-sonnet-5-5"
    assert req["fallbacks"] == "default" and "tool_choice" not in req
