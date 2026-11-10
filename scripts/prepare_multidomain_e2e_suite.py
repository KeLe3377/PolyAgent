# -*- coding: utf-8 -*-
"""Prepare a focused multi-domain E2E suite from public benchmark data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_OUT = Path("data/benchmarks/e2e_multidomain")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")


def _keywords_from_answer(answer: str, *, max_keywords: int = 3) -> list[str]:
    normalized = answer.replace("\n", "; ")
    parts = [p.strip(" .,:;()[]{}\"'") for p in normalized.split(";")]
    out: list[str] = []
    for part in parts:
        if 3 <= len(part) <= 60 and part.upper() != "NO_ANSWER":
            out.append(part)
        if len(out) >= max_keywords:
            return out
    words = [w.strip(" .,:;()[]{}\"'") for w in normalized.split()]
    for word in words:
        if len(word) >= 4 and word not in out:
            out.append(word)
        if len(out) >= max_keywords:
            break
    return out


def _select_cases(rows: list[dict[str, Any]], *, domain: str, count: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_docs: set[str] = set()
    for row in rows:
        category = str((row.get("metadata") or {}).get("category") or "")
        if domain == "legal_compliance" and category.lower() == "document name":
            continue
        answer = str(row.get("gold_answer") or "")
        docs = [str(x) for x in row.get("gold_evidence_doc_ids") or []]
        if not docs or not answer or answer.upper() == "NO_ANSWER":
            continue
        keywords = _keywords_from_answer(answer)
        if not keywords:
            continue
        doc_key = docs[0]
        if doc_key in seen_docs and len(seen_docs) < count:
            continue
        seen_docs.add(doc_key)
        selected.append(
            {
                "case_id": f"e2e_{row.get('case_id')}",
                "domain": domain,
                "mode": "react",
                "query": row.get("query"),
                "gold_answer": answer,
                "gold_evidence_doc_ids": docs,
                "expected_keywords": keywords,
                "category": row.get("task_type") or "rag_qa",
                "dataset": row.get("dataset"),
                "source_category": category,
            }
        )
        if len(selected) >= count:
            break
    return selected


def build_suite(root: Path, *, per_domain: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dataset_specs = [
        ("financial_tatqa", "financial"),
        ("legal_cuad", "legal_compliance"),
        ("medical_spl_adr", "medical_adr"),
    ]
    cases: list[dict[str, Any]] = []
    # 结构化语料(RAG 质量升级)下,同一 doc_id 可能有多条 chunk
    # (table_doc / row_fact / cell_fact / contract_doc / contract_clause),
    # 这里收集全部行而非按 doc_id 去重,保证结构化片段进入 E2E 语料。
    corpus_rows: list[dict[str, Any]] = []
    seen_row_keys: set[tuple[str, str]] = set()

    for dataset_name, domain in dataset_specs:
        ds_root = root / dataset_name
        corpus = _read_jsonl(ds_root / "corpus.jsonl")
        eval_rows = _read_jsonl(ds_root / "eval_cases.jsonl")
        selected = _select_cases(eval_rows, domain=domain, count=per_domain)
        cases.extend(selected)
        wanted_docs = {doc_id for case in selected for doc_id in case["gold_evidence_doc_ids"]}
        for doc in corpus:
            doc_id = str(doc.get("doc_id"))
            if doc_id in wanted_docs:
                chunk_type = str((doc.get("metadata") or {}).get("chunk_type") or "")
                key = (doc_id, chunk_type, str(doc.get("text") or "")[:64])
                if key in seen_row_keys:
                    continue
                seen_row_keys.add(key)
                corpus_rows.append(doc)

    cases.append(
        {
            "case_id": "e2e_financial_deliberation_apple",
            "domain": "financial",
            "mode": "deliberation",
            "query": "请用多空双方视角分析苹果公司的投资价值。",
            "gold_answer": "",
            "gold_evidence_doc_ids": [],
            "expected_keywords": ["苹果", "多头", "空头", "风险"],
            "category": "deliberation",
            "dataset": "PolyAgent financial corpus",
        }
    )
    return list(corpus_rows), cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a focused multi-domain E2E suite")
    parser.add_argument("--benchmarks-root", type=Path, default=Path("data/benchmarks"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--per-domain", type=int, default=2)
    parser.add_argument("--confirmed", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    corpus, cases = build_suite(args.benchmarks_root, per_domain=args.per_domain)
    summary = {
        "status": "dry_run" if not args.confirmed else "ok",
        "out": str(args.out),
        "corpus_count": len(corpus),
        "case_count": len(cases),
        "cases": [{"case_id": c["case_id"], "domain": c["domain"], "mode": c["mode"]} for c in cases],
    }
    if not args.confirmed:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(args.out / "corpus.jsonl", corpus)
    (args.out / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
