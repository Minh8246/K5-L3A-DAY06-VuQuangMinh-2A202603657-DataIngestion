"""Run the benchmark for strategies A, B, C and save top-3 traces and metrics.

Run from starter/ after scripts/build_chunks.py and scripts/index_chunks.py:
    python -m src.run --split dev     # choose / check configurations on dev only
    python -m src.run --split test    # once, after the configuration is frozen

Strategies (same corpus, embedding model, store and questions):
    A  fixed-size chunks (500/50), no filter
    B  structure-aware chunks (Điều/khoản, max 800, article header), no filter
    C  same rows as B, plus the question's metadata filter when it has one;
       questions without a filter run unfiltered (identical to B) and are marked so.
Outputs: results/traces_<split>.jsonl and results/metrics_<split>.json
"""
import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from .embeddings import GeminiEmbedder
from .evaluation import evaluate_query, summarize
from .store import PgVectorStore

STARTER = Path(__file__).resolve().parents[1]
BENCHMARK = STARTER.parent / "benchmark" / "questions.jsonl"
RESULTS = STARTER / "results"
TOP_K = 3
STRATEGIES = {  # name -> (rows to search, use the question's filter?)
    "A": ("A", False),
    "B": ("B", False),
    "C": ("B", True),
}


def check_corpus() -> None:
    with open(RESULTS / "ingest_log.csv", encoding="utf-8") as f:
        content = sum(1 for r in csv.DictReader(f) if r["status"] == "ok")
    if content < 30:
        raise SystemExit(f"only {content} content pages; the lab needs >= 30")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    split = parser.parse_args().split
    load_dotenv(STARTER / ".env")
    check_corpus()

    questions = [json.loads(line) for line in BENCHMARK.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    questions = [q for q in questions if q["split"] == split]
    embedder = GeminiEmbedder()
    store = PgVectorStore(os.environ["DATABASE_URL"], embedder.dimensions)
    for rows in {"A", "B"}:
        models = {m for _, m in store.stored_hashes(rows).values()}
        if models != {embedder.model_name}:
            raise SystemExit(f"index {rows} built with {models or 'nothing'}; "
                             f"run scripts/index_chunks.py with {embedder.model_name}")

    t0 = time.perf_counter()
    query_vectors = embedder.embed_queries([q["question"] for q in questions])
    t_embed = time.perf_counter() - t0

    traces, timings = [], {name: 0.0 for name in STRATEGIES}
    for q, vector in zip(questions, query_vectors):
        for name, (rows, use_filter) in STRATEGIES.items():
            filters = q.get("filter") if use_filter else None
            t = time.perf_counter()
            hits = store.search(rows, vector, top_k=TOP_K, filters=filters)
            timings[name] += time.perf_counter() - t
            result = evaluate_query(q, hits)
            traces.append({
                "strategy": name, "split": split, "id": q["id"], "type": q.get("type"),
                "question": q["question"], "question_filter": q.get("filter"),
                "filter_applied": filters, "gold_source_id": q["gold_source_id"],
                "gold_page": q["gold_page"], "evidence_quote": q["evidence_quote"],
                "alt_gold": q.get("alt_gold", []), **result,
            })

    metrics = {
        "split": split, "questions": len(questions), "top_k": TOP_K,
        "embedding_model": embedder.model_name, "dimensions": embedder.dimensions,
        "query_embedding_seconds": round(t_embed, 2),
        "search_seconds": {k: round(v, 3) for k, v in timings.items()},
        "api_usage": embedder.usage,
        "summary": summarize(traces),
    }
    RESULTS.mkdir(exist_ok=True)
    with open(RESULTS / f"traces_{split}.jsonl", "w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    (RESULTS / f"metrics_{split}.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2),
                                                   encoding="utf-8")

    print(f"{split}: {len(questions)} questions x {len(STRATEGIES)} strategies, top-{TOP_K}")
    for key, s in metrics["summary"].items():
        print(f"  {key:<8} Hit@1 {s['hit@1']:>6}  Hit@3 {s['hit@3']:>6}  "
              f"miss-but-gold-page {s['miss_but_gold_page_in_top3']}  "
              f"filter-compliance {s['filter_compliance_top3']}")
    print("\nPer question (first hit rank; - = miss):")
    print("  id   type                 filter  " + "  ".join(STRATEGIES))
    by_id = {}
    for t in traces:
        by_id.setdefault(t["id"], {})[t["strategy"]] = t
    for qid, row in by_id.items():
        any_t = next(iter(row.values()))
        marks = "  ".join(str(row[s]["first_hit_rank"] or "-") for s in STRATEGIES)
        print(f"  {qid}  {any_t['type']:<20} {'yes' if any_t['question_filter'] else '   '}     {marks}")


if __name__ == "__main__":
    main()
