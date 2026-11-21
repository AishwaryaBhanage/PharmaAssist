"""Shared helpers for the semantic cache tests: seeded 3072-d vectors at a chosen cosine similarity,
and a factory for valid cache entries. No tests live here."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import numpy as np

from pharmassist.cache.base import CacheEntry

DIM = 3072


def unit(rng: np.random.Generator, dim: int = DIM) -> np.ndarray:
    v = rng.standard_normal(dim)
    return v / np.linalg.norm(v)


def at_cosine(base: np.ndarray, cosine: float, rng: np.random.Generator) -> np.ndarray:
    """A unit vector whose cosine similarity with `base` is exactly `cosine` (to float64 precision):
    cos * base + sin * (a random direction orthogonal to base)."""
    w = rng.standard_normal(base.size)
    w -= w.dot(base) * base
    w /= np.linalg.norm(w)
    return cosine * base + np.sqrt(1.0 - cosine ** 2) * w


def citation(doc_id: str = "va_dod_cpg_opioids_2022", page: int = 27) -> dict:
    """A CitationOut dict as the API stores it; returned verbatim on a hit."""
    return {"id": f"{doc_id}:p{page}", "doc_id": doc_id, "document": "VA/DoD CPG Opioids 2022",
            "label": f"Page {page}", "page": page, "sheet": None, "row": None, "url": None,
            "local_url": f"/api/v1/sources/{doc_id}/p{page}.pdf", "flagged": False, "flag_reason": None,
            "figures": []}


def entry(question: str = "What is the maximum daily dose?", generation: int = 1, *, status: str = "answered",
          citations: list | None = None, created_at: datetime | None = None, **extra) -> CacheEntry:
    return CacheEntry(id=uuid.uuid4().hex, question=question, answer=f"Answer to: {question}", status=status,
                      citations=[citation()] if citations is None else citations, generation=generation,
                      created_at=created_at or datetime.now(timezone.utc), **extra)
