# Email triage evaluation

Model: `claude-sonnet-5-5` · emails: 100 · cost of this run: $0.36

**Category accuracy: 97/100 = 97%** (target 85%) — PASS
Urgent flag agreement: 95/100 = 95%

## Confusion (rows = correct label, columns = assistant's answer)

| | reply_needed | scheduling | fyi |
|---|---|---|---|
| reply_needed | 35 | 3 | 0 |
| scheduling | 0 | 27 | 0 |
| fyi | 0 | 0 | 35 |

## Mistakes

| Email | Subject | Correct | Assistant | Assistant's reason |
|---|---|---|---|---|
| e080 | Can we talk sooner? | reply_needed | scheduling | Ava is having a hard week, says she is safe, and is asking to talk sooner than her next appointment, so she needs an earlier time soon. |
| e076 | Can we talk sooner? | reply_needed | scheduling | Devon is having a hard week and is asking to talk sooner than the next appointment; they say they're safe, but a client wanting an earlier time is urgent, and the message was sent over the weekend. |
| e026 | Can we talk sooner? | reply_needed | scheduling | Hector is having a hard week and is asking to talk sooner than his next appointment; he says he's safe, but this message has been waiting since Wednesday, so it's worth replying today. |

Caveat: the team wrote the emails, labels, and prompt, so this score is optimistic.
