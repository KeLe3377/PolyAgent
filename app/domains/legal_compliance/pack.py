# -*- coding: utf-8 -*-
"""legal_compliance domain pack: contract clause review over CUAD-style corpora."""

from __future__ import annotations

from app.core.tools.base import BaseTool
from app.core.tools.builtin.contract_clause_locator import ContractClauseLocatorTool
from app.core.tools.builtin.rag_search import RagSearchTool
from app.domains.base import (
    CorpusDoc,
    DeliberationSpec,
    DomainContext,
    DomainPack,
    EvalDataset,
    IntentHints,
)

VERSION = "0.1.0"

LEGAL_SYSTEM_PROMPT = """你是一名企业合同与合规知识助手。

工作方式:
1. 面对合同条款、义务、限制、终止、转让、管辖法等问题,优先调用 rag_search 检索合同知识库。
2. 当问题指明具体合同或条款类别时,再调用 contract_clause_locator,在候选片段中按
   contract_name / clause_type 精确过滤,得到 matched_clauses,避免不同合同互相干扰。
3. 只基于检索/过滤片段回答,指出相关条款或说明未检索到证据。
4. 不提供正式法律意见;需要律师判断时明确提示。
5. 回答应包含:结论、依据片段摘要、风险/注意事项。
"""


class LegalCompliancePack:
    """Contract review domain using platform RAG."""

    name = "legal_compliance"
    version = VERSION
    default_mode = "react"
    system_prompt = LEGAL_SYSTEM_PROMPT

    def corpus_docs(self) -> list[CorpusDoc]:
        return []

    def tools(self, ctx: DomainContext) -> list[BaseTool]:
        return [
            RagSearchTool(
                retriever=ctx.retriever,
                description="在合同与合规知识库中检索相关条款片段。",
                domain_filter=self.name,
            ),
            # RAG 质量升级:CUAD 长合同按 contract_name / clause_type 精确定位,
            # 避免法律域内部不同合同/条款互相干扰。
            ContractClauseLocatorTool(),
        ]

    def deliberation_spec(self) -> DeliberationSpec | None:
        return None

    def eval_dataset(self) -> EvalDataset | None:
        return None

    def intent_hints(self) -> IntentHints | None:
        return IntentHints(intent_overrides={"知识问答": "react", "搜索": "react"})


PACK: DomainPack = LegalCompliancePack()

__all__ = ["LegalCompliancePack", "ContractClauseLocatorTool", "PACK"]
