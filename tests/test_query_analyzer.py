# -*- coding: utf-8 -*-
"""QueryAnalyzer 离线契约测试(RAG 质量升级 2026-08-11)。

覆盖典型 TAT-QA / CUAD / SPL-ADR 问题到 QueryPlan 的抽取,零模型成本。
"""

from __future__ import annotations

import pytest

from app.core.rag.query_analyzer import QueryAnalyzer, QueryPlan


@pytest.fixture()
def analyzer() -> QueryAnalyzer:
    return QueryAnalyzer()


def test_tatqa_extracts_year_metric_and_chunk_prefs(analyzer: QueryAnalyzer) -> None:
    plan = analyzer.analyze("What is the operating loss carryforward for 2019?")

    assert plan.domain == "financial"
    assert plan.dataset == "tatqa"
    assert plan.entities["years"] == ["2019"]
    assert "operating" in plan.entities["metric"]
    # 纯查表(lookup)不算计算推理
    assert plan.needs_calculation is False
    assert plan.filters["year"] == "2019"
    assert plan.preferred_chunk_types[0] == "cell_fact"


def test_tatqa_ratio_question_marks_calculation(analyzer: QueryAnalyzer) -> None:
    plan = analyzer.analyze("What is the ratio of revenue in 2019 to 2018?")

    assert plan.dataset == "tatqa"
    assert plan.entities["years"] == ["2019", "2018"]
    assert plan.needs_calculation is True


def test_cuad_extracts_contract_and_clause(analyzer: QueryAnalyzer) -> None:
    plan = analyzer.analyze(
        "In contract ADAMSGOLFINC_03_21_2005-EX-10.17-ENDORSEMENT AGREEMENT, "
        'identify the parties related to "Parties".'
    )

    assert plan.domain == "legal_compliance"
    assert plan.dataset == "cuad"
    assert "ADAMSGOLFINC" in plan.entities["contract_name"]
    assert plan.entities["clause_type"].lower() == "parties"
    assert plan.filters["clause_type"].lower() == "parties"
    assert plan.preferred_chunk_types == ["contract_clause"]


def test_cuad_clause_from_keyword(analyzer: QueryAnalyzer) -> None:
    plan = analyzer.analyze("In contract ACME-EX-1, what governs termination?")

    assert plan.domain == "legal_compliance"
    assert plan.entities["clause_type"].lower() == "termination"


def test_spl_adr_extracts_drug(analyzer: QueryAnalyzer) -> None:
    plan = analyzer.analyze("What adverse drug reactions are annotated for Ibuprofen?")

    assert plan.domain == "medical_adr"
    assert plan.dataset == "spl_adr"
    assert plan.entities["drug_name"].lower() == "ibuprofen"
    assert plan.filters["drug_name"].lower() == "ibuprofen"
    assert plan.preferred_chunk_types[0] == "spl_label"


def test_domain_hint_overrides_inference(analyzer: QueryAnalyzer) -> None:
    # 文本不含领域线索,domain_hint 应被采纳
    plan = analyzer.analyze("Summarize the document.", domain_hint="legal_compliance")
    assert plan.domain == "legal_compliance"


def test_plan_defaults(analyzer: QueryAnalyzer) -> None:
    plan = analyzer.analyze("hello")
    assert isinstance(plan, QueryPlan)
    assert plan.intent == "rag_qa"
    assert plan.needs_rerank is True
    assert plan.needs_calculation is False
