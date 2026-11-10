# 项目架构图 (GRAPH.md) — PolyAgent

> 修改规则:只在架构本身(节点、边、失败路径、阶段范围、人审边界)变化时更新,日常开发不动此文件。

## 1. 概览

- **项目**:PolyAgent —— 领域无关企业级 Agent 平台 + 项目内领域 Skill。
- **目标**:把 project-python 的企业架构 + MiroFish 的金融领域逻辑,合并成用户自己的、可写进简历的项目。
- **架构模式**:四层(API / 编排 / 能力 / 基础设施)+ 项目内领域 Skill;编排器按【意图+领域】分派到三种模式(ReAct / Plan-Execute / **多视角审议**)。
- **当前示例 Skill**:`financial`(旗舰,deliberation),`kb_qa`(通用 RAG),`legal_compliance`(合同/合规 RAG),`medical_adr`(药品 ADR RAG)。这些是验证样例,不是平台领域上限。
- **旗舰**:多视角审议(N agent 并行评议 + 综合,立场/数量可配)。

## 2. 运行时请求图(Nodes)

| 节点ID | 类型 | 职责 | 输入 | 输出 |
|---|---|---|---|---|
| R0-api-in | function | 接收 chat 请求(messages, domain, mode?) | HTTP 请求 | ChatRequest |
| R1-intent | function(agent) | 意图识别 | user_text | IntentContext |
| R2-domain | function | 从 registry 取领域 Skill adapter | domain 名 | Skill(tools/prompt/spec) |
| R3-orchestrator | agent | 按 mode 分派到 R4a/R4b/R4c | skill + intent + mode | AgentResponse |
| R4a-react | agent | ReAct 循环(思考-行动-观察) | query + tools | AgentResult |
| R4b-plan | agent | Plan-and-Execute(任务分解执行) | query + tools | AgentResult |
| R4c-deliberation | agent(旗舰) | 多视角审议:共享检索→并行评议→综合 | query + DeliberationSpec | AgentResult |
| R5-memory | function | 读写短期(Redis)/长期(Postgres)记忆 | session_id + turn | memory context |
| R6-trace | function | 全链路追踪记录 | span/event | trace 记录 |
| R7-api-out | function | 返回 ChatResponse(非流式/SSE) | AgentResponse | HTTP 响应 |

### R4c 多视角审议子图(旗舰)

| 子节点 | 类型 | 职责 | 失败时 |
|---|---|---|---|
| D1-shared-retrieve | function | MultiRetriever 用 query 检共享上下文 | 无结果 → 上下文为空,继续 |
| D2-participants | function(并行) | asyncio.gather N 个 participant 各出立场观点 | 单个失败 → 该立场缺席,不整批失败 |
| D3-synthesis | agent | LLM 综合全部立场观点 → 答复 | — |
| (无 D-reflection) | — | 反思门槛已砍,deliberation 不挂 reflection | — |

## 3. 边(Edges)与失败处理

| 从 → 到 | 触发条件 | 失败时 |
|---|---|---|
| R0 → R1 | 请求合法 | 参数错 → 4xx,不进意图 |
| R1 → R2 | 意图识别完成 | — |
| R2 → R3 | Skill 存在 | domain 为空 → 默认 Skill;未知 domain → 404 |
| R3 → R4a/R4b/R4c | mode 选定(请求>intent_hints>default_mode) | 未知 mode → 回退 react |
| R4b → R4a | plan_execute 失败 | 自动降级 react(已有) |
| R4c: D1 → D2 | 共享检索结束(含空) | D1 异常 → 空上下文,仍进 D2 |
| R4c: D2 → D3 | 至少一个 participant 成功 | 全失败 → AgentResult(success=False) |
| R4* → R7 | 编排完成 | 未捕获异常 → AgentResponse(success=False),不抛 500 |
| R3 ↔ R5 | 每轮读写记忆 | 记忆异常 → 降级无记忆,不阻断主流程 |
| R3 ↔ R6 | 每步记 trace | trace 异常 → 仅日志,不阻断 |

**关键闭环**:R0 → R1 → R2 → R3 → R4{a/b/c} → R7;旗舰路径 R0 → R1 → R2 → R3 → R4c(D1→D2→D3) → R7。

## 4. 构建阶段图(与 TASKS.md 对应)

```text
P0-bootstrap
-> P1-runtime-bootstrap (基础设施通电 + compose + 灌库)
-> P2-domain-skill (Skill registry + 示例领域 Skill)
-> P3-rag-wire (MultiRetriever 通电 + rag_search)
-> P4-deliberation (旗舰:deliberation.py + orchestrator 分支)
-> P5-chat-wire (chat.py 接 Orchestrator)
-> P6-eval (评测管线 + 黄金集)
-> P7-finish (端到端 demo + 文档)
```

依赖:P4 依赖 P2(Skill deliberation spec)+ LLM;P3 依赖 P1(milvus)+ P2(Skill corpus);P5 依赖 P2/P3/P4。

## 5. 共享状态 Schema

- `AGENT.md`:操作规则、安全边界、当前优先级。
- `TASKS.md`:P0–P7 任务 + 验收标准 + 状态。
- `MEMORY.md`:关键决策与陷阱(provider-agnostic、FAISS 砍、反思砍、来源仓库边界等)。
- `RUN_LOG.md`:每个节点改完后的变更 + 验证摘要。
- 领域 Skill 适配契约:`app/domains/base.py`;运行时注册:`app/domains/registry.py`;领域知识入口:`skills/<domain>/SKILL.md`;设计:`docs/superpowers/specs/2026-08-07-polyagent-design.md`。

## 6. 禁止事项 / 边界

- 编排器对 `DeliberationSpec` 的立场数量/内容**无知**——泛化不得通过硬编码金融概念实现。
- deliberation **不挂** reflection 门槛、不调 Firecrawl、不画图、不做 web_search。
- 运行时编排器**不调 RAGAS**;RAGAS 只在 `app/core/eval/` 离线跑。
- 加新领域 = 新建 `skills/<domain>/SKILL.md`,**不改平台/编排器代码**。
- 多领域共用向量集合时,领域工具需按 `metadata.domain` 做 domain filter,避免跨领域检索污染。
- 任何节点验收不过不得标 done;失败回修复而非绕过。
- 持久写(部署、迁移、CREATE)走 plan-first,人审 `--confirmed` 后执行。
