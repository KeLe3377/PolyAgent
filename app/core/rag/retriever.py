# -*- coding: utf-8 -*-
"""多路检索：向量（Milvus）、BM25 关键词、混合 + RRF 融合。"""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import re
from collections import defaultdict
from typing import Any, Protocol, runtime_checkable

from loguru import logger

from app.models.enums import RetrievalMode
from app.models.schemas import RetrievalResult
from app.core.rag.reranker import NoopReranker, Reranker
from app.core.rag.types import RetrievalRequest


@runtime_checkable
class EmbeddingProtocol(Protocol):
    """与 LangChain Embeddings 兼容的嵌入接口。"""

    def embed_query(self, text: str) -> list[float]:
        ...


@runtime_checkable
class MilvusSearchable(Protocol):
    """支持向量检索的 Milvus Collection 或兼容封装。"""

    def search(
        self,
        data: list[list[float]],
        anns_field: str,
        param: dict[str, Any],
        limit: int,
        output_fields: list[str] | None = None,
        **kwargs: Any,
    ) -> Any:
        ...


def _tokenize(text: str) -> list[str]:
    """简单中英文分词：按非字母数字 Unicode 切分。"""
    return [t.lower() for t in re.findall(r"[\w\u4e00-\u9fff]+", text) if t]


def _metadata_value(result: RetrievalResult, key: str) -> Any:
    if key == "id":
        return result.id
    if key == "source":
        return result.metadata.get("source") or result.source
    return result.metadata.get(key)


def _matches_value(actual: Any, expected: Any) -> bool:
    if expected is None:
        return True
    if isinstance(expected, (list, tuple, set)):
        return any(_matches_value(actual, item) for item in expected)
    if isinstance(actual, (list, tuple, set)):
        return any(_matches_value(item, expected) for item in actual)
    return str(actual).casefold() == str(expected).casefold()


def _matches_filters(result: RetrievalResult, filters: dict[str, Any]) -> bool:
    return all(_matches_value(_metadata_value(result, key), value) for key, value in filters.items())


def _apply_filters(results: list[RetrievalResult], filters: dict[str, Any]) -> list[RetrievalResult]:
    if not filters:
        return results
    return [result for result in results if _matches_filters(result, filters)]


def _quote_milvus_value(value: Any) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _milvus_expr(filters: dict[str, Any]) -> str | None:
    clauses: list[str] = []
    indexed_fields = {
        "id",
        "domain",
        "dataset",
        "doc_id",
        "chunk_type",
        "contract_name",
        "drug_name",
        "source",
    }
    for key in indexed_fields:
        if key not in filters:
            continue
        value = filters[key]
        if isinstance(value, (list, tuple, set)):
            values = ", ".join(_quote_milvus_value(item) for item in value)
            clauses.append(f"{key} in [{values}]")
        else:
            clauses.append(f"{key} == {_quote_milvus_value(value)}")
    return " and ".join(clauses) if clauses else None


def _parse_metadata(raw_metadata: Any) -> dict[str, Any]:
    if isinstance(raw_metadata, dict):
        return dict(raw_metadata)
    if isinstance(raw_metadata, str) and raw_metadata.strip():
        try:
            parsed = json.loads(raw_metadata)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {"metadata_raw": raw_metadata}
    return {}


class _BM25Index:
    """内存 BM25（Okapi）索引，用于关键词检索。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._doc_ids: list[str] = []
        self._documents: list[str] = []
        self._doc_freqs: list[dict[str, int]] = []
        self._doc_lens: list[int] = []
        self._avgdl: float = 0.0
        self._df: defaultdict[str, int] = defaultdict(int)
        self._N: int = 0
        self._idf: dict[str, float] = {}

    def clear(self) -> None:
        """清空索引。"""
        self._doc_ids.clear()
        self._documents.clear()
        self._doc_freqs.clear()
        self._doc_lens.clear()
        self._avgdl = 0.0
        self._df.clear()
        self._N = 0
        self._idf.clear()

    def add_document(self, doc_id: str, text: str) -> None:
        """添加文档并更新统计量。"""
        tokens = _tokenize(text)
        tf: defaultdict[str, int] = defaultdict(int)
        for t in tokens:
            tf[t] += 1
        for t in tf:
            self._df[t] += 1
        self._doc_ids.append(doc_id)
        self._documents.append(text)
        self._doc_freqs.append(dict(tf))
        self._doc_lens.append(len(tokens))
        self._N += 1
        dl_sum = sum(self._doc_lens)
        self._avgdl = dl_sum / self._N if self._N else 0.0
        # 重新计算 IDF（对当前语料）
        self._idf = {}
        for term, df in self._df.items():
            # 平滑 IDF
            self._idf[term] = math.log(1.0 + (self._N - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        """返回 (doc_id, bm25_score) 降序。"""
        if self._N == 0:
            return []
        q_terms = _tokenize(query)
        if not q_terms:
            return []
        scores: dict[str, float] = {}
        for i, doc_id in enumerate(self._doc_ids):
            tf = self._doc_freqs[i]
            dl = self._doc_lens[i]
            s = 0.0
            for term in q_terms:
                if term not in tf:
                    continue
                idf = self._idf.get(term, 0.0)
                f = tf[term]
                denom = f + self.k1 * (1 - self.b + self.b * dl / (self._avgdl or 1.0))
                s += idf * (f * (self.k1 + 1)) / denom
            if s > 0:
                scores[doc_id] = s
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return ranked


class MultiRetriever:
    """多路检索引擎：支持向量检索 + BM25 关键词检索 + 混合检索（RRF）。"""

    # Milvus 常见字段名，若集合不同可通过类属性或实例赋值覆盖（与 Schema 一致）
    anns_field: str = "embedding"
    text_field: str = "text"
    id_field: str = "id"

    # 向量检索参数
    metric_param: dict[str, Any] = {"metric_type": "L2", "params": {"nprobe": 16}}

    def __init__(
        self,
        milvus_client: Any,
        embedding_model: Any,
        *,
        collection_name: str = "agent_knowledge",
        reranker: Reranker | None = None,
    ) -> None:
        """
        :param milvus_client: pymilvus Collection 或实现 ``search`` 的兼容对象
        :param embedding_model: 含 ``embed_query(str) -> list[float]`` 的嵌入模型
        """
        self._milvus = milvus_client
        self._embed = embedding_model
        self._collection_name = collection_name
        self._reranker = reranker or NoopReranker()
        self._bm25 = _BM25Index()
        # doc_id -> 全文，用于 BM25 结果组装
        self._id_to_text: dict[str, str] = {}
        self._id_to_metadata: dict[str, dict[str, Any]] = {}
        self._rrf_k: int = 60

    def register_keyword_documents(
        self,
        id_to_text: dict[str, str],
        id_to_metadata: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """
        注册用于 BM25 的文档（通常与向量库中的分块 ID 一致）。

        :param id_to_text: 文档 ID 到文本的映射
        """
        self._bm25.clear()
        self._id_to_text.clear()
        self._id_to_metadata.clear()
        for did, text in id_to_text.items():
            self._bm25.add_document(did, text)
            self._id_to_text[did] = text
            self._id_to_metadata[did] = dict((id_to_metadata or {}).get(did, {}))
        logger.info("BM25 索引已更新，文档数: {}", len(id_to_text))

    async def retrieve(
        self,
        query: str | RetrievalRequest,
        top_k: int = 10,
        mode: str = "hybrid",
        *,
        domain: str | None = None,
        dataset: str | None = None,
        filters: dict[str, Any] | None = None,
        top_n: int | None = None,
        rerank: bool | None = None,
    ) -> list[RetrievalResult]:
        """执行检索。"""
        request = self._coerce_request(
            query,
            top_k=top_k,
            mode=mode,
            domain=domain,
            dataset=dataset,
            filters=filters,
            top_n=top_n,
            rerank=rerank,
        )
        mode_norm = request.mode.lower().strip()
        try:
            rm = RetrievalMode(mode_norm)
        except ValueError:
            logger.warning("未知检索模式 {}，回退为 hybrid", request.mode)
            rm = RetrievalMode.HYBRID

        first_stage_k = max(request.top_n, request.top_k)
        merged_filters = request.merged_filters()
        if rm == RetrievalMode.VECTOR:
            results = await self.vector_search(request.query, first_stage_k, filters=merged_filters)
            return await self._maybe_rerank(request.query, results, request.top_k, request.rerank)
        if rm == RetrievalMode.KEYWORD:
            results = await self.keyword_search(request.query, first_stage_k, filters=merged_filters)
            return await self._maybe_rerank(request.query, results, request.top_k, request.rerank)
        return await self.hybrid_search(
            request.query,
            top_k=request.top_k,
            top_n=first_stage_k,
            filters=merged_filters,
            rerank=request.rerank,
        )

    def _coerce_request(
        self,
        query: str | RetrievalRequest,
        *,
        top_k: int,
        mode: str,
        domain: str | None,
        dataset: str | None,
        filters: dict[str, Any] | None,
        top_n: int | None,
        rerank: bool | None,
    ) -> RetrievalRequest:
        if isinstance(query, RetrievalRequest):
            return query
        return RetrievalRequest(
            query=query,
            domain=domain,
            dataset=dataset,
            filters=filters or {},
            mode=mode,
            top_n=top_n or max(top_k, 50),
            top_k=top_k,
            rerank=True if rerank is None else rerank,
        )

    async def vector_search(
        self,
        query: str,
        top_k: int,
        *,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalResult]:
        """向量语义检索。"""
        if not isinstance(self._embed, EmbeddingProtocol):
            raise TypeError("embedding_model 需实现 embed_query 方法")

        def _sync_embed() -> list[float]:
            return self._embed.embed_query(query)

        try:
            vector = await asyncio.to_thread(_sync_embed)
        except Exception as e:
            logger.exception("向量编码失败: {}", e)
            raise RuntimeError(f"向量编码失败: {e}") from e

        if not vector:
            raise RuntimeError("嵌入向量为空")

        try:
            results = await self._search_milvus(vector, top_k, filters=filters or {})
            return _apply_filters(results, filters or {})
        except Exception as e:
            logger.exception("Milvus 向量检索失败: {}", e)
            raise RuntimeError(f"向量检索失败: {e}") from e

    async def _search_milvus(
        self,
        vector: list[float],
        top_k: int,
        *,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalResult]:
        """同步 Milvus 查询并封装为 RetrievalResult。"""
        coll = self._milvus
        search_fn = getattr(coll, "search", None)
        if not callable(search_fn):
            raise TypeError("milvus_client 需实现 search 方法")

output_fields = [
            self.text_field,
            self.id_field,
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
        ]
        expr = _milvus_expr(filters or {})
        if inspect.iscoroutinefunction(search_fn):
            raw = await search_fn(
                self._collection_name,
                vector,
                top_k=top_k,
                params=self.metric_param,
                output_fields=output_fields,
                expr=expr,
            )
        elif isinstance(coll, MilvusSearchable):
            raw = await asyncio.to_thread(
                search_fn,
                data=[vector],
                anns_field=self.anns_field,
                param=self.metric_param,
                limit=top_k,
                output_fields=output_fields,
                expr=expr,
            )
        else:
            raw = await asyncio.to_thread(
                search_fn,
                self._collection_name,
                vector,
                top_k,
                params=self.metric_param,
                output_fields=output_fields,
                expr=expr,
            )
        results: list[RetrievalResult] = []
        hits = raw[0] if raw and not isinstance(raw[0], dict) else raw
        for rank, hit in enumerate(hits):
            entity: dict[str, Any] = hit if isinstance(hit, dict) else getattr(hit, "entity", None) or {}
            if not isinstance(hit, dict) and hasattr(hit, "entity"):
                try:
                    entity = hit.entity.to_dict()  # type: ignore[assignment]
                except Exception:
                    entity = getattr(hit, "entity", {})
            # 距离 / 分数：distance 越小越好（L2）；IP 越大越好
            score = float(entity.get("distance", getattr(hit, "distance", 0.0)) or 0.0)
            # 统一为「越大越好」：对 L2 做简单反转（仅用于展示）
            text = entity.get(self.text_field) or entity.get("text") or ""
            rid = str(entity.get(self.id_field) or entity.get("id") or getattr(hit, "id", ""))
metadata = _parse_metadata(entity.get("metadata"))
            if entity.get("domain"):
                metadata.setdefault("domain", entity.get("domain"))
            if entity.get("source"):
                metadata.setdefault("source", entity.get("source"))
            for key in (
                "dataset",
                "doc_id",
                "chunk_type",
                "contract_name",
                "clause_type",
                "drug_name",
                "year",
            ):
                if entity.get(key):
                    metadata.setdefault(key, entity.get(key))
            metadata.setdefault("doc_id", metadata.get("doc_id") or rid)
            metadata.setdefault("rank", rank)
            results.append(
                RetrievalResult(
                    id=rid,
                    content=str(text),
                    score=score,
metadata=metadata,
                    source="vector",
                )
            )
        return results

    async def keyword_search(
        self,
        query: str,
        top_k: int,
        *,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalResult]:
        """BM25 关键词检索（需先 register_keyword_documents）。"""
        def _run() -> list[RetrievalResult]:
            ranked = self._bm25.search(query, top_k)
            out: list[RetrievalResult] = []
            for doc_id, sc in ranked:
                text = self._id_to_text.get(doc_id, "")
                metadata = dict(self._id_to_metadata.get(doc_id, {}))
                metadata.setdefault("doc_id", metadata.get("doc_id") or doc_id)
                out.append(
                    RetrievalResult(
                        id=doc_id,
                        content=text,
                        score=float(sc),
                        metadata=metadata,
                        source="keyword",
                    )
                )
            return _apply_filters(out, filters or {})

        try:
            return await asyncio.to_thread(_run)
        except Exception as e:
            logger.exception("BM25 检索失败: {}", e)
            raise RuntimeError(f"BM25 检索失败: {e}") from e

    def _rrf_fuse(
        self,
        lists: list[list[RetrievalResult]],
        top_k: int,
    ) -> list[RetrievalResult]:
        """倒数排名融合（RRF），按 id 合并多路结果。"""
        scores: dict[str, float] = {}
        id_best: dict[str, RetrievalResult] = {}
        k = self._rrf_k
        for lst in lists:
            for rank, item in enumerate(lst):
                rid = item.id
                scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank + 1)
                if rid not in id_best or item.score > id_best[rid].score:
                    id_best[rid] = item
        merged_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:top_k]
        merged: list[RetrievalResult] = []
        for rid in merged_ids:
            base = id_best[rid].model_copy(deep=True)
            base.score = scores[rid]
            base.metadata = {**base.metadata, "rrf": scores[rid]}
            base.source = "hybrid"
            merged.append(base)
        return merged

    async def _maybe_rerank(
        self,
        query: str,
        candidates: list[RetrievalResult],
        top_k: int,
        enabled: bool,
    ) -> list[RetrievalResult]:
        if not enabled or not candidates:
            return candidates[:top_k]
        return await self._reranker.rerank(query, candidates, top_k=top_k)

    async def hybrid_search(
        self,
        query: str,
        top_k: int,
        *,
        top_n: int | None = None,
        filters: dict[str, Any] | None = None,
        rerank: bool = True,
    ) -> list[RetrievalResult]:
        """混合检索：并行向量 + BM25，RRF 融合。"""
        first_stage_k = top_n or max(top_k, 50)
        vec_task = self.vector_search(query, first_stage_k, filters=filters)
        kw_task = self.keyword_search(query, first_stage_k, filters=filters)
        vec_res, kw_res = await asyncio.gather(vec_task, kw_task, return_exceptions=True)

        lists: list[list[RetrievalResult]] = []
        if isinstance(vec_res, list):
            lists.append(vec_res)
        else:
            logger.error("向量检索分支失败: {}", vec_res)
        if isinstance(kw_res, list) and kw_res:
            lists.append(kw_res)
        elif isinstance(kw_res, Exception):
            logger.error("关键词检索分支失败: {}", kw_res)

        if not lists:
            return []
        if len(lists) == 1:
            return await self._maybe_rerank(query, lists[0], top_k, rerank)
        fused = self._rrf_fuse(lists, first_stage_k)
        return await self._maybe_rerank(query, fused, top_k, rerank)
