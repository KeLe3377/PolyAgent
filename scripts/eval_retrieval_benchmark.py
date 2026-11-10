# -*- coding: utf-8 -*-
"""Offline retrieval benchmark for benchmark corpus/eval JSONL."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.rag.retriever import MultiRetriever


class _ZeroEmbedding:
    def embed_query(self, text: str) -> list[float]:
        return [0.0]


class _NoopMilvus:
    async def search(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lower = int(k)
    upper = min(lower + 1, len(ordered) - 1)
    weight = k - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


async def run_benchmark(corpus: Path, eval_cases: Path, *, top_k: int, max_cases: int | None) -> dict[str, Any]:
    docs = _read_jsonl(corpus)
    cases = _read_jsonl(eval_cases)
    if max_cases is not None:
        cases = cases[:max_cases]
    id_to_text: dict[str, str] = {}
    id_to_metadata: dict[str, dict[str, Any]] = {}
    for doc in docs:
        doc_id = str(doc.get("doc_id") or doc.get("id"))
        metadata = {
            **dict(doc.get("metadata") or {}),
            "doc_id": doc_id,
            "domain": doc.get("domain"),
            "dataset": doc.get("dataset"),
            "source": doc.get("source"),
        }
        id_to_text[doc_id] = str(doc.get("text") or "")
        id_to_metadata[doc_id] = metadata
    retriever = MultiRetriever(_NoopMilvus(), _ZeroEmbedding())
    retriever.register_keyword_documents(id_to_text, id_to_metadata)

    hits = 0
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    results: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        retrieved = await retriever.retrieve(str(case.get("query") or ""), mode="keyword", top_k=top_k, rerank=False)
        latencies.append((time.perf_counter() - started) * 1000)
        retrieved_doc_ids = [str(r.metadata.get("doc_id") or r.id) for r in retrieved]
        gold = [str(x) for x in case.get("gold_evidence_doc_ids") or []]
        matched_rank = next((idx + 1 for idx, doc_id in enumerate(retrieved_doc_ids) if doc_id in set(gold)), None)
        hit = matched_rank is not None
        hits += 1 if hit else 0
        reciprocal_ranks.append(1.0 / matched_rank if matched_rank else 0.0)
        results.append(
            {
                "case_id": case.get("case_id"),
                "hit": hit,
                "rank": matched_rank,
                "gold_evidence_doc_ids": gold,
                "retrieved_doc_ids": retrieved_doc_ids,
            }
        )
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus": str(corpus),
        "eval_cases": str(eval_cases),
        "summary": {
            "total_cases": len(cases),
            "top_k": top_k,
            "hit_count": hits,
            "recall_at_k": hits / len(cases) if cases else None,
            "mrr": statistics.mean(reciprocal_ranks) if reciprocal_ranks else None,
            "latency_ms": {
                "avg": statistics.mean(latencies) if latencies else None,
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
            },
        },
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate keyword retrieval over benchmark JSONL")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--eval-cases", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--plan", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.plan:
        print(json.dumps({"status": "plan", "corpus": str(args.corpus), "eval_cases": str(args.eval_cases), "top_k": args.top_k}, ensure_ascii=False, indent=2))
        return 0
    report = asyncio.run(run_benchmark(args.corpus, args.eval_cases, top_k=args.top_k, max_cases=args.max_cases))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
