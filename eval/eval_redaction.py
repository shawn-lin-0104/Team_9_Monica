"""Scope objective: the privacy guardrail must catch >= 95% of planted identifiers
before any model call.

An identifier counts as caught if its exact text no longer appears anywhere in
the redacted email that would be sent to the model.

Run:  python eval/eval_redaction.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assistant import data_store  # noqa: E402
from assistant.redaction import redact_email  # noqa: E402

TARGET = 0.95


def main() -> float:
    truth = json.loads((ROOT / "data/ground_truth/identifiers.json").read_text())
    caught, missed, by_type = 0, [], Counter()
    total_by_type = Counter()
    for eid, items in truth.items():
        safe, _ = redact_email(data_store.email(eid))
        blob = json.dumps(safe, ensure_ascii=False)
        for it in items:
            total_by_type[it["type"]] += 1
            if it["value"] in blob:
                missed.append((eid, it["type"], it["value"]))
            else:
                caught += 1
                by_type[it["type"]] += 1
    total = sum(total_by_type.values())
    rate = caught / total
    print(f"Caught {caught}/{total} planted identifiers = {rate:.1%} (target {TARGET:.0%})")
    for t, n in sorted(total_by_type.items()):
        print(f"  {t:24s} {by_type[t]}/{n}")
    for m in missed:
        print("  MISSED", m)

    # Show how much ordinary text gets hidden (over-redaction makes the assistant less useful).
    over = Counter()
    for e in data_store.emails():
        if e["id"] in truth:
            continue
        _, r = redact_email(e)
        for ph, orig in r.mapping.items():
            over[(ph.split("_")[0].strip("["), orig)] += 1
    print(f"\nItems hidden in the {100 - len(truth)} emails with no planted identifiers "
          f"(review for over-redaction): {sum(over.values())}")
    for (kind, orig), n in over.most_common(15):
        print(f"  {kind:10s} {orig!r} x{n}")
    return rate


if __name__ == "__main__":
    sys.exit(0 if main() >= TARGET else 1)
