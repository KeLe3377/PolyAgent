# -*- coding: utf-8 -*-
"""ContractClauseLocator —— CUAD 长合同条款定位工具。

RAG 质量升级(2026-08-11):CUAD 合同问题高度同质化,真正关键是
``contract_name`` / ``clause_type``。当前只做 domain_filter,法律域内部
不同合同/不同条款仍互相干扰。本工具在 rag_search 召回的候选片段内,按
``contract_name`` 与 ``clause_type`` 做确定性过滤,输出 ``matched_clauses``。

设计取舍:
- **纯确定性**:输入是候选片段(JSON 列表,通常由 agent 传入 rag_search 的
  observation),输出 JSON。不调 LLM,可独立单测。
- **容错解析**:候选可以是 ``[{"metadata": {...}, "text": "..."}]``,也可以是
  rag_search 返回的纯文本块(带 ``doc_id=..., source=...`` 头)——后者按工具
  输出格式回解出 doc_id/source。
- **不绑基础设施**:无 retriever/llm 依赖。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.tools.base import BaseTool, ToolParameter

logger = logging.getLogger(__name__)


# rag_search 输出形如:"[1] (score=0.12, doc_id=xxx, source=yyy)\n<content>"
_OBS_HEADER = re.compile(r"doc_id=([^,)]+)")
_OBS_SOURCE = re.compile(r"source=([^)]+)\)")


def _normalize(text: str | None) -> str:
    if text is None:
        return ""
    return " ".join(str(text).split()).strip().strip(".")


def _parse_candidates(raw: Any) -> list[dict[str, Any]]:
    """把多种候选形态统一成 ``[{metadata, text}]`` 列表。"""
    if raw is None:
        return []
    items: list[Any] = []
    if isinstance(raw, (list, tuple)):
        items = list(raw)
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        parsed: Any = None
        if s.startswith("[") or s.startswith("{"):
            try:
                parsed = json.loads(s)
            except json.JSONDecodeError:
                parsed = None  # 可能是 rag_search 文本输出(以 "[1] ..." 开头),走文本分支
        if parsed is not None:
            items = parsed if isinstance(parsed, list) else [parsed]
        else:
            # rag_search 的纯文本输出:按空行切块
            blocks = re.split(r"\n\s*\n", s)
            items = []
            for block in blocks:
                block = block.strip()
                if not block:
                    continue
                header_match = _OBS_HEADER.search(block)
                source_match = _OBS_SOURCE.search(block)
                meta: dict[str, Any] = {}
                if header_match:
                    meta["doc_id"] = header_match.group(1).strip()
                if source_match:
                    meta["source"] = source_match.group(1).strip()
                # 去掉首行头部 "[i] (...)"
                text = re.sub(r"^\[\d+\]\s*\([^)]*\)\s*\n?", "", block).strip()
                items.append({"metadata": meta, "text": text})
    else:
        raise _LocateError(f"candidates 类型不支持: {type(raw).__name__}")

    rows: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        if isinstance(item, dict):
            meta = dict(item.get("metadata") or {})
            text = str(item.get("text") or item.get("content") or "")
            rows.append({"metadata": meta, "text": text})
        elif isinstance(item, str):
            rows.append({"metadata": {}, "text": item})
        else:
            raise _LocateError(f"candidates[{i}] 不是对象或字符串: {item!r}")
    return rows


def _meta_get(row: dict[str, Any], key: str) -> str:
    meta = row.get("metadata") or {}
    return _normalize(meta.get(key))


class ContractClauseLocatorTool(BaseTool):
    """在候选片段内按 contract_name / clause_type 过滤的确定性工具。

    参数:
        - ``candidates``:rag_search 召回的候选片段(JSON 列表,或带 doc_id 头的文本块)。
        - ``contract_name``:目标合同名(子串匹配,大小写/空白/标点不敏感)。
        - ``clause_type``:目标条款类别(归一化后相等)。
        - ``top_n``:最多返回多少条(默认 5)。
    """

    name = "contract_clause_locator"
    description = (
        "在候选检索片段中按 contract_name / clause_type 精确定位合同条款,"
        "输出 matched_clauses,避免长合同互相干扰。"
    )

    def __init__(self) -> None:
        super().__init__()
        self.parameters = [
            ToolParameter(
                name="candidates",
                type="string",
                description="候选片段(JSON 列表 或 rag_search 文本输出)",
                required=True,
            ),
            ToolParameter(
                name="contract_name", type="string", description="目标合同名(可选)", required=False
            ),
            ToolParameter(
                name="clause_type", type="string", description="目标条款类别(可选)", required=False
            ),
            ToolParameter(
                name="top_n", type="integer", description="最多返回条数(默认 5)", required=False
            ),
        ]

    async def execute(self, **kwargs: Any) -> str:
        contract_name = _normalize(str(kwargs.get("contract_name") or ""))
        clause_type = _normalize(str(kwargs.get("clause_type") or ""))
        top_n_raw = kwargs.get("top_n")
        try:
            top_n = int(top_n_raw) if top_n_raw not in (None, "") else 5
        except (TypeError, ValueError):
            top_n = 5

        try:
            candidates = _parse_candidates(kwargs.get("candidates"))
        except _LocateError as e:
            return self._err(str(e))

        if not candidates:
            return json.dumps(
                {"ok": True, "matched_clauses": [], "matched_count": 0, "filters": _filters(contract_name, clause_type)},
                ensure_ascii=False,
            )

        matched: list[dict[str, Any]] = []
        for row in candidates:
            row_contract = _meta_get(row, "contract_name") or _meta_get(row, "doc_id")
            row_clause = _meta_get(row, "clause_type")
            if contract_name and _normalize(row_contract) != contract_name:
                # 退化为子串匹配(合同标题常带后缀/版本号)
                if contract_name.lower() not in _normalize(row_contract).lower():
                    continue
            if clause_type and _normalize(row_clause) != clause_type:
                continue
            matched.append(
                {
                    "contract_name": row_contract,
                    "clause_type": row_clause,
                    "doc_id": _meta_get(row, "doc_id"),
                    "text": (row.get("text") or "").strip(),
                }
            )

        matched = matched[: max(0, top_n)]
        payload = {
            "ok": True,
            "filters": _filters(contract_name, clause_type),
            "matched_count": len(matched),
            "matched_clauses": matched,
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _err(message: str) -> str:
        return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _filters(contract_name: str, clause_type: str) -> dict[str, Any]:
    return {
        "contract_name": contract_name or None,
        "clause_type": clause_type or None,
    }


class _LocateError(Exception):
    """候选解析过程中的可向用户报告的错误。"""


__all__ = ["ContractClauseLocatorTool"]
