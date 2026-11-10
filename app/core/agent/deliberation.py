# -*- coding: utf-8 -*-
"""
多视角审议(旗舰编排模式)。

流程(D1 → D2 → D3):
  D1 共享检索:用 query 在平台 MultiRetriever 检一次 → 共享上下文(空也能继续)
  D2 并行评议:asyncio.gather N 个 participant,各出立场观点
       单个失败 → 该立场缺席,不整批失败;全失败 → success=False
  D3 综合:LLM 综合全部立场观点 → 答复

平台对立场数量与内容**完全无知**:只认 ``DeliberationSpec``。金融填 bull/bear,
换领域换 participants,本模块一行不改 —— 这是「泛化为平台模式」的兑现。
不挂反思门槛、不调 Firecrawl、不画图、不做 web_search。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Protocol, Sequence

from app.core.agent.react_agent import AgentResult
from app.domains.base import DeliberationSpec

logger = logging.getLogger(__name__)


class DeliberationLLM(Protocol):
    """审议所需的 LLM 接口(与 react_agent.LLMCallable 一致)。"""

    async def acomplete(self, messages: Sequence[Dict[str, str]], **kwargs: Any) -> str:
        ...


class _RetrieverLike(Protocol):
    async def retrieve(self, query: str, top_k: int = ..., mode: str = ...) -> List[Any]:
        ...


# ---------------------------------------------------------------------------
# D1 共享检索
# ---------------------------------------------------------------------------
async def _shared_retrieve(
    query: str,
    retriever: Optional[_RetrieverLike],
    top_k: int,
) -> tuple[str, List[Dict[str, Any]]]:
    """D1:检一次共享上下文。失败/空都返回空串,不阻断。"""
    if retriever is None:
        return "", [{"phase": "d1", "note": "retriever 未注入,空上下文"}]
    try:
        results = await retriever.retrieve(query, top_k=top_k, mode="hybrid")
    except Exception as e:  # noqa: BLE001
        logger.warning("D1 共享检索失败,以空上下文继续: %s", e)
        return "", [{"phase": "d1", "error": str(e)}]

    if not results:
        return "", [{"phase": "d1", "hits": 0}]

    blocks: list[str] = []
    for i, r in enumerate(results, 1):
        blocks.append(f"[{i}] (source={getattr(r, 'source', '?')})\n{getattr(r, 'content', '')}")
    shared = "\n\n".join(blocks)
    return shared, [{"phase": "d1", "hits": len(results)}]


# ---------------------------------------------------------------------------
# D2 单个 participant 评议
# ---------------------------------------------------------------------------
async def _participant_view(
    participant,  # ParticipantSpec
    query: str,
    shared_context: str,
    llm: DeliberationLLM,
) -> Dict[str, Any]:
    """D2 单个立场评议。失败返回 ok=False,不抛出。"""
    user_msg = (
        f"## 共享上下文(检索片段)\n{shared_context or '(无)'}\n\n"
        f"## 分析对象 / 问题\n{query}\n\n"
        f"请基于上述上下文,严格按你的立场与输出格式给出分析。"
    )
    messages = [
        {"role": "system", "content": participant.stance_prompt},
        {"role": "user", "content": user_msg},
    ]
    try:
        text = await llm.acomplete(messages, temperature=participant.temperature)
        return {"role": participant.role, "ok": True, "view": text}
    except Exception as e:  # noqa: BLE001
        logger.warning("D2 立场 %s 评议失败,该立场缺席: %s", participant.role, e)
        return {"role": participant.role, "ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# D3 综合
# ---------------------------------------------------------------------------
async def _synthesize(
    spec: DeliberationSpec,
    query: str,
    shared_context: str,
    views: List[Dict[str, Any]],
    llm: DeliberationLLM,
) -> str:
    """D3:综合各立场观点。"""
    views_block = "\n\n".join(
        f"### 立场:{v['role']}\n{v['view']}" for v in views if v.get("ok")
    )
    absent = [v["role"] for v in views if not v.get("ok")]
    absence_note = f"\n\n(缺席立场:{', '.join(absent)})" if absent else ""

    user_msg = (
        f"## 原始问题\n{query}\n\n"
        f"## 共享上下文(检索片段)\n{shared_context or '(无)'}\n\n"
        f"## 各立场分析{absence_note}\n{views_block}\n\n"
        f"请综合以上各方观点,给出平衡、有数据出处的最终分析。"
    )
    messages = [
        {"role": "system", "content": spec.synthesis_prompt},
        {"role": "user", "content": user_msg},
    ]
    return await llm.acomplete(messages, temperature=spec.synthesis_temperature)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
async def run_deliberation(
    *,
    query: str,
    spec: DeliberationSpec,
    llm: DeliberationLLM,
    retriever: Optional[_RetrieverLike] = None,
    trace_id: Optional[str] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    log_event=None,
) -> AgentResult:
    """执行多视角审议:D1 → D2 → D3,返回 AgentResult。"""
    steps = steps if steps is not None else []

    def _log(name: str, payload: Dict[str, Any]) -> None:
        steps.append({"ts": time.time(), **payload})
        if log_event is not None and trace_id is not None:
            try:
                log_event(trace_id, name, payload)
            except Exception:  # noqa: BLE001
                pass

    # D1
    _log("deliberation.d1.begin", {"participants": len(spec.participants)})
    shared_context, d1_info = await _shared_retrieve(query, retriever, spec.shared_retrieve_top_k)
    for info in d1_info:
        _log("deliberation.d1.done", info)

    # D2 并行评议
    _log("deliberation.d2.begin", {})
    tasks = [_participant_view(p, query, shared_context, llm) for p in spec.participants]
    views = await asyncio.gather(*tasks, return_exceptions=False)
    ok_views = [v for v in views if v.get("ok")]
    _log(
        "deliberation.d2.done",
        {"ok": len(ok_views), "failed": len(views) - len(ok_views), "roles": [v["role"] for v in views]},
    )

    if not ok_views:
        _log("deliberation.failed", {"reason": "all participants failed"})
        return AgentResult(
            success=False,
            final_answer="",
            steps=steps,
            error="所有立场评议均失败,无法综合。",
            trace_id=trace_id,
        )

    # D3 综合
    _log("deliberation.d3.begin", {"synthesizing": len(ok_views)})
    try:
        answer = await _synthesize(spec, query, shared_context, views, llm)
    except Exception as e:  # noqa: BLE001
        logger.exception("D3 综合失败")
        _log("deliberation.d3.error", {"error": str(e)})
        return AgentResult(
            success=False,
            final_answer="",
            steps=steps,
            error=f"综合阶段失败: {e}",
            trace_id=trace_id,
        )

    _log("deliberation.d3.done", {"answer_len": len(answer)})
    return AgentResult(success=True, final_answer=answer, steps=steps, trace_id=trace_id)


__all__ = ["run_deliberation", "DeliberationLLM"]
