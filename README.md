# Monica's Assistant (Team 9, Intro to AI, Fall 2026)

A prototype AI assistant that brings Monica's three calendars and her email into one place,
sorts email, drafts replies, and suggests meeting times, with her approval required for every action.
**Simulated data only. No real patient, client, or employer information.**

## Layout
```
assistant/   AI back end (Python, FastAPI): calendar merge, redaction, triage, drafting, chat
web/         Website (website team); served at /, files at /static/...
data/        Simulated dataset (regenerate: python scripts/generate_data.py)
  ground_truth/  Answer keys for evaluation. Never sent to the app or the AI model.
docs/API.md  API contract between the website and the assistant
tests/       Automated checks against the scope objectives
eval/        Evaluation scripts and results
```

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm   # local name detection for the privacy filter
uvicorn assistant.app:app --reload     # http://localhost:8000
pytest                                  # run the checks
```
The AI features need an Anthropic API key in the `ANTHROPIC_API_KEY` environment variable.
Never commit the key.

## Progress against scope objectives
| Objective | Target | Status |
|---|---|---|
| Calendar merge: all events, no duplicates or missing | 100% | Passing (105 raw events, 4 planted duplicates merged into 101; 5 planted conflicts found) |
| Privacy filter catches planted identifiers | ≥ 95% | Passing: 66/66 (100%). Run `python eval/eval_redaction.py` |
| Email triage accuracy | ≥ 85% | Not started |
| Actions require approval | 100% | Not started |

## Privacy filter: known limits
The 100% score is on identifiers our team planted, using formats we knew about. `tests/test_redaction.py`
also checks 13 formats that are not in the dataset (all caught) and records 3 known gaps:
names typed in lowercase mid-sentence, street addresses with no "St/Ave/Rd", and spelled-out emails
("jordan dot kessler at gmail dot com"). A real deployment would need a stronger detector and a
review by Monica's organization.

## Dataset
- 100 inbox emails: 38 reply needed, 27 scheduling, 35 FYI, some with earlier thread history
- 66 planted fake identifiers in 17 emails (names, phones, DOBs, insurance IDs, addresses, MRNs)
- 3 calendars (Thriveworks, book, podcast) covering Nov 9 to Dec 6, 2026
- Fake by construction: 555-01xx phone numbers, never-issued 9xx SSNs, example.* domains

The assistant runs on Claude (Anthropic) behind a custom persona.
