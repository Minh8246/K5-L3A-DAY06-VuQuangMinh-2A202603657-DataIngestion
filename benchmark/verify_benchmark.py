"""Verify benchmark/questions.jsonl against the corpus PDFs before any retrieval run.

Run from the repo root:
    python benchmark/verify_benchmark.py

Checks:
  - required fields, unique ids, split in {dev, test}
  - every evidence_quote (gold and alt_gold) is on its stated PHYSICAL page;
    matching ignores all whitespace because pypdf splits words ("Thông t ư")
  - totals: >= 20 questions, >= 15 dev, >= 5 test, >= 3 with filter, >= 1 filter in test
Exit code 1 if any evidence or field check fails; count shortfalls are reported as TODO.
"""
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "benchmark" / "questions.jsonl"
MANIFEST = ROOT / "starter" / "data" / "manifest.csv"
REQUIRED = ["id", "split", "question", "expected_answer",
            "gold_source_id", "gold_page", "evidence_quote"]


def key(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


def load_pages() -> dict[str, list[str]]:
    pages = {}
    with open(MANIFEST, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            reader = PdfReader(ROOT / "starter" / row["local_path"])
            pages[row["source_id"]] = [key(p.extract_text() or "") for p in reader.pages]
    return pages


def main() -> int:
    pages = load_pages()
    questions = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    errors, seen = [], set()

    for q in questions:
        qid = q.get("id", "?")
        missing = [f for f in REQUIRED if f not in q]
        if missing:
            errors.append(f"{qid}: missing fields {missing}")
            continue
        if qid in seen:
            errors.append(f"{qid}: duplicate id")
        seen.add(qid)
        if q["split"] not in ("dev", "test"):
            errors.append(f"{qid}: split must be dev/test, got {q['split']!r}")

        golds = [(q["gold_source_id"], q["gold_page"], q["evidence_quote"])]
        golds += [(g["source_id"], g["page"], g["evidence_quote"]) for g in q.get("alt_gold", [])]
        for sid, page, quote in golds:
            if sid not in pages:
                errors.append(f"{qid}: unknown source_id {sid!r}")
                continue
            ev = key(quote)
            if not 1 <= page <= len(pages[sid]):
                errors.append(f"{qid}: {sid} has no page {page}")
            elif ev not in pages[sid][page - 1]:
                found = [i + 1 for i, t in enumerate(pages[sid]) if ev in t]
                hint = f"found on physical page(s) {found}" if found else "not found anywhere (retyped? spans two pages?)"
                errors.append(f"{qid}: evidence not on {sid} p{page}; {hint}")

    dev = [q for q in questions if q.get("split") == "dev"]
    test = [q for q in questions if q.get("split") == "test"]
    filt = [q for q in questions if q.get("filter")]
    filt_test = [q for q in filt if q.get("split") == "test"]
    counts = [("total", len(questions), 20), ("dev", len(dev), 15), ("test", len(test), 5),
              ("with filter", len(filt), 3), ("filter in test", len(filt_test), 1)]

    print(f"Checked {len(questions)} questions from {QUESTIONS.relative_to(ROOT)}")
    for name, have, need in counts:
        print(f"  {'OK  ' if have >= need else 'TODO'} {name}: {have} (need >= {need})")
    for e in errors:
        print("  ERROR", e)
    print("Evidence/fields OK." if not errors else f"{len(errors)} error(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
