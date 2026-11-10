# AGENT.md — PolyAgent 操作规则

> 本文件定义 PolyAgent 的操作规则与当前优先级。每次开工先读 AGENT.md → GRAPH.md → TASKS.md → MEMORY.md → RUN_LOG.md。

## 项目身份

- **项目**:PolyAgent —— 领域无关的企业级 Agent 平台 + 项目内领域 Skill。
- **来源**:`ai-agent-interview-guide-main/project-python`(企业骨架,教学仓库,**不可当作品直接用**)+ `MiroFish-FinSight-master`(用户自己的金融 Agent)。PolyAgent 是用户自己的独立项目,独立目录 `d:\project\PolyAgent`,不回写来源仓库。
- **旗舰特性**:多视角审议(N agent 并行评议 + 综合,立场/数量可配)。
- **完整设计**:见 `docs/superpowers/specs/2026-08-07-polyagent-design.md`。

## 当前优先级

1. P1–P5 代码已合入 main；当前优先级是 **Docker 端到端验收**:compose up → health → ingest corpus → chat 三模式。
2. 下一阶段是 P6 评测管线；P1–P5 只有端到端验收通过后才标最终 done。

## 开发纪律(agent-dev-workflow)

- **先契约后实现**:改 CLI/工具/接口前,先在契约文档/本文件/TASKS 定下输入输出、成功/错误信封、退出行为。
- **节点验证**:每个 phase 节点先实现再验证;probe/回归失败 → 回修复,不标 done。
- **状态文件同回合更新**:设计/开发/验证/修复后追加 `RUN_LOG.md`;状态/验收变化更新 `TASKS.md`;架构变化更新 `GRAPH.md`;持久决策更新 `MEMORY.md`。
- **保持运行入口稳定**:用项目 wrapper 做编码/路径/可写目录设置。

## 安全边界

- 改造期对两个源仓库(`project-python`、`MiroFish-FinSight-master`)**只读**;所有写入只在 PolyAgent。
- `.env`、API key、连接串、密码**不进** stdout/stderr/日志/trace/manifest/commit。
- 对话归档只写入 `.archives/`,默认**不提交**;除非用户明确要求提交归档文件。
- 安装、迁移、`CREATE`、部署类持久写命令:先出 plan,人审确认后再加 `--confirmed` 执行。
- 探查/验证保持 readonly,除非用户显式批准写操作。
- 不靠弱化测试、绕过校验、删历史来让失败"通过"。

## 关键约定

- LLM **完全 provider-agnostic**,全走 `.env`(`LLM_*` / `EMBED_*`),不绑厂商。复用已有 `ModelRouter`。
- 依赖注入保持 Protocol 风格:适配器实现 Protocol,装配在 lifespan,路由从 `app.state` 取,不自己 `new`。
- **已砍除**(聚焦多 agent 讨论):Firecrawl 取证、反思门槛(deliberation 不挂 reflection)、画图、web_search、运行时 RAGAS。RAGAS 只进 `app/core/eval/` 离线评测。
- RAG 复用 project-python 现有 `MultiRetriever`(向量+BM25+RRF),不另造;FAISS 不保留。
- app.state 固定 key:`orchestrator` / `registry` / `retriever` / `memory` / `router_llm` / `embedding` / `milvus` / `redis`。
- 领域扩展固定走 `skills/<domain>/SKILL.md`:领域知识、提示词、工具、语料路径、评测和审议配置都放在 Skill;不要再为新领域新增硬编码 Python 领域包。
