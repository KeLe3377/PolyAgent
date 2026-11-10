# -*- coding: utf-8 -*-
"""QueryAnalyzer —— 把自然语言问题解析为结构化 ``QueryPlan``。

RAG 质量升级(2026-08-11)的领域侧入口:在检索之前理解问题,产出
``QueryPlan``,供 MetadataRouter / MultiRetriever / 领域工具使用。

设计取舍:
- **规则优先,零模型成本**。TAT-QA/CUAD/SPL-ADR 的典型问题有强结构特征
  (年份、合同标题、药品名、数值运算词),正则 + 关键词即可稳定抽取,且
  可离线单测、不依赖 provider 余额。LLM 增强可后置为 ``llm`` 可选参数。
- **不绑基础设施**:本模块只做纯文本 → dataclass,不 import retriever/llm
  实例,保证可独立 import 与单测。
- **领域无关**:不硬编码金融概念;``domain`` 由调用方给提示或从 query 启发式推断。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# QueryPlan 契约(与 docs/superpowers/specs/2026-08-11-rag-quality-upgrade-plan.md 第 3 节对齐)
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class QueryPlan:
    """结构化查询计划。"""

    domain: str
    dataset: str | None = None
    intent: str = "rag_qa"
    entities: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)
    preferred_chunk_types: list[str] = field(default_factory=list)
    needs_rerank: bool = True
    needs_calculation: bool = False


# ---------------------------------------------------------------------------
# 词典(保守,避免假阳性)
# ---------------------------------------------------------------------------
_CALC_VERBS = re.compile(
    r"\b(sum|total|totals|add|added|subtract|difference|ratio|percentage|"
    r"percent|growth|decline|increase|decrease|average|count|how many|"
    r"how much|net|gross|change|compared to|vs\.?|versus)\b",
    re.IGNORECASE,
)

_YEAR = re.compile(r"\b(19|20)\d{2}\b")
# CUAD 转换后的问题形如:"In contract <title>, ..."
_CUAD_CONTRACT = re.compile(r"\bin contract\s+(.+?),\s", re.IGNORECASE)
# SPL-ADR:"... for <drug>?" / "<drug> label" / "adverse ... for <drug>"
_DRUG_FOR = re.compile(r"\b(?:for|on)\s+([A-Za-z][A-Za-z0-9\-]{2,40})\s*\?", re.IGNORECASE)
# CUAD clause_type:问题里引号包裹的类别,或常见 CUAD 类别名
_CUAD_CATEGORY = re.compile(r'related to\s+"([^"]+)"', re.IGNORECASE)
_CUAD_CATEGORY_KEYWORDS = [
    "parties", "agreement date", "effective date", "expiration date",
    "renewal", "termination", "governing law", "jurisdiction", "assignment",
    "indemnification", "liability", "warranty", "audit", "confidentiality",
    "license", "payment", "pricing", "notices", "amendment",
]
# TAT-QA:常见金融行/列指标词
_FINANCIAL_METRIC = re.compile(
    r"\b(revenue|loss|income|profit|expense|asset|liabilit|cash|equity|"
    r"operating|fixed price|cost|margin|sales|earnings|dividend|"
    r"carryforward|deferred|tax|interest|depreciation|amortization)\w*",
    re.IGNORECASE,
)
_SCALE = re.compile(r"\b(thousands?|millions?|billions?|in (?:thousands|millions|billions))\b", re.IGNORECASE)


def _coerce_year(token: str) -> str:
    return token.strip()


def _looks_like_tatqa(query: str, entities: dict[str, Any]) -> bool:
    """TAT-QA 启发式:有年份或金融指标,且不是合同/药品问题。"""
    return bool(entities.get("years")) or bool(entities.get("metric")) or bool(entities.get("scale"))


def _looks_like_cuad(query: str, entities: dict[str, Any]) -> bool:
    return bool(entities.get("contract_name")) or bool(entities.get("clause_type"))


def _looks_like_spl_adr(query: str, entities: dict[str, Any]) -> bool:
    return bool(entities.get("drug_name")) or bool(re.search(r"\badverse (drug )?reaction", query, re.IGNORECASE))


class QueryAnalyzer:
    """规则驱动的查询分析器。

    用法::

        plan = QueryAnalyzer().analyze("What is the operating loss in 2019?")
        plan.domain          # "financial"
        plan.needs_calculation  # depends on verbs
        plan.entities["years"]  # ["2019"]
    """

    def __init__(self, default_domain: str = "financial") -> None:
        self.default_domain = default_domain

    # -- 公共入口 ----------------------------------------------------------
    def analyze(self, query: str, domain_hint: str | None = None) -> QueryPlan:
        """解析单个问题。``domain_hint`` 由调用方(领域包/路由层)提供时优先。"""
        q = (query or "").strip()
        entities = self._extract_entities(q)

        domain = self._infer_domain(q, entities, domain_hint)
        dataset = self._infer_dataset(domain, entities)

        filters: dict[str, Any] = {}
        preferred: list[str] = []
        needs_calc = bool(_CALC_VERBS.search(q)) or bool(entities.get("scale"))

        if dataset == "tatqa":
            if entities.get("years"):
                filters["year"] = entities["years"][0]
            preferred = ["cell_fact", "row_fact", "table_doc"]
        elif dataset == "cuad":
            if entities.get("contract_name"):
                filters["contract_name"] = entities["contract_name"]
            if entities.get("clause_type"):
                filters["clause_type"] = entities["clause_type"]
            preferred = ["contract_clause"]
        elif dataset == "spl_adr":
            if entities.get("drug_name"):
                filters["drug_name"] = entities["drug_name"]
            preferred = ["spl_label", "section", "text"]

        return QueryPlan(
            domain=domain,
            dataset=dataset,
            intent="calculation_qa" if needs_calc else "rag_qa",
            entities=entities,
            filters=filters,
            preferred_chunk_types=preferred,
            needs_rerank=True,
            needs_calculation=needs_calc,
        )

    # -- 实体抽取 ----------------------------------------------------------
    def _extract_entities(self, q: str) -> dict[str, Any]:
        out: dict[str, Any] = {}

        year_matches = list(_YEAR.finditer(q))
        if year_matches:
            out["years"] = [m.group(0) for m in year_matches]

        metric = _FINANCIAL_METRIC.search(q)
        if metric:
            out["metric"] = metric.group(0).lower()

        scale = _SCALE.search(q)
        if scale:
            out["scale"] = scale.group(0).lower()

        contract = _CUAD_CONTRACT.search(q)
        if contract:
            out["contract_name"] = contract.group(1).strip().rstrip(".")

        clause = _CUAD_CATEGORY.search(q)
        if clause:
            out["clause_type"] = clause.group(1).strip()
        else:
            low = q.lower()
            for cat in _CUAD_CATEGORY_KEYWORDS:
                if cat in low:
                    out["clause_type"] = cat.title()
                    break

        drug = _DRUG_FOR.search(q)
        if drug:
            out["drug_name"] = drug.group(1).strip()

        return out

    # -- 领域 / 数据集推断 --------------------------------------------------
    def _infer_domain(
        self, q: str, entities: dict[str, Any], domain_hint: str | None
    ) -> str:
        if domain_hint:
            return domain_hint
        if _looks_like_cuad(q, entities):
            return "legal_compliance"
        if _looks_like_spl_adr(q, entities):
            return "medical_adr"
        if _looks_like_tatqa(q, entities):
            return "financial"
        return self.default_domain

    def _infer_dataset(self, domain: str, entities: dict[str, Any]) -> str | None:
        if domain == "financial":
            return "tatqa" if (_looks_like_tatqa("", entities)) else None
        if domain == "legal_compliance":
            return "cuad"
        if domain == "medical_adr":
            return "spl_adr"
        return None


__all__ = ["QueryPlan", "QueryAnalyzer"]
