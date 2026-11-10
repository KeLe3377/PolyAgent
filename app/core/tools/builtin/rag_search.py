# -*- coding: utf-8 -*-
"""
共享 RAG 检索工具:封装平台 ``MultiRetriever``(向量 + BM25 + RRF 混合检索)。

各领域包在自己的 ``tools(ctx)`` 里实例化它、绑定 ``ctx.retriever`` 与领域化描述,
从而复用同一检索实现而呈现各自的知识库语义。retriever 为空时返回友好提示而非抛错,
保证工具/领域包可独立 import 与单测。
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.rag.evidence import EvidenceBuilder
from app.core.rag.query_analyzer import QueryAnalyzer
from app.core.rag.types import RetrievalRequest
from app.core.tools.base import BaseTool, ToolParameter

logger = logging.getLogger(__name__)


class RagSearchTool(BaseTool):
    """知识库混合检索工具。"""

    name = "rag_search"

    def __init__(
        self,
        retriever: Any | None = None,
        default_top_k: int = 5,
        description: str | None = None,
        domain_filter: str | None = None,
        dataset_filter: str | None = None,
        default_filters: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._retriever = retriever
        self.default_top_k = default_top_k
        self.domain_filter = domain_filter
self.dataset_filter = dataset_filter
        self.default_filters = default_filters or {}
        self._query_analyzer = QueryAnalyzer(default_domain=domain_filter or "financial")
        self._evidence_builder = EvidenceBuilder()
        self.description = description or "在知识库中检索与问题相关的片段(向量+BM25+RRF 混合)。"
        self.parameters = [
            ToolParameter(name="query", type="string", description="检索查询", required=True),
            ToolParameter(name="top_k", type="integer", description="返回条数(可选)", required=False),
        ]

    async def execute(self, **kwargs: Any) -> str:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return "错误:缺少 query 参数。"
        if self._retriever is None:
            return "检索不可用:向量库未就绪(基础设施未通电)。"

        top_k = int(kwargs.get("top_k") or self.default_top_k)
        filters = dict(self.default_filters)
        plan = self._query_analyzer.analyze(query, domain_hint=self.domain_filter)
        filters.update(plan.filters)
        if plan.preferred_chunk_types and "chunk_type" not in filters:
            filters["chunk_type"] = plan.preferred_chunk_types

        dataset = self.dataset_filter or plan.dataset
        has_structured_filters = bool(plan.filters or plan.preferred_chunk_types)
        top_n = max(top_k, 120) if has_structured_filters else None
        request = RetrievalRequest(
            query=query,
            domain=self.domain_filter or plan.domain,
            dataset=dataset,
            filters=filters,
            mode="hybrid",
            top_n=top_n or max(top_k, 50),
            top_k=top_k,
            rerank=plan.needs_rerank,
        )
        try:
            results = await self._retriever.retrieve(
                request,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("rag_search 检索失败")
            return f"检索失败: {e}"

        if self.domain_filter:
            results = [
                result
                for result in results
                if str(result.metadata.get("domain") or "") == self.domain_filter
            ][:top_k]

        if not results:
            return "未检索到相关片段。"

        evidence_pack = self._evidence_builder.build(plan, results)
        lines = [
            "RETRIEVED_EVIDENCE_INDEX:",
            evidence_pack.to_json(),
            "RETRIEVED_CHUNKS:",
        ]
        for i, r in enumerate(results, 1):
            metadata = getattr(r, "metadata", {}) or {}
            doc_id = metadata.get("doc_id") or getattr(r, "id", "")
            source = metadata.get("source") or getattr(r, "source", "")
            dataset = metadata.get("dataset") or ""
            chunk_type = metadata.get("chunk_type") or ""
            lines.append(
                "[{idx}] (score={score:.4f}, doc_id={doc_id}, source={source}, "
                "dataset={dataset}, chunk_type={chunk_type})\n{content}".format(
                    idx=i,
                    score=float(getattr(r, "score", 0.0)),
                    doc_id=doc_id,
                    source=source,
                    dataset=dataset,
                    chunk_type=chunk_type,
                    content=getattr(r, "content", ""),
                )
            )
        lines.extend(
            [
            (
                "ANSWER_SYNTHESIS_RULES:\n"
                "- Use RETRIEVED_EVIDENCE_INDEX.evidence_items as the factual grounding.\n"
                "- Prioritize RETRIEVED_EVIDENCE_INDEX.key_facts when answering extraction-style questions.\n"
                "- Explain and analyze the evidence; do not merely paste a flat list.\n"
                "- Include cited doc_id values for concrete claims.\n"
                "- If coverage.missing_filters is non-empty, state the evidence gap."
            ),
            ]
        )
        return "\n\n".join(lines)


__all__ = ["RagSearchTool"]
