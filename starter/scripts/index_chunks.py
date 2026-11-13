"""Embed chunks A/B with Gemini and store them in pgvector (checkpoint 2:40, indexing part).

Run from starter/ after scripts/build_chunks.py:
    python scripts/index_chunks.py

- Only new or changed chunks (different text hash or model) are embedded; unchanged
  ones are skipped, so a re-run costs nothing and creates no duplicates.
- Chunks that the current chunking no longer produces are deleted.
- Strategy C has no rows of its own: it searches the B rows with a metadata filter.
Writes results/index_log.json (model, dimensions, counts, time, API usage).
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

STARTER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STARTER))
sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
load_dotenv(STARTER / ".env")

from src.embeddings import GeminiEmbedder  # noqa: E402
from src.models import Chunk  # noqa: E402
from src.store import PgVectorStore, content_hash  # noqa: E402

RESULTS = STARTER / "results"
STRATEGIES = ["A", "B"]
DEMO_QUESTION = "Sinh viên bị ốm trong đợt thi thì phải làm thủ tục gì?"  # not in the benchmark


def load_chunks(strategy: str) -> list[Chunk]:
    path = RESULTS / f"chunks_{strategy}.jsonl"
    return [Chunk(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def main() -> None:
    embedder = GeminiEmbedder()
    store = PgVectorStore(os.environ["DATABASE_URL"], embedder.dimensions)
    store.create_schema()
    log = {"embedding_model": embedder.model_name, "dimensions": embedder.dimensions,
           "distance": "cosine", "search": "exact (no ANN index)", "strategies": {}}

    for strategy in STRATEGIES:
        chunks = load_chunks(strategy)
        stored = store.stored_hashes(strategy)
        todo = [c for c in chunks
                if stored.get(c.chunk_id) != (content_hash(c.text), embedder.model_name)]
        t0 = time.perf_counter()
        if todo:
            vectors = embedder.embed_documents([c.text for c in todo])
            store.upsert(strategy, todo, vectors, embedder.model_name)
        deleted = store.delete_missing(strategy, [c.chunk_id for c in chunks])
        seconds = time.perf_counter() - t0
        rows = store.count(strategy)
        if rows != len(chunks):
            raise RuntimeError(f"{strategy}: {rows} rows in DB but {len(chunks)} chunks")
        log["strategies"][strategy] = {"chunks": len(chunks), "embedded": len(todo),
                                       "skipped_unchanged": len(chunks) - len(todo),
                                       "deleted_obsolete": deleted, "rows_in_db": rows,
                                       "seconds": round(seconds, 2)}
        print(f"{strategy}: {len(chunks)} chunks | embedded {len(todo)}, unchanged "
              f"{len(chunks) - len(todo)}, deleted {deleted} | rows in DB {rows} | {seconds:.1f}s")

    log["api_usage"] = embedder.usage
    log["run_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    (RESULTS / "index_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    # Keep every run: the first (full embedding) and later no-op reloads are both evidence.
    with open(RESULTS / "index_runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(log, ensure_ascii=False) + "\n")
    print(f"API usage: {embedder.usage}")

    print(f"\nDemo query: {DEMO_QUESTION}")
    q = embedder.embed_query(DEMO_QUESTION)
    for label, strategy, filters in [("A", "A", None), ("B", "B", None),
                                     ("C (issued_year=2007)", "B", {"issued_year": 2007})]:
        print(f"  {label}:")
        for hit in store.search(strategy, q, top_k=3, filters=filters):
            print(f"    {hit['score']:.3f} {hit['chunk_id']:<24} {hit['article'] or '-':<9} "
                  f"{hit['text'][:70]}")


if __name__ == "__main__":
    main()
