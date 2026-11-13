"""Cross-check results/audit_metadata.csv against the raw PDF text.

Run from starter/ (no API, no database):
    python scripts/verify_metadata_audit.py
For every audited chunk it checks, independently of src/chunking.py:
  - page    : the first characters of the chunk text occur on the labelled physical page;
  - article : the label equals the "Điều N." heading in force at the chunk's first character,
              and no other "Điều" heading starts inside the chunk (a chunk that mixes two
              articles but names only the first one counts as a wrong label). A chunk that
              opens with a "Chương" line is expected to carry the article it introduces;
  - year    : issued_year equals the year of the document (see YEAR below).
It prints a verdict per row and lists rows where it disagrees with the hand label
(all_correct_YN). Matching ignores whitespace and case because pypdf inserts stray spaces
inside words, and uses only a short prefix because the pipeline removes footnote numbers
that remain in the raw text.
"""
import csv
import json
import logging
import re
import sys
import unicodedata
from pathlib import Path

from pypdf import PdfReader

logging.getLogger("pypdf").setLevel(logging.ERROR)
sys.stdout.reconfigure(encoding="utf-8")

STARTER = Path(__file__).resolve().parents[1]
RESULTS = STARTER / "results"
PDF = {"qd43-2007": "data/qd43_2007_quy_che_tin_chi_sua_doi_2012.pdf",
       "tt08-2021": "data/tt08_2021_quy_che_dao_tao_dai_hoc.pdf"}
YEAR = {"qd43-2007": 2007, "tt08-2021": 2021}  # issued_date in data/manifest.csv
PROBE = 16


def squash(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text)).lower()


def load_pages(doc: str) -> tuple[list[str], list[tuple[int, int, str]]]:
    """Squashed text per physical page and (page, offset, article number) of each heading."""
    pages, heads = [], []
    for number, page in enumerate(PdfReader(STARTER / PDF[doc]).pages, start=1):
        text = unicodedata.normalize("NFC", page.extract_text() or "")
        pages.append(squash(text))
        offset = 0
        for line in text.split("\n"):
            m = re.match(r"^\s*Điều (\d+[a-z]?)\.\s", line)
            if m:
                heads.append((number, len(squash(text[:text.find(line, offset)])), m.group(1)))
            offset = text.find(line, offset) + len(line)
    return pages, heads


def main() -> None:
    chunks = {}
    for strategy in "AB":
        for line in (RESULTS / f"chunks_{strategy}.jsonl").read_text(encoding="utf-8").splitlines():
            c = json.loads(line)
            chunks[c["chunk_id"]] = c
    corpus = {doc: load_pages(doc) for doc in PDF}
    with open(RESULTS / "audit_metadata.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    ok_by_strategy, disagreements = {}, []
    for r in rows:
        c = chunks[r["chunk_id"]]
        doc, page = c["document_id"], c["page"]
        pages, heads = corpus[doc]
        body = squash(re.sub(r"^\[Điều[^\]]*\]\s*", "", c["text"]))
        pos = pages[page - 1].find(body[:PROBE])
        page_ok = pos >= 0
        # The pipeline drops footnote numbers, so locate the chunk's end by its tail, not by length.
        tail = pages[page - 1].find(body[-PROBE:], max(pos, 0))
        end = tail + PROBE if tail >= 0 else pos + len(body)
        started = [h for h in heads if h[0] == page and pos <= h[1] < end]
        before = [h for h in heads if (h[0], h[1]) <= (page, max(pos, 0))]
        if body.startswith("chương") and started:      # chapter line + the article it introduces
            expected, inside = "Điều " + started[0][2], started[1:]
        else:
            expected = "Điều " + before[-1][2] if before else None
            inside = [h for h in started if h[1] > pos]
        article_ok = page_ok and r["article"] == expected and not inside
        year_ok = c["metadata"]["issued_year"] == YEAR[doc]
        verdict = page_ok and article_ok and year_ok
        note = "" if verdict else (f"page_ok={page_ok} expected={expected} "
                                   f"label={r['article']} inside={['Điều ' + h[2] for h in inside]} year_ok={year_ok}")
        ok_by_strategy.setdefault(r["strategy"], []).append(verdict)
        print(f"{r['id']} {r['strategy']} #{r['rank']} {r['chunk_id']}: {'OK ' if verdict else 'BAD'} {note}")
        if verdict != (r["all_correct_YN"].strip().upper() == "Y"):
            disagreements.append(f"{r['id']} {r['strategy']} #{r['rank']} {r['chunk_id']}")

    print()
    for strategy, flags in sorted(ok_by_strategy.items()):
        print(f"{strategy}: {sum(flags)}/{len(flags)} metadata đủ và đúng (script)")
    print("Khác nhãn tay:", disagreements or "không")


if __name__ == "__main__":
    main()
