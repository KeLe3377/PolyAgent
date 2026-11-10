# -*- coding: utf-8 -*-
"""Ingest benchmark corpus JSONL into Milvus.

Default mode is dry-run. Use --confirmed to call embedding provider and write Milvus.
The script prints only structural counts and never prints secrets.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings, get_settings
from app.etl.chunker import ChunkStrategy, DocumentChunker
from app.infrastructure.llm.embedding import OpenAIEmbeddingAdapter
from app.infrastructure.vectordb import MilvusManager


@dataclass(frozen=True)
class BenchmarkDoc:
    doc_id: str
    domain: str
    dataset: str
    source: str
    title: str
    text: str
    metadata: dict[str, Any]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_docs(path: Path) -> list[BenchmarkDoc]:
    docs: list[BenchmarkDoc] = []
    for row in _read_jsonl(path):
        metadata = dict(row.get("metadata") or {})
        doc_id = str(row.get("doc_id") or metadata.get("doc_id") or "")
        if not doc_id:
            raise ValueError(f"Missing doc_id in {path}")
        docs.append(
            BenchmarkDoc(
                doc_id=doc_id,
                domain=str(row.get("domain") or metadata.get("domain") or ""),
                dataset=str(row.get("dataset") or metadata.get("dataset") or ""),
                source=str(row.get("source") or metadata.get("source") or ""),
                title=str(row.get("title") or metadata.get("title") or doc_id),
                text=str(row.get("text") or ""),
                metadata=metadata,
            )
        )
    return docs


def _chunk_id(doc: BenchmarkDoc, index: int, text: str) -> str:
    raw = f"{doc.dataset}:{doc.doc_id}:{index}:{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def _normalize_dataset(value: str) -> str:
    """Normalize dataset identifiers used by QueryAnalyzer/RetrievalRequest filters."""
    normalized = value.strip().lower()
    aliases = {
        "tat-qa": "tatqa",
        "tat_qa": "tatqa",
        "tatqa": "tatqa",
        "cuad": "cuad",
        "spl-adr": "spl_adr",
        "spl_adr": "spl_adr",
        "spl-adr-200db": "spl_adr",
        "spl_adr_200db": "spl_adr",
    }
    return aliases.get(normalized, normalized)


def build_rows(docs: list[BenchmarkDoc], *, chunk_size: int, chunk_overlap: int) -> list[dict[str, Any]]:
    chunker = DocumentChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    rows: list[dict[str, Any]] = []
    for doc in docs:
        base_metadata = {
            **doc.metadata,
            "doc_id": doc.doc_id,
            "domain": doc.domain,
            "dataset": _normalize_dataset(doc.dataset),
            "dataset_raw": doc.dataset,
            "source": doc.source,
            "title": doc.title,
        }
        for idx, chunk in enumerate(chunker.chunk(doc.text, strategy=ChunkStrategy.RECURSIVE)):
            rows.append(
                {
                    **base_metadata,
                    "id": _chunk_id(doc, idx, chunk),
                    "text": chunk,
                    "chunk_index": idx,
                    "chunk_type": base_metadata.get("chunk_type") or "text_chunk",
                }
            )
    return rows


async def ingest_rows(
    rows: list[dict[str, Any]],
    settings: Settings,
    *,
    collection: str,
    batch_size: int,
    recreate: bool = False,
) -> dict[str, Any]:
    if not rows:
        return {"status": "ok", "documents": 0, "chunks": 0}
    embedding = OpenAIEmbeddingAdapter(
        api_key=settings.embed_api_key,
        base_url=settings.embed_base_url,
        model=settings.embed_model,
    )
    milvus = MilvusManager(
        host=settings.milvus_host,
        port=str(settings.milvus_port),
        user=settings.milvus_user or None,
        password=settings.milvus_password or None,
    )
    if recreate:
        await milvus.drop_collection(collection)

    dim = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        vectors = await embedding.embed_texts([str(row["text"]) for row in batch])
        if vectors and not dim:
            dim = len(vectors[0])
            await milvus.create_collection(collection, dim=dim)
        await milvus.insert(collection, vectors, batch)
    return {"status": "ok", "chunks": len(rows), "dim": dim}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest benchmark corpus JSONL into Milvus")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--chunk-size", type=int, default=768)
    parser.add_argument("--chunk-overlap", type=int, default=96)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--confirmed", action="store_true")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="drop and recreate the target collection; only takes effect with --confirmed",
    )
    return parser.parse_args()


async def _amain() -> int:
    args = parse_args()
    docs = load_docs(args.corpus)
    rows = build_rows(docs, chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap)
    settings = get_settings()
    collection = args.collection or settings.milvus_collection_name
    plan = {
        "status": "dry_run" if not args.confirmed else "ok",
        "corpus": str(args.corpus),
        "collection": collection,
        "documents": len(docs),
        "chunks": len(rows),
        "chunk_size": args.chunk_size,
        "chunk_overlap": args.chunk_overlap,
        "recreate": bool(args.recreate and args.confirmed),
    }
    if not args.confirmed:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    result = await ingest_rows(
        rows,
        settings,
        collection=collection,
        batch_size=args.batch_size,
        recreate=args.recreate,
    )
    print(json.dumps({**plan, **result}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
