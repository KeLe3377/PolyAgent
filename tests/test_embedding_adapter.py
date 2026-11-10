import pytest

from app.infrastructure.llm.embedding import OpenAIEmbeddingAdapter


class _EmbeddingData:
    def __init__(self, embedding):
        self.embedding = embedding


class _EmbeddingResponse:
    def __init__(self, embeddings):
        self.data = [_EmbeddingData(item) for item in embeddings]


class _EmbeddingsClient:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _EmbeddingResponse([[0.1, 0.2], [0.3, 0.4]])


class _Client:
    def __init__(self):
        self.embeddings = _EmbeddingsClient()


@pytest.mark.asyncio
async def test_embed_texts_calls_openai_compatible_embeddings_api():
    client = _Client()
    adapter = OpenAIEmbeddingAdapter(
        api_key="test-key",
        base_url="https://embed.example/v1",
        model="embed-model",
        client=client,
    )

    vectors = await adapter.embed_texts(["alpha", "beta"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert client.embeddings.calls == [{"model": "embed-model", "input": ["alpha", "beta"]}]


def test_embed_query_uses_single_text_batch():
    client = _Client()
    adapter = OpenAIEmbeddingAdapter(
        api_key="test-key",
        base_url=None,
        model="embed-model",
        client=client,
    )

    assert adapter.embed_query("alpha") == [0.1, 0.2]
