# CODEX.md — Codex 工作分配(基础设施 + RAG 能力层)

> 你(Codex)和 Claude 并行开发 PolyAgent。开工前按顺序读:
> `AGENT.md` → `GRAPH.md` → `TASKS.md` → `MEMORY.md` → `RUN_LOG.md` → 本文件 → `docs/superpowers/specs/2026-08-07-polyagent-design.md`(第 3、4 节)。
> 你在分支 `codex/infra-rag`(本工作树),Claude 在 `claude/domain-deliberation`。

## 你的范围(P1 runtime-bootstrap + P3 rag-wire)

按 TASKS.md 的验收标准做。一句话:**把休眠的基础设施和 RAG 通电接进 `app.state`,能 `docker compose up` 起来、health 全绿、corpus 能检出 chunk。**

### P1 runtime-bootstrap(见 TASKS.md)
1. **`app/config.py`** — env 命名重构(见下「env 决策」):`openai_*` → `llm_*`,新增 `embed_*`。
2. **`app/infrastructure/llm/embedding.py`**(新)— OpenAI 兼容 embedding 适配器,实现一个 Protocol(参照现有 `model_router.py` 风格),走 `EMBED_*`,方法 `embed_texts(list[str]) -> list[list[float]]`。
3. **`app/main.py` lifespan** — 实例化并注入 `app.state`:milvus / embedding / MultiRetriever / redis / memory / ModelRouter / Orchestrator / DomainRegistry。**只改 `lifespan()` 函数体,不要改 `create_app()` 的 router 列表(那是 Claude 的)。**
4. **`.env.example` + `.env`** — `LLM_*` + `EMBED_*` + DB/Redis/Milvus 结构(去厂商默认值,不填真实 key)。
5. **`docker-compose.yml`** — app 对 milvus 改用 `condition: service_healthy` + 给 milvus 加 healthcheck(`milvus` 镜像健康端口 9091)。
6. **灌库脚本** — `scripts/ingest_corpus.py` 或等价:把 `app/domains/*/corpus/*` 分块灌进 Milvus(Claude 负责放 corpus 文件,你负责脚本读取该约定路径)。
7. **`app/api/routes/health.py`** — 扩展 `GET /api/v1/health` 报告 milvus/redis/pg 连通性(各一项 ok/fail,不泄漏连接串)。

### P3 rag-wire
8. **`app/core/rag/retriever.py`** — `MultiRetriever` 接 P1 已实例化的 embedding + milvus,接业务路径。
9. **financial `rag_search` 工具** — 封装 `MultiRetriever.retrieve`,作为 DomainPack tool 暴露(注册到 `app/core/tools/` 体系)。
10. **ETL** — financial corpus 经 `app/etl/chunker.py` 分块入 Milvus 集合。

## env 决策(已定,照做)
- 字段改名:`openai_api_key/openai_api_base/openai_model` → `llm_api_key/llm_base_url/llm_model`。
- 新增:`embed_api_key/embed_base_url/embed_model`。
- **向后兼容**:用 pydantic `Field(validation_alias=AliasChoices("llm_api_key","openai_api_key"))` 之类,保证旧 `OPENAI_*` 环境变量仍能跑,零破坏现有 `model_router.py`/`chat.py`。
- `.env.example` 只放占位符,**绝不填真实 key**。

## 你的文件所有权(可改)
`app/config.py` · `app/infrastructure/llm/embedding.py`(新)· `app/main.py`(仅 `lifespan`)· `app/infrastructure/{vectordb,cache}/*`(接线)· `app/core/rag/retriever.py` · `app/etl/*` · `app/api/routes/health.py` · `.env.example` · `.env` · `docker-compose.yml` · `scripts/ingest_corpus.py`(新)· `app/core/tools/*`(注册 rag_search)

## 禁区(Claude 在改,不要碰,避免冲突)
- `app/domains/**`(整层,Claude)
- `app/core/agent/deliberation.py`(新,Claude)
- `app/core/agent/orchestrator.py`(Claude)
- `app/api/routes/chat.py`(Claude)
- `app/api/routes/domains.py`(新,Claude)
- `app/main.py` 的 `create_app()` 内 router include(Claude);你只动 `lifespan()`。
- `AGENT.md`/`GRAPH.md`/`TASKS.md`/`MEMORY.md`/`RUN_LOG.md`(由 Claude 统一同步状态文件,你只在本工作树根写 `CODEX_RUNLOG.md` 记你的进度)

## 安全边界(强制)
- `.env`、API key、连接串、密码**不进** stdout/stderr/日志/trace/commit。
- 任何持久写(建库、CREATE TABLE、灌库、迁移、部署):先 `--dry-run` 或出 plan,本次按脚本本地灌库即可,不需要线上。
- 改造期对 `ai-agent-interview-guide-main/`、`MiroFish-FinSight-master/` 两个来源仓库**只读**;写入只在你这个工作树。

## 验收(P1)
`docker compose up` 起来;`/api/v1/health` 全绿(milvus/redis/pg ok);corpus 灌入后能用 milvus client 检出 chunk;无 key 泄漏到日志。

## 协作约定
- 你的 commit 只进 `codex/infra-rag`。完成后留 `CODEX_RUNLOG.md` 写清:改了哪些文件、验证命令与结果、未决问题。
- 接口契约对齐:Codex 的 `OpenAIEmbeddingAdapter`、`MultiRetriever` 实例在 `app.state` 上的 key 名,按设计文档第 4 节③(`app.state = {orchestrator, retriever, registry, milvus, embedding, redis, memory, router_llm}`)。Claude 的 Orchestrator 会从这些 key 取依赖。
- 不确定就按「契约优先」在 `CODEX_RUNLOG.md` 写下假设,不要私自改 Claude 的禁区文件。
