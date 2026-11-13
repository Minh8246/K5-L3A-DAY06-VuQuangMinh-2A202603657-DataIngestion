"""Ingest the corpus, export page log, chunks A/B and chunk statistics (checkpoint 1:50).

Run from starter/:
    python scripts/build_chunks.py

Outputs in results/:
    ingest_log.csv          one row per physical page (status, chars, footnotes removed)
    chunks_A.jsonl          fixed-size chunks
    chunks_B.jsonl          structure-aware chunks (strategy C reuses these + filter)
    chunk_stats.json        count / length distribution / total chars per strategy

Also prints a DEV-ONLY sanity check: for each dev question, does any chunk on a gold
page contain the whole evidence? Test questions are deliberately not inspected here.
"""
import csv
import json
import re
import statistics
import sys
import time
import unicodedata
from dataclasses import asdict
from pathlib import Path

STARTER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STARTER))

from src.chunking import by_paragraph, fixed_size  # noqa: E402
from src.ingestion import load_corpus  # noqa: E402

MANIFEST = STARTER / "data" / "manifest.csv"
BENCHMARK = STARTER.parent / "benchmark" / "questions.jsonl"
RESULTS = STARTER / "results"

FIXED_SIZE, FIXED_OVERLAP = 500, 50
PARAGRAPH_MAX = 800


def key(text: str) -> str:
    """Whitespace-insensitive form, same rule as benchmark/verify_benchmark.py."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


def stats(chunks) -> dict:
    lengths = [len(c.text) for c in chunks]
    return {
        "chunks": len(chunks),
        "total_chars": sum(lengths),
        "min": min(lengths),
        "median": statistics.median(lengths),
        "mean": round(statistics.mean(lengths), 1),
        "max": max(lengths),
    }


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    pages, log_rows = load_corpus(MANIFEST, STARTER)
    t_ingest = time.perf_counter() - t0

    strategies = {
        "A": [c for p in pages for c in fixed_size(p, FIXED_SIZE, FIXED_OVERLAP)],
        "B": [c for p in pages for c in by_paragraph(p, PARAGRAPH_MAX)],
    }

    with open(RESULTS / "ingest_log.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(log_rows[0]))
        writer.writeheader()
        writer.writerows(log_rows)
    summary = {"ingest_seconds": round(t_ingest, 2), "content_pages": len(pages),
               "params": {"A": {"size": FIXED_SIZE, "overlap": FIXED_OVERLAP},
                          "B": {"max_size": PARAGRAPH_MAX, "with_header": True}}}
    for name, chunks in strategies.items():
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids)), f"duplicate chunk ids in {name}"
        with open(RESULTS / f"chunks_{name}.jsonl", "w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
        summary[name] = stats(chunks)
    (RESULTS / "chunk_stats.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                              encoding="utf-8")

    skipped = [r for r in log_rows if r["status"] != "ok"]
    print(f"Pages: {len(log_rows)} physical, {len(pages)} content, {len(skipped)} skipped "
          f"({', '.join(r['page_id'] + '=' + r['status'] for r in skipped)})")
    print(f"Footnote lines removed: {sum(r['footnotes_removed'] for r in log_rows)}; "
          f"ingest {t_ingest:.2f}s")
    for name in strategies:
        print(f"{name}: {summary[name]}")

    # Dev-only sanity check: can the evidence be found whole inside one chunk?
    dev = [json.loads(line) for line in BENCHMARK.read_text(encoding="utf-8").splitlines()
           if line.strip() and json.loads(line)["split"] == "dev"]
    print(f"\nDev evidence fully inside one chunk on a gold page ({len(dev)} dev questions):")
    for name, chunks in strategies.items():
        index = {}
        for c in chunks:
            index.setdefault((c.document_id, c.page), []).append(key(c.text))
        missed = []
        for q in dev:
            golds = [(q["gold_source_id"], q["gold_page"], q["evidence_quote"])]
            golds += [(g["source_id"], g["page"], g["evidence_quote"]) for g in q.get("alt_gold", [])]
            if not any(key(ev) in t for sid, pg, ev in golds for t in index.get((sid, pg), [])):
                missed.append(q["id"])
        print(f"  {name}: {len(dev) - len(missed)}/{len(dev)}"
              + (f"  split evidence: {', '.join(missed)}" if missed else ""))


if __name__ == "__main__":
    main()
