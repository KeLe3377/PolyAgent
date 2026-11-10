# -*- coding: utf-8 -*-
"""对话 API:经编排器(AgentOrchestrator)+ 领域 Skill 分派,支持三模式。"""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from openai import AsyncOpenAI

from app.config import get_settings
from app.core.agent.orchestrator import AgentOrchestrator, IntentContext
from app.core.intent.recognizer import IntentRecognizer
from app.core.tools.registry import ToolRegistry
from app.domains.base import DomainContext
from app.domains.registry import DomainRegistry
from app.infrastructure.trace.tracer import Tracer
from app.models.schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])

_tracer = Tracer()
_intent = IntentRecognizer()


# ---------------------------------------------------------------------------
# 从 app.state 取编排器 / 注册表(Codex 在 lifespan 装配;未装配时 503)
# ---------------------------------------------------------------------------
def _get_orchestrator(request: Request) -> AgentOrchestrator:
    orchestrator: AgentOrchestrator | None = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="编排器未装配(lifespan 未注入 app.state.orchestrator)")
    return orchestrator


def _get_registry(request: Request) -> DomainRegistry:
    registry: DomainRegistry | None = getattr(request.app.state, "registry", None)
    if registry is None:
        registry = DomainRegistry()
        registry.scan()
        request.app.state.registry = registry
    return registry


def _resolve_mode(request: ChatRequest, pack, intent_ctx: IntentContext) -> str:
    """模式优先级:请求显式 mode > 领域 Skill intent_hints > default_mode。"""
    if request.mode:
        return request.mode
    hints = pack.intent_hints()
    if hints:
        via_intent = hints.intent_overrides.get(intent_ctx.intent)
        via_sub = hints.intent_overrides.get(intent_ctx.slots.get("sub_intent") or "")
        if via_intent:
            return via_intent
        if via_sub:
            return via_sub
    return pack.default_mode


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
    """非流式对话:意图→取领域 Skill→编排器选模式→返回。"""
    trace_id = str(uuid.uuid4())
    span = _tracer.start_trace(trace_id, "chat")

    try:
        orchestrator = _get_orchestrator(http_request)
        registry = _get_registry(http_request)

        pack = registry.get(request.domain)
        if pack is None:
            available = registry.list_domains()
            raise HTTPException(
                status_code=404,
                detail=f"未知领域: {request.domain!r},可用: {available}",
            )

        user_text = request.messages[-1].content if request.messages else ""
        session_id = request.conversation_id or str(uuid.uuid4())

        # 意图识别 + 模式分派
        intent_result = await _intent.recognize(user_text)
        intent_ctx = IntentContext(
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            slots=intent_result.slots,
        )
        mode = _resolve_mode(request, pack, intent_ctx)

        # 领域 Skill 工具(按运行时依赖构建)→ 请求级 ToolRegistry
        domain_ctx = DomainContext(
            retriever=getattr(http_request.app.state, "retriever", None),
            memory=getattr(http_request.app.state, "memory", None),
        )
        tool_registry = ToolRegistry()
        for tool in pack.tools(domain_ctx):
            tool_registry.register(tool)

        # deliberation 需要 spec
        deliberation_spec = None
        if mode == "deliberation":
            deliberation_spec = pack.deliberation_spec()
            if deliberation_spec is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"领域 {pack.name} 不支持 deliberation 模式",
                )

        logger.info(
            "chat domain={} mode={} intent={} session={}",
            pack.name, mode, intent_result.intent, session_id,
        )

        agent_resp = await orchestrator.run(
            user_text,
            session_id,
            mode=mode,
            intent=intent_ctx,
            deliberation_spec=deliberation_spec,
            tool_registry=tool_registry,
        )

        _tracer.end_span(
            span,
            result={"mode": agent_resp.mode_used, "success": agent_resp.success},
        )

        return ChatResponse(
            id=str(uuid.uuid4()),
            content=agent_resp.answer,
            trace_id=agent_resp.trace_id,
            mode_used=agent_resp.mode_used,
            domain=pack.name,
            success=agent_resp.success,
            degraded=agent_resp.degraded,
            steps=agent_resp.steps,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("chat 失败: {}", exc)
        _tracer.end_span(span, error=str(exc))
        raise HTTPException(status_code=500, detail=f"对话失败: {exc!s}") from exc


# ---------------------------------------------------------------------------
# 流式(SSE):非旗舰,目前直连 LLM。后续可改为编排器事件流。
# ---------------------------------------------------------------------------
def _llm_settings():
    """兼容 env 字段改名(openai_* → llm_*,由 P1 落地)。"""
    s = get_settings()
    api_key = getattr(s, "llm_api_key", None) or getattr(s, "openai_api_key", "")
    base_url = getattr(s, "llm_base_url", None) or getattr(s, "openai_api_base", None)
    model = getattr(s, "llm_model", None) or getattr(s, "openai_model", None)
    return api_key, base_url, model


async def _stream_generator(request: ChatRequest, trace_id: str) -> AsyncIterator[bytes]:
    """SSE 风格流:每行 data: {json}\\n\\n。"""
    api_key, base_url, model_default = _llm_settings()
    if not api_key:
        yield b"data: " + json.dumps({"error": "未配置 API Key"}, ensure_ascii=False).encode() + b"\n\n"
        return

    client = AsyncOpenAI(api_key=api_key, base_url=base_url or None)
    messages = [m.model_dump() for m in request.messages]
    model = request.model or model_default

    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                payload = {"content": delta, "trace_id": trace_id}
                yield b"data: " + json.dumps(payload, ensure_ascii=False).encode() + b"\n\n"
        yield b"data: " + json.dumps({"done": True}, ensure_ascii=False).encode() + b"\n\n"
    except Exception as exc:
        logger.exception("chat_stream 失败: {}", exc)
        yield b"data: " + json.dumps({"error": str(exc)}, ensure_ascii=False).encode() + b"\n\n"


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """流式输出(Server-Sent Events 兼容格式)。"""
    trace_id = str(uuid.uuid4())
    span = _tracer.start_trace(trace_id, "chat_stream")
    _tracer.end_span(span, result={"mode": "stream"})

    return StreamingResponse(
        _stream_generator(request, trace_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Trace-Id": trace_id,
        },
    )
