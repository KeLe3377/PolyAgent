# -*- coding: utf-8 -*-
"""FastAPI 应用入口：生命周期内初始化异步数据库引擎。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.api.routes import chat, document, domains, health
from app.config import get_settings
from app.infrastructure.database.session import configure_session, init_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("启动 {} ({})", settings.app_name, settings.app_env)
    engine = init_engine(settings.database_url)
    configure_session(engine)
    app.state.engine = engine
    from app.core.agent.orchestrator import AgentOrchestrator, InMemoryTracer
    from app.core.memory.manager import MemoryManager
    from app.core.memory.short_term import ShortTermMemory
    from app.core.rag.retriever import MultiRetriever
    from app.core.tools import ToolRegistry
    from app.core.tools.builtin.rag_search import RagSearchTool
    from app.infrastructure.cache import RedisCache
    from app.infrastructure.llm import ModelConfig, ModelRouter, OpenAIEmbeddingAdapter
    from app.infrastructure.vectordb import MilvusManager

    class _RegistryFallback:
        def list_domains(self):
            return []

        def get(self, name):
            raise KeyError(f"domain registry is not available: {name}")

        def default(self):
            return None

    class _MemoryProtocolAdapter:
        def __init__(self, manager):
            self._manager = manager

        async def get_relevant(self, session_id: str, query: str, limit: int = 8):
            context = await self._manager.get_context(session_id, query)
            short = [m.content for m in context.short_term_messages[-limit:]]
            long = [m.content for m in context.long_term_items[:limit]]
            return [*short, *long][:limit]

        async def append_turn(self, session_id: str, role: str, content: str, metadata=None):
            from app.models.enums import MessageRole
            from app.models.schemas import Message

            role_value = role if role in {item.value for item in MessageRole} else MessageRole.USER.value
            await self._manager.save(
                session_id,
                Message(role=MessageRole(role_value), content=content, metadata=metadata or {}),
            )

    class _NoopLongTermMemory:
        async def recall(self, query: str, session_id: str, top_k: int = 5):
            return []

    milvus = MilvusManager(
        host=settings.milvus_host,
        port=str(settings.milvus_port),
        user=settings.milvus_user or None,
        password=settings.milvus_password or None,
    )
    embedding = OpenAIEmbeddingAdapter(
        api_key=settings.embed_api_key,
        base_url=settings.embed_base_url,
        model=settings.embed_model,
    )
    retriever = MultiRetriever(
        milvus,
        embedding,
        collection_name=settings.milvus_collection_name,
    )
    from app.domains.registry import DomainRegistry

    try:
        from app.etl.chunker import DocumentChunker

        startup_registry = DomainRegistry()
        startup_registry.scan()
        chunker = DocumentChunker()
        keyword_docs = {}
        for domain in startup_registry.list_domains():
            skill = startup_registry.get(domain)
            if skill is None:
                continue
            for doc in skill.corpus_docs():
                for idx, chunk in enumerate(chunker.chunk(doc.text)):
                    keyword_docs[f"{domain}:{doc.source}:{idx}"] = chunk
        if keyword_docs:
            retriever.register_keyword_documents(keyword_docs)
    except Exception as exc:
        logger.warning("领域 Skill 或 BM25 语料启动注册失败，使用空注册表，向量检索仍可用: {}", exc)
        startup_registry = _RegistryFallback()
    redis = RedisCache(settings.redis_url)
    router_llm = ModelRouter(
        [
            ModelConfig(
                model_id=settings.llm_model,
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
            )
        ]
    )
    memory_manager = MemoryManager(
        ShortTermMemory(redis._client, router_llm.get_llm("memory")),
        _NoopLongTermMemory(),
    )
    memory = _MemoryProtocolAdapter(memory_manager)
    tools = ToolRegistry()
    tools.register(RagSearchTool(retriever))
    tracer = InMemoryTracer()
    orchestrator = AgentOrchestrator(
        config={"enable_reflection": False, "fallback_react_on_plan_failure": True},
        model_router=router_llm,
        memory_manager=memory,
        tool_registry=tools,
        tracer=tracer,
        retriever=retriever,
    )
    registry = startup_registry

    app.state.milvus = milvus
    app.state.embedding = embedding
    app.state.retriever = retriever
    app.state.redis = redis
    app.state.memory = memory
    app.state.router_llm = router_llm
    app.state.orchestrator = orchestrator
    app.state.registry = registry
    yield
    await redis.aclose()
    await engine.dispose()
    logger.info("关闭 {}", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )
    application.include_router(health.router, prefix=settings.api_prefix)
    application.include_router(chat.router, prefix=settings.api_prefix)
    application.include_router(document.router, prefix=settings.api_prefix)
    application.include_router(domains.router, prefix=settings.api_prefix)
    return application


app = create_app()
