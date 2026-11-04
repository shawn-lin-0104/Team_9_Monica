# Assistant API: contract for the website team

Base URL: the same site that serves the web pages (e.g. `https://<app>.onrender.com`), so call
paths like `fetch('/api/calendar/day')` with no extra setup.

All times are ISO 8601 with a timezone offset (`2026-11-10T09:00:00-05:00`). All-day items use
plain dates (`2026-11-13`). The demo's "today" is **Monday Nov 9, 2026, 8:00am** (see `/api/health`).

Status: **Real** = works now. **Mock** = returns example data with `"mock": true` in the final
shape; the real version will keep the same fields.

| Method | Path | Status | What it's for |
|---|---|---|---|
| GET | `/api/health` | Real | Server is up; returns the demo's current time |
| GET | `/api/calendar/day?date=YYYY-MM-DD` | Real | **Today's schedule** screen |
| GET | `/api/calendar/events?start=&end=` | Real | Merged events for a date range (default: 4 weeks) |
| GET | `/api/calendar/conflicts` | Real | Upcoming overlapping events |
| GET | `/api/calendar/free-slots?date=&minutes=30` | Real | Open times on a day (9am-6pm by default) |
| GET | `/api/emails` | Real (triage Mock) | Inbox list; `triage` is `null` until triage ships |
| GET | `/api/emails/{id}` | Real | One email, with earlier messages in `history` |
| GET | `/api/followups` | Real | "I'm waiting for a response" list |
| POST | `/api/emails/{id}/summary` | Mock | Main request, deadline, what's already agreed |
| POST | `/api/emails/{id}/draft` | Mock | Suggested reply; body `{"tone": "shorter" \| "friendlier" \| null}` |
| POST | `/api/emails/{id}/schedule` | Mock | Meeting request into suggested times |
| GET | `/api/actions` | Mock | Things waiting for Monica's approval |
| POST | `/api/actions/{id}/approve` | Mock | Monica approves (only way anything is sent/booked) |
| POST | `/api/actions/{id}/reject` | Mock | Monica rejects |
| GET | `/api/briefing` | Mock | Daily briefing text and counts |
| GET | `/api/meetings/{event_id}/prep` | Mock | Related emails and open questions for a meeting |
| POST | `/api/chat` | Mock | Chat assistant; body `{"message": "...", "history": []}` |

## Shapes

### Event (from calendar endpoints)
```json
{
  "id": "m-book_bo-004+podcast_po-005",
  "title": "Book launch planning",
  "start": "2026-11-17T17:30:00-05:00",
  "end": "2026-11-17T18:30:00-05:00",
  "all_day": false,
  "calendars": ["book", "podcast"],
  "source_ids": ["book/bo-004", "podcast/po-005"],
  "location": "",
  "attendees": ["Priya", "Marcus"],
  "description": ""
}
```
`calendars` has more than one entry when the same meeting was on several calendars. Show one
card with both labels. Calendar names: `thriveworks`, `book`, `podcast`.

### `/api/calendar/day`
```json
{
  "date": "2026-11-10",
  "all_day": [Event],
  "events": [Event],
  "next_event": Event | null,
  "free_slots": [{"start": "...", "end": "...", "minutes": 130}],
  "conflicts": [{"a": Event, "b": Event}]
}
```

### Email list row (`/api/emails`)
```json
{
  "id": "e042", "from_name": "Priya", "from_email": "...", "subject": "...",
  "received_at": "...", "preview": "first 140 characters",
  "triage": {"category": "reply_needed" | "scheduling" | "fyi", "urgent": true, "reason": "plain-language why"}
}
```

### Actions (approval queue)
Every AI suggestion that would change something (send an email, book a meeting) is created as an
action with `"status": "pending_approval"`. Nothing happens until the website calls
`/approve`. Show the full draft or meeting details before the Approve button.

## Running it locally
```bash
pip install -r requirements.txt
uvicorn assistant.app:app --reload
```
Then open http://localhost:8000 (website) or http://localhost:8000/docs (interactive API docs).
