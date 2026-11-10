# -*- coding: utf-8 -*-
"""Ingest project-local domain Skill corpora into Milvus.

Default mode is a dry-run plan. Use --confirmed to perform the persistent write.
The script never prints secrets or connection strings.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings, get_settings
from app.etl.chunker import ChunkStrategy, DocumentChunker
from app.infrastructure.llm.embedding import OpenAIEmbeddingAdapter
from app.infrastructure.vectordb import MilvusManager
from app.domains.registry import DomainRegistry


@dataclass(frozen=True)
class CorpusItem:
    domain: str
    source_path: Path
    text: str


@dataclass(frozen=True)
class IngestPlan:
    domain: str | None
    items: list[CorpusItem]

    @property
    def file_count(self) -> int:
        return len(self.items)


def _iter_corpus_items(root: Path, domain: str | None) -> Iterable[CorpusItem]:
    registry = DomainRegistry(skills_root=root / "skills")
    registry.scan()
    domains = [domain] if domain else registry.list_domains()
    for domain_name in domains:
        skill = registry.get(domain_name)
        if skill is None or skill.name != domain_name:
            continue
        for doc in skill.corpus_docs():
            path = Path(doc.source)
            if path.is_file() and path.suffix.lower() in {".md", ".txt"}:
                yield CorpusItem(
                    domain=skill.name,
                    source_path=path,
                    text=path.read_text(encoding="utf-8"),
                )


def build_ingest_plan(root: Path, domain: str | None = None) -> IngestPlan:
    """Build a readonly corpus ingest plan."""
    items: list[CorpusItem] = []
    for item in _iter_corpus_items(root, domain):
        items.append(item)
    return IngestPlan(domain=domain, items=items)


def _chunk_id(domain: str, source: Path, index: int, text: str) -> str:
    raw = f"{domain}:{source.as_posix()}:{index}:{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


async def ingest_plan(plan: IngestPlan, settings: Settings) -> dict[str, int | str]:
    """Execute the persistent Milvus ingest for a previously built plan."""
    chunker = DocumentChunker()
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

    rows: list[tuple[str, str, str, str]] = []
    for item in plan.items:
        for idx, chunk in enumerate(chunker.chunk(item.text, strategy=ChunkStrategy.RECURSIVE)):
            rows.append((item.domain, str(item.source_path), _chunk_id(item.domain, item.source_path, idx, chunk), chunk))

    if not rows:
        return {"status": "ok", "files": plan.file_count, "chunks": 0}

    vectors = await embedding.embed_texts([row[3] for row in rows])
    dim = len(vectors[0]) if vectors else 0
    await milvus.create_collection(settings.milvus_collection_name, dim=dim)
    await milvus.insert(
        settings.milvus_collection_name,
        vectors,
        [
            {
                "id": chunk_id,
                "text": text,
                "domain": domain,
                "source": source,
            }
            for domain, source, chunk_id, text in rows
        ],
    )
    return {"status": "ok", "files": plan.file_count, "chunks": len(rows)}


def _plan_payload(plan: IngestPlan) -> dict[str, object]:
    return {
        "status": "dry_run",
        "domain": plan.domain,
        "files": [
            {"domain": item.domain, "path": str(item.source_path), "chars": len(item.text)}
            for item in plan.items
        ],
    }


async def _amain() -> int:
    parser = argparse.ArgumentParser(description="Ingest domain corpus into Milvus")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--domain", default=None)
    parser.add_argument("--confirmed", action="store_true", help="perform Milvus writes")
    args = parser.parse_args()

    root = args.root.resolve()
    plan = build_ingest_plan(root, domain=args.domain)
    if not args.confirmed:
        print(json.dumps(_plan_payload(plan), ensure_ascii=False, indent=2))
        return 0

    result = await ingest_plan(plan, get_settings())
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
