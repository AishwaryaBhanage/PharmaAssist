"""Shared embedder interface."""

from abc import ABC, abstractmethod

import numpy as np


class Embedder(ABC):
    name: str
    model_name: str

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        """L2-normalized float32 vectors, one row per text."""

    @abstractmethod
    def embed_query(self, text: str) -> np.ndarray:
        """L2-normalized float32 vector for a search query."""

    @abstractmethod
    def token_spans(self, text: str) -> list[tuple[int, int]]:
        """(start, end) character span of each model token, so chunkers can size chunks exactly."""


class TransientError(Exception):
    """A provider failure that may succeed later (rate limit, timeout, 5xx), after the embedder's
    own bounded retries are spent."""
