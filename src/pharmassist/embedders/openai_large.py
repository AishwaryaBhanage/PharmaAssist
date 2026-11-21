"""OpenAI text-embedding-3-large through the openai SDK (API key from .env).

The one OpenAI embedding path, for index builds, ingestion and queries. Requests are
batched; transient failures (rate limits, timeouts, connection errors, 5xx) are retried with
bounded exponential backoff and counted in `stats`. Keys and vector values are never logged.
"""

import time

import numpy as np

from pharmassist.embedders.base import Embedder, TransientError

BATCH = 256          # inputs per request; ~350-token chunks keep a request well under the token cap
PRICE_PER_MTOK = 0.13
MAX_BACKOFF_S = 30.0


class OpenAIEmbedder(Embedder):
    name = "openai"

    def __init__(self, model: str = "text-embedding-3-large", dimension: int | None = None,
                 batch_size: int = BATCH, max_retries: int = 5, base_delay_s: float = 1.0,
                 timeout_s: float = 60, client=None, sleep=time.sleep):
        """`dimension`, when given, is enforced on every response (3072 for text-embedding-3-large)."""
        if client is None:
            from dotenv import load_dotenv
            from openai import OpenAI

            from pharmassist.config import PROJECT_ROOT
            load_dotenv(PROJECT_ROOT / ".env")
            client = OpenAI(max_retries=0, timeout=timeout_s)  # retries are ours: bounded and counted
        self.model_name, self.client = model, client
        self.dimension, self.batch_size = dimension, batch_size
        self.max_retries, self.base_delay_s, self.sleep = max_retries, base_delay_s, sleep
        self.tokens_used = 0  # reported by the API; the manifest prices it
        self.stats = {"requests": 0, "batches": 0, "retries": 0, "failures": 0, "seconds": 0.0}

    def _request(self, texts: list[str]):
        import openai
        transient = (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError,
                     openai.InternalServerError)
        for attempt in range(self.max_retries + 1):
            self.stats["requests"] += 1
            t0 = time.perf_counter()
            try:
                resp = self.client.embeddings.create(model=self.model_name, input=texts)
                self.stats["seconds"] = round(self.stats["seconds"] + time.perf_counter() - t0, 3)
                return resp
            except transient as e:
                self.stats["failures"] += 1
                if attempt == self.max_retries:
                    raise TransientError(f"{type(e).__name__} after {attempt + 1} attempts") from None
                self.stats["retries"] += 1
                self.sleep(min(self.base_delay_s * 2 ** attempt, MAX_BACKOFF_S))
        raise AssertionError("unreachable")

    def _embed(self, texts: list[str]) -> np.ndarray:
        resp = self._request(texts)
        self.stats["batches"] += 1
        self.tokens_used += resp.usage.total_tokens
        vecs = np.array([d.embedding for d in sorted(resp.data, key=lambda d: d.index)], dtype=np.float32)
        if self.dimension is not None and vecs.shape[1] != self.dimension:
            raise ValueError(f"{self.model_name} returned {vecs.shape[1]} dimensions, expected {self.dimension}")
        return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.vstack([self._embed(texts[i:i + self.batch_size]) for i in range(0, len(texts), self.batch_size)])

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text])[0]

    def token_spans(self, text: str):
        raise NotImplementedError("chunk with a bge setup and reuse its chunks (chunks_from)")
