# -*- coding: utf-8 -*-

import json

from app.core.rag.evidence import EvidenceBuilder
from app.core.rag.query_analyzer import QueryAnalyzer
from app.models.schemas import RetrievalResult


def test_evidence_builder_marks_entity_coverage_and_claims() -> None:
    plan = QueryAnalyzer().analyze(
        "What adverse drug reactions are annotated for actemra?",
        domain_hint="medical_adr",
    )
    results = [
        RetrievalResult(
            id="chunk-1",
            content="Upper respiratory tract infections are listed. Active tuberculosis is a warning.",
            score=0.8,
            metadata={
                "domain": "medical_adr",
                "dataset": "spl_adr",
                "doc_id": "spl_adr_gold_actemra",
                "chunk_type": "spl_label",
                "drug_name": "actemra",
                "annotated_reactions": [
                    "abdominal pain upper",
                    "abscess",
                    "active tuberculosis",
                ],
                "source": "ACTEMRA.xml",
            },
        )
    ]

    pack = EvidenceBuilder().build(plan, results)
    payload = json.loads(pack.to_json())

    assert payload["coverage"]["entity_matched"] is True
    assert payload["coverage"]["missing_filters"] == {}
    assert payload["evidence_items"][0]["doc_id"] == "spl_adr_gold_actemra"
    assert "annotated ADR: abdominal pain upper" in payload["evidence_items"][0]["claims"]
    assert "annotated ADR: active tuberculosis" in payload["key_facts"]
    assert any("ADR" in rule for rule in payload["answer_directives"])


def test_evidence_builder_reports_missing_filter() -> None:
    plan = QueryAnalyzer().analyze(
        "What adverse drug reactions are annotated for actemra?",
        domain_hint="medical_adr",
    )
    results = [
        RetrievalResult(
            id="chunk-2",
            content="A different drug label.",
            score=0.2,
            metadata={"domain": "medical_adr", "dataset": "spl_adr", "drug_name": "adempas"},
        )
    ]

    pack = EvidenceBuilder().build(plan, results)

    assert pack.coverage.entity_matched is False
    assert pack.coverage.missing_filters["drug_name"] == "actemra"
