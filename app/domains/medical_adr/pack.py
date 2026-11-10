# -*- coding: utf-8 -*-
"""medical_adr domain pack: adverse drug reaction lookup over SPL-ADR labels."""

from __future__ import annotations

from app.core.tools.base import BaseTool
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

MEDICAL_ADR_SYSTEM_PROMPT = """你是一名药品说明书不良反应知识助手。

工作方式:
1. 面对药物不良反应、ADR、adverse reaction 等问题,优先调用 rag_search 检索 SPL-ADR 标签语料。
2. rag_search 会返回 RETRIEVED_EVIDENCE_INDEX;你必须优先使用 key_facts,并基于 evidence_items 与 answer_directives 组织回答。
3. 不要只机械罗列片段;应先给结论,再按证据来源归纳不良反应/风险信号,并引用 doc_id。
4. 区分明确标注的不良反应、boxed warning、warnings and precautions 等不同证据层级。
5. 不要编造药品说明书中没有的反应。
6. 这不是医疗诊断或用药建议;涉及治疗决策时提示咨询医生或药师。
"""


class MedicalAdrPack:
    """Adverse drug reaction lookup domain using platform RAG."""

    name = "medical_adr"
    version = VERSION
    default_mode = "react"
    system_prompt = MEDICAL_ADR_SYSTEM_PROMPT

    def corpus_docs(self) -> list[CorpusDoc]:
        return []

    def tools(self, ctx: DomainContext) -> list[BaseTool]:
        return [
            RagSearchTool(
                retriever=ctx.retriever,
                description="在 SPL-ADR 药品说明书语料中检索指定药物的不良反应标注。",
                domain_filter=self.name,
                dataset_filter="spl_adr",
            )
        ]

    def deliberation_spec(self) -> DeliberationSpec | None:
        return None

    def eval_dataset(self) -> EvalDataset | None:
        return None

    def intent_hints(self) -> IntentHints | None:
        return IntentHints(intent_overrides={"知识问答": "react", "搜索": "react"})


PACK: DomainPack = MedicalAdrPack()

__all__ = ["MedicalAdrPack", "PACK"]
