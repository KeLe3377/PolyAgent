# -*- coding: utf-8 -*-
"""Reranker interfaces for second-stage retrieval ranking."""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from app.models.schemas import RetrievalResult


@runtime_checkable
class Reranker(Protocol):
    """Second-stage reranker contract."""

    async def rerank(
        self,
        query: str,
        candidates: list[RetrievalResult],
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        ...


class NoopReranker:
    """Deterministic fallback that preserves first-stage order."""

    async def rerank(
        self,
        query: str,
        candidates: list[RetrievalResult],
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        return candidates[:top_k]


class CrossEncoderReranker:
    """SentenceTransformers CrossEncoder reranker loaded lazily."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return self._model

    async def rerank(
        self,
        query: str,
        candidates: list[RetrievalResult],
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        if not candidates:
            return []

        def _predict() -> list[float]:
            model = self._get_model()
            pairs = [(query, item.content) for item in candidates]
            scores = model.predict(pairs)
            return [float(score) for score in scores]

        scores = await asyncio.to_thread(_predict)
        ranked: list[RetrievalResult] = []
        for item, score in sorted(zip(candidates, scores, strict=True), key=lambda x: x[1], reverse=True):
            updated = item.model_copy(deep=True)
            updated.score = score
            updated.metadata = {**updated.metadata, "rerank_score": score}
            ranked.append(updated)
        return ranked[:top_k]


__all__ = ["CrossEncoderReranker", "NoopReranker", "Reranker"]
