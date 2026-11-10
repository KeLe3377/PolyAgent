# -*- coding: utf-8 -*-
"""健康检查：进程存活与依赖探测。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.infrastructure.database.session import get_async_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Health probe including core dependency connectivity."""
    checks = await _dependency_checks(request)
    status = "ok" if all(checks.values()) else "degraded"
    return {"status": status, "dependencies": checks}


@router.get("/health/ready")
async def health_ready(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """就绪探针：检查数据库连通性。"""
    settings = get_settings()
    checks = await _dependency_checks(request=request, session=session)

    return {
        "status": "ready" if all(checks.values()) else "degraded",
        "database": "up" if checks["postgres"] else "down",
        "dependencies": checks,
        "app_env": settings.app_env,
    }


async def _dependency_checks(
    request: Request | None = None,
    session: AsyncSession | None = None,
) -> dict[str, bool]:
    checks = {"milvus": False, "redis": False, "postgres": False}
    app = request.app if request is not None else None

    try:
        milvus = getattr(app.state, "milvus", None) if app is not None else None
        if milvus is not None and hasattr(milvus, "ping"):
            checks["milvus"] = bool(await milvus.ping())
    except Exception as exc:
        logger.warning("Milvus 健康检查异常: {}", exc)

    try:
        redis = getattr(app.state, "redis", None) if app is not None else None
        if redis is not None and hasattr(redis, "ping"):
            checks["redis"] = bool(await redis.ping())
    except Exception as exc:
        logger.warning("Redis 健康检查异常: {}", exc)

    try:
        if session is not None:
            await session.execute(text("SELECT 1"))
            checks["postgres"] = True
        elif app is not None and hasattr(app.state, "engine"):
            async with app.state.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["postgres"] = True
    except Exception as exc:
        logger.warning("Postgres 健康检查异常: {}", exc)

    return checks
