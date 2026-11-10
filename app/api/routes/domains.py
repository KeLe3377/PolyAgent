# -*- coding: utf-8 -*-
"""领域 Skill 查询路由:列出已注册的项目内领域 Skill。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from loguru import logger

from app.domains.registry import DomainRegistry, DomainSummary

router = APIRouter(tags=["domains"])


def _get_registry(request: Request) -> DomainRegistry:
    """从 app.state 取注册表;lifespan 未装配时即时 scan 一个(便于早期联调)。"""
    registry: DomainRegistry | None = getattr(request.app.state, "registry", None)
    if registry is None:
        registry = DomainRegistry()
        registry.scan()
        request.app.state.registry = registry
    return registry


@router.get("/domains")
async def list_domains(request: Request) -> dict[str, Any]:
    """列出已注册领域 Skill(名称/版本/默认模式/是否支持多视角审议/是否有评测集)。"""
    registry = _get_registry(request)
    summaries: list[DomainSummary] = registry.summarize()
    default_pack = registry.default()
    return {
        "domains": [
            {
                "name": s.name,
                "version": s.version,
                "default_mode": s.default_mode,
                "supports_deliberation": s.supports_deliberation,
                "has_eval": s.has_eval,
                "tool_count": s.tool_count,
            }
            for s in summaries
        ],
        "default": default_pack.name if default_pack else None,
        "count": len(summaries),
    }


@router.get("/domains/{name}")
async def get_domain(name: str, request: Request) -> dict[str, Any]:
    """查询单个领域 Skill 详情。"""
    registry = _get_registry(request)
    pack = registry.get(name)
    if pack is None:
        return {"error": f"未知领域: {name}", "available": registry.list_domains()}
    spec = pack.deliberation_spec()
    return {
        "name": pack.name,
        "version": pack.version,
        "default_mode": pack.default_mode,
        "supports_deliberation": spec is not None,
        "deliberation_participants": (
            [p.role for p in spec.participants] if spec else []
        ),
        "has_eval": pack.eval_dataset() is not None,
        "system_prompt_preview": pack.system_prompt[:160],
    }
