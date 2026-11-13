"""Create the manual audit sheets (CSV, UTF-8 with BOM so Excel shows Vietnamese).

Run from starter/ after `python -m src.run --split test`:
    python scripts/make_audit_sheets.py
Writes to results/ (refuses to overwrite a sheet that already has scores):
    audit_coherence.csv   10 fixed source positions x strategies A/B/C
    audit_metadata.csv    5 test questions x top-3 x A/B/C  (45 records)
    audit_grounding.csv   5 test questions x A/B/C          (15 rows)
Fill the empty columns by hand, then run scripts/summarize_audit.py.

Coherence positions are chosen by a fixed rule, independent of any score: sort the
content page IDs, take every 4th page (1st, 5th, ..., 37th), and use the character in
the middle of that page's normalized text. For each strategy, the audited chunk is the
first chunk (lowest index) whose span covers that character. C uses B's chunks.
"""
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

STARTER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STARTER))
sys.stdout.reconfigure(encoding="utf-8")

from src.ingestion import load_corpus  # noqa: E402

RESULTS = STARTER / "results"
STRIDE, POSITIONS = 4, 10


def key(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


def load_chunks(strategy: str) -> list[dict]:
    return [json.loads(line) for line in
            (RESULTS / f"chunks_{strategy}.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


def write(name: str, rows: list[dict], manual_cols: list[str]) -> None:
    path = RESULTS / name
    if path.exists():
        with open(path, encoding="utf-8-sig") as f:
            if any(any((r.get(c) or "").strip() for c in manual_cols) for r in csv.DictReader(f)):
                print(f"skip {name}: already has manual labels (delete it to regenerate)")
                return
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {name}: {len(rows)} rows")


def coherence_rows(pages) -> list[dict]:
    chunks = {s: load_chunks(s) for s in ("A", "B")}
    ordered = sorted(pages, key=lambda p: f"{p.document_id}:p{p.page:02d}")
    rows = []
    for n, page in enumerate(ordered[::STRIDE][:POSITIONS], start=1):
        offset = len(page.text) // 2
        context = (page.text[max(0, offset - 90):offset] + " ▶" +
                   page.text[offset:offset + 90]).replace("\n", " ")
        for strategy in ("A", "B", "C"):
            pool = [c for c in chunks["A" if strategy == "A" else "B"]
                    if c["document_id"] == page.document_id and c["page"] == page.page]
            covering = [c for c in pool
                        if c["metadata"]["char_start"] <= offset <= c["metadata"]["char_end"]]
            chunk = covering[0] if covering else min(
                pool, key=lambda c: abs(c["metadata"]["char_start"] - offset))
            rows.append({
                "position_id": f"pos{n:02d}",
                "page_id": f"{page.document_id}:p{page.page:02d}",
                "char_offset": offset,
                "context_at_position (▶ = vị trí)": context,
                "strategy": strategy,
                "chunk_id": chunk["chunk_id"],
                "chunk_chars": len(chunk["text"]),
                "chunk_text": chunk["text"],
                "note": "C dùng chunk của B: chấm giống B" if strategy == "C" else "",
                "score_0_1_2": "",
                "reason": "",
            })
    return rows


def metadata_and_grounding_rows(pages) -> tuple[list[dict], list[dict]]:
    page_text = {(p.document_id, p.page): key(p.text) for p in pages}
    traces = [json.loads(line) for line in
              (RESULTS / "traces_test.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    meta, ground = [], []
    for t in traces:
        for r in t["results"]:
            body = re.sub(r"^\[Điều [^\]]*\]\s*", "", r["text"])
            meta.append({
                "id": t["id"], "strategy": t["strategy"], "rank": r["rank"],
                "question_filter": json.dumps(t["question_filter"], ensure_ascii=False) if t["question_filter"] else "",
                "chunk_id": r["chunk_id"], "document_id": r["document_id"], "page": r["page"],
                "article": r["article"] or "", "issued_year": r["issued_year"],
                "auto_hint_text_found_on_page": "Y" if key(body) in page_text.get((r["document_id"], r["page"]), "") else "N",
                "chunk_text": r["text"],
                "source_page_correct_YN": "", "article_correct_YN": "", "issued_year_correct_YN": "",
                "all_correct_YN": "", "error_note": "",
            })
        top = {f"top{r['rank']}": f"[{r['chunk_id']} | {r['article'] or '-'} | {r['score']}]\n{r['text']}"
               for r in t["results"]}
        ground.append({
            "id": t["id"], "strategy": t["strategy"], "question": t["question"],
            "filter_applied": json.dumps(t["filter_applied"], ensure_ascii=False) if t["filter_applied"] else "",
            "gold": f"{t['gold_source_id']} p{t['gold_page']}" +
                    "".join(f"; {g['source_id']} p{g['page']}" for g in t["alt_gold"]),
            "evidence_quote": t["evidence_quote"],
            "auto_evidence_hit@3 (proxy)": "Y" if t["hit@3"] else "N",
            **{k: top.get(k, "") for k in ("top1", "top2", "top3")},
            "score_0_1_2": "", "reason": "",
        })
    return meta, ground


def main() -> None:
    pages, _ = load_corpus(STARTER / "data" / "manifest.csv", STARTER)
    write("audit_coherence.csv", coherence_rows(pages), ["score_0_1_2", "reason"])
    meta, ground = metadata_and_grounding_rows(pages)
    write("audit_metadata.csv", meta, ["source_page_correct_YN", "article_correct_YN",
                                       "issued_year_correct_YN", "all_correct_YN", "error_note"])
    write("audit_grounding.csv", ground, ["score_0_1_2", "reason"])


if __name__ == "__main__":
    main()
