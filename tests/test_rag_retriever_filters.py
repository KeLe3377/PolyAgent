import pytest

from app.core.rag.retriever import MultiRetriever


class _Embedding:
    def embed_query(self, text):
        return [0.1, 0.2]


class _Milvus:
    async def search(self, collection, vector, top_k=10, **kwargs):
        self.last_kwargs = kwargs
        return [
            {
                "id": "a",
                "text": "target financial table fact",
                "metadata": '{"domain":"financial","dataset":"tatqa","doc_id":"doc-a","chunk_type":"cell_fact","year":"2019"}',
                "domain": "financial",
                "source": "TAT-QA",
                "distance": 0.1,
            },
            {
                "id": "b",
                "text": "other legal clause",
                "metadata": '{"domain":"legal_compliance","dataset":"cuad","doc_id":"doc-b","chunk_type":"contract_clause"}',
                "domain": "legal_compliance",
                "source": "CUAD",
                "distance": 0.2,
            },
        ][:top_k]


@pytest.mark.asyncio
async def test_retriever_filters_vector_results_by_metadata():
    milvus = _Milvus()
    retriever = MultiRetriever(milvus, _Embedding())

    results = await retriever.retrieve(
        "operating loss 2019",
        mode="vector",
        domain="financial",
        dataset="tatqa",
        filters={"chunk_type": "cell_fact", "year": "2019"},
        top_k=5,
        rerank=False,
    )

    assert [r.id for r in results] == ["a"]
    assert results[0].metadata["doc_id"] == "doc-a"
    assert "expr" in milvus.last_kwargs
    assert "domain" in milvus.last_kwargs["expr"]
    assert "dataset" in milvus.last_kwargs["expr"]
    assert "chunk_type" in milvus.last_kwargs["expr"]


@pytest.mark.asyncio
async def test_retriever_promotes_contract_filters_to_milvus_expr():
    milvus = _Milvus()
    retriever = MultiRetriever(milvus, _Embedding())

    await retriever.retrieve(
        "contract parties",
        mode="vector",
        domain="legal_compliance",
        dataset="cuad",
        filters={
            "contract_name": "ADAMSGOLFINC_03_21_2005-EX-10.17-ENDORSEMENT AGREEMENT",
            "clause_type": "Parties",
            "chunk_type": "contract_clause",
        },
        top_k=5,
        rerank=False,
    )

    expr = milvus.last_kwargs["expr"]
    assert "contract_name" in expr
    assert "chunk_type" in expr
    assert "clause_type" not in expr


@pytest.mark.asyncio
async def test_retriever_promotes_drug_name_to_milvus_expr():
    milvus = _Milvus()
    retriever = MultiRetriever(milvus, _Embedding())

    await retriever.retrieve(
        "adverse drug reactions actemra",
        mode="vector",
        domain="medical_adr",
        dataset="spl_adr",
        filters={"drug_name": "actemra", "chunk_type": "spl_label"},
        top_k=5,
        rerank=False,
    )

    expr = milvus.last_kwargs["expr"]
    assert "drug_name" in expr
    assert "actemra" in expr


@pytest.mark.asyncio
async def test_retriever_filters_keyword_results_by_metadata():
    retriever = MultiRetriever(_Milvus(), _Embedding())
    retriever.register_keyword_documents(
        {"a": "operating loss carryforward 2019", "b": "operating loss legal"},
        {
            "a": {"domain": "financial", "dataset": "tatqa", "year": "2019"},
            "b": {"domain": "legal_compliance", "dataset": "cuad"},
        },
    )

    results = await retriever.retrieve(
        "operating loss",
        mode="keyword",
        domain="financial",
        dataset="tatqa",
        filters={"year": "2019"},
        top_k=5,
        rerank=False,
    )

    assert [r.id for r in results] == ["a"]
