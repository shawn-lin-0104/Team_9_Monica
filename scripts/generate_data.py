"""Generate the simulated dataset for Monica's assistant.

Everything here is fictional. Phone numbers use the reserved 555-01xx range,
SSNs use the never-issued 9xx area numbers, and email domains are example.*.

Outputs (all under data/):
  emails.json                      inbox the app sees (no labels)
  sent.json                        messages Monica sent (for follow-up tracking)
  calendars/<name>.json            three separate calendars
  ground_truth/email_labels.json   category / urgency / reason per email
  ground_truth/identifiers.json    planted identifiers per email (redaction test)
  ground_truth/calendar_truth.json expected merge result (duplicates, conflicts)

Run:  python scripts/generate_data.py
The output is deterministic for a given SEED.
"""
from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

SEED = 9
TZ = "-05:00"  # Pittsburgh, EST (Nov-Dec 2026, after DST ends)
NOW = datetime(2026, 11, 9, 8, 0)  # demo "today": Monday 8:00am
CAL_START = date(2026, 11, 9)
CAL_DAYS = 28
ROOT = Path(__file__).resolve().parent.parent / "data"

rng = random.Random(SEED)

CLIENTS = ["Ava", "Ben", "Carla", "Devon", "Elena", "Felix", "Grace", "Hector", "Isla", "Jamal"]
LAST_NAMES = ["Kessler", "Moreno", "Okonkwo", "Lindqvist", "Brennan", "Takahashi",
              "Abernathy", "Delacroix", "Whitfield", "Novak", "Castellano", "Hargrove"]
STREETS = ["Murray Ave", "Forbes Ave", "Walnut St", "Penn Ave", "Shady Ave",
           "Liberty Ave", "Butler St", "Beechwood Blvd"]
ZIPS = ["15217", "15213", "15232", "15222", "15206", "15201"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

EDITOR = ("Priya", "priya@harborlight-press.example.com")
COHOST = ("Marcus", "marcus@thrivingtogetherpod.example.com")
TW_ADMIN = ("Thriveworks Clinical Ops", "clinical-ops@thriveworks.example.com")
SUPERVISOR = ("Dana", "dana@thriveworks.example.com")
MONICA = "monica@example.com"


def iso(d: date, h: int, m: int = 0) -> str:
    return f"{d.isoformat()}T{h:02d}:{m:02d}:00{TZ}"


# ---------------------------------------------------------------------------
# Fake identifiers. Each call records what was planted so we can test redaction.
# ---------------------------------------------------------------------------
class Planter:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def _add(self, kind: str, value: str) -> str:
        self.items.append({"type": kind, "value": value})
        return value

    def phone(self) -> str:
        n = rng.randint(100, 199)
        fmt = rng.choice(["({a}) 555-0{n}", "{a}-555-0{n}", "{a}.555.0{n}"])
        return self._add("phone", fmt.format(a=rng.choice(["412", "724", "878"]), n=n))

    def full_name(self, first: str | None = None) -> str:
        first = first or rng.choice(["Jordan", "Riley", "Morgan", "Casey", "Taylor", "Avery", "Quinn"])
        return self._add("person_name", f"{first} {rng.choice(LAST_NAMES)}")

    def personal_email(self, name: str) -> str:
        parts = name.lower().split()
        last = parts[1] if len(parts) > 1 else rng.choice(LAST_NAMES).lower()
        return self._add("email", f"{parts[0]}.{last}{rng.randint(1, 99)}@example.net")

    def dob(self) -> str:
        y, mo, d = rng.randint(1958, 2016), rng.randint(1, 12), rng.randint(1, 28)
        if rng.random() < 0.5:
            return self._add("date_of_birth", f"{mo:02d}/{d:02d}/{y}")
        return self._add("date_of_birth", f"{MONTHS[mo - 1]} {d}, {y}")

    def ssn(self) -> str:
        return self._add("ssn", f"9{rng.randint(10, 99)}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}")

    def member_id(self) -> str:
        return self._add("insurance_id", f"{rng.choice(['HPX', 'UPM', 'AET', 'BCB'])}{rng.randint(100000000, 999999999)}")

    def mrn(self) -> str:
        return self._add("medical_record_number", f"{rng.randint(1000000, 9999999)}")

    def address(self) -> str:
        return self._add("address", f"{rng.randint(100, 4999)} {rng.choice(STREETS)}, Pittsburgh, PA {rng.choice(ZIPS)}")


# ---------------------------------------------------------------------------
# Email templates. Each returns a dict; the generator adds ids and dates.
# label: reply_needed | scheduling | fyi
# ---------------------------------------------------------------------------
def t_client_homework(p: Planter):
    c = rng.choice(CLIENTS)
    body = rng.choice([
        f"Hi Monica,\n\nI tried the thought record worksheet this week but I got stuck on the 'evidence against' column. "
        f"Should I be filling that in right away, or after I've calmed down? I don't want to do it wrong before Thursday.\n\nThanks,\n{c}",
        f"Hi Monica, quick question about the breathing exercise you showed me. Is it okay to do it at work when I feel "
        f"a panic attack starting, or should I step outside first? Let me know when you can.\n\n{c}",
    ])
    return dict(from_name=c, from_email=f"{c.lower()}.client@example.org", subject=rng.choice(
        ["Question about the worksheet", "Quick question before our next session", "Homework question"]),
        body=body, label="reply_needed", urgent=False,
        reason="Client is asking a direct question about their homework.")


def t_editor_approval(p: Planter):
    due = rng.choice(["Friday", "Thursday end of day", "November 13"])
    body = (f"Hi Monica,\n\nAttached is the final back-cover copy for *Holding Space*. Marketing needs your sign-off by {due} "
            f"so it can go to the printer. Two small changes from last time: we shortened the second paragraph and added the "
            f"endorsement line. Could you reply with 'approved' or any edits?\n\nBest,\nPriya\nHarborlight Press")
    return dict(from_name=EDITOR[0], from_email=EDITOR[1], subject="Back-cover copy: approval needed",
                body=body, label="reply_needed", urgent=True,
                reason=f"Editor needs approval of the back-cover copy by {due}.",
                history=[{"from": MONICA, "date": "2026-11-02T19:12:00" + TZ,
                          "body": "Hi Priya, the copy looks close. Can we shorten the second paragraph and add Dr. Ellis's endorsement?"}])


def t_guest_prep(p: Planter):
    g = rng.choice(["Dr. Lena", "Tomas", "Rachel", "Keisha"])
    body = (f"Hi Monica,\n\nReally looking forward to being on the show. Could you send over the questions or themes you'd like "
            f"to cover so I can prepare? Also, should I bring up my own experience with grief or keep it professional?\n\n{g}")
    return dict(from_name=g, from_email=f"{g.split()[-1].lower()}@guestmail.example.com", subject="Prep for the episode",
                body=body, label="reply_needed", urgent=False,
                reason="Podcast guest is asking for prep questions and guidance.")


def t_tw_documentation(p: Planter):
    n = rng.randint(2, 5)
    body = (f"Hello Monica,\n\nOur records show {n} progress notes from last week are still unsigned. Please sign them in the "
            f"portal and reply to confirm, or let us know if there is a technical issue. Notes must be signed within 7 days "
            f"of the session.\n\nThank you,\nClinical Operations")
    return dict(from_name=TW_ADMIN[0], from_email=TW_ADMIN[1], subject=f"Action required: {n} unsigned progress notes",
                body=body, label="reply_needed", urgent=True,
                reason=f"{n} progress notes need signing within the 7-day deadline.")


def t_parent_consent(p: Planter):
    child_first = rng.choice(["Mia", "Leo", "Noah", "Zoe"])
    child = p.full_name(child_first)
    body = (f"Hi Ms. Cwynar,\n\nI'm the parent of {child} (date of birth {p.dob()}). The school counselor asked whether "
            f"you can share a short note confirming {child_first} is in treatment, for the 504 plan meeting. Is that something "
            f"you can do, and do I need to sign a release first? You can reach me at {p.phone()}.\n\nThank you,\n"
            f"{p.full_name()}")
    return dict(from_name="Parent of client", from_email=p.personal_email("parent"), subject="Note for school / release form?",
                body=body, label="reply_needed", urgent=False,
                reason="Parent is asking whether Monica can share a note and if a release is needed.")


def t_referral(p: Planter):
    body = rng.choice([
        "Hi Monica,\n\nI have a client relocating to the South Hills who needs an EMDR-trained therapist who takes UPMC. "
        "Do you have anyone you'd recommend?\n\nThanks so much,\nJen",
        "Hey Monica, hope you're well. A friend is looking for a child therapist who works with selective mutism. "
        "Anyone come to mind? No rush, but would love a name or two.\n\nJen",
    ])
    return dict(from_name="Jen", from_email="jen@northsidecounseling.example.com", subject="Referral question",
                body=body, label="reply_needed", urgent=False,
                reason="Colleague is asking for a referral recommendation.")


def t_billing_confirm(p: Planter):
    body = (f"Dear Provider,\n\nWe are reviewing a claim for a session on 10/27/2026. Please confirm the following for the "
            f"patient on file:\nMember ID: {p.member_id()}\nDate of birth: {p.dob()}\nMRN: {p.mrn()}\n\nReply to this "
            f"message to confirm the CPT code (90837 vs 90834) so we can process payment.\n\nClaims Department")
    return dict(from_name="Claims Department", from_email="claims@highmark-plan.example.com",
                subject="Claim review: please confirm session code", body=body, label="reply_needed", urgent=False,
                reason="Insurer needs Monica to confirm the session code before paying a claim.")


def t_cohost_titles(p: Planter):
    body = ("Hey!\n\nI need to lock the title for Wednesday's episode tonight. Options:\n1) Grief Isn't a Straight Line\n"
            "2) The Waves of Loss\n3) When Grief Shows Up at Work\nWhich one do you like? Mine is #1.\n\nMarcus")
    return dict(from_name=COHOST[0], from_email=COHOST[1], subject="Pick a title for Wednesday?", body=body,
                label="reply_needed", urgent=True, reason="Co-host needs a title choice tonight.")


def t_event_bio(p: Planter):
    body = ("Hi Monica,\n\nWe're thrilled to host you at Riverstone Books on December 3. Could you send a 100-word bio and a "
            "headshot for the flyer by next Monday? Also let us know if you'd like a table for signing.\n\nWarmly,\nEvents Team")
    return dict(from_name="Riverstone Books Events", from_email="events@riverstonebooks.example.com",
                subject="Bio and headshot for Dec 3 event", body=body, label="reply_needed", urgent=False,
                reason="Bookstore needs a bio and headshot by next Monday.")


def t_records_request(p: Planter):
    name = p.full_name()
    body = (f"Hello,\n\nI was a client of yours a few years ago and I'd like a copy of my records for a new provider. My name "
            f"is {name}, date of birth {p.dob()}. Please mail them to {p.address()} or call me at {p.phone()}.\n\nThank you")
    return dict(from_name=name.split()[0], from_email=p.personal_email(name), subject="Records request",
                body=body, label="reply_needed", urgent=False,
                reason="Former client is requesting a copy of their records.")


def t_rec_letter(p: Planter):
    body = ("Hi Monica,\n\nThank you again for supervising my practicum last spring. I'm applying to the MSW advanced-standing "
            "program and the letter of recommendation is due December 1. Would you be willing to write one? I can send my "
            "resume and the form link.\n\nGratefully,\nSofia")
    return dict(from_name="Sofia", from_email="sofia.student@university.example.edu", subject="Recommendation letter request",
                body=body, label="reply_needed", urgent=False,
                reason="Former intern is asking for a recommendation letter due December 1.")


def t_client_hard_week(p: Planter):
    c = rng.choice(CLIENTS)
    body = (f"Hi Monica,\n\nThis week has been really hard and I'm not sure I can wait until our next appointment. "
            f"Is there any way to talk sooner? I'm safe, I just feel like I'm falling behind again.\n\n{c}")
    return dict(from_name=c, from_email=f"{c.lower()}.client@example.org", subject="Can we talk sooner?",
                body=body, label="reply_needed", urgent=True,
                reason="Client is struggling and asking to talk before the next session.")


# --- scheduling ---
def t_client_reschedule(p: Planter):
    c = rng.choice(CLIENTS)
    body = rng.choice([
        f"Hi Monica,\n\nI have a work trip and can't make our Tuesday session. Could we move it to Thursday afternoon or "
        f"sometime Friday morning instead?\n\nThanks,\n{c}",
        f"Hi! My daughter's school has a half day so I need to reschedule this week's appointment. Any chance you have "
        f"something Wednesday or Thursday after 3?\n\n{c}",
    ])
    return dict(from_name=c, from_email=f"{c.lower()}.client@example.org", subject="Need to reschedule this week",
                body=body, label="scheduling", urgent=False, reason="Client asks to move this week's session.")


def t_editor_call(p: Planter):
    body = ("Hi Monica,\n\nCan we find 45 minutes next week to go through the copyedits on chapters 6-9? I'm free most "
            "afternoons except Wednesday. Send me a couple of times that work for you.\n\nPriya")
    return dict(from_name=EDITOR[0], from_email=EDITOR[1], subject="45 min next week for copyedits?",
                body=body, label="scheduling", urgent=False, reason="Editor wants a 45-minute call next week.")


def t_guest_times(p: Planter):
    g = rng.choice(["Dr. Okafor", "Rabbi Stern", "Coach Lisa", "Dr. Patel"])
    body = (f"Hello Monica,\n\nThanks for the invitation to join Thriving Together! I could record on Nov 18 at 3pm, "
            f"Nov 20 at 11am, or Dec 2 at 3pm. About an hour works for me. Which is best?\n\n{g}")
    return dict(from_name=g, from_email="guest@speakers.example.com", subject="Recording date options",
                body=body, label="scheduling", urgent=False, reason="Podcast guest offered three recording times.")


def t_tw_sync(p: Planter):
    body = ("Hi Monica,\n\nCould you join a 30-minute team sync this Thursday to go over the new intake process? "
            "We're aiming for 12:30 or 4:30. Let me know which works.\n\nDana")
    return dict(from_name=SUPERVISOR[0], from_email=SUPERVISOR[1], subject="30-min team sync Thursday?",
                body=body, label="scheduling", urgent=False, reason="Supervisor asks for a 30-minute meeting Thursday.")


def t_library_event(p: Planter):
    body = ("Dear Monica,\n\nThe Squirrel Hill library would love to host a talk on your book in early December. Would "
            "Tuesday December 1 or Thursday December 3 in the evening (6-7:30pm) work?\n\nBest regards,\nAdult Programs")
    return dict(from_name="Library Programs", from_email="programs@library.example.org", subject="Author talk in December",
                body=body, label="scheduling", urgent=False, reason="Library proposes two dates for an author talk.")


def t_new_intake(p: Planter):
    name = p.full_name()
    body = (f"Hello,\n\nI was referred by my primary care doctor and I'm looking to start therapy for anxiety. My insurance "
            f"is Aetna, member ID {p.member_id()}. I'm available weekday mornings. My phone is {p.phone()}.\n\n{name}")
    return dict(from_name=name.split()[0], from_email=p.personal_email(name), subject="New client - looking for first appointment",
                body=body, label="scheduling", urgent=False, reason="New client wants to book an intake appointment.")


def t_move_supervision(p: Planter):
    body = ("Hi Monica,\n\nI have a conflict with our Wednesday supervision at noon next week. Could we push it to 1pm, "
            "or would Thursday at noon be better?\n\nDana")
    return dict(from_name=SUPERVISOR[0], from_email=SUPERVISOR[1], subject="Move supervision next week?",
                body=body, label="scheduling", urgent=False, reason="Supervisor wants to move next week's supervision.")


def t_cohost_edit(p: Planter):
    body = ("Hey Monica,\n\nCan we grab an hour sometime this week to review the rough cut of the grief episode? "
            "I'm flexible except Friday.\n\nMarcus")
    return dict(from_name=COHOST[0], from_email=COHOST[1], subject="Hour to review the rough cut?",
                body=body, label="scheduling", urgent=False, reason="Co-host wants an hour this week to review an edit.",
                history=[{"from": MONICA, "date": "2026-11-05T21:40:00" + TZ,
                          "body": "Sounds good, let's review the rough cut together before it goes out."}])


# --- fyi ---
def t_tw_newsletter(p: Planter):
    return dict(from_name="Thriveworks", from_email="news@thriveworks.example.com", subject="November provider newsletter",
                body="This month: updated telehealth guidelines, a new CE course on grief, and holiday office hours. "
                     "No action is needed.", label="fyi", urgent=False, reason="Newsletter with no action needed.")


def t_pod_stats(p: Planter):
    n = rng.randint(800, 2400)
    return dict(from_name="PodHost", from_email="reports@podhost.example.com", subject="Your weekly podcast stats",
                body=f"Thriving Together had {n} downloads this week, up 12% from last week. Top episode: 'Anxiety at Night'.",
                label="fyi", urgent=False, reason="Automated weekly stats report.")


def t_proofs_shipped(p: Planter):
    return dict(from_name=EDITOR[0], from_email=EDITOR[1], subject="Proofs are on their way",
                body="Hi Monica, just a heads-up that the printed proofs shipped today and should arrive by Thursday. "
                     "Nothing needed from you until they arrive.\n\nPriya", label="fyi", urgent=False,
                reason="Editor says proofs shipped; nothing needed yet.")


def t_invite_accepted(p: Planter):
    who = rng.choice(["Priya", "Marcus", "Dana"])
    return dict(from_name="Calendar", from_email="calendar-notification@example.com", subject=f"Accepted: meeting with {who}",
                body=f"{who} has accepted your invitation.", label="fyi", urgent=False,
                reason="Automatic calendar acceptance notice.")


def t_receipt(p: Planter):
    svc = rng.choice(["Zoom", "Canva", "Riverside.fm", "Google Workspace"])
    return dict(from_name=svc, from_email="billing@vendor.example.com", subject=f"Your {svc} receipt",
                body=f"Thanks for your payment of ${rng.randint(12, 35)}.00 for your monthly {svc} plan.",
                label="fyi", urgent=False, reason="Payment receipt.")


def t_ce_promo(p: Planter):
    return dict(from_name="CE Learning", from_email="promo@celearning.example.com", subject="6 CE credits: trauma-informed care",
                body="Earn 6 CE credits with our self-paced trauma-informed care course. 20% off this week.",
                label="fyi", urgent=False, reason="Promotional email.")


def t_billing_processed(p: Planter):
    body = (f"Payment processed for patient {p.full_name()} (Member ID {p.member_id()}), session 10/20/2026. "
            f"Amount: $112.40. This is an automated notice.")
    return dict(from_name="Claims Department", from_email="claims@highmark-plan.example.com", subject="Payment processed",
                body=body, label="fyi", urgent=False, reason="Automated payment notice.")


def t_client_confirm(p: Planter):
    c = rng.choice(CLIENTS)
    return dict(from_name=c, from_email=f"{c.lower()}.client@example.org", subject="See you Tuesday",
                body=f"Hi Monica, just confirming I'll see you Tuesday at the usual time. Thanks!\n{c}",
                label="fyi", urgent=False, reason="Client is confirming an existing appointment; no reply needed.")


def t_listener_thanks(p: Planter):
    return dict(from_name="A listener", from_email="listener@example.net", subject="Thank you for the grief episode",
                body="I just wanted to say your episode on grief helped me get through my mom's anniversary. Thank you.",
                label="fyi", urgent=False, reason="Thank-you note from a listener.")


def t_association_news(p: Planter):
    return dict(from_name="PA Society for Clinical Social Work", from_email="news@pscsw.example.org",
                subject="Legislative update and member news",
                body="Updates on telehealth licensure compacts, plus our winter conference call for proposals.",
                label="fyi", urgent=False, reason="Professional association newsletter.")


def t_episode_uploaded(p: Planter):
    return dict(from_name=COHOST[0], from_email=COHOST[1], subject="Episode 42 is live",
                body="Uploaded episode 42 and scheduled the social posts. Nothing needed from you!\n\nMarcus",
                label="fyi", urgent=False, reason="Co-host reports the episode is published; nothing needed.")


def t_meeting_recap(p: Planter):
    return dict(from_name=EDITOR[0], from_email=EDITOR[1], subject="Recap of today's call",
                body="Thanks for the call. Recap: (1) we keep the current title, (2) chapter 7 moves before chapter 6, "
                     "(3) final manuscript due Nov 20. I'll send the updated schedule.\n\nPriya",
                label="fyi", urgent=False, reason="Recap of agreed decisions; no question asked.")


TEMPLATES = {
    "reply_needed": [t_client_homework, t_editor_approval, t_guest_prep, t_tw_documentation, t_parent_consent,
                     t_referral, t_billing_confirm, t_cohost_titles, t_event_bio, t_records_request, t_rec_letter,
                     t_client_hard_week],
    "scheduling": [t_client_reschedule, t_editor_call, t_guest_times, t_tw_sync, t_library_event, t_new_intake,
                   t_move_supervision, t_cohost_edit],
    "fyi": [t_tw_newsletter, t_pod_stats, t_proofs_shipped, t_invite_accepted, t_receipt, t_ce_promo,
            t_billing_processed, t_client_confirm, t_listener_thanks, t_association_news, t_episode_uploaded,
            t_meeting_recap],
}
COUNTS = {"reply_needed": 38, "scheduling": 27, "fyi": 35}
# Templates that plant identifiers; we make sure each appears enough to reach ~50 identifiers.
IDENTIFIER_TEMPLATES = [t_parent_consent, t_billing_confirm, t_records_request, t_new_intake, t_billing_processed]


def build_emails():
    plan: list = []
    for label, n in COUNTS.items():
        temps = TEMPLATES[label]
        chosen = temps * (n // len(temps)) + rng.sample(temps, n % len(temps))
        plan.extend(chosen)
    rng.shuffle(plan)

    emails, labels, identifiers = [], {}, {}
    start = NOW - timedelta(days=7)
    for i, tmpl in enumerate(plan, 1):
        p = Planter()
        e = tmpl(p)
        eid = f"e{i:03d}"
        received = start + timedelta(minutes=int(i * (7 * 24 * 60 - 60) / len(plan)) + rng.randint(0, 40))
        emails.append({
            "id": eid,
            "from_name": e["from_name"],
            "from_email": e["from_email"],
            "to": MONICA,
            "subject": e["subject"],
            "received_at": received.strftime("%Y-%m-%dT%H:%M:00") + TZ,
            "body": e["body"],
            "history": e.get("history", []),
        })
        labels[eid] = {"category": e["label"], "urgent": e["urgent"], "reason": e["reason"], "template": tmpl.__name__}
        if p.items:
            identifiers[eid] = p.items
    emails.sort(key=lambda x: x["received_at"], reverse=True)
    return emails, labels, identifiers


def build_sent():
    return [
        {"id": "s001", "to": EDITOR[1], "subject": "Chapter 5 revisions", "sent_at": "2026-11-03T20:15:00" + TZ,
         "body": "Hi Priya, attached are my chapter 5 revisions. Can you confirm you received them?", "replied": False},
        {"id": "s002", "to": "events@riverstonebooks.example.com", "subject": "Parking for Dec 3",
         "sent_at": "2026-11-04T10:02:00" + TZ, "body": "Is there parking near the store for the event?", "replied": False},
        {"id": "s003", "to": COHOST[1], "subject": "Rough cut", "sent_at": "2026-11-05T21:40:00" + TZ,
         "body": "Sounds good, let's review the rough cut together before it goes out.", "replied": True},
        {"id": "s004", "to": SUPERVISOR[1], "subject": "CE hours form", "sent_at": "2026-11-02T16:30:00" + TZ,
         "body": "Dana, could you sign my CE hours form when you get a chance?", "replied": False},
        {"id": "s005", "to": EDITOR[1], "subject": "Back-cover copy", "sent_at": "2026-11-02T19:12:00" + TZ,
         "body": "Hi Priya, the copy looks close. Can we shorten the second paragraph and add Dr. Ellis's endorsement?",
         "replied": True},
        {"id": "s006", "to": "guest@speakers.example.com", "subject": "Invitation to Thriving Together",
         "sent_at": "2026-11-01T11:00:00" + TZ, "body": "Would you like to be a guest on our podcast?", "replied": True},
    ]


# ---------------------------------------------------------------------------
# Calendars
# ---------------------------------------------------------------------------
def build_calendars():
    cals = {"thriveworks": [], "book": [], "podcast": []}
    counters = {k: 0 for k in cals}
    busy: dict[date, list[tuple[int, int]]] = {}  # minutes-from-midnight intervals used by any calendar

    def add(cal, title, d, sh, sm, eh, em, uid=None, all_day=False, location="", attendees=None, note=""):
        counters[cal] += 1
        ev_id = f"{cal[:2]}-{counters[cal]:03d}"
        ev = {"id": ev_id, "uid": uid or f"{ev_id}@{cal}.example.com", "title": title,
              "all_day": all_day, "location": location, "attendees": attendees or [], "description": note}
        if all_day:
            ev["start"], ev["end"] = d.isoformat(), (d + timedelta(days=1)).isoformat()
        else:
            ev["start"], ev["end"] = iso(d, sh, sm), iso(d, eh, em)
            busy.setdefault(d, []).append((sh * 60 + sm, eh * 60 + em))
        cals[cal].append(ev)
        return ev

    def free(d, s, e):
        return all(e <= bs or s >= be for bs, be in busy.get(d, []))

    days = [CAL_START + timedelta(days=i) for i in range(CAL_DAYS)]
    thanksgiving = date(2026, 11, 26)
    chapters = iter(range(6, 30))

    # Book and podcast first (fixed rhythms), then therapy sessions fill around them.
    for d in days:
        wd = d.weekday()
        if wd == 2:  # Wednesday
            add("book", f"Writing block: chapter {next(chapters)}", d, 9, 0, 11, 0)
            add("podcast", "Guest prep", d, 14, 0, 14, 45)
            add("podcast", "Podcast recording: Thriving Together", d, 15, 0, 16, 30,
                location="Riverside studio", attendees=["Marcus"])
        if wd == 4 and (d - CAL_START).days % 14 == 4:  # every other Friday
            add("book", "Editor call with Priya", d, 13, 0, 13, 45, location="Zoom", attendees=["Priya"])
        if wd == 4 and (d - CAL_START).days % 14 == 11:
            add("podcast", "Edit review with Marcus", d, 11, 0, 12, 0, location="Zoom", attendees=["Marcus"])
        if wd == 2 and d != thanksgiving:
            add("thriveworks", "Clinical supervision with Dana", d, 12, 0, 13, 0, attendees=["Dana"])

    add("book", "Back-cover copy approval due", date(2026, 11, 13), 0, 0, 0, 0, all_day=True)
    add("book", "Final manuscript due to Harborlight", date(2026, 11, 20), 0, 0, 0, 0, all_day=True)
    add("book", "Author event: Riverstone Books", date(2026, 12, 3), 18, 30, 20, 0, location="Riverstone Books")

    # Planted duplicates: same meeting on two calendars.
    dup_groups = []
    shared_uid = "launch-planning-1@harborlight.example.com"
    a = add("book", "Book launch planning", date(2026, 11, 17), 17, 30, 18, 30, uid=shared_uid, attendees=["Priya", "Marcus"])
    b = add("podcast", "Book launch planning", date(2026, 11, 17), 17, 30, 18, 30, uid=shared_uid, attendees=["Priya", "Marcus"])
    dup_groups.append([f"book/{a['id']}", f"podcast/{b['id']}"])
    shared_uid2 = "launch-episode@thrivingtogether.example.com"
    a = add("podcast", "Launch episode planning", date(2026, 12, 1), 17, 30, 18, 15, uid=shared_uid2, attendees=["Marcus", "Priya"])
    b = add("book", "Launch episode planning", date(2026, 12, 1), 17, 30, 18, 15, uid=shared_uid2, attendees=["Marcus", "Priya"])
    dup_groups.append([f"podcast/{a['id']}", f"book/{b['id']}"])
    # Copied by hand (different uid, same title/time, slightly different capitalisation)
    a = add("thriveworks", "Team meeting: intake process", date(2026, 11, 12), 16, 30, 17, 0, attendees=["Dana"])
    b = add("book", "Team Meeting: Intake Process", date(2026, 11, 12), 16, 30, 17, 0)
    dup_groups.append([f"thriveworks/{a['id']}", f"book/{b['id']}"])
    a = add("podcast", "Podcast recording: holiday stress special", date(2026, 12, 4), 10, 0, 11, 0, attendees=["Marcus"])
    b = add("thriveworks", "Podcast recording: Holiday Stress Special", date(2026, 12, 4), 10, 0, 11, 0)
    dup_groups.append([f"podcast/{a['id']}", f"thriveworks/{b['id']}"])

    # Therapy sessions (50 min) on Mon/Tue/Thu (+2 on Fri mornings), avoiding everything above.
    client_cycle = iter(CLIENTS * 20)
    for d in days:
        wd = d.weekday()
        if d == thanksgiving or wd >= 5:
            continue
        if wd in (0, 1, 3):
            hours = [9, 10, 11, 13, 14, 15, 16]
            k = rng.randint(4, 6)
        elif wd == 4:
            hours = [9, 10]
            k = 2
        else:
            continue
        for h in sorted(rng.sample(hours, k)):
            if free(d, h * 60, h * 60 + 50):
                c = next(client_cycle)
                add("thriveworks", f"Session: {c}", d, h, 0, h, 50, location="Telehealth" if wd == 4 else "Office")

    # Planted conflicts: genuinely different events that overlap.
    conflicts = []

    def plant_conflict(cal_a, title_a, cal_b, title_b, d, sh, eh_a, eh_b):
        x = add(cal_a, title_a, d, sh, 0, eh_a, 0)
        y = add(cal_b, title_b, d, sh, 30, eh_b, 0)
        conflicts.append(sorted([f"{cal_a}/{x['id']}", f"{cal_b}/{y['id']}"]))

    plant_conflict("thriveworks", "Session: Grace", "podcast", "Sponsor call", date(2026, 11, 10), 17, 18, 18)
    plant_conflict("book", "Interview with Pittsburgh Magazine", "thriveworks", "Session: Ben", date(2026, 11, 16), 18, 19, 19)
    plant_conflict("podcast", "Mic test with guest", "book", "Cover photo shoot", date(2026, 11, 23), 18, 19, 20)
    plant_conflict("thriveworks", "Session: Isla", "book", "Podcast-to-book webinar", date(2026, 11, 30), 18, 19, 20)
    plant_conflict("podcast", "Guest prep: Dr. Patel", "thriveworks", "Session: Hector", date(2026, 12, 3), 7, 8, 9)

    for v in cals.values():
        v.sort(key=lambda e: e["start"])
    return cals, dup_groups, conflicts


def main():
    emails, labels, identifiers = build_emails()
    cals, dup_groups, conflicts = build_calendars()
    total_events = sum(len(v) for v in cals.values())
    (ROOT / "calendars").mkdir(parents=True, exist_ok=True)
    (ROOT / "ground_truth").mkdir(parents=True, exist_ok=True)

    def dump(path, obj):
        (ROOT / path).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")

    dump("emails.json", {"now": NOW.strftime("%Y-%m-%dT%H:%M:00") + TZ, "emails": emails})
    dump("sent.json", {"sent": build_sent()})
    for name, events in cals.items():
        dump(f"calendars/{name}.json", {"calendar": name, "timezone": "America/New_York", "events": events})
    dump("ground_truth/email_labels.json", labels)
    dump("ground_truth/identifiers.json", identifiers)
    dump("ground_truth/calendar_truth.json", {
        "total_raw_events": total_events,
        "expected_merged_events": total_events - len(dup_groups),
        "duplicate_groups": dup_groups,
        "planted_conflicts": conflicts,
    })
    n_ids = sum(len(v) for v in identifiers.values())
    cats = {c: sum(1 for l in labels.values() if l["category"] == c) for c in COUNTS}
    print(f"emails={len(emails)} {cats} identifiers={n_ids} in {len(identifiers)} emails")
    print(f"events={total_events} per calendar={ {k: len(v) for k, v in cals.items()} } "
          f"duplicates={len(dup_groups)} conflicts={len(conflicts)}")


if __name__ == "__main__":
    main()
