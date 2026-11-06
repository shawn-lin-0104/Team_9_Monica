# Assistant API: contract for the website team

Base URL: the same site that serves the web pages, so call paths like `fetch('/api/calendar/day')`.
Interactive docs with a "Try it" button: `/docs` on the running server.

All times are ISO 8601 with offset (`2026-11-10T09:00:00-05:00`); all-day items use plain dates.
The demo's "today" is **Monday Nov 9, 2026, 8:00am** (see `/api/health`).

**AI** = calls Claude (needs `ANTHROPIC_API_KEY` on the server; costs a little per call).
Without a key, AI endpoints return **503** `{"error": "ai_unavailable", "message": "..."}`.
If Claude declines a request: **422** `{"error": "ai_refused", "message": "..."}`. Show `message` to Monica.

## Endpoints

| Method | Path | AI? | Purpose |
|---|---|---|---|
| GET | `/api/health` | | `now`, `assistant_name`, `ai_available`, `model` |
| GET | `/api/usage` | | Estimated API spend so far, by feature |
| POST | `/api/demo/reset` | | Clear approvals/bookings/follow-up status before a demo |
| GET | `/api/briefing` | | Daily briefing text + counts (plain code, free) |
| GET | `/api/calendar/day?date=` | | Today's schedule: events, next, free gaps, overlaps |
| GET | `/api/calendar/events?start=&end=` | | Merged events (default 4 weeks) |
| GET | `/api/calendar/conflicts` | | Upcoming overlaps |
| GET | `/api/calendar/free-slots?date=&minutes=` | | Open times on a day |
| GET | `/api/meetings/{event_id}/prep` | AI | Related emails + summary + `follow_up_actions` (short action sentences; cached after first call) |
| GET | `/api/emails?category=` | | Inbox with saved `triage`; category = reply_needed / scheduling / fyi / urgent |
| GET | `/api/emails/{id}` | | One email + `history` + `triage` |
| GET | `/api/emails/{id}/privacy` | | Exactly what the AI receives + `hidden_count` |
| POST | `/api/triage/run` | AI | Sort all unsorted emails (body `{"fresh": true}` to redo all) |
| POST | `/api/emails/{id}/triage` | AI | Sort one email |
| POST | `/api/emails/{id}/summary` | AI | `main_request`, `deadline`, `already_agreed[]`, `suggested_next_step` |
| POST | `/api/emails/{id}/draft` | AI | Creates a pending `send_email` action. Body: `{"tone": "shorter"\|"friendlier"\|"formal", "instructions": "...", "previous_action_id": "act-..."}` |
| POST | `/api/emails/{id}/schedule` | AI | Creates a pending `book_meeting` action with up to 3 free `options` |
| GET | `/api/actions?status=` | | Approval queue (default `pending_approval`; `all` for everything) |
| PATCH | `/api/actions/{id}` | | Monica edits a draft: `{"subject": "...", "body": "..."}` |
| POST | `/api/actions/{id}/approve` | | **The only way anything happens.** `{"choice": 0}` picks a meeting option |
| POST | `/api/actions/{id}/reject` | | Discard |
| GET | `/api/outbox` | | Approved emails (simulated; nothing leaves the server) |
| GET | `/api/followups` | | `need_to_reply[]` and `waiting_for_response[]` |
| POST | `/api/followups/{id}/done` | | Mark done |
| POST | `/api/followups/{id}/snooze` | | `{"days": 1}` |
| POST | `/api/chat` | AI | `{"message": "...", "history": [{"role": "user"\|"assistant", "content": "..."}]}` returns `{"reply", "proposed_actions": [Action]}` |

## Shapes

### Event
```json
{"id": "m-book_bo-004+podcast_po-005", "title": "Book launch planning",
 "start": "2026-11-17T17:30:00-05:00", "end": "2026-11-17T18:30:00-05:00", "all_day": false,
 "calendars": ["book", "podcast"], "source_ids": ["book/bo-004", "podcast/po-005"],
 "location": "", "attendees": ["Priya", "Marcus"], "description": ""}
```
More than one entry in `calendars` = the same meeting was on several calendars; show one card with both labels.

### Triage
```json
{"category": "reply_needed", "urgent": true, "reason": "Priya needs your approval on the cover copy by Friday."}
```

### Action (approval queue)
```json
{"id": "act-1a2b3c4d", "type": "send_email", "status": "pending_approval",
 "summary": "Reply to Priya: Back-cover copy: approval needed",
 "payload": {"email_id": "e042", "to": "priya@...", "subject": "Re: ...", "body": "Hi Priya, ..."}}
```
```json
{"id": "act-5e6f7a8b", "type": "book_meeting", "status": "pending_approval", "summary": "Book: Copyedit call",
 "payload": {"title": "Copyedit call", "calendar": "book", "minutes": 45, "attendees": ["Priya"],
             "options": [{"start": "...", "end": "...", "why": "You're free then."}]}}
```
`status` becomes `approved` or `rejected`. Approving twice returns 409.

## Running locally
```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm
uvicorn assistant.app:app --reload
```
