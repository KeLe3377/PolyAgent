# -*- coding: utf-8 -*-
"""Prepare multi-domain benchmark corpora for PolyAgent.

The command converts local public benchmark datasets into a unified JSONL shape:

data/benchmarks/<dataset>/
  corpus.jsonl
  eval_cases.jsonl
  manifest.json

Default mode is a dry run. Use --confirmed to write files.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


_YEAR_CELL = re.compile(r"^(19|20)\d{2}$")



@dataclass(frozen=True)
class PreparedDataset:
    name: str
    corpus: list[dict[str, Any]]
    eval_cases: list[dict[str, Any]]
    notes: list[str]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonl_line(item: dict[str, Any]) -> str:
    return json.dumps(item, ensure_ascii=False, separators=(",", ":"))


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for item in rows:
            f.write(_jsonl_line(item))
            f.write("\n")
            count += 1
    return count


def _table_to_markdown(table: list[list[Any]]) -> str:
    if not table:
        return ""
    rows = [[str(cell).strip() for cell in row] for row in table]
    max_cols = max(len(row) for row in rows)
    rows = [row + [""] * (max_cols - len(row)) for row in rows]
    header = rows[0]
    body = rows[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * max_cols) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _answer_to_text(answer: Any) -> str:
    if isinstance(answer, list):
        return "; ".join(str(x) for x in answer)
    if isinstance(answer, dict):
        return json.dumps(answer, ensure_ascii=False, sort_keys=True)
    return "" if answer is None else str(answer)


def _row_header(row: list[Any]) -> str:
    """数据行的行头:第一个非空 cell(通常是行标签)。"""
    for cell in row:
        s = str(cell).strip()
        if s:
            return s
    return ""


def _detect_header_row(table_rows: list[list[Any]]) -> int:
    """返回列头所在行索引:第一个含 >=2 个年份 cell 的行;否则 0。"""
    for i, row in enumerate(table_rows):
        year_like = sum(1 for c in row if _YEAR_CELL.match(str(c).strip()))
        if year_like >= 2:
            return i
    return 0


def _decompose_tatqa_table(
    table_rows: list[list[Any]],
    *,
    doc_id: str,
    table_uid: str,
    split: str,
    source: str,
    ctx_idx: int,
) -> Iterable[dict[str, Any]]:
    """把一张 TAT-QA 表分解为 row_fact / cell_fact 两条结构化语料。

    所有行共享 ``doc_id``(与 table_doc 同源),保证 evidence 召回按 doc_id
    仍可命中;额外写入 ``chunk_type`` + ``row_header`` / ``column_header`` /
    ``year`` / ``value`` / ``table_uid`` 供 MetadataRouter 过滤。

    表头约定(TAT-QA 实测):第 0 行常是分组表头(如 "Years Ended ..."),
    其后一行是列头(年份),再之后是数据行。检测不到列头时按第 0 行兜底。
    """
    if not table_rows:
        return

    header_idx = _detect_header_row(table_rows)
    column_headers = [str(c).strip() for c in table_rows[header_idx]]
    data_rows = table_rows[header_idx + 1 :]

    for r_off, row in enumerate(data_rows, start=1):
        cells = [str(c).strip() for c in row]
        row_header = _row_header(cells)
        if not row_header:
            continue
        # 行内非空值 cell(去掉行头本身)
        value_cells = [(c_idx, cells[c_idx]) for c_idx in range(len(cells)) if c_idx > 0 and cells[c_idx]]
        if not value_cells:
            continue

        # row_fact:整行作为一条事实
        pairs = " | ".join(
            f"{column_headers[c_idx] if c_idx < len(column_headers) else f'col{c_idx}'}={val}"
            for c_idx, val in value_cells
        )
        yield {
            "doc_id": doc_id,
            "domain": "financial",
            "dataset": "TAT-QA",
            "source": source,
            "title": f"TAT-QA {split} context {ctx_idx} row {r_off}",
            "text": f"{row_header} | {pairs}",
            "metadata": {
                "split": split,
                "table_uid": table_uid,
                "chunk_type": "row_fact",
                "row_header": row_header,
                "values": {column_headers[c_idx] if c_idx < len(column_headers) else f"col{c_idx}": val for c_idx, val in value_cells},
            },
        }

        # cell_fact:每个数值 cell 一条(便于按 year/column 精确过滤)
        for c_idx, val in value_cells:
            column_header = column_headers[c_idx] if c_idx < len(column_headers) else ""
            year = column_header if _YEAR_CELL.match(column_header) else ""
            yield {
                "doc_id": doc_id,
                "domain": "financial",
                "dataset": "TAT-QA",
                "source": source,
                "title": f"TAT-QA {split} context {ctx_idx} cell {row_header}@{column_header or c_idx}",
                "text": f"{row_header} {column_header or ''}: {val}".strip(),
                "metadata": {
                    "split": split,
                    "table_uid": table_uid,
                    "chunk_type": "cell_fact",
                    "row_header": row_header,
                    "column_header": column_header,
                    "year": year,
                    "value": val,
                    "answer_from": "table",
                },
            }


def prepare_tatqa(
    dataset_root: Path,
    *,
    splits: list[str],
    max_eval_cases: int | None,
    structured_facts: bool = True,
) -> PreparedDataset:
    corpus: list[dict[str, Any]] = []
    eval_cases: list[dict[str, Any]] = []
    notes: list[str] = []

    for split in splits:
        path = dataset_root / f"tatqa_dataset_{split}.json"
        if not path.exists():
            notes.append(f"missing split: {path}")
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        for ctx_idx, item in enumerate(raw, start=1):
            table = item.get("table") or {}
            table_uid = table.get("uid") or f"{split}_{ctx_idx:05d}"
            doc_id = f"tatqa_{split}_{table_uid}"
            paragraphs = item.get("paragraphs") or []
            paragraph_text = "\n\n".join(
                f"[P{p.get('order', i)}] {p.get('text', '')}".strip()
                for i, p in enumerate(paragraphs, start=1)
                if p.get("text")
            )
            table_rows = table.get("table") or []
            table_text = _table_to_markdown(table_rows)
            text = "\n\n".join(part for part in [table_text, paragraph_text] if part)
            base_meta = {
                "split": split,
                "table_uid": table_uid,
                "paragraph_uids": [p.get("uid") for p in paragraphs if p.get("uid")],
            }
            # ① table_doc:整表 + 段落(既有全量文本,保留通用检索能力)
            corpus.append(
                {
                    "doc_id": doc_id,
                    "domain": "financial",
                    "dataset": "TAT-QA",
                    "source": str(path),
                    "title": f"TAT-QA {split} context {ctx_idx}",
                    "text": text,
                    "metadata": {
                        **base_meta,
                        "chunk_type": "table_doc",
                        "answer_from": "table",
                    },
                }
            )
            # ② row_fact / cell_fact:结构化表格分解(RAG 质量升级)
            if structured_facts:
                for fact in _decompose_tatqa_table(
                    table_rows,
                    doc_id=doc_id,
                    table_uid=table_uid,
                    split=split,
                    source=str(path),
                    ctx_idx=ctx_idx,
                ):
                    corpus.append(fact)
            for q in item.get("questions") or []:
                if max_eval_cases is not None and len(eval_cases) >= max_eval_cases:
                    continue
                qid = q.get("uid") or f"{doc_id}_q{q.get('order', len(eval_cases) + 1)}"
                eval_cases.append(
                    {
                        "case_id": f"tatqa_{split}_{qid}",
                        "domain": "financial",
                        "dataset": "TAT-QA",
                        "query": q.get("question", ""),
                        "gold_answer": _answer_to_text(q.get("answer")),
                        "gold_evidence_doc_ids": [doc_id],
                        "task_type": "table_text_financial_qa",
                        "metadata": {
                            "split": split,
                            "answer_type": q.get("answer_type"),
                            "answer_from": q.get("answer_from"),
                            "derivation": q.get("derivation"),
                            "scale": q.get("scale"),
                            "rel_paragraphs": q.get("rel_paragraphs") or [],
                            "req_comparison": q.get("req_comparison"),
                        },
                    }
                )

    if max_eval_cases is not None and len(eval_cases) >= max_eval_cases:
        notes.append(f"eval cases capped at {max_eval_cases}")
    return PreparedDataset("financial_tatqa", corpus, eval_cases, notes)


def _cuad_category(qid: str, question: str) -> str:
    if "__" in qid:
        return qid.rsplit("__", 1)[-1]
    marker = 'related to "'
    if marker in question:
        return question.split(marker, 1)[1].split('"', 1)[0]
    return "unknown"


def _extract_cuad_clauses(
    paragraphs: list[dict[str, Any]],
    *,
    doc_id: str,
    contract_name: str,
    source: str,
) -> Iterable[dict[str, Any]]:
    """按 clause_type 聚合 CUAD 的标注答案,生成 contract_clause 语料行。

    每个 (合同, clause_type) 合并为一条:文本去重拼接该类别下的标注条款片段。
    所有行共享合同 ``doc_id``,并写入 ``contract_name`` / ``clause_type`` /
    ``chunk_type=contract_clause`` 供 ContractClauseLocator 精确过滤。
    """
    bucket: dict[str, list[str]] = {}
    section_hint: dict[str, int] = {}
    for p_idx, paragraph in enumerate(paragraphs, start=1):
        for qa in paragraph.get("qas") or []:
            answers = qa.get("answers") or []
            category = _cuad_category(str(qa.get("id", "")), qa.get("question", ""))
            for a in answers:
                text = str(a.get("text", "")).strip()
                if not text:
                    continue
                if text not in bucket.setdefault(category, []):
                    bucket[category].append(text)
                    section_hint.setdefault(category, p_idx)

    for category, texts in bucket.items():
        joined = "\n".join(texts)
        yield {
            "doc_id": doc_id,
            "domain": "legal_compliance",
            "dataset": "CUAD",
            "source": source,
            "title": f"{contract_name} :: {category}",
            "text": joined,
            "metadata": {
                "contract_name": contract_name,
                "clause_type": category,
                "chunk_type": "contract_clause",
                "section_hint": section_hint.get(category),
                "snippet_count": len(texts),
            },
        }


def prepare_cuad(
    data_zip: Path,
    *,
    max_eval_cases: int | None,
    structured_clauses: bool = True,
) -> PreparedDataset:
    corpus: list[dict[str, Any]] = []
    eval_cases: list[dict[str, Any]] = []
    notes: list[str] = []

    with zipfile.ZipFile(data_zip) as zf:
        raw = json.loads(zf.read("CUADv1.json").decode("utf-8"))

    for doc_idx, item in enumerate(raw.get("data") or [], start=1):
        title = item.get("title") or f"contract_{doc_idx:05d}"
        paragraphs = item.get("paragraphs") or []
        context = "\n\n".join(p.get("context", "") for p in paragraphs if p.get("context"))
        doc_id = f"cuad_{doc_idx:05d}_{title[:80]}"
        corpus.append(
            {
                "doc_id": doc_id,
                "domain": "legal_compliance",
                "dataset": "CUAD",
                "source": str(data_zip) + "!CUADv1.json",
                "title": title,
                "text": context,
                "metadata": {
                    "doc_index": doc_idx,
                    "paragraph_count": len(paragraphs),
                    "contract_name": title,
                    "chunk_type": "contract_doc",
                },
            }
        )
        # ② contract_clause:按 clause_type 聚合的条款片段(RAG 质量升级)
        if structured_clauses:
            for fact in _extract_cuad_clauses(
                paragraphs,
                doc_id=doc_id,
                contract_name=title,
                source=str(data_zip) + "!CUADv1.json",
            ):
                corpus.append(fact)
        for p_idx, paragraph in enumerate(paragraphs, start=1):
            for qa in paragraph.get("qas") or []:
                if max_eval_cases is not None and len(eval_cases) >= max_eval_cases:
                    continue
                answers = qa.get("answers") or []
                eval_cases.append(
                    {
                        "case_id": f"cuad_{qa.get('id')}",
                        "domain": "legal_compliance",
                        "dataset": "CUAD",
                        "query": f"In contract {title}, {qa.get('question', '')}",
                        "gold_answer": "; ".join(a.get("text", "") for a in answers) if answers else "NO_ANSWER",
                        "gold_evidence_doc_ids": [doc_id],
                        "task_type": "contract_clause_extraction",
                        "metadata": {
                            "category": _cuad_category(str(qa.get("id", "")), qa.get("question", "")),
                            "contract_title": title,
                            "original_question": qa.get("question", ""),
                            "is_impossible": bool(qa.get("is_impossible", False)),
                            "paragraph_index": p_idx,
                            "answer_starts": [a.get("answer_start") for a in answers],
                        },
                    }
                )

    if max_eval_cases is not None and len(eval_cases) >= max_eval_cases:
        notes.append(f"eval cases capped at {max_eval_cases}")
    return PreparedDataset("legal_cuad", corpus, eval_cases, notes)


def _xml_text(elem: ET.Element | None) -> str:
    if elem is None:
        return ""
    return " ".join(" ".join(elem.itertext()).split())


def _iter_xml_files(paths: list[Path]) -> Iterable[tuple[str, Path]]:
    for split, root in (("train", paths[0]), ("gold", paths[1])):
        if not root.exists():
            continue
        for path in sorted(root.glob("*.xml")):
            yield split, path


def prepare_spl_adr(
    train_dir: Path,
    gold_dir: Path,
    *,
    max_eval_cases: int | None,
) -> PreparedDataset:
    corpus: list[dict[str, Any]] = []
    eval_cases: list[dict[str, Any]] = []
    notes: list[str] = []

    for split, path in _iter_xml_files([train_dir, gold_dir]):
        root = ET.parse(path).getroot()
        drug = root.attrib.get("drug") or path.stem
        reactions_elem = root.find("Reactions")
        annotated_reactions = []
        if reactions_elem is not None:
            annotated_reactions = sorted(
                {r.attrib.get("str", "").strip() for r in reactions_elem if r.attrib.get("str")}
            )
        sections = []
        text_root = root.find("Text")
        if text_root is not None:
            for section in text_root.findall("Section"):
                sections.append(
                    {
                        "id": section.attrib.get("id"),
                        "name": section.attrib.get("name"),
                        "text": _xml_text(section),
                    }
                )
        text = "\n\n".join(
            f"[{s.get('name') or s.get('id')}] {s.get('text', '')}".strip()
            for s in sections
            if s.get("text")
        )
        doc_id = f"spl_adr_{split}_{drug}"
        corpus.append(
            {
                "doc_id": doc_id,
                "domain": "medical_adr",
                "dataset": "SPL-ADR-200db",
                "source": str(path),
                "title": f"{drug} structured product label",
                "text": text,
                "metadata": {
                    "split": split,
                    "drug": drug,
                    "drug_name": drug,
                    "chunk_type": "spl_label",
                    "annotated_reactions": annotated_reactions,
                    "annotated_reaction_count": len(annotated_reactions),
                    "section_count": len(sections),
                    "track": root.attrib.get("track"),
                },
            }
        )
        if split != "gold":
            continue
        if max_eval_cases is not None and len(eval_cases) >= max_eval_cases:
            continue
        eval_cases.append(
            {
                "case_id": f"spl_adr_gold_{drug}",
                "domain": "medical_adr",
                "dataset": "SPL-ADR-200db",
                "query": f"What adverse drug reactions are annotated for {drug}?",
                "gold_answer": "; ".join(annotated_reactions),
                "gold_evidence_doc_ids": [doc_id],
                "task_type": "adverse_drug_reaction_extraction",
                "metadata": {
                    "split": split,
                    "drug": drug,
                    "reaction_count": len(annotated_reactions),
                    "gold_answer_list": annotated_reactions,
                },
            }
        )

    if max_eval_cases is not None and len(eval_cases) >= max_eval_cases:
        notes.append(f"eval cases capped at {max_eval_cases}")
    return PreparedDataset("medical_spl_adr", corpus, eval_cases, notes)


def _manifest(dataset: PreparedDataset) -> dict[str, Any]:
    return {
        "name": dataset.name,
        "created_at": _now(),
        "corpus_count": len(dataset.corpus),
        "eval_case_count": len(dataset.eval_cases),
        "notes": dataset.notes,
        "schema": {
            "corpus": ["doc_id", "domain", "dataset", "source", "title", "text", "metadata"],
            "eval_cases": [
                "case_id",
                "domain",
                "dataset",
                "query",
                "gold_answer",
                "gold_evidence_doc_ids",
                "task_type",
                "metadata",
            ],
        },
    }


def _write_dataset(out_root: Path, dataset: PreparedDataset) -> dict[str, Any]:
    ds_dir = out_root / dataset.name
    ds_dir.mkdir(parents=True, exist_ok=True)
    corpus_path = ds_dir / "corpus.jsonl"
    eval_path = ds_dir / "eval_cases.jsonl"
    manifest_path = ds_dir / "manifest.json"
    corpus_count = _write_jsonl(corpus_path, dataset.corpus)
    eval_count = _write_jsonl(eval_path, dataset.eval_cases)
    manifest = _manifest(dataset)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "name": dataset.name,
        "corpus": str(corpus_path),
        "eval_cases": str(eval_path),
        "manifest": str(manifest_path),
        "corpus_count": corpus_count,
        "eval_case_count": eval_count,
        "notes": dataset.notes,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare PolyAgent benchmark corpora")
    parser.add_argument("--out", type=Path, default=Path("data/benchmarks"))
    parser.add_argument("--tatqa-root", type=Path, default=Path("TAT-QA/dataset_raw"))
    parser.add_argument("--tatqa-splits", default="dev,test_gold")
    parser.add_argument("--cuad-zip", type=Path, default=Path("cuad/data.zip"))
    parser.add_argument("--spl-train", type=Path, default=Path("train_xml"))
    parser.add_argument("--spl-gold", type=Path, default=Path("gold_xml"))
    parser.add_argument("--max-eval-cases", type=int, default=1000)
    parser.add_argument(
        "--datasets",
        default="tatqa,cuad,spl_adr",
        help="comma-separated subset: tatqa,cuad,spl_adr",
    )
    parser.add_argument("--confirmed", action="store_true", help="write converted benchmark files")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected = {x.strip().lower() for x in args.datasets.split(",") if x.strip()}
    max_eval = args.max_eval_cases if args.max_eval_cases >= 0 else None
    datasets: list[PreparedDataset] = []

    if "tatqa" in selected:
        splits = [x.strip() for x in args.tatqa_splits.split(",") if x.strip()]
        datasets.append(prepare_tatqa(args.tatqa_root, splits=splits, max_eval_cases=max_eval))
    if "cuad" in selected:
        datasets.append(prepare_cuad(args.cuad_zip, max_eval_cases=max_eval))
    if "spl_adr" in selected:
        datasets.append(prepare_spl_adr(args.spl_train, args.spl_gold, max_eval_cases=max_eval))

    summary = {
        "status": "dry_run" if not args.confirmed else "ok",
        "out": str(args.out),
        "datasets": [
            {
                "name": ds.name,
                "corpus_count": len(ds.corpus),
                "eval_case_count": len(ds.eval_cases),
                "notes": ds.notes,
            }
            for ds in datasets
        ],
    }

    if not args.confirmed:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    written = [_write_dataset(args.out, ds) for ds in datasets]
    summary["written"] = written
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
