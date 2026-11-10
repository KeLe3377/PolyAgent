# -*- coding: utf-8 -*-
"""ContractClauseLocatorTool 确定性契约测试(RAG 质量升级 2026-08-11)。"""

from __future__ import annotations

import json

import pytest

from app.core.tools.builtin.contract_clause_locator import ContractClauseLocatorTool


@pytest.fixture()
def tool() -> ContractClauseLocatorTool:
    return ContractClauseLocatorTool()


CANDIDATES = [
    {
        "metadata": {
            "doc_id": "cuad_0001_ACME",
            "contract_name": "ACME-EX-10-DISTRIBUTOR AGREEMENT",
            "clause_type": "Parties",
            "chunk_type": "contract_clause",
        },
        "text": "This agreement is between ACME Inc. and Beta Corp.",
    },
    {
        "metadata": {
            "doc_id": "cuad_0002_OTHER",
            "contract_name": "OTHER-EX-1-SUPPLY AGREEMENT",
            "clause_type": "Parties",
            "chunk_type": "contract_clause",
        },
        "text": "Between Other Co. and Gamma Ltd.",
    },
    {
        "metadata": {
            "doc_id": "cuad_0001_ACME",
            "contract_name": "ACME-EX-10-DISTRIBUTOR AGREEMENT",
            "clause_type": "Governing Law",
            "chunk_type": "contract_clause",
        },
        "text": "Governed by the laws of Delaware.",
    },
]


@pytest.mark.asyncio
async def test_filter_by_contract_and_clause(tool: ContractClauseLocatorTool) -> None:
    out = json.loads(
        await tool.execute(
            candidates=json.dumps(CANDIDATES),
            contract_name="ACME-EX-10-DISTRIBUTOR AGREEMENT",
            clause_type="Parties",
        )
    )
    assert out["ok"] is True
    assert out["matched_count"] == 1
    clause = out["matched_clauses"][0]
    assert clause["contract_name"] == "ACME-EX-10-DISTRIBUTOR AGREEMENT"
    assert clause["clause_type"] == "Parties"
    assert "ACME Inc." in clause["text"]


@pytest.mark.asyncio
async def test_filter_by_clause_only_across_contracts(tool: ContractClauseLocatorTool) -> None:
    out = json.loads(
        await tool.execute(candidates=json.dumps(CANDIDATES), clause_type="Parties")
    )
    assert out["matched_count"] == 2


@pytest.mark.asyncio
async def test_filter_returns_empty_when_no_match(tool: ContractClauseLocatorTool) -> None:
    out = json.loads(
        await tool.execute(candidates=json.dumps(CANDIDATES), clause_type="Nonexistent")
    )
    assert out["matched_count"] == 0
    assert out["matched_clauses"] == []


@pytest.mark.asyncio
async def test_parses_rag_search_text_output(tool: ContractClauseLocatorTool) -> None:
    # 模拟 RagSearchTool 的纯文本 observation(带 doc_id/source 头)
    text = (
        "[1] (score=0.12, doc_id=cuad_0001_ACME, source=CUAD)\n"
        "Governed by the laws of Delaware."
    )
    out = json.loads(await tool.execute(candidates=text))
    assert out["ok"] is True
    assert out["matched_count"] == 1
    assert out["matched_clauses"][0]["doc_id"] == "cuad_0001_ACME"


@pytest.mark.asyncio
async def test_top_n_limits_results(tool: ContractClauseLocatorTool) -> None:
    out = json.loads(
        await tool.execute(candidates=json.dumps(CANDIDATES), clause_type="Parties", top_n=1)
    )
    assert out["matched_count"] == 1


@pytest.mark.asyncio
async def test_empty_candidates_returns_clean_empty(tool: ContractClauseLocatorTool) -> None:
    out = json.loads(await tool.execute(candidates="", clause_type="Parties"))
    assert out["ok"] is True
    assert out["matched_count"] == 0
