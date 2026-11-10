# -*- coding: utf-8 -*-
"""Milvus 向量库管理器：集合生命周期与向量检索封装。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

try:
    from pymilvus import (
        Collection,
        CollectionSchema,
        DataType,
        FieldSchema,
        connections,
        utility,
    )
except ImportError:  # pragma: no cover
    Collection = Any  # type: ignore[misc, assignment]
    CollectionSchema = Any  # type: ignore[misc, assignment]
    DataType = Any  # type: ignore[misc, assignment]
    FieldSchema = Any  # type: ignore[misc, assignment]
    connections = Any  # type: ignore[misc, assignment]
    utility = Any  # type: ignore[misc, assignment]


def _run_sync(func, *args, **kwargs):
    """在线程池中执行同步 Milvus SDK 调用，避免阻塞事件循环。"""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, lambda: func(*args, **kwargs))


class MilvusManager:
    """Milvus 向量数据库管理器（异步包装同步 SDK）。"""

    def __init__(
        self,
        host: str = "localhost",
        port: str = "19530",
        alias: str = "default",
        **conn_kwargs: Any,
    ) -> None:
        self._host = host
        self._port = port
        self._alias = alias
        self._conn_kwargs = conn_kwargs
        self._connected = False

    async def _ensure_connection(self) -> None:
        if self._connected:
            return
        try:

            def _connect() -> None:
                connections.connect(
                    alias=self._alias,
                    host=self._host,
                    port=self._port,
                    **self._conn_kwargs,
                )

            await _run_sync(_connect)
            self._connected = True
            logger.info("已连接 Milvus {}:{}", self._host, self._port)
        except Exception as exc:
            logger.exception("连接 Milvus 失败: {}", exc)
            raise

    async def create_collection(self, name: str, dim: int) -> None:
        """创建向量集合；若已存在则跳过。"""
        await self._ensure_connection()

        def _create() -> None:
            if utility.has_collection(name, using=self._alias):
                logger.info("集合 [{}] 已存在，跳过创建", name)
                return
            fields = [
                FieldSchema(
                    name="id",
                    dtype=DataType.VARCHAR,
                    is_primary=True,
                    max_length=64,
                ),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=8192),
                FieldSchema(name="metadata", dtype=DataType.VARCHAR, max_length=8192),
                FieldSchema(name="domain", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="dataset", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=1024),
                FieldSchema(name="chunk_type", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="contract_name", dtype=DataType.VARCHAR, max_length=1024),
                FieldSchema(name="clause_type", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="drug_name", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="year", dtype=DataType.VARCHAR, max_length=32),
                FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=1024),
            ]
            schema = CollectionSchema(
                fields=fields,
                description=f"向量集合 {name}",
            )
            col = Collection(name, schema, using=self._alias)
            idx = {"index_type": "IVF_FLAT", "metric_type": "L2", "params": {"nlist": 128}}
            col.create_index(field_name="embedding", index_params=idx)
            logger.info("已创建集合 [{}] dim={}", name, dim)

        try:
            await _run_sync(_create)
        except Exception as exc:
            logger.exception("创建集合失败 name={}: {}", name, exc)
            raise

    async def insert(
        self,
        collection: str,
        vectors: list[list[float]],
        metadata: list[dict[str, Any]],
    ) -> list[str]:
        """插入向量与元数据；主键取自 metadata 中的 id 字段。"""
        await self._ensure_connection()
        if len(vectors) != len(metadata):
            raise ValueError("vectors 与 metadata 长度必须一致")

        ids: list[str] = []
        for i, m in enumerate(metadata):
            rid = m.get("id")
            if rid is None:
                rid = f"auto_{i}"
            ids.append(str(rid))

        def _insert() -> None:
            col = Collection(collection, using=self._alias)
            texts = [str(m.get("text", ""))[:8192] for m in metadata]
            metadata_json = [
                json.dumps({k: v for k, v in m.items() if k != "text"}, ensure_ascii=False)[:8192]
                for m in metadata
            ]
            domains = [str(m.get("domain", ""))[:128] for m in metadata]
            datasets = [str(m.get("dataset", ""))[:128] for m in metadata]
            doc_ids = [str(m.get("doc_id", ""))[:1024] for m in metadata]
            chunk_types = [str(m.get("chunk_type", ""))[:128] for m in metadata]
            contract_names = [str(m.get("contract_name", ""))[:1024] for m in metadata]
            clause_types = [str(m.get("clause_type", ""))[:256] for m in metadata]
            drug_names = [str(m.get("drug_name", ""))[:256] for m in metadata]
            years = [str(m.get("year", ""))[:32] for m in metadata]
            sources = [str(m.get("source", ""))[:1024] for m in metadata]
            try:
                col.insert([
                    ids,
                    vectors,
                    texts,
                    metadata_json,
                    domains,
                    datasets,
                    doc_ids,
                    chunk_types,
                    contract_names,
                    clause_types,
                    drug_names,
                    years,
                    sources,
                ])
            except Exception as exc:
                logger.warning("Milvus 新 schema 插入失败,尝试旧 schema: {}", exc)
                col.insert([ids, vectors, texts, metadata_json, domains, sources])
            col.flush()

        try:
            await _run_sync(_insert)
            return ids
        except Exception as exc:
            logger.exception("Milvus 插入失败 collection={}: {}", collection, exc)
            raise

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 10,
        **search_params: Any,
    ) -> list[dict[str, Any]]:
        """向量相似度检索，返回命中 id 与距离。"""
        await self._ensure_connection()
        params = search_params.get(
            "params",
            {"metric_type": "L2", "params": {"nprobe": 10}},
        )

        def _search():
            col = Collection(collection, using=self._alias)
            col.load()
            output_fields = search_params.get(
                "output_fields",
                [
                    "id",
                    "text",
                    "metadata",
                    "domain",
                    "dataset",
                    "doc_id",
                    "chunk_type",
                    "contract_name",
                    "clause_type",
                    "drug_name",
                    "year",
                    "source",
                ],
            )
            try:
                res = col.search(
                    data=[query_vector],
                    anns_field="embedding",
                    param=params,
                    limit=top_k,
                    expr=search_params.get("expr"),
                    output_fields=output_fields,
                )
            except Exception as exc:
                logger.warning("Milvus 新 schema 检索失败,尝试旧 schema: {}", exc)
                res = col.search(
                    data=[query_vector],
                    anns_field="embedding",
                    param=params,
                    limit=top_k,
                    output_fields=["id", "text", "metadata", "domain", "source"],
                )
            out: list[dict[str, Any]] = []
            for hits in res:
                for hit in hits:
                    entity = getattr(hit, "entity", {}) or {}
                    row = {
                        "id": entity.get("id"),
                        "text": entity.get("text", ""),
                        "metadata": entity.get("metadata", ""),
                        "domain": entity.get("domain", ""),
                        "source": entity.get("source", ""),
                        "distance": float(hit.distance),
                    }
                    for key in (
                        "dataset",
                        "doc_id",
                        "chunk_type",
                        "contract_name",
                        "clause_type",
                        "drug_name",
                        "year",
                    ):
                        value = entity.get(key)
                        if value is not None:
                            row[key] = value
                    out.append(
                        row
                    )
            return out

        try:
            return await _run_sync(_search)
        except Exception as exc:
            logger.exception("Milvus 检索失败 collection={}: {}", collection, exc)
            raise

    async def delete(self, collection: str, ids: list[str]) -> None:
        """按主键删除向量。"""
        await self._ensure_connection()
        if not ids:
            return

        expr = "id in [" + ", ".join(f'"{i}"' for i in ids) + "]"

        def _delete() -> None:
            col = Collection(collection, using=self._alias)
            col.delete(expr)

        try:
            await _run_sync(_delete)
        except Exception as exc:
            logger.exception("Milvus 删除失败 collection={}: {}", collection, exc)
            raise

    async def drop_collection(self, name: str) -> None:
        """删除集合；仅由显式 recreate/维护流程调用。"""
        await self._ensure_connection()

        def _drop() -> None:
            if utility.has_collection(name, using=self._alias):
                utility.drop_collection(name, using=self._alias)
                logger.info("已删除集合 [{}]", name)

        try:
            await _run_sync(_drop)
        except Exception as exc:
            logger.exception("删除集合失败 name={}: {}", name, exc)
            raise

    async def ping(self) -> bool:
        """Check Milvus connectivity without returning connection details."""
        try:
            await self._ensure_connection()
            await _run_sync(lambda: utility.list_collections(using=self._alias))
            return True
        except Exception as exc:
            logger.warning("Milvus 健康检查失败: {}", exc)
            return False
