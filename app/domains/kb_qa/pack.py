# -*- coding: utf-8 -*-
"""
kb_qa 领域包(轻量对照包)。

证明 PolyAgent 既能扛重流程(financial 多视角审议),也能装轻流程(单轮 RAG 问答)。
语料运行时通过 ETL / document 路由入库(本包不带静态 corpus);默认 ReAct 模式。
无多视角审议配置(deliberation_spec 返回 None),意图路由也不覆盖。
"""

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

KB_QA_SYSTEM_PROMPT = """你是一名通用知识问答助手。

工作方式:
1. 收到事实性问题时,优先调用 rag_search 检索知识库,依据检索到的片段作答。
2. 严格依据检索内容回答;未检索到相关内容时,诚实说明「知识库中暂无相关数据」,不编造。
3. 回答简洁、结构清晰,必要时引用出处片段。
"""


class KbQaPack:
    """kb_qa 领域包(轻量:ReAct + RAG)。"""

    name = "kb_qa"
    version = VERSION
    default_mode = "react"
    system_prompt = KB_QA_SYSTEM_PROMPT

    def corpus_docs(self) -> list[CorpusDoc]:
        # 无静态语料:通用文档运行时经 ETL / document 路由入库。
        return []

    def tools(self, ctx: DomainContext) -> list[BaseTool]:
        return [
            RagSearchTool(
                retriever=ctx.retriever,
                description="在通用知识库中检索与问题相关的片段。",
                domain_filter=self.name,
            )
        ]

    def deliberation_spec(self) -> DeliberationSpec | None:
        return None  # 轻量包不启用多视角审议

    def eval_dataset(self) -> EvalDataset | None:
        return None  # 通用问答集后续按实际入库文档自建

    def intent_hints(self) -> IntentHints | None:
        return None


PACK: DomainPack = KbQaPack()

__all__ = ["KbQaPack", "PACK"]
