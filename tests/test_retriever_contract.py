import pytest

from app.core.rag.retriever import MultiRetriever


class _Embedder:
    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


class _AsyncMilvusManager:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def search(self, collection, query_vector, top_k=10, **kwargs):
        self.calls.append(
            {
                "collection": collection,
                "query_vector": query_vector,
                "top_k": top_k,
                "kwargs": kwargs,
            }
        )
        return self.rows[:top_k]


@pytest.mark.asyncio
async def test_vector_search_supports_async_milvus_manager_contract():
    milvus = _AsyncMilvusManager(
        [{"id": "chunk-1", "text": "revenue grew quickly", "distance": 0.12}]
    )
    retriever = MultiRetriever(milvus, _Embedder(), collection_name="financial_chunks")

    results = await retriever.retrieve("revenue", top_k=1, mode="vector")

    assert results[0].id == "chunk-1"
    assert results[0].content == "revenue grew quickly"
    assert results[0].source == "vector"
    assert milvus.calls[0]["collection"] == "financial_chunks"


@pytest.mark.asyncio
async def test_hybrid_search_returns_empty_list_when_all_branches_are_empty():
    retriever = MultiRetriever(
        _AsyncMilvusManager([]),
        _Embedder(),
        collection_name="financial_chunks",
    )

    assert await retriever.retrieve("missing", top_k=3, mode="hybrid") == []
