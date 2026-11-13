"""Gemini embedding adapter (google-genai). Fails loudly; never falls back to mock vectors."""
import math
import os
import time
from typing import Protocol

from google import genai
from google.genai import errors, types

DEFAULT_MODEL = "gemini-embedding-001"
DEFAULT_DIMENSIONS = 768   # Matryoshka output size; small enough for any pgvector index type
BATCH_SIZE = 100           # texts per request
MAX_RETRIES = 5


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class GeminiEmbedder:
    """Documents use task_type RETRIEVAL_DOCUMENT, questions RETRIEVAL_QUERY.

    Vectors are L2-normalized: Gemini only normalizes the full 3072-d output, and
    normalized vectors make cosine distance well defined for every size.
    `usage` counts requests and characters sent, for the cost/time report.
    """

    def __init__(self, model_name: str | None = None, dimensions: int = DEFAULT_DIMENSIONS,
                 api_key: str | None = None) -> None:
        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set (starter/.env)")
        self.model_name = model_name or os.getenv("EMBEDDING_MODEL") or DEFAULT_MODEL
        self.dimensions = dimensions
        self._client = genai.Client(api_key=api_key)
        self.usage = {"requests": 0, "texts": 0, "chars": 0, "retries": 0}

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, question: str) -> list[float]:
        return self._embed([question], "RETRIEVAL_QUERY")[0]

    def embed_queries(self, questions: list[str]) -> list[list[float]]:
        """Same as embed_query for many questions, batched into few requests."""
        return self._embed(questions, "RETRIEVAL_QUERY")

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        config = types.EmbedContentConfig(task_type=task_type,
                                          output_dimensionality=self.dimensions)
        vectors: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            response = self._call_with_retry(batch, config)
            if len(response.embeddings) != len(batch):
                raise RuntimeError(f"expected {len(batch)} embeddings, got {len(response.embeddings)}")
            for emb in response.embeddings:
                values = list(emb.values)
                if len(values) != self.dimensions:
                    raise RuntimeError(f"expected {self.dimensions} dimensions, got {len(values)}")
                norm = math.sqrt(sum(v * v for v in values))
                if norm == 0:
                    raise RuntimeError("received a zero vector")
                vectors.append([v / norm for v in values])
            self.usage["requests"] += 1
            self.usage["texts"] += len(batch)
            self.usage["chars"] += sum(len(t) for t in batch)
        return vectors

    def _call_with_retry(self, batch: list[str], config: types.EmbedContentConfig):
        for attempt in range(MAX_RETRIES):
            try:
                return self._client.models.embed_content(model=self.model_name, contents=batch,
                                                         config=config)
            except (errors.ClientError, errors.ServerError) as exc:
                retryable = isinstance(exc, errors.ServerError) or getattr(exc, "code", None) == 429
                if not retryable or attempt == MAX_RETRIES - 1:
                    raise
                self.usage["retries"] += 1
                time.sleep(2 ** attempt * 5)   # 5s, 10s, 20s, 40s: free-tier rate limits
        raise AssertionError("unreachable")
