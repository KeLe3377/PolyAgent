# -*- coding: utf-8 -*-
"""
领域 Skill 运行时适配契约(DomainPack Protocol)。

设计原则(对齐 agent-to-skill-converter 三分类):
  - 判断逻辑 → system_prompt(进 prompt)
  - 确定性操作 → tools(进工具)
  - 领域事实 → corpus_docs(进语料)

平台对领域「无知」:编排器只认本文件定义的数据结构(DomainPack / DeliberationSpec
等),不 import 任何具体领域的概念。加新领域 = 新建 ``skills/<domain>/SKILL.md``,
由 registry 解析并适配成本协议,不改平台/编排器代码。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.core.tools.base import BaseTool


# ---------------------------------------------------------------------------
# 语料与上下文
# ---------------------------------------------------------------------------
@dataclass
class CorpusDoc:
    """领域语料的一条文档(供 ETL 分块入库 + 评测召回)。

    与具体向量库解耦:灌库脚本(app/etl 或 scripts/ingest_corpus)读取
    ``corpus_docs()`` 或直接读 ``corpus/*.md`` 文件,二者同源。
    """

    id: str
    text: str
    source: str = ""  # 原始文件名 / 来源标记
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DomainContext:
    """平台在运行时注入给领域 Skill 的共享服务上下文。

    由编排器(lifespan 装配后从 ``app.state`` 取)在调用 ``pack.tools(ctx)`` 时
    构造。领域 Skill 据此构建需要运行时依赖的工具(如 rag_search 需要 retriever),
    而不在 import 期硬连基础设施 —— 这保证了「加领域不改平台、不绑基础设施实例」。
    """

    retriever: Any | None = None  # MultiRetriever(向量+BM25+RRF)
    memory: Any | None = None  # MemoryManager
    llm: Any | None = None  # LLM callable,需实现 async acomplete(messages, **kw) -> str
    config: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 多视角审议配置(模式 3 的数据,由领域 Skill 定义、平台执行)
# ---------------------------------------------------------------------------
@dataclass
class ParticipantSpec:
    """一个审议参与者(立场)。

    立场内容完全由领域 Skill 决定:金融 Skill 填 bull/bear,别的领域填别的。
    平台执行逻辑对立场数量与内容无知,只认本结构。
    """

    role: str  # "bull" / "bear" / "risk_officer" / ... 立场标识
    stance_prompt: str  # 该立场的 system prompt 片段(判断原则 + 人设)
    temperature: float = 0.7  # 各立场可独立调温(多头可更发散,综合更收敛)


@dataclass
class DeliberationSpec:
    """多视角审议配置:谁参与、怎么综合。

    泛化自 MiroFish 多空辩论:把「bull + bear 两方」泛化为「N 个 ParticipantSpec」。
    用户可在请求里覆盖 participants / 数量(见 orchestrator 请求层)。
    """

    participants: list[ParticipantSpec]  # N 个,数量与立场由领域 Skill/用户给
    synthesis_prompt: str  # 综合各方观点的 system prompt
    synthesis_temperature: float = 0.5
    max_rounds: int = 1  # 预留多轮交锋;一期默认单轮(D1→D2→D3)
    shared_retrieve_top_k: int = 8  # D1 共享检索取多少 chunk 喂给所有 participant


# ---------------------------------------------------------------------------
# 意图路由提示与评测数据集
# ---------------------------------------------------------------------------
@dataclass
class IntentHints:
    """意图 → 模式 路由提示(可选)。

    模式选择优先级:请求显式 mode > intent_hints > 领域 Skill default_mode。
    intent_overrides 的 key 是意图标签(来自 app/core/intent/recognizer),
    value 是建议模式。
    """

    intent_overrides: dict[str, str] = field(default_factory=dict)
    # 例:{"deep_analysis": "deliberation", "qa": "react"}


@dataclass
class EvalCase:
    """评测黄金集的单条用例(供 app/core/eval 离线跑)。"""

    query: str
    reference_answer: str = ""  # 参考答复(可为空,仅做召回/延迟评测)
    expected_keywords: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalDataset:
    """领域评测黄金集。"""

    cases: list[EvalCase] = field(default_factory=list)
    metrics: list[str] = field(
        default_factory=lambda: ["faithfulness", "answer_relevancy", "recall_at_k", "latency_ms"]
    )


# ---------------------------------------------------------------------------
# 领域 Skill 适配协议
# ---------------------------------------------------------------------------
@runtime_checkable
class DomainPack(Protocol):
    """领域 Skill 适配后的运行时协议。

    DomainRegistry 启动时扫描 ``skills/<domain>/SKILL.md``,解析后生成实现本协议的
    adapter。保留 DomainPack 名称是为了不扰动编排器内部类型边界。
    """

    name: str  # "financial" / "kb_qa" —— 唯一标识,请求带 domain=用它
    version: str
    default_mode: str  # "react" / "plan_execute" / "deliberation"
    system_prompt: str  # ① 判断原则 + 人设(三分类:判断逻辑)

    def corpus_docs(self) -> list[CorpusDoc]:  # ② 领域事实语料
        ...

    def tools(self, ctx: DomainContext) -> list[BaseTool]:  # ③ 确定性工具(按运行时依赖构建)
        ...

    def deliberation_spec(self) -> DeliberationSpec | None:  # ④ 可选:多视角审议配置
        ...

    def eval_dataset(self) -> EvalDataset | None:  # ⑤ 可选:评测黄金集
        ...

    def intent_hints(self) -> IntentHints | None:  # ⑥ 可选:意图→模式 路由提示
        ...


__all__ = [
    "CorpusDoc",
    "DomainContext",
    "ParticipantSpec",
    "DeliberationSpec",
    "IntentHints",
    "EvalCase",
    "EvalDataset",
    "DomainPack",
]
