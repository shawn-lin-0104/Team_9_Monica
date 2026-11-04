"""Scope objective: email triage accuracy >= 85% against the labeled simulated emails.

Uses the saved results in data/cache/triage.json; only emails not yet sorted call the API.
  python eval/eval_triage.py            # sort what's missing, then score (~$0.30-0.60 for all 100 on Sonnet 5.5)
  python eval/eval_triage.py --fresh    # re-sort everything (after changing the prompt)

Writes eval/results/triage.md.
Caveat: the same team wrote the labels, the emails, and the prompt, so this score is
optimistic. Monica's review of the dataset and her own judgment in the demo matter more.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assistant import data_store as ds  # noqa: E402
from assistant import features, llm  # noqa: E402

TARGET = 0.85
CATS = ["reply_needed", "scheduling", "fyi"]


def main() -> float:
    fresh = "--fresh" in sys.argv
    before = llm.usage_summary()["usd"]
    results = features.triage_all(use_cache=not fresh)
    spent = llm.usage_summary()["usd"] - before
    labels = json.loads((ROOT / "data/ground_truth/email_labels.json").read_text())

    correct, urgent_ok, rows = 0, 0, []
    confusion = Counter()
    for e in ds.emails():
        truth, got = labels[e["id"]], results.get(e["id"], {})
        pred = got.get("category", "error")
        confusion[(truth["category"], pred)] += 1
        correct += pred == truth["category"]
        urgent_ok += got.get("urgent") == truth["urgent"]
        if pred != truth["category"]:
            rows.append(f"| {e['id']} | {e['subject']} | {truth['category']} | {pred} | {got.get('reason', got.get('error', ''))} |")

    n = len(ds.emails())
    acc = correct / n
    lines = [
        "# Email triage evaluation", "",
        f"Model: `{llm.MODEL}` · emails: {n} · cost of this run: ${spent:.2f}", "",
        f"**Category accuracy: {correct}/{n} = {acc:.0%}** (target {TARGET:.0%}) — "
        + ("PASS" if acc >= TARGET else "BELOW TARGET"),
        f"Urgent flag agreement: {urgent_ok}/{n} = {urgent_ok / n:.0%}", "",
        "## Confusion (rows = correct label, columns = assistant's answer)", "",
        "| | " + " | ".join(CATS) + " |", "|---|" + "---|" * len(CATS),
        *[f"| {t} | " + " | ".join(str(confusion[(t, p)]) for p in CATS) + " |" for t in CATS], "",
        "## Mistakes", "", "| Email | Subject | Correct | Assistant | Assistant's reason |", "|---|---|---|---|---|",
        *rows, "",
        "Caveat: the team wrote the emails, labels, and prompt, so this score is optimistic.",
    ]
    out = ROOT / "eval/results/triage.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:7]))
    print(f"Full report: {out}")
    return acc


if __name__ == "__main__":
    sys.exit(0 if main() >= TARGET else 1)
