# -*- coding: utf-8 -*-
"""OpenAI-compatible embedding adapter."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable

from openai import AsyncOpenAI


@runtime_checkable
class EmbeddingAdapterProtocol(Protocol):
    """Embedding contract used by RAG and memory components."""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


class OpenAIEmbeddingAdapter:
    """OpenAI-compatible embeddings client.

    The async batch API is the primary contract. ``embed_query`` is provided for
    existing synchronous Protocol users and is called from worker threads by the
    current retriever/memory code paths.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        model: str,
        client: Any | None = None,
    ) -> None:
        self.model = model
        if client is not None:
            self._client = client
            return
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a non-empty batch of texts."""
        if not texts:
            return []
        resp = await self._client.embeddings.create(model=self.model, input=texts)
        return [list(item.embedding) for item in resp.data]

    def embed_query(self, text: str) -> list[float]:
        """Synchronous single-query helper for legacy retriever Protocols."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.embed_texts([text]))[0]

        # Existing callers execute this method inside asyncio.to_thread; if a
        # caller invokes it on the event loop thread, fail loudly instead of
        # deadlocking.
        raise RuntimeError("embed_query must not be called from an active event loop")
