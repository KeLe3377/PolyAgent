import pytest

from app.core.tools.builtin.rag_search import RagSearchTool


class _Retriever:
    async def retrieve(self, query, top_k=10, mode="hybrid", **kwargs):
        self.query = query
        self.kwargs = kwargs
        return [
            type(
                "Result",
                (),
                {
                    "id": "chunk-1",
                    "content": "Revenue increased because recurring subscriptions expanded.",
                    "score": 0.7,
                    "metadata": {
                        "domain": "financial",
                        "dataset": "tatqa",
                        "doc_id": "doc-1",
                        "chunk_type": "cell_fact",
                        "source": "TAT-QA",
                    },
                    "source": "hybrid",
                },
            )()
        ]


@pytest.mark.asyncio
async def test_rag_search_tool_wraps_retriever_results_in_plain_payload():
    retriever = _Retriever()
    tool = RagSearchTool(retriever, default_top_k=5, domain_filter="financial", dataset_filter="tatqa")

    payload = await tool.execute(query="revenue")

    assert "RETRIEVED_EVIDENCE_INDEX:" in payload
    assert "ANSWER_SYNTHESIS_RULES:" in payload
    assert "Revenue increased" in payload
    assert "doc_id=doc-1" in payload
    assert "source=TAT-QA" in payload
    assert "dataset=tatqa" in payload
    assert "chunk_type=cell_fact" in payload
    assert retriever.query.domain == "financial"
    assert retriever.query.dataset == "tatqa"


@pytest.mark.asyncio
async def test_rag_search_tool_builds_structured_filters_for_cuad_query():
    retriever = _Retriever()
    tool = RagSearchTool(retriever, default_top_k=5, domain_filter="legal_compliance")

    await tool.execute(
        query=(
            "In contract ADAMSGOLFINC_03_21_2005-EX-10.17-ENDORSEMENT AGREEMENT, "
            'identify the parties related to "Parties".'
        )
    )

    assert retriever.query.domain == "legal_compliance"
    assert retriever.query.dataset == "cuad"
    assert retriever.query.top_n >= 120
    assert "ADAMSGOLFINC" in retriever.query.filters["contract_name"]
    assert retriever.query.filters["clause_type"] == "Parties"
    assert retriever.query.filters["chunk_type"] == ["contract_clause"]
