"""Store and search chunk vectors in PostgreSQL + pgvector.

One table holds every strategy; rows are keyed by (strategy, chunk_id), so re-ingesting
the same chunks updates them in place instead of duplicating. Search is exact
(sequential scan, cosine distance `<=>`): no ANN index, so filters never reduce recall.
"""
import hashlib
import json
from typing import Any

import psycopg

from .models import Chunk

TABLE = "chunks"
# Filterable metadata: filter key -> SQL column. Only these keys are accepted, so no
# user-supplied text ever becomes part of the SQL; values are always bound parameters.
FILTER_COLUMNS = {
    "issued_year": "issued_year",
    "document_type": "document_type",
    "article": "article",
}


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.database_url = database_url
        self.dimensions = dimensions

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, connect_timeout=5)

    def create_schema(self) -> None:
        """Create the table if needed and refuse to reuse it with another vector size."""
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    strategy        text    NOT NULL,
                    chunk_id        text    NOT NULL,
                    document_id     text    NOT NULL,
                    source          text    NOT NULL,
                    page            integer NOT NULL,
                    article         text,
                    issued_year     integer NOT NULL,
                    document_type   text    NOT NULL,
                    content         text    NOT NULL,
                    content_sha256  text    NOT NULL,
                    metadata        jsonb   NOT NULL,
                    embedding_model text    NOT NULL,
                    embedding       vector({self.dimensions}) NOT NULL,
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            conn.execute(f"CREATE INDEX IF NOT EXISTS {TABLE}_filter_idx "
                         f"ON {TABLE} (strategy, issued_year, document_type)")
            existing = conn.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = %s::regclass AND attname = 'embedding'", (TABLE,)).fetchone()[0]
            if existing != f"vector({self.dimensions})":
                raise RuntimeError(f"{TABLE}.embedding is {existing}, model gives "
                                   f"vector({self.dimensions}); drop the table to re-index")

    def stored_hashes(self, strategy: str) -> dict[str, tuple[str, str]]:
        """chunk_id -> (content_sha256, embedding_model), to skip re-embedding unchanged chunks."""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT chunk_id, content_sha256, embedding_model FROM {TABLE} "
                                "WHERE strategy = %s", (strategy,)).fetchall()
        return {cid: (sha, model) for cid, sha, model in rows}

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]],
               embedding_model: str) -> None:
        """Insert or update chunks by stable ID (one transaction)."""
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        for v in vectors:
            if len(v) != self.dimensions:
                raise ValueError(f"vector has {len(v)} dimensions, expected {self.dimensions}")
        rows = [(
            strategy, c.chunk_id, c.document_id, c.source, c.page, c.metadata.get("article"),
            c.metadata["issued_year"], c.metadata["document_type"], c.text, content_hash(c.text),
            json.dumps(c.metadata, ensure_ascii=False), embedding_model, _vector_literal(v),
        ) for c, v in zip(chunks, vectors)]
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(f"""
                INSERT INTO {TABLE} (strategy, chunk_id, document_id, source, page, article,
                    issued_year, document_type, content, content_sha256, metadata,
                    embedding_model, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id, source = EXCLUDED.source,
                    page = EXCLUDED.page, article = EXCLUDED.article,
                    issued_year = EXCLUDED.issued_year, document_type = EXCLUDED.document_type,
                    content = EXCLUDED.content, content_sha256 = EXCLUDED.content_sha256,
                    metadata = EXCLUDED.metadata, embedding_model = EXCLUDED.embedding_model,
                    embedding = EXCLUDED.embedding""", rows)

    def delete_missing(self, strategy: str, keep_chunk_ids: list[str]) -> int:
        """Remove chunks of this strategy that the current chunking no longer produces."""
        with self._connect() as conn:
            cur = conn.execute(f"DELETE FROM {TABLE} WHERE strategy = %s "
                               "AND NOT (chunk_id = ANY(%s))", (strategy, keep_chunk_ids))
            return cur.rowcount

    def count(self, strategy: str) -> int:
        with self._connect() as conn:
            return conn.execute(f"SELECT count(*) FROM {TABLE} WHERE strategy = %s",
                                (strategy,)).fetchone()[0]

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Exact cosine search within one strategy, filtering in SQL before ranking."""
        if len(query_vector) != self.dimensions:
            raise ValueError(f"query has {len(query_vector)} dimensions, expected {self.dimensions}")
        where, params = ["strategy = %s"], [strategy]
        for key, value in (filters or {}).items():
            if key not in FILTER_COLUMNS:
                raise ValueError(f"unsupported filter {key!r}; allowed: {sorted(FILTER_COLUMNS)}")
            where.append(f"{FILTER_COLUMNS[key]} = %s")
            params.append(value)
        q = _vector_literal(query_vector)
        sql = (f"SELECT chunk_id, document_id, source, page, article, issued_year, document_type, "
               f"content, metadata, 1 - (embedding <=> %s::vector) AS score FROM {TABLE} "
               f"WHERE {' AND '.join(where)} ORDER BY embedding <=> %s::vector, chunk_id LIMIT %s")
        with self._connect() as conn:
            rows = conn.execute(sql, [q, *params, q, top_k]).fetchall()
        return [{
            "chunk_id": r[0], "document_id": r[1], "source": r[2], "page": r[3], "article": r[4],
            "issued_year": r[5], "document_type": r[6], "text": r[7], "metadata": r[8],
            "score": round(float(r[9]), 4),
        } for r in rows]
