# PolyAgent 设计文档

> 状态:已与用户确认(2026-08-07),进入实施。
> 类型:架构设计 + 实施分阶段。
> 关联状态文件:`AGENT.md` `GRAPH.md` `TASKS.md` `MEMORY.md` `RUN_LOG.md`(项目根目录)。

---

## 0. 背景与目标

把两个仓库合并成一个**可写进简历、自己拥有**的企业级 Agent 项目:

- **来源 A**:`ai-agent-interview-guide-main/project-python` —— 企业级骨架,FastAPI + 分层 + Protocol 依赖注入,有真实的 orchestrator/ReAct/planner/reflection/RAG/ETL/基础设施客户端逻辑,但**领域无关且未通电**(Orchestrator/MultiRetriever 从未被实例化,chat 路由绕过 agent 层直连 LLM)。定位是面试教学仓库,**学习可用,不能直接当作品**。
- **来源 B**:`MiroFish-FinSight-master` —— **用户自己写的**金融分析 Agent(CLI),有多空辩论多智能体流水线、RAGAS 质检、FAISS RAG、角色安全。能跑,但 CLI 化、非企业架构。
- **目标产物**:**PolyAgent** = project-python 的企业架构 + MiroFish 的真实领域逻辑,做成**领域无关平台 + 可插拔领域包**,以金融深度分析为旗舰、通用知识问答为轻量对照包,内置评测管线产出简历可用的真实数字。

**关键边界**:
- project-python 是教学仓库,代码可学可改,但 PolyAgent 是用户自己的独立项目(独立目录、独立演进),不回写来源仓库。
- MiroFish 是用户自己的,其逻辑可自由搬迁。

---

## 1. 总体架构与定位

**一句话**:领域无关的企业级 Agent 平台,通过**可插拔领域包(DomainPack)**承载不同业务,内置三种编排模式(ReAct / Plan-Execute / 多视角审议)+ 评测管线;以"金融深度分析"和"通用知识问答"两个领域包证明可插拔性。

**项目命名**:PolyAgent。`poly = 多`(多领域、多 agent、多视角),一个词同时点题多领域可插拔与多视角审议。不用 MiroFish(那是别人的品牌)。

**四层架构**(在 project-python 现有分层上明确职责):

```
┌─────────────────────────────────────────────────────┐
│  API 层   app/api/   FastAPI 路由:chat / domains /    │
│           document / eval / health                   │
├─────────────────────────────────────────────────────┤
│  编排层   app/core/agent/                            │
│    orchestrator ── 按【意图+领域】选模式              │
│    ├─ react_agent        (模式1: 思考-行动-观察)      │
│    ├─ planner            (模式2: 任务分解-执行,已有)  │
│    ├─ deliberation       (模式3: 多视角审议,旗舰)    │
│    └─ reflection         (通用 LLM 自批评,默认关)    │
├─────────────────────────────────────────────────────┤
│  能力层   app/core/{rag,memory,tools,intent} + eval/  │
│    RAG(向量+BM25+RRF 混合检索) 记忆(短/长) 工具 意图  │
│    eval(ragas + Recall@k + 延迟/成本)                │
├─────────────────────────────────────────────────────┤
│  领域层   app/domains/  ← 新增,可插拔领域包           │
│    ├─ financial/  (旗舰,来自 MiroFish)               │
│    └─ kb_qa/      (轻量,证明可插拔)                  │
├─────────────────────────────────────────────────────┤
│  基础设施 app/infrastructure/  (Protocol → 真实适配)  │
│    llm(provider-agnostic) vectordb(Milvus)            │
│    cache(Redis) database(Postgres) trace(链路追踪)    │
└─────────────────────────────────────────────────────┘
```

**相对 project-python 的四项核心改动**:
1. 新增 `app/domains/`(领域包机制)——合并的核心新增层。
2. 编排层新增 `deliberation`(多视角审议模式)——MiroFish 多空流水线的泛化,**旗舰**。
3. 新增 `app/core/eval/`(评测管线)——project-python 完全缺失。
4. 基础设施层从"Protocol 接口"接上**真实适配器** + 新增 embedding 适配器——目前是空壳/休眠。

**LLM 提供方**:**完全 provider-agnostic**。复用 project-python 已有的 `ModelRouter`(OpenAI 兼容 `base_url` 模式,chat.py 已在用)。provider/model/base_url/key 全走 `.env`,不绑定任何厂商。

---

## 2. 领域包契约与注册机制

可插拔的最小单元。契约严格按 `agent-to-skill-converter` 的**三分类**落地:判断逻辑进 prompt、确定性操作进 tools、领域事实进语料。

**领域包接口(`app/domains/base.py`)**

```python
class DomainPack(Protocol):
    name: str                       # "financial" / "kb_qa"
    version: str
    default_mode: str               # "react" / "deliberation"
    system_prompt: str              # ① 判断原则 + 人设(三分类:判断逻辑)

    def corpus_docs(self) -> list[Document]: ...           # ② 领域事实语料(三分类:领域事实)
    def tools(self) -> list[Tool]: ...                     # ③ 确定性工具(三分类:确定性操作)
    def deliberation_spec(self) -> DeliberationSpec | None # ④ 可选:多视角审议配置
    def eval_dataset(self) -> EvalDataset | None           # ⑤ 可选:评测黄金集
    def intent_hints(self) -> IntentHints | None           # ⑥ 可选:意图→模式 路由提示
```

**多视角审议配置(模式 3 的数据,由领域包定义、平台执行)**

```python
@dataclass
class ParticipantSpec:
    role: str            # "bull" / "risk_officer" / ... 立场由领域包定
    stance_prompt: str   # 该立场 system prompt 片段

@dataclass
class DeliberationSpec:
    participants: list[ParticipantSpec]  # N 个,数量与立场由领域包/用户给
    synthesis_prompt: str                # 综合各方观点的 prompt
    max_rounds: int = 1                  # 可多轮交锋
```

→ 金融包填 `participants=[bull, bear]`;换领域换 participants,平台执行逻辑不变。用户也能在请求里覆盖 participants/数量(兑现"用户可设")。

**注册机制(`app/domains/registry.py`)**

- 启动时扫描 `app/domains/<name>/pack.py`,每个 pack 暴露 `PACK: DomainPack`。
- `DomainRegistry`: `list_domains()` / `get(name)` / `default()`。
- 请求带 `domain` 参数(缺省=配置的默认包),orchestrator 取包 → 拿 tools/prompt/spec → 选模式 → 跑。
- 加第三个领域 = 新建目录 + 实现 `DomainPack`,**不改平台代码**——这是可插拔的证明点。

**两个领域包内容**

| | `domains/financial/`(旗舰) | `domains/kb_qa/`(轻量) |
|---|---|---|
| 语料 | MiroFish `knowledge/*.md`(6 篇) | ETL 入库的通用文档 |
| 工具 | `rag_search`(仅此一个) | `rag_search` |
| 审议配置 | bull + bear 两方 | 无(只走 ReAct/RAG) |
| 评测集 | MiroFish `benchmark_tasks.md` → 黄金集 | 自建通用问答集 |
| 路由提示 | "深度分析"意图→deliberation | 默认→react |
| 默认模式 | deliberation | react |

两包形成"复杂(多视角审议)/ 简单(单轮 RAG)"对照,证明平台既扛重流程、也装轻流程。

---

## 3. 编排层与多视角审议(旗舰)

project-python 的 `orchestrator.run()` 已能在 `react`/`plan_execute` 间切换、带 plan→react 降级。**加第三条分支 `deliberation`**。

**模式分派**

```python
mode = request.mode or intent.preferred_mode or domain.default_mode
if mode == "react":          → _run_react(...)
elif mode == "plan_execute": → _run_plan_execute(...)   # 失败自动降级 react(已有)
elif mode == "deliberation": → _run_deliberation(...)   # 新增
```

**模式 3:多视角审议流程(`app/core/agent/deliberation.py` 新增)** —— 极简,只留讨论本身

```
请求(query + domain)
  ├─ ① 共享检索:MultiRetriever 用 query 检一次 → 共享上下文(无上下文也能继续)
  ├─ ② 并行评议:asyncio.gather(N 个 participant)        ← 核心
  │     每个 = LLM(stance_prompt_i + query + 共享上下文) → 立场观点_i
  │     单个失败 → 该立场缺席,synthesis 标注,不整批失败
  ├─ ③ 综合:LLM(synthesis_prompt + 全部立场观点) → 答复   ← 核心
  └─ 返回 AgentResponse(answer, mode_used="deliberation", steps)
```

**已砍除(用户决定,聚焦多 agent 讨论)**:
- ❌ Firecrawl 取证(data_fetcher / research_tool)
- ❌ 反思门槛(_run_reflection,deliberation 不挂;现有 ReflectionAgent 留代码默认关)
- ❌ 画图(revenue_visualizer / draw_chart)
- ❌ web_search(依赖 Firecrawl,一并砍)
- ❌ RAGAS 不进运行时编排器

**泛化是诚实的**:平台执行逻辑(共享检索→并行评议→综合)对立场数量和内容**完全无知**,只认 `DeliberationSpec`。金融填 bull/bear,换领域填别的——平台代码一行不改。

**MiroFish 资产映射(仅保留两节点)**

| MiroFish 节点 | PolyAgent 去向 |
|---|---|
| `bull_analyst` / `bear_analyst` | ② 两个 `ParticipantSpec`(prompt 进配置,非硬节点) |
| `debater_node` | ③ `synthesis_prompt` |
| `data_fetcher` / `quality_inspector` / `reflect` / `revenue_visualizer` | **全部不搬** |

**模式选择优先级**:请求显式 `mode` > 领域包 `intent_hints` > 领域包 `default_mode`。

---

## 4. 基础设施适配与启动装配

**接线现状(已核实)**:
- LLM/ModelRouter:真实现(171 行)+ chat.py 已用 + 已 provider-agnostic。**复用不改**。
- Milvus:`milvus_client.py` 真(190 行),休眠。
- RAG:`MultiRetriever` 真实现(向量+BM25+RRF 混合)+ reranker + generator,**休眠**(全仓库零调用点)。
- Redis:`redis_cache.py` 真(230 行),休眠。
- Postgres:`session.py`/`models.py` 真,main.py lifespan 已 init engine。
- Trace:`tracer.py` 真(137 行),chat.py 已用。
- Memory:`short_term`/`long_term` 真,休眠。
- Embedding:**缺独立适配器**,需新增。

**① 请求路径改造(`app/api/routes/chat.py`)**

```
现在:  请求 → 意图识别 → 直连 LLM → 返回
改成:  请求(带 domain) → 取 DomainPack → Orchestrator(pick mode) → 返回
                      Orchestrator 内部: react / plan / deliberation
                      + 按需调 MultiRetriever / tools / memory
```

**② 适配器接线表**

| 组件 | 现状 | 接线工作 |
|---|---|---|
| LLM / ModelRouter | ✅ 真+已用+agnostic | 复用不改 |
| Milvus | ✅ 真 | 实例化 + 灌 corpus + 接给 MultiRetriever |
| Embedding | ❌ 缺 | **新增** OpenAI 兼容 embedding 适配器(同 base_url/key),接给 retriever |
| Redis | ✅ 真 | 实例化 → 短期记忆 + 缓存 |
| Postgres | ✅ 真 | 实例化 → 长期记忆 + 元数据 |
| Trace | ✅ 真 | 扩展到 orchestrator 每步 |
| Memory | ✅ 真 | 接 Redis(短期)/ Postgres(长期) |

**③ 启动装配(`app/main.py` lifespan 扩展)**

```
lifespan:
  engine = init_engine(DB)            # 已有
  milvus = MilvusClient(...)          # 新增
  embed = OpenAIEmbeddingAdapter(...) # 新增
  retriever = MultiRetriever(milvus, embed)  # 通电
  redis = RedisCache(...)             # 通电
  memory = MemoryManager(redis, db)   # 通电
  router_llm = ModelRouter([cfg])     # 已有
  orchestrator = Orchestrator(...)    # 通电(核心)
  registry = DomainRegistry(scans app/domains/)
  app.state = {orchestrator, retriever, registry, ...}
```

路由从 `app.state` 取对象,不自己 `new`——保持现有 Protocol + 依赖注入风格。

**④ `.env` 多 provider 结构**

```env
# LLM(任一 OpenAI 兼容 provider)
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.siliconflow.cn/v1   # 或 openai/deepseek/vllm
LLM_MODEL=Qwen/Qwen2.5-72B-Instruct
# Embedding(可与 LLM 同或不同 provider)
EMBED_API_KEY=sk-...
EMBED_BASE_URL=https://api.siliconflow.cn/v1
EMBED_MODEL=BAAI/bge-m3
# 中间件
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://...
MILVUS_HOST=localhost  MILVUS_PORT=19530
```

**⑤ docker-compose**:已有 app/postgres/redis/milvus(+etcd+minio)。加:app 对 milvus 健康检查依赖 + 灌库脚本/命令(把 `domains/*/corpus` 灌进 Milvus)。

**⑥ 安全边界**:改造期对两个源仓库只读;所有写入只在 PolyAgent;`.env` 不进 git;连接串/key 不进任何日志、trace、commit。

---

## 5. 目录结构 / API / 分阶段 / 简历映射

**目录结构(project-python 基础上的 diff)**

```
PolyAgent/app/
  api/routes/  chat.py(改造) · document.py · eval.py(新) · health.py · domains.py(新)
  core/
    agent/  orchestrator.py(扩展) · react_agent · planner · deliberation.py(新,旗舰) · reflection(默认关)
    rag/  memory/  tools/  intent/   (已有,通电)
    eval/        (新:ragas + Recall@k + 延迟/成本)
  domains/              ← 新增层
    base.py  registry.py
    financial/  pack.py · corpus/*.md(←MiroFish) · prompts.py · eval_cases.json
    kb_qa/      pack.py
  infrastructure/  llm/(model_router+embedding.py新) · vectordb · cache · database · trace(全通电)
  etl/ models/  main.py(lifespan 装配扩展)
AGENT.md GRAPH.md TASKS.md MEMORY.md RUN_LOG.md   ← 状态文件(新)
docs/superpowers/specs/  ← 本设计文档
```

**API 面**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/chat` | `{messages, domain, mode?}` → 答复(非流式 + SSE 流式) |
| GET | `/api/v1/domains` | 列出已注册领域包 |
| POST | `/api/v1/eval` | `{domain}` → 跑评测管线,返回报告 |
| POST | `/api/v1/documents` | ETL 文档入库(已有) |
| GET | `/api/v1/health` | 健康检查 |

**分阶段计划**(详见 `TASKS.md`,GRAPH 节点见 `GRAPH.md`)

| Phase | 节点 | 内容 | 验收 |
|---|---|---|---|
| P0 | bootstrap | 状态文件 + 骨架(已复制) | 5 状态文件就位 |
| P1 | runtime-bootstrap | 基础设施通电 + compose up + 灌库 | health 通,corpus 可检 |
| P2 | domain-pack | base 契约 + registry + 两包 | `/domains` 列出两包 |
| P3 | rag-wire | MultiRetriever 通电 + rag_search | query 能检索出 chunk |
| P4 | **deliberation(旗舰)** | deliberation.py + orchestrator 分支 | bull/bear 评议→综合,带 steps |
| P5 | chat-wire | chat.py 接 Orchestrator | 三模式经 `/chat` 触发 |
| P6 | eval | 评测管线 + 黄金集 | `/eval` 出 RAGAS+Recall+延迟 |
| P7 | finish | 端到端 demo + 文档 | 一键 compose up + chat/eval 通 |

**简历映射(STAR bullet,数字待 P6 评测填充)**

- **平台/可插拔**:设计并实现可插拔多领域 Agent 平台,通过 `DomainPack` 契约实现新领域零改平台代码接入,以金融深度分析 + 通用知识问答两包验证。
- **多 agent 讨论(核心)**:将单领域多空辩论泛化为可复用的多视角审议编排模式,N 个 agent 并行评议 + 综合,立场与数量可配置。
- **评测量化**:在 `_N_` 条黄金集上用 RAGAS(Faithfulness/AnswerRelevancy)+ Recall@k 评测,综合答复 Faithfulness `_X→Y_`,Recall@5=`_Z_`,P95=`_W_ms`。
- **工程深度**:基于 Protocol 依赖注入接通 Milvus/Redis/Postgres 全栈,混合检索(向量+BM25+RRF)+ 模型熔断 + 全链路追踪。

---

## 6. 备选方案与取舍记录

- **方案 A vs B(辩论模式泛化)**:选 A(泛化为平台"多视角审议模式")。理由:B 会在面试里被迫解释"为什么只有金融";A 有金融 + kb_qa 两个真实使用者支撑,不是投机抽象。
- **领域定位**:选"通用平台 + 可插拔多领域",而非纯金融。理由:匹配 project-python 的领域无关架构,可插拔是更强的简历故事。
- **skill 实现形式**:选 Python 原生领域插件,而非 Claude-Skill 格式包。理由:具体、可跑、简历好讲;`agent-to-skill-converter` 的三分类作为*编写方法*而非运行时格式。
- **基础设施范围**:选完整企业栈(docker-compose 全栈)。理由:简历可写多中间件集成/熔断/追踪。

---

## 7. 未决 / 待实现时定

- settings 字段沿用 `openai_*` 还是重命名 `llm_*`/`embed_*`:不影响架构,P1 实现时定。
- 评测黄金集规模与具体指标阈值:P6 定。
- 流式 SSE 是否一期做:P5 定(非旗舰,可后置)。
