import pytest

from app.core.rag.reranker import NoopReranker
from app.models.schemas import RetrievalResult


@pytest.mark.asyncio
async def test_noop_reranker_preserves_first_stage_order():
    candidates = [
        RetrievalResult(id="a", content="first", score=0.1),
        RetrievalResult(id="b", content="second", score=0.9),
    ]

    out = await NoopReranker().rerank("query", candidates, top_k=1)

    assert [item.id for item in out] == ["a"]
