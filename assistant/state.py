"""Small JSON-file store for things that change while the app runs:
the approval queue, simulated outbox, bookings, follow-up status, and cached AI results.

Approval rule (scope: 100% of actions need Monica's approval): AI code may only call
``propose``. Only ``approve`` executes an action, and only the approve endpoint calls it.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

STATE_DIR = Path(os.environ.get("ASSISTANT_STATE_DIR", Path(__file__).resolve().parent.parent / "data/state"))
CACHE_DIR = Path(os.environ.get("ASSISTANT_CACHE_DIR", Path(__file__).resolve().parent.parent / "data/cache"))
_lock = threading.RLock()
_DEFAULT = {"actions": {}, "outbox": [], "booked": [], "followups": {}}


def _path() -> Path:
    return STATE_DIR / "state.json"


def load() -> dict:
    with _lock:
        if _path().exists():
            data = json.loads(_path().read_text())
            return {**json.loads(json.dumps(_DEFAULT)), **data}
        return json.loads(json.dumps(_DEFAULT))


def save(data: dict) -> None:
    with _lock:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _path().with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(_path())


def reset() -> None:
    with _lock:
        if _path().exists():
            _path().unlink()


# ------------------------------------------------------------------ approval queue
def propose(kind: str, summary: str, payload: dict, source: str = "") -> dict:
    """Record a suggested action. Does NOT carry it out."""
    with _lock:
        s = load()
        action = {"id": f"act-{uuid.uuid4().hex[:8]}", "type": kind, "status": "pending_approval",
                  "summary": summary, "payload": payload, "source": source,
                  "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        s["actions"][action["id"]] = action
        save(s)
        return action


def get_action(action_id: str) -> dict | None:
    return load()["actions"].get(action_id)


def list_actions(status: str | None = None) -> list[dict]:
    acts = sorted(load()["actions"].values(), key=lambda a: a["created_at"], reverse=True)
    return [a for a in acts if status is None or a["status"] == status]


def update_payload(action_id: str, changes: dict) -> dict:
    with _lock:
        s = load()
        a = s["actions"][action_id]
        if a["status"] != "pending_approval":
            raise ValueError("Only pending actions can be edited.")
        a["payload"].update(changes)
        save(s)
        return a


def reject(action_id: str) -> dict:
    with _lock:
        s = load()
        a = s["actions"][action_id]
        if a["status"] == "pending_approval":
            a["status"] = "rejected"
            save(s)
        return a


def approve(action_id: str, choice: int | None = None) -> dict:
    """Monica said yes: carry out the action (simulated: nothing leaves this server)."""
    with _lock:
        s = load()
        a = s["actions"][action_id]
        if a["status"] != "pending_approval":
            raise ValueError(f"Action is already {a['status']}.")
        p = a["payload"]
        if a["type"] == "send_email":
            s["outbox"].append({"to": p["to"], "subject": p["subject"], "body": p["body"],
                                "in_reply_to": p.get("email_id"), "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
            if p.get("email_id"):
                s["followups"][p["email_id"]] = {"status": "done"}
        elif a["type"] == "book_meeting":
            options = p["options"]
            idx = 0 if choice is None else choice
            if not 0 <= idx < len(options):
                raise ValueError("Pick one of the suggested times.")
            opt = options[idx]
            s["booked"].append({"id": f"bk-{uuid.uuid4().hex[:6]}", "uid": f"{a['id']}@assistant",
                                "title": p["title"], "start": opt["start"], "end": opt["end"],
                                "calendar": p["calendar"], "attendees": p.get("attendees", []),
                                "all_day": False, "location": "", "description": "Booked by Sage after Monica approved."})
            a["chosen"] = idx
            if p.get("email_id"):
                s["followups"][p["email_id"]] = {"status": "done"}
        else:
            raise ValueError(f"Unknown action type {a['type']}")
        a["status"] = "approved"
        a["approved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        save(s)
        return a


# ------------------------------------------------------------------ follow-ups
def set_followup(item_id: str, status: str, until: str | None = None) -> None:
    with _lock:
        s = load()
        s["followups"][item_id] = {"status": status, "until": until}
        save(s)


# ------------------------------------------------------------------ AI result cache
def cache_get(name: str) -> dict:
    with _lock:
        p = CACHE_DIR / f"{name}.json"
        return json.loads(p.read_text()) if p.exists() else {}


def cache_put(name: str, key: str, value) -> None:
    with _lock:
        data = cache_get(name)
        data[key] = value
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_DIR / f"{name}.json.tmp"
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        tmp.replace(CACHE_DIR / f"{name}.json")  # atomic: readers never see a half-written file
