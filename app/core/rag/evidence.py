# -*- coding: utf-8 -*-
"""Evidence Pack: retrieval evidence normalization for grounded answers.

This module deliberately stops short of producing final answers. It converts
retrieved chunks into a compact, auditable evidence package that LLM agents can
use for analysis, citations, and multi-turn grounding.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.rag.query_analyzer import QueryPlan
from app.models.schemas import RetrievalResult


@dataclass(slots=True)
class EvidenceItem:
    """One grounded evidence item derived from a retrieved chunk."""

    index: int
    doc_id: str
    chunk_id: str
    source: str
    dataset: str
    chunk_type: str
    score: float
    quote: str
    claims: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvidenceCoverage:
    """Evidence quality signals used before synthesis."""

    entity_matched: bool
    required_filters: dict[str, Any] = field(default_factory=dict)
    matched_filters: dict[str, Any] = field(default_factory=dict)
    missing_filters: dict[str, Any] = field(default_factory=dict)
    item_count: int = 0


@dataclass(slots=True)
class EvidencePack:
    """A compact evidence object for grounded synthesis."""

    domain: str
    dataset: str | None
    intent: str
    entity: dict[str, Any]
    coverage: EvidenceCoverage
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    key_facts: list[str] = field(default_factory=list)
    answer_directives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "dataset": self.dataset,
            "intent": self.intent,
            "entity": self.entity,
            "coverage": {
                "entity_matched": self.coverage.entity_matched,
                "required_filters": self.coverage.required_filters,
                "matched_filters": self.coverage.matched_filters,
                "missing_filters": self.coverage.missing_filters,
                "item_count": self.coverage.item_count,
            },
            "evidence_items": [
                {
                    "index": item.index,
                    "doc_id": item.doc_id,
                    "chunk_id": item.chunk_id,
                    "source": item.source,
                    "dataset": item.dataset,
                    "chunk_type": item.chunk_type,
                    "score": item.score,
                    "quote": item.quote,
                    "claims": item.claims,
                    "metadata": item.metadata,
                }
                for item in self.evidence_items
            ],
            "key_facts": self.key_facts,
            "answer_directives": self.answer_directives,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def _metadata(result: RetrievalResult) -> dict[str, Any]:
    return dict(getattr(result, "metadata", {}) or {})


def _meta_value(result: RetrievalResult, key: str) -> Any:
    metadata = _metadata(result)
    if key == "id":
        return result.id
    if key == "source":
        return metadata.get("source") or result.source
    return metadata.get(key)


def _matches(actual: Any, expected: Any) -> bool:
    if expected is None:
        return True
    if isinstance(expected, (list, tuple, set)):
        return any(_matches(actual, item) for item in expected)
    if isinstance(actual, (list, tuple, set)):
        return any(_matches(item, expected) for item in actual)
    return str(actual).casefold() == str(expected).casefold()


def _truncate(text: str, limit: int = 900) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _claim_sentences(text: str, *, max_claims: int = 3) -> list[str]:
    compact = " ".join(str(text or "").split())
    if not compact:
        return []
    parts = [p.strip() for p in re.split(r"(?<=[.!?。！？])\s+", compact) if p.strip()]
    if not parts:
        parts = [compact]
    return [_truncate(part, 240) for part in parts[:max_claims]]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [part.strip() for part in value.split(";") if part.strip()]
    return []


class EvidenceCompressor:
    """Extract concise, high-value facts from retrieval metadata and text."""

    def compress_item(self, plan: QueryPlan, result: RetrievalResult, metadata: dict[str, Any]) -> list[str]:
        if plan.domain == "medical_adr":
            reactions = _string_list(metadata.get("annotated_reactions"))
            if reactions:
                return [f"annotated ADR: {reaction}" for reaction in reactions[:24]]
        return _claim_sentences(result.content)

    def key_facts(self, plan: QueryPlan, items: list[EvidenceItem]) -> list[str]:
        facts: list[str] = []
        seen: set[str] = set()
        for item in items:
            for claim in item.claims:
                if claim.casefold() in seen:
                    continue
                seen.add(claim.casefold())
                facts.append(claim)
                if plan.domain == "medical_adr" and len(facts) >= 30:
                    return facts
                if len(facts) >= 12:
                    return facts
        return facts


def _answer_directives(plan: QueryPlan) -> list[str]:
    base = [
        "Base the answer only on evidence_items; say when evidence is insufficient.",
        "Cite source doc_id values for factual claims.",
        "Use evidence to analyze the user's question instead of mechanically listing chunks.",
    ]
    if plan.domain == "medical_adr":
        base.extend(
            [
                "For ADR questions, include the drug name and organize adverse reactions by evidence source.",
                "Distinguish explicitly annotated reactions from broader warnings or precautions.",
                "Do not give diagnosis or treatment advice.",
            ]
        )
    elif plan.domain == "legal_compliance":
        base.extend(
            [
                "For contract questions, identify the relevant clause and explain why it matters.",
                "Do not present the answer as formal legal advice.",
            ]
        )
    elif plan.domain == "financial":
        base.append("For financial questions, separate retrieved facts from calculations or interpretation.")
    return base


class EvidenceBuilder:
    """Build an EvidencePack from retrieval results and a QueryPlan."""

    def __init__(self, compressor: EvidenceCompressor | None = None) -> None:
        self._compressor = compressor or EvidenceCompressor()

    def build(self, plan: QueryPlan, results: list[RetrievalResult]) -> EvidencePack:
        required = dict(plan.filters)
        matched: dict[str, Any] = {}
        missing: dict[str, Any] = {}
        for key, expected in required.items():
            if any(_matches(_meta_value(result, key), expected) for result in results):
                matched[key] = expected
            else:
                missing[key] = expected

        items: list[EvidenceItem] = []
        for idx, result in enumerate(results, 1):
            metadata = _metadata(result)
            compressed_claims = self._compressor.compress_item(plan, result, metadata)
            items.append(
                EvidenceItem(
                    index=idx,
                    doc_id=str(metadata.get("doc_id") or result.id),
                    chunk_id=str(result.id),
                    source=str(metadata.get("source") or result.source),
                    dataset=str(metadata.get("dataset") or plan.dataset or ""),
                    chunk_type=str(metadata.get("chunk_type") or ""),
                    score=float(result.score),
                    quote=_truncate(result.content),
                    claims=compressed_claims,
                    metadata={
                        key: value
                        for key, value in metadata.items()
                        if key
                        in {
                            "annotated_reaction_count",
                            "annotated_reactions",
                            "domain",
                            "dataset",
                            "doc_id",
                            "chunk_type",
                            "contract_name",
                            "clause_type",
                            "drug_name",
                            "year",
                            "source",
                            "title",
                        }
                    },
                )
            )

        coverage = EvidenceCoverage(
            entity_matched=not missing,
            required_filters=required,
            matched_filters=matched,
            missing_filters=missing,
            item_count=len(items),
        )
        return EvidencePack(
            domain=plan.domain,
            dataset=plan.dataset,
            intent=plan.intent,
            entity=dict(plan.entities),
            coverage=coverage,
            evidence_items=items,
            key_facts=self._compressor.key_facts(plan, items),
            answer_directives=_answer_directives(plan),
        )


__all__ = ["EvidenceBuilder", "EvidenceCompressor", "EvidenceCoverage", "EvidenceItem", "EvidencePack"]
