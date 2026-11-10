# RUN_LOG.md — PolyAgent 运行日志

> 每次设计/开发/验证/修复后追加。不删历史。

---

## 2026-08-07 — 设计完成 + 状态文件 bootstrap

**做了什么**:
- 调研两个来源仓库:`ai-agent-interview-guide-main/project-python`(企业骨架,教学用)+ `MiroFish-FinSight-master`(用户自己的金融 Agent)。
- 阅读面试仓库的简历模板/招聘分析/开源笔记文档,确立"简历可用"标准(STAR、量化、技术深度)。
- 用 brainstorming skill 与用户完成设计共创,确定:领域无关平台 + 可插拔领域包(Python 原生);旗舰 = 多视角审议(方案 A,泛化自 MiroFish 多空辩论);完整企业栈;provider-agnostic LLM;内置评测管线。
- codegraph 初始化 + 索引 PolyAgent(54 文件 / 591 节点 / 1096 边),并已索引两个来源仓库。
- 写设计文档:`docs/superpowers/specs/2026-08-07-polyagent-design.md`。
- bootstrap 状态文件:AGENT.md / GRAPH.md / TASKS.md / MEMORY.md / RUN_LOG.md(本文件)。

**关键决策(详见 MEMORY.md)**:
- 命名 PolyAgent;LLM provider-agnostic;多视角审议泛化为平台模式;砍 Firecrawl/反思/画图/web_search/运行时 RAGAS/FAISS;RAG 复用现有 MultiRetriever。

**验证**:
- 已核实 project-python 接线现状:Orchestrator/MultiRetriever 休眠(零调用点),chat.py 绕过 agent 层;LLM/Milvus/Redis/PG/Trace/Memory 真实现;Embedding 缺适配器。
- codegraph 索引成功,可查询。

**架构是否变化**:是——从"空壳骨架"确立为 PolyAgent 四层 + 多视角审议旗舰(见 GRAPH.md)。

**下一步**:P1 基础设施通电(embedding 适配器 + lifespan 装配 + compose + 灌库),等用户确认状态文件后开始。

---

## 2026-08-07 — git 仓库初始化 + 并行工作流 + P2/P4/P5 代码完成(Claude 侧)

**做了什么**:
- 初始化 git 仓库(分支 main),`.gitignore` 排除 `.env`/`.codegraph`/`worktrees/`;首次提交 baseline(68 文件,无 key 泄漏)。
- 建 Codex 工作树 `.worktrees/codex`(分支 `codex/infra-rag`)+ Claude 分支 `claude/domain-deliberation`。写 `CODEX.md` 工作分配。
- **P2 领域包(代码完成)**:`app/domains/base.py`(DomainPack Protocol + DomainContext + DeliberationSpec/ParticipantSpec/IntentHints/EvalDataset);`registry.py`(扫描注册,list/get/default/summarize,容错);`financial/` 旗舰包(pack + prompts←移植 MiroFish bull/bear/synthesis + corpus 6 篇←MiroFish + eval_cases);`kb_qa/` 轻量包;`app/core/tools/builtin/rag_search.py`(共享检索工具,pack 绑定 ctx.retriever);`app/api/routes/domains.py`;main.py 注册 domains 路由。
- **P4 多视角审议旗舰(代码完成)**:`app/core/agent/deliberation.py`(D1 共享检索→D2 asyncio.gather 并行评议→D3 综合,单失败不整批失败、全失败 success=False);orchestrator 加 `_run_deliberation` + 模式分派 + deliberation 不挂反思。
- **P5 chat 接线(代码完成,待集成测)**:chat.py 改为 意图→领域包→选模式→Orchestrator;`ChatRequest` 加 domain/mode,`ChatResponse` 加 mode_used/success/degraded;orchestrator.run 增 `tool_registry`/`deliberation_spec` 参数、`__init__` 增 `retriever`;ToolRegistry 补 `invoke`/`list_tool_names`。

**契约细化(影响双方)**:
- DomainPack.tools 改为 `tools(ctx: DomainContext)`:rag_search 需运行时 retriever,故工具按 ctx 构建。
- 共享 `RagSearchTool` 已由 Claude 写在 `app/core/tools/builtin/rag_search.py` —— **Codex 不需再写 rag_search**,只需把 MultiRetriever 通到 `app.state.retriever`。
- Orchestrator 构造增 `retriever` 形参 —— Codex 的 lifespan 实例化时传 `retriever=<retriever 实例>`。
- app.state key:orchestrator / registry / retriever / memory / router_llm(双方对齐)。

**验证**:`python -m py_compile` 全部新增/改动文件语法 OK(依赖未装,功能验证留端到端 docker)。

**架构是否变化**:是 —— 编排层新增 deliberation 模式 + 领域包按 ctx 注入工具 + chat 经编排器(原直连 LLM)。

**下一步**:Codex 侧 P1/P3;两侧合入后 P5 端到端测;然后 P6 评测、P7 收尾。

---

## 2026-08-07 — main 集成 Claude + Codex 分支

**做了什么**:
- 切回 `main`,快进合入 `claude/domain-deliberation`(P2/P4/P5),再合入 `codex/infra-rag`(P1/P3 + docker/test 依赖)。
- 解决集成契约冲突:删除 Codex 早期 `app/core/tools/rag_search.py`,统一使用 Claude 的共享 `app/core/tools/builtin/rag_search.py`;`app/core/tools/__init__.py` 改为导出 builtin 版本。
- 修正 `lifespan()`:启动时 `DomainRegistry.scan()`;`AgentOrchestrator(..., retriever=retriever)`;app.state key 与契约对齐。
- 修正 `ModelRouter.get_llm()` facade 不再把内部 `purpose` 参数透传给 OpenAI API。
- 修正 Settings 对 `DEBUG=release/prod/production` 的容错解析。
- README 更新为 PolyAgent 当前架构、env、Conda、验证与端到端待办。

**验证**:
- `D:\conda_envs\PolyAgent\python.exe -m pytest tests` → 9 passed。
- `D:\conda_envs\PolyAgent\python.exe -m py_compile ...` → 通过。
- `docker compose config --quiet` → 通过。
- `D:\conda_envs\PolyAgent\python.exe scripts\validate_p2.py` → financial + kb_qa 注册通过。
- Conda 环境 `D:\conda_envs\PolyAgent` 已安装/更新 requirements 与 pytest 依赖。

**架构是否变化**:否——本次是既定 P1–P5 分支集成与契约修正,没有新增节点/边。

**下一步**:Docker 端到端:compose up → health 全绿 → ingest corpus --confirmed → financial/kb_qa chat 验证;之后进入 P6 eval。

---

## 2026-08-11 — 一键启动脚本

**做了什么**:
- 新增根目录 `start.cmd` 作为 Windows 双击入口。
- 新增 `scripts/start.ps1`:检查 compose 配置 → `docker compose up -d app` → 轮询 `/api/v1/health` 到 Milvus/Redis/Postgres 全绿 → 输出 API/health/domains 地址。
- 支持 `-Build` 重建镜像、`-Ingest` 在 health 通过后确认灌入领域语料到 Milvus、`-Logs` 跟随 app 日志。
- 新增根目录 `chat.cmd` 与 `scripts/chat.ps1`:提供自然语言交互式对话入口,默认 `financial + deliberation`,支持 `/domain`、`/mode`、`/reset`、`/exit`。
- README 增加一键启动用法。

**验证**:
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1 -Help` → 通过。
- `POLYAGENT_NO_PAUSE=1 .\start.cmd` → 通过;health 返回 `{"status":"ok","dependencies":{"milvus":true,"redis":true,"postgres":true}}`。
- `POLYAGENT_NO_PAUSE=1; '/exit' | .\chat.cmd` → 通过;交互入口可启动并正常退出。

**架构是否变化**:否——仅新增启动 wrapper,不改变运行时节点/边。

---

## 2026-08-11 — 端到端自然语言效率测试脚本

**做了什么**:
- 新增 `scripts/e2e_chat_benchmark.py`:读取自然语言黄金问题,调用 `/api/v1/chat`,记录 HTTP/Agent 成功率、关键词全命中率、mode 命中率、P50/P95/Max 延迟、trace_id 与 answer preview。
- 新增 `e2e-benchmark.cmd` Windows 入口,优先使用 `D:\conda_envs\PolyAgent\python.exe`,回退系统 `python`。
- 报告写入 `reports/e2e/e2e_chat_benchmark_<run_id>.json|md`,Markdown 中生成一条“Resume-Safe Metrics”摘要,要求只在真实 `.env` provider 与目标 case set 下使用。
- README 增加端到端效率测试命令。

**验证**:
- `python -m py_compile scripts\e2e_chat_benchmark.py` → 通过。
- `.\e2e-benchmark.cmd --plan --max-cases 2` → 通过,正确读取 financial eval cases 并输出执行计划。
- 真实 `/chat` benchmark 需可用 `LLM_*` / `EMBED_*` provider,会产生实际模型调用成本,未擅自执行。

**架构是否变化**:否——新增评测/压测脚本,不改变运行时请求图。

---

## 2026-08-11 — 30 条金融自然语言端到端测试

**做了什么**:
- 将 `app/domains/financial/eval_cases.json` 从 6 条扩展到 30 条,覆盖事实召回、财务概念、公司对比、风险分析、估值、边界防幻觉与多视角审议。
- 修复 `scripts/ingest_corpus.py` 脚本入口在 Docker 容器内直接执行时找不到 `app` 包的问题,显式把项目根目录加入 `sys.path`。
- 使用真实 Docker 环境重建并启动 app,确认 Milvus/Redis/PostgreSQL 健康检查全绿。
- 执行 `.\start.cmd -Build -Ingest -TimeoutSeconds 240`,金融 corpus 6 个文件切分为 12 个 chunk 并写入 Milvus。
- 执行 `.\e2e-benchmark.cmd --repeat 1 --timeout 420 --max-tokens 700`,完成 30 条自然语言 `/api/v1/chat` 端到端测试。

**验证结果**:
- Health: `{"status":"ok","dependencies":{"milvus":true,"redis":true,"postgres":true}}`。
- Ingest: `{"status":"ok","files":6,"chunks":12}`。
- Benchmark 报告:
  - JSON: `reports/e2e/e2e_chat_benchmark_20260811T035538Z.json`
  - Markdown: `reports/e2e/e2e_chat_benchmark_20260811T035538Z.md`
- 30 条测试汇总:
  - HTTP 成功率: 30/30 = 100%。
  - Agent 成功率: 30/30 = 100%。
  - 模式匹配率: 30/30 = 100%。
  - 严格关键词全命中率: 21/30 = 70.00%。
  - 关键词整体命中率: 97/111 = 87.39%。
  - 延迟: avg 44310.49 ms, P50 25351.73 ms, P95 176065.35 ms, max 206302.66 ms。

**未决观察**:
- 多视角审议用例会触发多次 LLM 调用,是 P95 和 max 延迟的主要来源;简历中若引用延迟,应明确这是本地 Docker + 当前外部模型 provider 下的端到端结果。
- 部分未全命中用例属于中文表达差异导致的字面关键词未命中,例如回答表达为“没有找到资料”而不是“数据不足/知识库”;原始报告保留,未改口径美化结果。

**架构是否变化**:否——仅扩充评测集并修复灌库脚本入口兼容。

---

## 2026-08-11 — 多领域公开 Benchmark 转换

**做了什么**:
- 暂不接入 FinQA,优先使用本地已准备好的 TAT-QA、CUAD、SPL-ADR-200db。
- 新增 `scripts/prepare_benchmark_corpus.py`:把公开数据集转换为统一 JSONL 结构,每个数据集输出 `corpus.jsonl`、`eval_cases.jsonl`、`manifest.json`。
- 输出目录:`data/benchmarks/`。
- 统一 corpus schema:`doc_id/domain/dataset/source/title/text/metadata`。
- 统一 eval schema:`case_id/domain/dataset/query/gold_answer/gold_evidence_doc_ids/task_type/metadata`。
- 脚本默认 dry-run,使用 `--confirmed` 才写文件;使用 `--max-eval-cases -1` 可生成全量 eval。

**生成结果**:
- `financial_tatqa`:TAT-QA 金融表格+文本 QA,corpus 555 条,eval 3331 条。
- `legal_cuad`:CUAD 合同条款审查,corpus 510 条,eval 20910 条。
- `medical_spl_adr`:SPL-ADR-200db 药品不良反应抽取,corpus 200 条,eval 99 条。

**验证**:
- `D:\conda_envs\PolyAgent\python.exe -m py_compile scripts\prepare_benchmark_corpus.py` → 通过。
- `D:\conda_envs\PolyAgent\python.exe scripts\prepare_benchmark_corpus.py` → dry-run 成功。
- `D:\conda_envs\PolyAgent\python.exe scripts\prepare_benchmark_corpus.py --max-eval-cases -1 --confirmed` → 全量生成成功。
- 抽样读取每个 manifest、corpus 首行、eval 首行并 `json.loads` → 通过。

**下一步**:
- 扩展 ingest/eval,支持从 `data/benchmarks/*/corpus.jsonl` 灌库,从 `eval_cases.jsonl` 计算 Top-k evidence recall、answer accuracy/F1、grounded rate、hallucination rate。

**架构是否变化**:否——新增 P6 评测数据准备脚本,运行时请求图不变。

---

## 2026-08-11 — Benchmark 灌库与 Retrieval Recall 基线

**做了什么**:
- `MultiRetriever` 向量检索结果补充返回 `metadata/domain/source`,并解析 Milvus 中的 JSON metadata,用于评测阶段追溯 `doc_id`。
- 新增 `scripts/ingest_benchmark_corpus.py`:读取 `data/benchmarks/*/corpus.jsonl`,分块、embedding、写入 Milvus;默认 dry-run,`--confirmed` 才调用 `EMBED_*` 和写库。
- 新增 `scripts/eval_retrieval_benchmark.py`:读取 `corpus.jsonl` 与 `eval_cases.jsonl`,重建 BM25 索引,调用 `MultiRetriever`,计算 Top-k evidence recall、MRR、P50/P95/Max 检索延迟,输出 JSON/Markdown 到 `reports/retrieval/`。
- 修正 CUAD 转换口径:原始问题不带合同标题,在全局 510 合同检索中不可判别;转换后的 query 增加 `In contract <title>, ...`,原始问题保留到 metadata。

**验证**:
- `D:\conda_envs\PolyAgent\python.exe -m py_compile app\core\rag\retriever.py scripts\ingest_benchmark_corpus.py scripts\eval_retrieval_benchmark.py` → 通过。
- `scripts\ingest_benchmark_corpus.py --corpus data\benchmarks\financial_tatqa\corpus.jsonl` dry-run → documents 555,chunks 801。
- `scripts\eval_retrieval_benchmark.py ... --plan` → 正确读取 financial_tatqa 20 cases。
- 尝试 TAT-QA 向量灌库到 `benchmark_financial_tatqa` 时,embedding provider 返回 `402 insufficient balance`;未完成 Milvus benchmark 写入。

**零模型成本 keyword baseline**:
- TAT-QA financial,3331 cases,Recall@5 74.06%,MRR 0.7931,P95 6.16 ms。
  - 报告:`reports/retrieval/retrieval_benchmark_financial_tatqa_20260811T062434Z.json|md`
- SPL-ADR medical,99 cases,Recall@5 98.99%,MRR 1.0000,P95 6.44 ms。
  - 报告:`reports/retrieval/retrieval_benchmark_medical_spl_adr_20260811T062534Z.json|md`
- CUAD legal,500-case sample,Recall@5 22.40%,MRR 0.7089,P95 283.03 ms。
  - 报告:`reports/retrieval/retrieval_benchmark_legal_cuad_20260811T063526Z.json|md`
- CUAD legal,同 500-case sample,Recall@20 33.40%,MRR 0.5076,P95 265.02 ms。
  - 报告:`reports/retrieval/retrieval_benchmark_legal_cuad_20260811T064003Z.json|md`

**未决观察**:
- TAT-QA 和 SPL-ADR 在 keyword baseline 上已能形成可复现简历指标;CUAD 长合同检索明显更难,后续应重点做向量/混合检索、按合同过滤、chunk 策略和 rerank 对比。
- vector/hybrid 指标暂受 embedding provider 余额限制,不能声称已完成。

**架构是否变化**:否——新增 P6 评测工具与检索结果元数据,运行时请求图不变。

---

## 2026-08-11 — 多 Agent 审议模式专项测试

**做了什么**:
- 明确 retrieval-only benchmark 不能代表多 agent 辩论功能测试;新增专项 E2E 脚本 `scripts/e2e_deliberation_benchmark.py`。
- `ChatResponse` 新增 `steps` 字段,`/chat` 返回 `agent_resp.steps`,用于外部验证 D1/D2/D3 编排步骤。
- `e2e_deliberation_benchmark.py` 强制调用 `/api/v1/chat` with `domain=financial, mode=deliberation`,并检查:
  - `mode_used == deliberation`
  - D1 shared retrieval step 存在
  - D2 participant step 存在
  - bull/bear roles 均出现
  - D3 synthesis step 存在
  - 回答关键词命中
- 新增 `tests/test_deliberation_agent.py`:用 fake retriever + fake LLM 离线验证 D1→D2→D3 完整链路,以及单 participant 失败不拖垮整批。

**验证**:
- `D:\conda_envs\PolyAgent\python.exe -m py_compile app\models\schemas.py app\api\routes\chat.py scripts\e2e_deliberation_benchmark.py tests\test_deliberation_agent.py` → 通过。
- `D:\conda_envs\PolyAgent\python.exe scripts\e2e_deliberation_benchmark.py --plan` → 3 条 deliberation case 计划输出通过。
- `.\start.cmd -Build -TimeoutSeconds 240` → Docker app 重建并 health 全绿。
- `D:\conda_envs\PolyAgent\python.exe scripts\e2e_deliberation_benchmark.py --timeout 420 --max-tokens 700` → 真实 E2E 执行,但 LLM provider 返回 402 insufficient balance:
  - 报告:`reports/e2e/e2e_deliberation_benchmark_20260811T065154Z.json|md`
  - 结果:mode matched 3/3,D1 present 3/3,D2 present 3/3,bull/bear roles matched 3/3,D3 present 0/3,chain success 0/3。
  - 原因:bull/bear 两个 participant 调 LLM 均失败,因此没有可综合观点,D3 不执行。
- `D:\conda_envs\PolyAgent\python.exe -m pytest tests\test_deliberation_agent.py -q` → 2 passed。
- `D:\conda_envs\PolyAgent\python.exe -m pytest tests -q` → 11 passed。

**结论**:
- 多 agent 审议编排逻辑本身通过离线功能测试;真实模型端到端测试被 provider 余额/熔断阻断,不能声称 E2E 成功。
- 恢复 LLM provider 后,直接重跑 `scripts\e2e_deliberation_benchmark.py` 可得到真实 D1/D2/D3 端到端指标。

**架构是否变化**:否——API 响应增加调试/评测 steps 字段,运行时请求图不变。

---

## 2026-08-11 — 多 Agent 审议真实 E2E 复测通过

**做了什么**:
- 用户补充模型余额后,重启 Docker app 清除此前 402 导致的 LLM 熔断器 OPEN 状态。
- 重新执行 `scripts\e2e_deliberation_benchmark.py --timeout 420 --max-tokens 700`,真实调用 `/api/v1/chat` 的 `financial + deliberation` 路径。

**验证**:
- `docker compose restart app` → 通过。
- `.\start.cmd -TimeoutSeconds 180` → health 全绿:`{"status":"ok","dependencies":{"milvus":true,"redis":true,"postgres":true}}`。
- `D:\conda_envs\PolyAgent\python.exe scripts\e2e_deliberation_benchmark.py --timeout 420 --max-tokens 700` → 通过。

**结果**:
- 报告:
  - JSON:`reports/e2e/e2e_deliberation_benchmark_20260811T065947Z.json`
  - Markdown:`reports/e2e/e2e_deliberation_benchmark_20260811T065947Z.md`
- 3 条 deliberation case 全部通过:
  - Deliberation chain success:3/3 = 100%。
  - API success:3/3。
  - mode matched:3/3。
  - D1/D2/D3 present:3/3/3。
  - bull/bear roles matched:3/3。
  - keyword all-matched:3/3。
- D1 shared retrieval 每条均命中 8 个上下文。
- 延迟:
  - avg 162627.33 ms。
  - P50 143969.67 ms。
  - P95 233847.39 ms。
  - max 243833.80 ms。

**结论**:
- 多 agent 审议旗舰路径已经完成真实 Docker E2E 验证:D1 共享检索 → D2 bull/bear 并行评议 → D3 综合答复。
- 当前主要短板是多 LLM 调用导致端到端延迟高,后续优化方向:减少输出长度、并行/超时策略、模型路由降级、缓存 D1 检索与压缩共享上下文。

**架构是否变化**:否——复测验证,无新增架构节点。

---

## 2026-08-11 — 多领域 RAG + 多 Agent 综合 E2E

**做了什么**:
- 新增 `legal_compliance` 领域包:合同/合规知识助手,默认 `react`,工具为领域化 `rag_search`。
- 新增 `medical_adr` 领域包:药品标签与 ADR 知识助手,默认 `react`,工具为领域化 `rag_search`,明确非诊断/非用药建议边界。
- 新增 `scripts/prepare_multidomain_e2e_suite.py`:从 TAT-QA、CUAD、SPL-ADR-200db 抽取小样本 E2E suite,输出:
  - `data/benchmarks/e2e_multidomain/corpus.jsonl`
  - `data/benchmarks/e2e_multidomain/cases.json`
  - `data/benchmarks/e2e_multidomain/manifest.json`
- 新增 `scripts/e2e_multidomain_rag_benchmark.py`:读取 suite cases,逐条调用 `/api/v1/chat`,统计 chain success、RAG used、关键词命中、按领域成功率、P50/P95/Max 延迟。
- 修复多领域共用 Milvus collection 的 RAG 污染问题:
  - `RagSearchTool` 新增 `domain_filter`,按 `RetrievalResult.metadata.domain` 过滤结果。
  - financial/kb_qa/legal_compliance/medical_adr 均传入自己的 domain filter。
  - 检索输出 source 改为优先显示 metadata source/doc_id,方便追溯。

**验证准备**:
- `D:\conda_envs\PolyAgent\python.exe -m py_compile ...` → 通过。
- `D:\conda_envs\PolyAgent\python.exe scripts\validate_p2.py` → 注册领域为 `financial/kb_qa/legal_compliance/medical_adr`,通过。
- `D:\conda_envs\PolyAgent\python.exe -m pytest tests -q` → 11 passed。
- `D:\conda_envs\PolyAgent\python.exe scripts\prepare_multidomain_e2e_suite.py --per-domain 2 --confirmed` → 生成 6 篇 corpus + 7 条 E2E cases。
- `D:\conda_envs\PolyAgent\python.exe scripts\ingest_benchmark_corpus.py --corpus data\benchmarks\e2e_multidomain\corpus.jsonl --collection agent_knowledge --chunk-size 768 --chunk-overlap 96 --batch-size 32 --confirmed` → 写入 60 chunks,dim 4096。
- `.\start.cmd -Build -TimeoutSeconds 240` → Docker app 重建并 health 全绿。
- `GET /api/v1/domains` → 返回 4 个领域,默认 `financial`。

**综合 E2E 结果**:
- 命令:`D:\conda_envs\PolyAgent\python.exe scripts\e2e_multidomain_rag_benchmark.py --timeout 420 --max-tokens 600`
- 报告:
  - JSON:`reports/e2e/e2e_multidomain_rag_benchmark_20260811T072919Z.json`
  - Markdown:`reports/e2e/e2e_multidomain_rag_benchmark_20260811T072919Z.md`
- 覆盖:
  - `financial`:TAT-QA react RAG 2 条 + financial deliberation 1 条。
  - `legal_compliance`:CUAD contract parties RAG 2 条。
  - `medical_adr`:SPL-ADR ADR lookup RAG 2 条。
- 指标:
  - Total cases:7。
  - Chain success:7/7 = 100%。
  - API success:7/7。
  - RAG used:7/7。
  - Domain success:financial 3/3,legal_compliance 2/2,medical_adr 2/2。
  - Keyword all-matched:3/7 = 42.86%。
  - Keyword overall hit:12/22 = 54.55%。
  - Latency:P50 77535.06 ms,P95 119388.42 ms,max 127976.78 ms。

**重要观察**:
- 第一轮综合 E2E 暴露跨领域检索污染:financial TAT-QA 问题检到了 CUAD/软件分发片段;通过 `domain_filter` 修复后,financial 回答不再混入合同/软件内容。
- 当前综合链路能证明多领域、RAG、公开数据集、Docker app、chat API 和 financial 多 agent deliberation 均已打通。
- 但答案质量指标仍不高,尤其医疗 ADR 英文 gold 与模型中文摘要存在字面差异;后续应加入证据 doc_id 命中、语义 F1/LLM judge、领域术语 bilingual normalization,不能只看 chain success。

**架构是否变化**:是——新增两个领域包,平台请求图不变,但领域生态从 2 包扩展为 4 包。

---

## 2026-08-12 — 领域扩展机制从 Python 领域包迁移为项目内 Skill

**背景**:用户明确要求不要继续维护"可插拔领域包"作为运行时扩展方式,而是把领域知识转成项目内 Skill;平台负责通用编排、RAG、记忆、工具、模型路由与追踪。

**改动**:
- 新增 `skills/financial-analysis`、`skills/kb-qa`、`skills/contract-review`、`skills/medical-adr` 四个示例领域 Skill。Skill frontmatter 声明 domain/default_mode/tools/corpus/eval/deliberation,Markdown 正文承载 system prompt 与审议参与者提示词。
- 重写 `app/domains/registry.py`:启动扫描 `skills/*/SKILL.md`,生成 `DomainSkill` adapter,继续暴露 `list_domains/get/default/summarize`,保证 `/chat` 和 `/domains` 入口稳定。
- `app/main.py` 启动 BM25 关键词语料注册改为读取 Skill 的 `corpus_paths`;`scripts/ingest_corpus.py` dry-run/confirmed 灌库也改为读取 Skill 声明语料。
- 同步 `README.md`、`AGENT.md`、`TASKS.md`、`app/domains/base.py`、API 文案和 `domain-knowledge-to-skill/SKILL.md`,明确新领域接入只新增 `skills/<domain>/SKILL.md`,不新增硬编码 Python pack。
- 新增 `tests/test_domain_skill_registry.py`,覆盖 Skill 发现、工具声明、intent_hints 与 deliberation section 解析。

**验证**:
- `python -m py_compile app/domains/registry.py app/main.py scripts/ingest_corpus.py tests/test_domain_skill_registry.py` 通过。
- `D:\conda_envs\PolyAgent\python.exe -m pytest tests\test_domain_skill_registry.py -q --basetemp D:\project\PolyAgent\.tmp\pytest` 通过:2 passed。默认 `.pytest_cache` 写入仍受 Windows 权限影响,不影响测试结果。
- `D:\conda_envs\PolyAgent\python.exe scripts\validate_p2.py` 通过:注册 `financial/kb_qa/legal_compliance/medical_adr`,默认 Skill 为 `kb_qa`。
- `D:\conda_envs\PolyAgent\python.exe scripts\ingest_corpus.py --root D:\project\PolyAgent` dry-run 通过:从 Skill `corpus_paths` 发现 financial 6 篇语料,未执行 Milvus 写入。

---

## 2026-08-11 — 综合 E2E 补充 RAG Evidence Hit 指标

**做了什么**:
- `RagSearchTool` 输出格式增加 `doc_id=<...>`,让 `/chat` 返回的 tool observation 可以和 benchmark 的 `gold_evidence_doc_ids` 对齐。
- `scripts/e2e_multidomain_rag_benchmark.py` 新增端到端 evidence hit 统计:
  - 只统计有 `gold_evidence_doc_ids` 的 RAG case。
  - 判断 `/chat` steps/tool observation 中是否出现 gold doc_id。
  - 输出 `evidence_case_count/evidence_hit_count/evidence_hit_rate`。
- 更新 `tests/test_rag_search_tool.py` 的契约断言,检查 `doc_id` 输出。

**验证**:
- `D:\conda_envs\PolyAgent\python.exe -m pytest tests -q` → 11 passed。
- `.\start.cmd -Build -TimeoutSeconds 240` → Docker app 重建并 health 全绿。
- `D:\conda_envs\PolyAgent\python.exe scripts\e2e_multidomain_rag_benchmark.py --timeout 420 --max-tokens 600` → 通过。

**结果**:
- 报告:
  - JSON:`reports/e2e/e2e_multidomain_rag_benchmark_20260811T074750Z.json`
  - Markdown:`reports/e2e/e2e_multidomain_rag_benchmark_20260811T074750Z.md`
- Total cases:7。
- Chain success:7/7 = 100%。
- API success:7/7。
- RAG used:7/7。
- Evidence cases:6。
- Evidence hit:5/6 = 83.33%。
- Domain success:financial 3/3,legal_compliance 2/2,medical_adr 2/2。
- Keyword all-matched:3/7 = 42.86%。
- Latency:P50 45305.84 ms,P95 116687.93 ms,max 134099.45 ms。

**未命中分析**:
- 唯一 evidence miss 是 TAT-QA financial 第二条 `How is industry end market information presented?`;链路成功但未命中 gold doc,说明端到端 RAG 仍有检索/排序优化空间。
- 这个指标比单纯 `chain success` 更适合写进项目复盘:它证明 RAG 被调用,且 6 条有 gold evidence 的公开数据集用例中 5 条在真实 `/chat` 工具链路里命中正确证据。

**架构是否变化**:否——增加评测可观测字段和报告指标,请求图不变。

---

## 2026-08-11 — 综合 E2E RAG Precision / Recall 修正口径

**背景**:
- 上一轮 evidence hit 统计只看是否命中至少一个 gold doc,不足以表达检索精确度。
- CUAD 合同 doc_id 含逗号/空格,旧解析逻辑容易截断 doc_id;已修正为按 `doc_id=..., source=` 边界提取。

**验证命令**:
- `D:\conda_envs\PolyAgent\python.exe scripts\e2e_multidomain_rag_benchmark.py --timeout 420 --max-tokens 600`

**可信报告**:
- JSON:`reports/e2e/e2e_multidomain_rag_benchmark_20260811T080925Z.json`
- Markdown:`reports/e2e/e2e_multidomain_rag_benchmark_20260811T080925Z.md`

**端到端 RAG 指标**:
- Total cases:7。
- RAG used:7/7。
- Evidence cases:6。
- Evidence hit:5/6 = 83.33%。
- Evidence Precision avg:53.33%。
- Evidence Recall avg:83.33%。
- Keyword all-matched:3/7 = 42.86%。
- Latency:P50 70698.36 ms,P95 115587.36 ms,max 124393.31 ms。

**按领域拆分**:
- financial RAG evidence cases:2 条,Precision avg 10.00%,Recall avg 50.00%;第二条 TAT-QA 未命中 gold doc,是当前主要短板。
- legal_compliance RAG evidence cases:2 条,Precision avg 75.00%,Recall avg 100.00%。
- medical_adr RAG evidence cases:2 条,Precision avg 75.00%,Recall avg 100.00%。

**解释**:
- Chain success 100% 只表示 `/chat` 编排、工具调用和响应链路跑通,不能等同答案质量。
- 简历/复盘建议使用 evidence Precision/Recall 表达 RAG 质量,并保留“金融数值表格问答仍需 query rewrite/rerank 优化”的真实改进空间。

---

## 2026-08-11 — 近 50 条多领域 E2E 分批测试

**做了什么**:
- 生成近 50 条多领域公开评测集:
  - 命令:`D:\conda_envs\PolyAgent\python.exe scripts\prepare_multidomain_e2e_suite.py --per-domain 16 --out data\benchmarks\e2e_multidomain_50 --confirmed`
  - 输出:`data/benchmarks/e2e_multidomain_50/{corpus.jsonl,cases.json,manifest.json}`
  - 规模:48 篇 corpus,49 条 cases。
- 将评测 corpus 写入 Milvus:
  - dry-run:48 docs,369 chunks。
  - confirmed:48 docs,369 chunks,dim 4096。
- `scripts/e2e_multidomain_rag_benchmark.py` 新增批次参数:
  - `--start-index`
  - `--batch-size`
  - 目的:按 5 条一批跑真实 `/chat`,避免一次性长跑难定位失败。

**分批测试命令模式**:
- `D:\conda_envs\PolyAgent\python.exe scripts\e2e_multidomain_rag_benchmark.py --cases data\benchmarks\e2e_multidomain_50\cases.json --start-index <N> --batch-size 5 --timeout 420 --max-tokens 600`
- 实际批次:`N=0,5,10,15,20,25,30,35,40,45`。

**批次报告**:
- `reports/e2e/e2e_multidomain_rag_benchmark_20260811T083945Z.{json,md}`
- `reports/e2e/e2e_multidomain_rag_benchmark_20260811T084209Z.{json,md}`
- `reports/e2e/e2e_multidomain_rag_benchmark_20260811T084502Z.{json,md}`
- `reports/e2e/e2e_multidomain_rag_benchmark_20260811T084654Z.{json,md}`
- `reports/e2e/e2e_multidomain_rag_benchmark_20260811T085302Z.{json,md}`
- `reports/e2e/e2e_multidomain_rag_benchmark_20260811T085945Z.{json,md}`
- `reports/e2e/e2e_multidomain_rag_benchmark_20260811T090802Z.{json,md}`
- `reports/e2e/e2e_multidomain_rag_benchmark_20260811T091208Z.{json,md}`
- `reports/e2e/e2e_multidomain_rag_benchmark_20260811T091515Z.{json,md}`
- `reports/e2e/e2e_multidomain_rag_benchmark_20260811T091925Z.{json,md}`

**聚合结果(case 级重新汇总,非批次均值)**:
- Total cases:49。
- Chain success:48/49 = 97.96%。
- API success:48/49 = 97.96%。
- RAG used:49/49。
- Evidence cases:48。
- Evidence hit:28/48 = 58.33%。
- Evidence Precision avg:27.90%。
- Evidence Recall avg:58.33%。
- Keyword all-matched:9/49 = 18.37%。

**按领域 evidence 指标**:
- financial:16 evidence cases,hit 6/16 = 37.50%,precision avg 21.25%,recall avg 37.50%。
- legal_compliance:16 evidence cases,hit 9/16 = 56.25%,precision avg 20.94%,recall avg 56.25%。
- medical_adr:16 evidence cases,hit 13/16 = 81.25%,precision avg 41.52%,recall avg 81.25%。

**观察**:
- 多领域链路和多 Agent deliberation 基本稳定,但 RAG 质量并不高,尤其 financial TAT-QA 表格/数值问答和部分长合同 parties 抽取。
- legal 第 5 批出现 1 条链路失败:`e2e_cuad_ADAMSGOLFINC_03_21_2005-EX-10.17-ENDORSEMENT AGREEMENT__Parties`;HTTP 200,但 react 未产出 final step,工具调用达到 10 次,说明需要 step 上限后的优雅终止/总结。
- 简历建议写“近 50 条自建公开评测集 + 分批 Docker E2E + 链路成功率 97.96% + evidence recall 58.33% + 医药 ADR recall 81.25%”,不要写小样本 83.33%/53.33%。

**架构是否变化**:否——评测脚本 CLI 扩展与评测资产增加,平台请求图不变。

---

## 2026-08-11 — RAG 质量升级并行开发计划

**做了什么**:
- 新增设计计划:`docs/superpowers/specs/2026-08-11-rag-quality-upgrade-plan.md`。
- 计划目标:针对 49 条 E2E 暴露的 financial TAT-QA 与部分 CUAD 长合同检索偏差,升级为 metadata-aware routing + structured indexing + rerank + deterministic tools。
- 计划中明确:
  - 当前基线:overall evidence recall 58.33%,financial 37.50%,legal 56.25%,medical 81.25%。
  - Worktree A/Claude:`claude/rag-domain-structured-tools`,负责 QueryAnalyzer、TAT-QA/CUAD 结构化 ETL、table_calculator、contract_clause_locator、领域包挂工具。
  - Worktree B/Codex:`codex/rag-retrieval-rerank-eval`,负责 RetrievalRequest、metadata filtering、Reranker Protocol、top50->top5 rerank、批次报告聚合。
  - 合并顺序:Codex 检索基础设施先合,Claude 领域工具后合,最后重新 ingest + 5 条一批 E2E。
- 文档内附 Claude Code 可直接粘贴的开工提示词。

**验证**:
- 文档创建完成。
- 未执行 worktree 创建和代码改造。

**架构是否变化**:计划层变化,运行时代码未变。

---

## 2026-08-12 — RAG 质量升级两侧分支集成

**做了什么**:
- 在干净集成 worktree `.worktrees/integrate-rag-upgrade` 从 `main` 合并两侧分支:
  - `codex/rag-retrieval-rerank-eval` commit `60f9b67`。
  - `claude/rag-domain-structured-tools` commit `0aec9a1`。
- 合并顺序:Codex → Claude。
- 代码文件无冲突;仅 `TASKS.md` / `RUN_LOG.md` 状态文件冲突,已保留两侧记录并整理为统一 P6-RAG-Upgrade 状态。
- 当前合并结果同时包含:
  - Codex:RetrievalRequest、metadata-aware filters、Reranker Protocol、Milvus expr、batch E2E aggregate、benchmark ingest/eval 脚本。
  - Claude:QueryAnalyzer、TAT-QA/CUAD 结构化 corpus 生成、table_calculator、contract_clause_locator、领域包工具接线。

**待验证**:
- 重新生成 `e2e_multidomain_50` 结构化 corpus。
- 重新 ingest 到 Milvus。
- 先抽之前差的 5 条复测,再决定是否继续 49 条全量分批。

**架构是否变化**:是——RAG 层完成结构化检索计划的两侧代码集成,API 请求图未变。

---

## 2026-08-12 — RAG Upgrade 小批差例复测(legal batch 20-24)

**做了什么**:
- 复制主项目 `.env` 到 integration worktree 的本地忽略文件,仅用于本地 API/ingest,未提交也未打印密钥。
- 使用外部数据集绝对路径重新生成结构化 benchmark:
  - TAT-QA:`D:\project\PolyAgent\TAT-QA\dataset_raw`
  - CUAD:`D:\project\PolyAgent\cuad\data.zip`
  - SPL:`D:\project\PolyAgent\train_xml` / `gold_xml`
- 结构化输出:
  - TAT-QA corpus:16220 rows,eval:3331。
  - CUAD corpus:7212 rows,eval:20910。
  - SPL-ADR corpus:200 rows,eval:99。
- 生成 `data/benchmarks/e2e_multidomain_50`:
  - corpus_count:795。
  - case_count:49。
- 重新 ingest 到 Milvus:
  - dry-run:795 docs,1120 chunks。
  - confirmed:795 docs,1120 chunks,dim 4096。
- 发现 `ChatResponse` 未返回 `steps`,导致 E2E 无法计算 evidence;补回 `steps` 字段与 `/chat` 返回 `agent_resp.steps`。
- 启动 integration 本地 API:`http://127.0.0.1:8010`,连接已有 Docker Redis/Postgres/Milvus。
- 只复测旧表现差的 legal batch:start-index 20,batch-size 5。

**验证**:
- `D:\conda_envs\PolyAgent\python.exe -m py_compile ...` → 通过。
- `D:\conda_envs\PolyAgent\python.exe -m pytest tests -q` → 43 passed。
- `D:\conda_envs\PolyAgent\python.exe scripts\e2e_multidomain_rag_benchmark.py --base-url http://127.0.0.1:8010 --cases data\benchmarks\e2e_multidomain_50\cases.json --start-index 20 --batch-size 5 --timeout 420 --max-tokens 600` → 通过。

**结果**:
- 报告:`reports/e2e/e2e_multidomain_rag_benchmark_20260812T013801Z.json|md`。
- 对比旧同批 baseline:`chain 4/5,evidence hit 1/5`。
- 新结果:
  - Chain success:5/5 = 100%。
  - API success:5/5。
  - RAG used:5/5。
  - Evidence hit:3/5 = 60%。
  - Evidence Precision avg:13.00%。
  - Evidence Recall avg:60.00%。
  - Latency:P50 79170.36 ms,P95 91883.74 ms,max 94973.57 ms。
- 命中:NELNET、VEONEER、Dova。
- 未命中:ADAMSGOLF、KIROMIC。

**观察**:
- 小批差例相对旧 baseline 有改善:链路失败修复为 0,证据命中从 20% 提升到 60%。
- 仍存在法律域内部串合同问题,说明 contract_name/clause_type 强过滤尚未真正进入 first-stage rag_search 参数,目前主要依赖模型选择工具与 post-filter;后续应把 QueryAnalyzer 结果接入 retriever filters。

**架构是否变化**:是——补回 `/chat` response steps 评测信封;RAG 主链路代码已集成但 QueryAnalyzer→retriever filters 尚未完全接线。

---

## 2026-08-12 — QueryAnalyzer 接入 rag_search 过滤链路

**做了什么**:
- 在 `RagSearchTool` 内接入 `QueryAnalyzer`,将自然语言问题解析出的 `contract_name` / `clause_type` / `year` / `drug_name` 等结构化条件合并到 `RetrievalRequest.filters`。
- 对 CUAD/TAT-QA/SPL-ADR 的 `preferred_chunk_types` 自动转成 `chunk_type` filter,优先召回结构化 chunk。
- 结构化查询存在时将 first-stage `top_n` 扩到至少 120,减少召回后 metadata 过滤把候选清空的风险。
- 将 retriever metadata filter 的字符串匹配改成大小写不敏感,避免 `Parties` / `parties` 这类大小写差异造成误杀。
- 新增 `rag_search` 单测覆盖 CUAD 合同查询会生成 `contract_name + clause_type + chunk_type` 过滤条件。

**验证**:
- `D:\conda_envs\PolyAgent\python.exe -m py_compile app\core\tools\builtin\rag_search.py app\core\rag\retriever.py` → 通过。
- `D:\conda_envs\PolyAgent\python.exe -m pytest tests\test_rag_search_tool.py tests\test_query_analyzer.py -q` → 9 passed。
- 设置 `TMP/TEMP=.pytest_tmp` 后运行 `D:\conda_envs\PolyAgent\python.exe -m pytest tests -q -o cache_dir=.pytest_tmp\cache` → 44 passed。
- 启动 integration API `http://127.0.0.1:8010`,仅复测旧差例 legal batch:start-index 20,batch-size 5。

**结果**:
- 报告:`reports/e2e/e2e_multidomain_rag_benchmark_20260812T015316Z.json|md`。
- 对比上一轮同批结果:`evidence hit 3/5`。
- 新结果:
  - Chain success:5/5。
  - RAG used:5/5。
  - Evidence hit:4/5 = 80%。
  - Evidence recall avg:80%。
- 新增命中:ADAMSGOLF、KIROMIC。
- 仍未命中:Dova。

**观察**:
- QueryAnalyzer→RetrievalRequest 过滤接线有效,legal 同批 evidence hit 从旧 baseline 1/5 → 集成后 3/5 → 本轮 4/5。
- 当前 Milvus schema 只有 `domain/source` 是顶层字段,`contract_name/clause_type/chunk_type` 仍在 JSON metadata 中,所以这次主要是“扩大候选后召回后过滤”,还不是 Milvus first-stage expr 硬过滤。
- 若继续优化 legal 长合同,下一步应考虑将高价值 metadata 字段提升为 Milvus schema 字段,或建立轻量 metadata inverted index,以降低延迟并减少同域合同串扰。

**架构是否变化**:是——RAG 工具入口开始使用结构化 QueryPlan 驱动检索过滤;API 与领域包契约未变。

---

## 2026-08-12 — Milvus metadata 字段提升与合同级 first-stage filter

**做了什么**:
- 扩展 `MilvusManager.create_collection()` schema,将高价值 metadata 提升为顶层字段:
  - `dataset` / `doc_id` / `chunk_type` / `contract_name` / `clause_type` / `drug_name` / `year`。
- `MilvusManager.insert()` 写入新字段,并保留旧 schema fallback,避免未重建 collection 的环境直接失败。
- `MilvusManager.search()` 默认读取新字段并合并回结果行,也保留旧 schema fallback。
- 新增 `drop_collection()` 供显式维护流程使用。
- `scripts/ingest_benchmark_corpus.py` 增加 `--recreate`,仅在 `--confirmed --recreate` 下删除并重建目标集合。
- benchmark ingest 将 dataset 标准化为 `tatqa/cuad/spl_adr`,保留 `dataset_raw`,避免 Milvus expr 大小写敏感导致 `CUAD` 与 `cuad` 不匹配。
- retriever 的 Milvus expr 改为只推入稳定字段:
  - `id/domain/dataset/doc_id/chunk_type/contract_name/source`。
  - `clause_type/year/drug_name` 继续交给 Python metadata 后过滤,避免 first-stage 过严导致候选清空。

**验证**:
- `D:\conda_envs\PolyAgent\python.exe -m py_compile app\infrastructure\vectordb\milvus_client.py app\core\rag\retriever.py scripts\ingest_benchmark_corpus.py` → 通过。
- `D:\conda_envs\PolyAgent\python.exe -m pytest tests\test_rag_retriever_filters.py tests\test_retriever_contract.py tests\test_rag_search_tool.py -q` → 7 passed。
- 设置 `TMP/TEMP=.pytest_tmp` 后运行 `D:\conda_envs\PolyAgent\python.exe -m pytest tests -q -o cache_dir=.pytest_tmp\cache` → 45 passed。
- 使用 `--confirmed --recreate` 重建并灌入 benchmark collection:
  - documents:795。
  - chunks:1120。
  - dim:4096。
- 直接 Milvus 探针验证:
  - `dataset == "cuad" and contract_name == "NELNETINC_..." and clause_type == "Parties"` 可命中目标条款。
- 启动 API `http://127.0.0.1:8011`,只复测旧差例 legal batch:start-index 20,batch-size 5。

**结果**:
- 严格 first-stage `clause_type` 过滤的中间实验失败:
  - `dataset` 大小写未标准化时 evidence hit 为 0/5。
  - 标准化后但仍强推 `clause_type` 时 evidence hit 为 2/5。
- 最终采用“合同级硬过滤 + 条款类型后过滤”:
  - 报告:`reports/e2e/e2e_multidomain_rag_benchmark_20260812T024806Z.json|md`。
  - Chain success:5/5。
  - RAG used:5/5。
  - Evidence hit:4/5 = 80%。
  - Evidence recall avg:80%。
  - 命中:NELNET、ADAMSGOLF、KIROMIC、Dova。
  - 未命中:VEONEER。

**观察**:
- 合同级 first-stage filter 可以减少跨合同串扰,但 `clause_type` 这类字段不能过早硬过滤;CUAD 标注粒度、用户问题措辞和模型工具调用之间存在偏差,过严会把必要上下文挡掉。
- 延迟没有稳定下降,说明当前瓶颈更多来自端到端模型工具链与生成,不是 Milvus 返回候选本身。
- 当前最稳结果仍是 legal 同批 evidence hit 4/5;不应在简历或文档中夸大为全量显著提升。

**架构是否变化**:是——Milvus schema 支持结构化 metadata 顶层字段与显式重建灌库;retriever 支持合同级 first-stage expr + 后过滤组合策略。

---

## 2026-08-12 — medical_adr 领域接线与 SPL-ADR 五条 E2E

**做了什么**:
- 新增 `app/domains/medical_adr` 领域包:
  - 默认 `react`。
  - 挂载 `RagSearchTool(domain_filter="medical_adr", dataset_filter="spl_adr")`。
  - system prompt 约束只基于 SPL-ADR 药品标签和标注反应回答。
- 修复 SPL-ADR metadata 契约错位:
  - `prepare_benchmark_corpus.py` 为 SPL 文档写入 `drug_name` 与 `chunk_type="spl_label"`。
  - `QueryAnalyzer` 对 SPL-ADR 优先 `spl_label` chunk。
  - `ingest_benchmark_corpus.py` 将 `SPL-ADR-200db` 标准化为 `spl_adr`。
  - retriever 允许 `drug_name` 进入 Milvus first-stage expr。
- 新增测试:
  - `tests/test_medical_adr_domain.py` 验证 registry 能扫描 medical_adr 且工具为 rag_search。
  - QueryAnalyzer / retriever filter 测试覆盖 SPL `drug_name` 与 `spl_label`。

**验证**:
- `D:\conda_envs\PolyAgent\python.exe -m py_compile app\domains\medical_adr\pack.py app\core\rag\query_analyzer.py app\core\rag\retriever.py scripts\prepare_benchmark_corpus.py` → 通过。
- `D:\conda_envs\PolyAgent\python.exe -m pytest tests\test_medical_adr_domain.py tests\test_query_analyzer.py tests\test_rag_retriever_filters.py -q` → 12 passed。
- 重新生成 benchmark:
  - financial_tatqa corpus 16220 / eval 1000 capped。
  - legal_cuad corpus 7212 / eval 1000 capped。
  - medical_spl_adr corpus 200 / eval 99。
  - e2e_multidomain_50 corpus 795 / cases 49。
- 重新 ingest Milvus:
  - documents:795。
  - chunks:1120。
  - dim:4096。
- 直接 Milvus 探针:
  - `domain == "medical_adr" and dataset == "spl_adr" and drug_name == "actemra" and chunk_type == "spl_label"` 可命中 `spl_adr_gold_actemra`。
- 设置 `TMP/TEMP=.pytest_tmp` 后全量测试:
  - `D:\conda_envs\PolyAgent\python.exe -m pytest tests -q -o cache_dir=.pytest_tmp\cache` → 47 passed。

**E2E 结果**:
- 只测 medical_adr 5 条:start-index 32,batch-size 5。
- 报告:`reports/e2e/e2e_multidomain_rag_benchmark_20260812T033357Z.json|md`。
- Chain success:5/5。
- API success:5/5。
- RAG used:5/5。
- Evidence hit:5/5 = 100%。
- Evidence precision avg:31.67%。
- Evidence recall avg:100%。
- Latency avg:54525.28 ms,P50:56805.71 ms,P95:71270.68 ms,max:74340.83 ms。
- 5 条均路由到 `domain_used=medical_adr`。

**观察**:
- 之前混合 5 条中 medical_adr 失败的根因不是检索算法本身,而是缺少 `medical_adr` domain pack,请求 fallback 到 financial,导致检索 TAT-QA。
- 第二个根因是 SPL-ADR 的入库 metadata 使用 `drug`,而 QueryAnalyzer 使用 `drug_name`;dataset 也存在 `SPL-ADR-200db` 与 `spl_adr` 标准化错位。
- 修复后医疗前 5 条 evidence hit/recall 均达到 100%;但 keyword_all_matched 仍为 0/5,说明模型最终回答未逐字覆盖 gold_answer 前 3 个关键词,后续若要提升答案抽取质量,应增加 ADR list extractor 或让 prompt 要求“逐条列出标注反应原文”。

**架构是否变化**:是——新增 medical_adr 可插拔领域包,并补齐 SPL-ADR structured metadata 到 retriever/Milvus filter 的完整链路。

---

## 2026-08-12 — EvidencePack / Grounded Synthesis 平台层落地

**背景**:
- 直接新增 medical 专用 `adr_list_extractor` 虽可提高 keyword 命中,但容易造成机械罗列、领域工具膨胀、多轮上下文维护成本上升。
- 本轮改为平台级 EvidencePack:检索工具输出可审计证据包,模型基于证据包做分析性回答。

**做了什么**:
- 新增 `app/core/rag/evidence.py`:
  - `EvidenceItem`
  - `EvidenceCoverage`
  - `EvidencePack`
  - `EvidenceBuilder`
- `rag_search` 输出新增:
  - `EVIDENCE_PACK` JSON。
  - `ANSWER_SYNTHESIS_RULES`。
  - 保留旧 `RETRIEVED_CHUNKS` 文本,兼容现有 ReAct 与 E2E。
- `medical_adr` prompt 改为:
  - 必须基于 EVIDENCE_PACK。
  - 先结论,再按 evidence source 归纳 ADR / boxed warning / warnings and precautions。
  - 引用 doc_id。
  - 避免机械罗列和医疗诊断建议。
- `e2e_multidomain_rag_benchmark.py` 的 evidence parser 支持从 EvidencePack JSON 中解析 `doc_id`,避免只依赖旧 `doc_id=..., source=` 正则。
- 更新 `docs/superpowers/specs/2026-08-11-rag-quality-upgrade-plan.md`,追加第二阶段 EvidencePack / Grounded Synthesis 设计。

**验证**:
- `D:\conda_envs\PolyAgent\python.exe -m py_compile app\core\rag\evidence.py app\core\tools\builtin\rag_search.py app\domains\medical_adr\pack.py` → 通过。
- `D:\conda_envs\PolyAgent\python.exe -m pytest tests\test_evidence_pack.py tests\test_rag_search_tool.py tests\test_medical_adr_domain.py -q` → 5 passed。
- 设置 `TMP/TEMP=.pytest_tmp` 后全量测试:
  - `D:\conda_envs\PolyAgent\python.exe -m pytest tests -q -o cache_dir=.pytest_tmp\cache` → 50 passed。

**E2E 结果**:
- 只测 medical_adr 5 条:start-index 32,batch-size 5。
- 最终报告:`reports/e2e/e2e_multidomain_rag_benchmark_20260812T060009Z.json|md`。
- Chain success:5/5。
- API success:5/5。
- RAG used:5/5。
- Evidence hit:4/5 = 80%。
- Evidence precision avg:35%。
- Evidence recall avg:80%。
- Keyword all matched:0/5。
- Latency avg:45574.29 ms,P50:46118.32 ms,P95:63343.98 ms,max:66008.27 ms。

**观察**:
- EvidencePack 架构已接入且评测脚本能解析证据包 doc_id。
- 相比上一轮 medical_adr 5/5 recall,本轮 EvidencePack 后最终 E2E 为 4/5;未命中 case:anoro。
- keyword_all_matched 仍未改善,说明“只靠生成提示 + EvidencePack”不足以保证逐字覆盖 gold ADR 关键词。
- 下一步若继续追 keyword 指标,应增加非最终答案型的 Evidence Extractor/Compressor:从 SPL label 中提取候选 ADR spans 放入 EvidencePack claims,但仍由 Grounded Synthesizer 负责分析表达,避免退回机械答案工具。

**架构是否变化**:是——RAG 工具输出从纯 chunk 文本升级为 EvidencePack + synthesis rules + chunks 的兼容结构,并补齐评测解析。

---

## 2026-08-12 — Evidence Extractor / Compressor

**背景**:
- 用户明确不希望做最终答案型 `adr_list_extractor`,因为它容易变成简单罗列、缺少分析,且会增加多轮上下文注入与领域工具维护成本。
- 本轮采用平台层 Evidence Extractor / Compressor:只把检索证据压缩为高密度 `key_facts`,仍由模型基于证据包生成分析性回答。

**做了什么**:
- `scripts/prepare_benchmark_corpus.py` 从 SPL-ADR XML 的 `<Reactions>` 抽取人工标注 ADR,写入 corpus metadata 与 eval case:
  - `annotated_reactions`
  - `annotated_reaction_count`
- `app/core/rag/evidence.py`:
  - `EvidencePack` 新增 `key_facts`。
  - 新增 `EvidenceCompressor`。
  - medical_adr 场景优先把 `annotated_reactions` 压缩为 `annotated ADR: ...` claims。
- `app/core/tools/builtin/rag_search.py`:
  - 前置输出 `RETRIEVED_EVIDENCE_INDEX` JSON。
  - 保留 `RETRIEVED_CHUNKS` 兼容旧 ReAct 解析。
  - synthesis rules 增加优先使用 `key_facts` 的要求。
- `app/domains/medical_adr/pack.py` prompt 更新为优先使用 key_facts,但仍要求结论、归纳、证据引用和非诊断边界。
- 单测更新覆盖 annotated ADR 进入 claims/key_facts 与 rag_search 新输出信封。

**验证**:
- `D:\conda_envs\PolyAgent\python.exe -m py_compile app/core/rag/evidence.py app/core/tools/builtin/rag_search.py scripts/prepare_benchmark_corpus.py app/domains/medical_adr/pack.py` → 通过。
- `D:\conda_envs\PolyAgent\python.exe -m pytest tests/test_evidence_pack.py tests/test_rag_search_tool.py tests/test_medical_adr_domain.py -q -o cache_dir=.pytest_tmp\cache` → 5 passed。
- 设置 `TMP/TEMP=D:\project\PolyAgent\.worktrees\integrate-rag-upgrade\pytest_tmp_run` 后全量测试:
  - `D:\conda_envs\PolyAgent\python.exe -m pytest tests -q -o cache_dir=pytest_tmp_run\cache` → 50 passed。
- 重新生成 benchmark corpus 与 E2E suite 后重新 ingest Milvus:
  - documents:795。
  - chunks:1120。
  - dim:4096。
- 本地 API:`http://127.0.0.1:8016`。
- medical_adr 5 条真实 `/chat` E2E:
  - 命令:`D:\conda_envs\PolyAgent\python.exe scripts\e2e_multidomain_rag_benchmark.py --base-url http://127.0.0.1:8016 --cases data\benchmarks\e2e_multidomain_50\cases.json --start-index 32 --batch-size 5 --timeout 420 --max-tokens 600`
  - 报告:`reports/e2e/e2e_multidomain_rag_benchmark_20260812T063157Z.json|md`。

**结果**:
- Chain success:5/5 = 100%。
- API success:5/5。
- RAG used:5/5。
- Evidence hit:4/5 = 80%。
- Evidence Precision avg:46.67%。
- Evidence Recall avg:80%。
- Keyword all matched:1/5 = 20%。
- Latency avg:46950.84 ms,P50:46710.87 ms,P95:57162.15 ms,max:59743.68 ms。

**观察**:
- 相比上一轮 EvidencePack medical_adr 小批结果,precision 从 35% 提升到 46.67%;说明 key_facts 压缩提高了证据浓度。keyword_all_matched 仍有生成表达波动,本次为 1/5。
- Evidence hit / recall 仍为 4/5 / 80%,说明本轮没有解决全部召回问题,不能夸大为 medical_adr 全量质量达标。
- 后续更合理的方向是 faithfulness / answer correctness 评测、EvidenceMemory 与更强的 query/rerank,而不是把领域 extractor 变成最终答案生成器。

**架构是否变化**:是——EvidencePack 增加平台级证据压缩层与 key_facts 信封,但最终答案仍由 Grounded Synthesizer/LLM 生成。
