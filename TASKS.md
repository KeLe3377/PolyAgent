# TASKS.md — PolyAgent 任务与验收

> 分阶段执行,每阶段验收通过才进下一阶段(参见 `GRAPH.md` 构建阶段图)。状态标记:`[ ]` 待办 / `[~]` 进行中 / `[x]` 完成 / `[!]` 阻塞。

---

## P0 — bootstrap(状态文件 + 骨架)

- [x] 复制 project-python → PolyAgent(用户已完成)
- [x] codegraph 初始化 + 索引(54 文件 / 591 节点 / 1096 边)
- [x] 写设计文档 `docs/superpowers/specs/2026-08-07-polyagent-design.md`
- [x] bootstrap 状态文件(AGENT/GRAPH/TASKS/MEMORY/RUN_LOG)

**验收**:5 个状态文件就位;设计文档存在。

---

## P1 — runtime-bootstrap(基础设施通电) — 👤 Codex(`codex/infra-rag`) ✅ 代码合入 main

- [x] `app/config.py`:`openai_*` → `llm_*` + 新增 `embed_*`(pydantic alias 保留旧名兼容,见 MEMORY.md)
- [x] `app/infrastructure/llm/embedding.py`:新增 OpenAI 兼容 embedding 适配器(走 `EMBED_*`)
- [x] `app/main.py` lifespan 扩展:实例化 milvus / embedding / MultiRetriever / redis / memory / ModelRouter / Orchestrator / DomainRegistry,注入 `app.state`
- [x] `.env` / `.env.example`:`LLM_*` + `EMBED_*` + DB/Redis/Milvus 配置(去厂商默认)
- [x] `docker-compose.yml`:app 对 milvus 的健康检查依赖
- [x] 灌库脚本/命令:把 `domains/*/corpus` 灌进 Milvus
- [x] `GET /api/v1/health` 扩展:报告 milvus/redis/pg 连通性

**验收**:`docker compose up` 起来;health 全绿;corpus 灌入后能用 milvus_client 检出 chunk;无 key 泄漏到日志。当前:代码与焦点测试通过,端到端 docker 待跑。

---

## P2 — domain-skill(领域 Skill 机制 + 示例 Skill) — 👤 Claude(`claude/domain-deliberation`) ✅ 代码合入 main

> 已迁移为项目内领域 Skill:运行时扫描 `skills/<domain>/SKILL.md`,Skill 声明 system prompt / tools / corpus_paths / eval_cases / deliberation。`app/domains/base.py` 保留为平台内部 adapter 协议。
> 契约细化:`tools(ctx: DomainContext)` 接收平台注入(rag_search 需运行时 retriever);共享工具 `app/core/tools/builtin/rag_search.py`。

- [x] `app/domains/base.py`:平台内部 adapter Protocol + `DeliberationSpec`/`ParticipantSpec`/`IntentHints`/`EvalDataset`
- [x] `app/domains/registry.py`:扫描 `skills/*/SKILL.md` 注册;`list_domains/get/default`
- [x] `skills/financial-analysis/SKILL.md`:金融分析 Skill,声明 RAG、table_calculator、corpus/eval、多视角审议
- [x] `skills/kb-qa/SKILL.md`:通用知识库问答 Skill
- [x] `skills/contract-review/SKILL.md` + `skills/medical-adr/SKILL.md`:示例领域 Skill,证明领域扩展不改平台编排
- [x] `GET /api/v1/domains`:列出已注册 Skill

**验收**:`/domains` 返回 financial + kb_qa 等 Skill;Skill 能产出 tools/system_prompt/(financial 的)deliberation_spec;加新领域只需新增 `skills/<domain>/SKILL.md`,不改平台代码。

---

## P3 — rag-wire(MultiRetriever 通电) — 👤 Codex(`codex/infra-rag`) ✅ 代码合入 main

- [x] `MultiRetriever` 接 embedding + milvus(P1 已实例化,此处接业务)
- [x] financial `rag_search` 工具:由共享 `app/core/tools/builtin/rag_search.py` 封装 MultiRetriever.retrieve,领域包通过 ctx 绑定
- [x] ETL:financial corpus 经分块入 Milvus 集合

**验收**:给定 query 能从 financial 语料检索出相关 chunk;混合检索(向量+BM25+RRF)生效;空结果不报错。当前:空结果/混合检索焦点测试通过,Milvus 实库检索待 docker。

---

## P4 — deliberation(旗舰:多视角审议) — 👤 Claude(`claude/domain-deliberation`) ✅ 代码合入 main

> 已完成(待端到端测):`app/core/agent/deliberation.py`(D1 共享检索→D2 并行评议→D3 综合,单失败不整批失败)+ orchestrator 加 `_run_deliberation` 分支 + deliberation 不挂反思 + `run()` 增 `tool_registry`/`deliberation_spec` 参数 + `__init__` 增 `retriever`。

- [x] `app/core/agent/deliberation.py`:D1 共享检索 → D2 并行评议(asyncio.gather)→ D3 综合
- [x] `orchestrator.py`:新增 `_run_deliberation` 分支 + mode 分派
- [x] 单 participant 失败不整批失败;全失败返回 success=False
- [ ] 用户可在请求覆盖 participants/数量

**验收**:financial 包 bull/bear 并行评议 → 综合,返回带 steps 的答复;换 participants 数量平台代码不改;trace 记录每步。

---

## P5 — chat-wire(chat 路由接 Orchestrator) — 👤 Claude(整合两侧,需等 P1/P3 合入)[~] 代码合入 main,待集成测

> 已完成(待 P1/P3 合入后端到端测):chat.py 改为 意图→取领域包→选模式→Orchestrator;三模式经 /chat 触发(domain/mode);schemas 加 domain/mode/mode_used/success/degraded;ToolRegistry 补 invoke;SSE 流保留直连(非旗舰,兼容 env 改名)。

- [x] `app/api/routes/chat.py`:意图→取 pack→Orchestrator(选 mode),替换"直连 LLM"
- [x] 三种模式都能经 `/chat` 触发(请求带 domain/mode)
- [ ] SSE 流式(可后置,非旗舰)

**验收**:`/chat` 带 `domain=financial, mode=deliberation` 跑通;bqa 走 react;react/plan 可切换;记忆按会话保留。

---

## P6 — eval(评测管线)

- [~] 多领域公开 benchmark 数据准备:TAT-QA/CUAD/SPL-ADR-200db → `data/benchmarks/*/{corpus,eval_cases,manifest}`
- [~] 多领域 E2E suite:`financial/legal_compliance/medical_adr` + financial deliberation,输出 `reports/e2e/`
- [~] 检索 Recall@k + 延迟统计:`scripts/eval_retrieval_benchmark.py`
- [ ] `app/core/eval/`:RAGAS(Faithfulness/AnswerRelevancy)+ Answer F1/EM + grounded/hallucination 统计
- [~] financial 黄金集(30 条 toy eval + TAT-QA 样本,待升级为正式评测集)
- [ ] `POST /api/v1/eval {domain}`:跑评测,返回报告
- [~] 产出简历可填的基线数字(已有 retrieval baseline 与小样本 E2E;答案质量指标待补)

**验收**:`/eval` 产出 RAGAS + Recall@k + 延迟报告;数字可复现;报告无 key 泄漏。

---

## P6-RAG-Upgrade — RAG 质量升级(metadata-aware retrieval + structured tools)— [~] 两侧代码已合并,待端到端复测

> 设计:`docs/superpowers/specs/2026-08-11-rag-quality-upgrade-plan.md`。基线来自近 50 条多领域 Docker `/chat` 分批 E2E:overall evidence recall 58.33%,financial 37.50%,legal 56.25%,medical 81.25%。

Claude 侧:领域结构化与工具 — `claude/rag-domain-structured-tools`

- [x] `app/core/rag/query_analyzer.py`:`QueryPlan` + 规则驱动 `QueryAnalyzer`(零模型成本),抽取 years/metric/contract_name/clause_type/drug_name/scale,推断 domain/dataset/filters/preferred_chunk_types/needs_calculation。
- [x] `app/core/tools/builtin/table_calculator.py`:确定性 lookup/sum/difference/ratio/count,容忍脏数值(`$ 1,452.4`/`(1,200)`/千分位/量纲),输出 answer + calculation_trace。
- [x] `app/core/tools/builtin/contract_clause_locator.py`:在候选片段内按 contract_name/clause_type 过滤,兼容 rag_search 文本输出与 JSON 列表。
- [x] `scripts/prepare_benchmark_corpus.py`:TAT-QA 生成 table_doc + row_fact + cell_fact;CUAD 生成 contract_doc + contract_clause(按 clause_type 聚合)。
- [x] `scripts/prepare_multidomain_e2e_suite.py`:不再按 doc_id 去重,结构化 chunk 全部进入 E2E 语料。
- [x] `financial/pack.py` 挂 `table_calculator`;`legal_compliance/pack.py` 挂 `contract_clause_locator`;financial prompt 改为「数值推理走 table_calculator,禁止自己心算」。
- [x] tests:`test_query_analyzer.py` / `test_table_calculator.py` / `test_contract_clause_locator.py`。

Codex 侧:检索基础设施与评测 — `codex/rag-retrieval-rerank-eval`

- [x] `app/core/rag/types.py`:RetrievalRequest。
- [x] `app/core/rag/reranker.py`:Reranker Protocol + Noop/CrossEncoder reranker。
- [x] `app/core/rag/retriever.py`:metadata filters、top_n -> top_k、optional rerank、兼容旧 retrieve 调用。
- [x] `app/infrastructure/vectordb/milvus_client.py`:支持 Milvus expr 过滤。
- [x] `app/core/tools/builtin/rag_search.py`:输出 doc_id/source/dataset/chunk_type,支持 domain/dataset/default filters。
- [x] `scripts/ingest_benchmark_corpus.py`:benchmark corpus 灌库 dry-run/confirmed。
- [x] `scripts/e2e_multidomain_rag_benchmark.py`:5 条一批 E2E + report aggregate。
- [x] `scripts/eval_retrieval_benchmark.py`:零模型成本 keyword retrieval baseline。
- [x] tests:`test_rag_retriever_filters.py` / `test_reranker.py` / `test_e2e_batch_aggregation.py` / `test_rag_search_tool.py`。

**已验证**:
- Claude 侧新增 30 用例通过;全量测试除 Windows 默认临时目录权限问题外通过。
- Codex 侧 `py_compile` 通过;focused pytest 5 passed;full pytest 13 passed。

**整体验收(待执行)**:两侧合并后重新生成/ingest 结构化 corpus,先抽差的 5 条 E2E 复测,再按 5 条一批重跑 49 条 E2E。目标 overall evidence recall >=70%,financial >=55%,legal >=70%,medical >=80%,chain success >=95%。

---

## P7 — finish(端到端 + 文档)

- [ ] 一键 `docker compose up` + 跑通 chat/eval
- [ ] README:架构、快速开始、截图/示例
- [ ] 简历 STAR bullet(填入 P6 真实数字)
- [ ] 全量 `RUN_LOG.md` 收尾

**验收**:干净环境一键起;chat 三模式 + eval 可演示;README 自洽;简历 bullet 数字真实可复现。

---

## 依赖与风险

- P4 依赖 P2 + ModelRouter(已有);P3 依赖 P1 + P2;P5 依赖 P2/P3/P4;P6 依赖 P5。
- 风险:Milvus 首启就绪慢 → compose 健康检查 + 重试;LLM JSON 输出稳定性 → 用强模型 + 结构化约束。

