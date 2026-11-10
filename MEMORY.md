# MEMORY.md — PolyAgent 持久决策与陷阱

> 只记持久决策、重复教训、重要陷阱。每次决策后追加,不删历史。

## 来源仓库边界(重要)

- `ai-agent-interview-guide-main/project-python`:**面试教学仓库**的企业骨架。代码可学可改,但定位是教学,**不能直接当个人作品**。PolyAgent 借用其架构,但是用户独立项目,不回写、不声称是原仓库。
- `MiroFish-FinSight-master`:**用户自己写的**金融 Agent,逻辑可自由搬迁。(注:`MiroFish` 品牌不属于用户,不要用作 PolyAgent 的命名。)
- PolyAgent 目录:`d:\project\PolyAgent`(= project-python 副本,原地改造)。

## 关键设计决策

- **命名**:PolyAgent(`poly = 多`,多领域/多 agent/多视角)。曾考虑 Prism、MiroFish Agent Platform——MiroFish 因归属问题否决。
- **LLM provider-agnostic**:复用 project-python 已有 `ModelRouter`(OpenAI 兼容 base_url 模式,chat.py 已用)。**不绑任何厂商**,全走 `.env`(`LLM_*`/`EMBED_*`)。曾误设默认 Qwen/SiliconFlow,已纠正为通用。
- **多视角审议泛化(方案 A)**:把 MiroFish 多空辩论泛化为平台"多视角审议模式",而非保留为金融专有(方案 B)。理由:B 会在面试被迫解释"为何只有金融";A 有 financial + kb_qa 两真实使用者,非投机抽象。
- **领域 = 通用平台 + 项目内领域 Skill**(非纯金融);领域知识、提示词、工具契约、语料路径、评测和审议配置以 `skills/<domain>/SKILL.md` 为运行时事实来源。
- **基础设施 = 完整企业栈**(docker-compose 全栈),为简历可写多中间件集成/熔断/追踪。

## 砍除项(用户决定,聚焦多 agent 讨论)

- ❌ Firecrawl 取证(data_fetcher / research_tool)
- ❌ 反思门槛(deliberation 不挂 reflection;现有 ReflectionAgent 留代码默认关,不投入)
- ❌ 画图(revenue_visualizer / draw_chart)
- ❌ web_search(依赖 Firecrawl,一并砍)
- ❌ 运行时 RAGAS(RAGAS 只进 `app/core/eval/` 离线评测)
- ❌ FAISS(统一用平台 Milvus MultiRetriever,不保留)

## project-python 现状陷阱(已核实)

- **Orchestrator / MultiRetriever 从未被实例化**——写好了但休眠;chat.py 绕过 agent 层直连 LLM。PolyAgent 的核心工作 = 把它们通电接进请求路径。
- LLM/ModelRouter、Milvus、Redis、Postgres、Trace、Memory 客户端**都是真实现**,休眠;唯 **Embedding 缺独立适配器**,需新增。
- chat.py **不是占位**(走 意图→直连LLM),要改造成 意图→Orchestrator。

## 并行开发协作(Claude + Codex,2026-08-07 起)

- **git 仓库已初始化**,默认分支 `main`。`.env`/`.codegraph`/`worktrees/` 等已进 `.gitignore`(不泄漏 key)。
- **分工按层切,冲突面最小**:
  - Codex(`codex/infra-rag`)= P1 基础设施通电 + P3 RAG 能力。owns:`config.py`/`infrastructure/`/`main.py` lifespan/`.env`/`compose`/`health`/`retriever`/`etl`。见 `CODEX.md`。
  - Claude(`claude/domain-deliberation`)= P2 领域包 + P4 多视角审议 + P5 chat 接线(整合两侧)。owns:`domains/**`/`deliberation.py`/`orchestrator.py`/`chat.py`/`domains.py`/`main.py` create_app。
  - 共享文件 `main.py`:Codex 改 `lifespan()`,Claude 改 `create_app()` router 列表,函数级隔离。
- **Codex 工作树**:`.worktrees/codex`(git worktree,分支 codex/infra-rag)。Codex 只读项目状态文件,不改 AGENT/GRAPH/TASKS/MEMORY/RUN_LOG,自己的进度写 `CODEX_RUNLOG.md`。Claude 统一同步项目状态文件。
- **接口对齐**:`app.state` 上 key 名按设计文档第 4 节③(`orchestrator/retriever/registry/milvus/embedding/redis/memory/router_llm`),双方都按此取依赖。
- P5 chat-wire 依赖 P1+P3(Codex)+P2+P4(Claude)都就绪,由 Claude 最后整合。

## 领域包 / 编排器契约细化(2026-08-07,P2/P4/P5 落地)

- **DomainPack.tools 改为 `tools(ctx: DomainContext)`**(不是 `tools()`):rag_search 需运行时 MultiRetriever,故工具按平台注入的 ctx 构建,不在 import 期硬连基础设施。DomainContext 字段:retriever/memory/llm/config。
- **共享 `RagSearchTool` 在 `app/core/tools/builtin/rag_search.py`**(Claude 写),各领域包 import 并绑定 ctx.retriever —— 不要在每个 pack 重复实现。Codex 不需再写 rag_search,只把 MultiRetriever 通到 `app.state.retriever`。
- **Orchestrator 构造增 `retriever` 形参**:lifespan 实例化时传 `retriever=<MultiRetriever 实例>`(供 deliberation D1 共享检索)。
- **`orchestrator.run(...)` 增 `deliberation_spec` 与 `tool_registry` 参数**:deliberation 模式需 spec(领域包提供);tool_registry 按请求注入 pack 工具。
- **deliberation 不挂反思**:run() 中 `mode_used != "deliberation"` 才跑 reflection。
- **ToolRegistry 补 `invoke`/`list_tool_names`**(原休眠缺口):react/plan 才能真正调工具。
- **app.state 约定 key**:orchestrator / registry / retriever / memory / router_llm(双方对齐,Codex 在 lifespan 装配)。
- **ChatRequest 加 domain/mode;ChatResponse 加 mode_used/domain/success/degraded**。

## main 集成决策(2026-08-07)

- `main` 已合入 `claude/domain-deliberation` 与 `codex/infra-rag`。集成时以 Claude 的契约更新为准:共享 `RagSearchTool` 保留在 `app/core/tools/builtin/rag_search.py`;Codex 早期的 `app/core/tools/rag_search.py` 删除。
- `lifespan()` 必须 `registry.scan()` 后写入 `app.state.registry`,并在构造 `AgentOrchestrator` 时传 `retriever=retriever`。
- `ModelRouter.get_llm()` 的 facade 不得把内部 `purpose` 透传到 OpenAI chat API 参数里;purpose 只作本地选择/标识。
- 本机/CI 可能存在 `DEBUG=release`;Settings 将 deployment-ish 字符串解析为 `debug=False`,避免外部环境变量误伤启动和测试。

## env 命名决策(2026-08-07,P1 落地)

- 字段改名:`openai_api_key/openai_api_base/openai_model` → `llm_api_key/llm_base_url/llm_model`;新增 `embed_api_key/embed_base_url/embed_model`。
- **向后兼容**:pydantic `validation_alias` 同时接受 `llm_*` 与旧 `openai_*`/`OPENAI_*`,零破坏现有 `model_router.py`/`chat.py`。
- 理由:`openai_*` 字段名读起来像厂商绑定(面试不利);改名显式 provider-agnostic;alias 兼容避免回归。

## 工作流约定

- 用 `agent-dev-workflow` skill:状态文件(AGENT/GRAPH/TASKS/MEMORY/RUN_LOG)+ 节点验证 + plan-first 持久写。
- 参照 `d:\project\skills\Data Agent Meta-Skill\` 的 GRAPH.md 风格写状态文件(节点/边/失败表/边界)。
- codegraph 已索引两个源仓库 + PolyAgent,可用 `codegraph_explore`(projectPath)查符号与调用图。

## 领域 Skill 运行时决策(2026-08-12)

- 早期 Python `DomainPack` 机制已迁移为 project-local Skill。`app/domains/registry.py` 扫描 `skills/*/SKILL.md`,解析 frontmatter 与 Markdown section,生成 `DomainSkill` adapter。
- `app/domains/base.py` 保留 `DomainPack` Protocol 名称仅作编排器内部兼容边界;新增领域不要再写 `app/domains/<name>/pack.py`。
- Skill frontmatter 负责稳定配置:`domain/default_mode/tools/rag_domain_filter/corpus_paths/eval_cases_path/intent_overrides/deliberation_roles`;正文 `## System Prompt` 与 `## Deliberation Participant <role>` 承载长提示词。
- `app/main.py` 的启动 BM25 注册与 `scripts/ingest_corpus.py` 灌库都读取 Skill `corpus_paths`,保证领域选择、语料入口、工具声明同源。
- 默认 Skill 是 `kb_qa`;请求不传 domain 时走默认,传未知 domain 时返回 404。
