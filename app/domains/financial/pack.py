# -*- coding: utf-8 -*-
"""
financial 领域包(旗舰)。

语料:来自用户自己的 MiroFish-FinSight knowledge/(6 篇财报/指标/投资分析)。
旗舰模式:多视角审议(bull + bear 并行评议 → synthesis 综合),泛化自 MiroFish 多空辩论。
工具:rag_search 一个(封装平台 MultiRetriever 混合检索)。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.tools.base import BaseTool
from app.core.tools.builtin.rag_search import RagSearchTool
from app.core.tools.builtin.table_calculator import TableCalculatorTool
from app.domains.base import (
    CorpusDoc,
    DeliberationSpec,
    DomainContext,
    DomainPack,
    EvalCase,
    EvalDataset,
    IntentHints,
    ParticipantSpec,
)
from app.domains.financial import prompts as P

logger = logging.getLogger(__name__)

_PACK_DIR = Path(__file__).resolve().parent
_CORPUS_DIR = _PACK_DIR / "corpus"
_EVAL_CASES = _PACK_DIR / "eval_cases.json"

VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# FinancialPack
# ---------------------------------------------------------------------------
class FinancialPack:
    """financial 领域包(旗舰)。"""

    name = "financial"
    version = VERSION
    default_mode = "deliberation"
    system_prompt = P.FINANCIAL_SYSTEM_PROMPT

    # ② 领域事实语料
    def corpus_docs(self) -> list[CorpusDoc]:
        docs: list[CorpusDoc] = []
        if not _CORPUS_DIR.is_dir():
            logger.warning("financial corpus 目录不存在: %s", _CORPUS_DIR)
            return docs
        for path in sorted(_CORPUS_DIR.glob("*.md")):
            docs.append(
                CorpusDoc(
                    id=path.stem,
                    text=path.read_text(encoding="utf-8"),
                    source=str(path.relative_to(_PACK_DIR)),
                    metadata={"domain": self.name, "file": path.name},
                )
            )
        return docs

    # ③ 确定性工具(按运行时依赖构建)
    def tools(self, ctx: DomainContext) -> list[BaseTool]:
        return [
            RagSearchTool(
                retriever=ctx.retriever,
                description="在金融知识库(财报、财务指标、投资分析)中检索与问题相关的片段。",
                domain_filter=self.name,
            ),
            # RAG 质量升级:TAT-QA 表格数值推理退化为确定性计算,避免 LLM 直接算错。
            TableCalculatorTool(),
        ]

    # ④ 多视角审议配置(旗舰)
    def deliberation_spec(self) -> DeliberationSpec:
        return DeliberationSpec(
            participants=[
                ParticipantSpec(role="bull", stance_prompt=P.BULL_STANCE_PROMPT, temperature=0.7),
                ParticipantSpec(role="bear", stance_prompt=P.BEAR_STANCE_PROMPT, temperature=0.7),
            ],
            synthesis_prompt=P.SYNTHESIS_PROMPT,
            synthesis_temperature=0.5,
            max_rounds=1,
            shared_retrieve_top_k=8,
        )

    # ⑤ 评测黄金集
    def eval_dataset(self) -> EvalDataset | None:
        if not _EVAL_CASES.is_file():
            return None
        try:
            raw = json.loads(_EVAL_CASES.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.warning("读取 eval_cases.json 失败: %s", e)
            return None
        cases = [
            EvalCase(
                query=str(it.get("query", "")),
                reference_answer=str(it.get("reference_answer", "")),
                expected_keywords=list(it.get("expected_keywords", [])),
                metadata=dict(it.get("metadata", {})),
            )
            for it in raw
            if it.get("query")
        ]
        return EvalDataset(cases=cases)

    # ⑥ 意图 → 模式 路由提示
    def intent_hints(self) -> IntentHints:
        # 键对齐 app.core.intent.recognizer 产出的标签(root/sub)。
        # 事实类问答/搜索 → ReAct+RAG;其余(含深度分析)走默认的 deliberation。
        return IntentHints(
            intent_overrides={
                "知识问答": "react",
                "搜索": "react",
                "计算": "react",
            }
        )


PACK: DomainPack = FinancialPack()

__all__ = ["FinancialPack", "RagSearchTool", "TableCalculatorTool", "PACK"]
