# -*- coding: utf-8 -*-
"""Shared RAG request types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RetrievalRequest:
    """Structured retrieval request with optional metadata constraints."""

    query: str
    domain: str | None = None
    dataset: str | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    mode: str = "hybrid"
    top_n: int = 50
    top_k: int = 5
    rerank: bool = True

    def merged_filters(self) -> dict[str, Any]:
        """Return filters with domain/dataset promoted to metadata constraints."""
        merged = dict(self.filters)
        if self.domain and "domain" not in merged:
            merged["domain"] = self.domain
        if self.dataset and "dataset" not in merged:
            merged["dataset"] = self.dataset
        return merged
