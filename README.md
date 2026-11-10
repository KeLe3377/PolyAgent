# PolyAgent

PolyAgent 是一个企业级多领域 Agent 平台:基于 FastAPI 暴露 HTTP/SSE 接口,内置多模式 Agent 编排(ReAct / Plan-and-Execute / 多视角审议)、领域 Skill 注册与路由、向量+关键词混合检索与 reranker、长期/短期记忆、工具注册表、文档 ETL、Milvus/Redis/Postgres/LLM 基础设施。

平台特性:

- **多模式 Agent 编排**:`react` 单循环、`plan_execute` 任务分解与重规划、`deliberation` 多视角审议(共享检索 → N agent 并行评议 → 综合)。
- **多领域 Skill 注册**:`skills/<domain>/SKILL.md` 是领域的事实来源,声明提示词、可用工具、语料、评测与审议配置;新增领域只需添加一个目录,无需改动运行时。
- **混合检索 + reranker**:Milvus 向量召回 + BM25 关键词召回 + RRF 融合 + 二阶段 reranker;带 query 改写、过滤器注入、evidence 打包。
- **工具注册表**:内置 `rag_search` / `calculator` / `table_calculator` / `database` / `contract_clause_locator` / `search`,支持 Skill 维度声明工具白名单。
- **双层记忆**:短期会话记忆(Redis-backed)+ 长期用户级记忆。
- **意图识别**:`/chat` 先经过意图识别器,自动选择领域 Skill 与运行模式;用户也可在请求里显式覆盖。
- **文档 ETL**:上传任意文档 → 解析 → 分块 → 灌库,corpus 灌库支持 dry-run 与确认两步流程。
- **可观测与评测**:编排追踪、对话 trace、benchmark 套件(e2e 端到端、检索召回、多领域综合)与报告输出。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 进程与 Milvus/Redis/Postgres 健康检查 |
| GET | `/api/v1/health/ready` | 就绪检查 |
| GET | `/api/v1/domains` | 列出已注册领域 Skill |
| GET | `/api/v1/domains/{name}` | 查看单个领域 Skill 摘要 |
| POST | `/api/v1/chat` | 非流式 Agent 对话,支持 `domain`/`mode`/`conversation_id` |
| POST | `/api/v1/chat/stream` | SSE 流式直连 LLM |
| POST | `/api/v1/documents` | 文档上传 / ETL 入口 |

`/chat` 支持三种模式:

- `react`:Thought → Action → Observation 单循环,适合工具调用密集的问答。
- `plan_execute`:任务分解 → 顺序执行 → 重规划,适合多步推理。
- `deliberation`:共享检索 → 多 agent 并行评议(每视角独立 persona)→ 综合,适合需要多立场权衡的分析问题。

## 领域 Skill

平台以 `skills/<domain>/SKILL.md` 作为领域事实来源;`app/domains/registry.py` 在启动时扫描注册。当前内置:

| 领域 | 触发场景 |
|---|---|
| `financial-analysis` | 财报、KPI、市场、估值、风险、表格推理、投资分析 |
| `contract-review` | 合同、条款、义务、终止、转让、适用法、合规审查 |
| `kb-qa` | 通用知识库、内部制度、FAQ、支持问答 |
| `medical-adr` | 药品标签、不良反应、警告、安全段、SPL、用药风险、药物警戒 |

新增领域只需在 `skills/<domain>/SKILL.md` 写明触发场景与提示词,运行时无需改动;重启 `start.cmd` 自动注册。

## 配置

复制 `.env.example` 为 `.env`,填写 OpenAI-compatible provider:

```env
LLM_API_KEY=replace-with-your-llm-key
LLM_BASE_URL=https://provider.example/v1
LLM_MODEL=replace-with-your-chat-model

EMBED_API_KEY=replace-with-your-embedding-key
EMBED_BASE_URL=https://provider.example/v1
EMBED_MODEL=replace-with-your-embedding-model

DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/agent_db
REDIS_URL=redis://localhost:6379/0
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION_NAME=agent_knowledge
```

`LLM_*` 与 `EMBED_*` 接受任意 OpenAI-compatible provider(自托管网关、Azure OpenAI、本地 vLLM、硅基流动、DeepSeek 等)。旧 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` 仍可作为兼容输入,内部统一映射。

## Python 环境

FastAPI app 与 benchmark / ingest / eval 脚本都跑在你的本地 Python 环境里。推荐用 conda 创建一个独立 env,然后通过 `requirements.txt` 安装依赖:

```bash
# 1. 创建并激活环境(名字可任取,这里用 polyagent 作示例)
conda create -n polyagent python=3.12 -y
conda activate polyagent

# 2. 装依赖
pip install -r requirements.txt
```

> `requirements.txt` 是 FastAPI / langchain / langgraph / pymilvus / redis / sqlalchemy / sentence-transformers / tiktoken / unstructured 等运行时所需的全部 pip 依赖。基础设施(Postgres / Redis / Milvus / etcd / minio)不在这份清单里——它们由 Docker Compose 提供。

如果你用 venv / poetry / uv 也行,只要装齐 `requirements.txt` 里的依赖即可。

## 启动

平台以两个角色运行:基础设施(Postgres / Redis / Milvus 及其 etcd/minio 依赖)由 Docker Compose 管理;FastAPI app 可在 Docker 容器内运行,也可在你本机的 Python 环境运行。

### 一键启动(Windows / PowerShell)

```powershell
.\start.cmd            # 起基础设施 + app,等待 health 全绿
.\start.cmd -Ingest    # 起服后立即灌入领域语料到 Milvus
```

`start.cmd` 在运行 app 之前会按以下顺序解析 Python:

1. 环境变量 `POLYAGENT_PYTHON`(可选,显式指定某个 `python.exe` / `python`)
2. PATH 里的 `python`

推荐用法:先 `conda activate polyagent` 让 Python 进入 PATH,然后直接 `.\start.cmd`。如果你把环境装在非默认位置,也可以:

```powershell
$env:POLYAGENT_PYTHON = "D:\path\to\your-venv\python.exe"
.\start.cmd
```

### 纯 Docker 部署

```bash
docker compose up -d --build
```

Compose 包含 app、Postgres、Redis、Milvus standalone 及其 etcd/minio 依赖。app 会等待 Postgres healthy 与 Milvus healthy 后启动。

## 交互对话

```powershell
.\chat.cmd                              # 默认 domain=financial, mode=deliberation
.\chat.cmd -Domain kb_qa -Mode react    # 切领域与模式
```

会话内指令:`/domain NAME`、`/mode react|plan_execute|deliberation`、`/reset`、`/exit`。

## 端到端评测

```powershell
.\e2e-benchmark.cmd --plan          # 预览本轮会跑哪些用例
.\e2e-benchmark.cmd --repeat 1     # 实跑,生成报告
```

报告输出到 `reports/e2e/`,包含成功率、关键词命中率、模式命中率、P50/P95/Max 延迟与可复制的真实运行指标。

按模式/场景拆分的脚本(可选):

```bash
python scripts/e2e_deliberation_benchmark.py --plan
python scripts/e2e_deliberation_benchmark.py --timeout 420 --max-tokens 700
python -m pytest tests/test_deliberation_agent.py -q
```

`e2e_deliberation_benchmark.py` 强制走 `mode=deliberation`,校验 D1 共享检索 / D2 bull-bear 立场评议 / D3 综合是否出现在返回的 `steps` 中。

多领域 RAG + 综合端到端(从 TAT-QA / CUAD / SPL-ADR-200db 抽取样本,灌入 Milvus 后通过 `/chat` 测试 `financial` / `contract-review` / `medical-adr` 的 RAG 与 `financial` 的 `deliberation` 旗舰路径):

```bash
python scripts/prepare_multidomain_e2e_suite.py --per-domain 2 --confirmed
python scripts/ingest_benchmark_corpus.py --corpus data/benchmarks/e2e_multidomain/corpus.jsonl --collection agent_knowledge --chunk-size 768 --chunk-overlap 96 --confirmed
python scripts/e2e_multidomain_rag_benchmark.py --timeout 420 --max-tokens 600
```

报告统计 chain success、RAG used、evidence hit rate、keyword hit、per-domain success、P50/P95/Max 延迟。

## Benchmark 数据准备与检索评测

公开 benchmark 转换(默认 dry-run,加 `--confirmed` 才会落盘到 `data/benchmarks/`):

```bash
python scripts/prepare_benchmark_corpus.py
python scripts/prepare_benchmark_corpus.py --max-eval-cases -1 --confirmed
```

输出数据集:

- `financial_tatqa`:TAT-QA 金融表格+文本 QA。
- `legal_cuad`:CUAD 合同条款审查。
- `medical_spl_adr`:SPL-ADR-200db 药品不良反应抽取。

每个数据集包含 `corpus.jsonl`、`eval_cases.jsonl`、`manifest.json`,供后续计算 evidence recall、answer accuracy / F1、grounded rate、hallucination rate。

灌库与检索评测:

```bash
# dry-run:只预览写入量,不调用 embedding
python scripts/ingest_benchmark_corpus.py --corpus data/benchmarks/financial_tatqa/corpus.jsonl --collection benchmark_financial_tatqa

# confirmed:调用 EMBED_* 并写入 Milvus
python scripts/ingest_benchmark_corpus.py --corpus data/benchmarks/financial_tatqa/corpus.jsonl --collection benchmark_financial_tatqa --confirmed

# keyword 基线:不调用模型,计算 Top-k evidence recall
python scripts/eval_retrieval_benchmark.py \
  --corpus data/benchmarks/financial_tatqa/corpus.jsonl \
  --eval-cases data/benchmarks/financial_tatqa/eval_cases.jsonl \
  --dataset financial_tatqa --mode keyword --top-k 5 --max-cases 3331
```

报告输出到 `reports/retrieval/`。`keyword` 模式为零模型成本基线;`vector` / `hybrid` 需要先灌库并保证 embedding provider 可用。

## 领域语料灌库

`skills/<domain>/SKILL.md` 里声明的语料文件会通过以下命令灌入 Milvus。默认 dry-run,加 `--confirmed` 才会写入:

```bash
python scripts/ingest_corpus.py                # 默认扫描仓库根目录的 skills/
python scripts/ingest_corpus.py --confirmed    # 实际灌入
```

## 示例请求

非流式对话(走完整 Agent 编排):

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"分析 NVIDIA 的增长机会和风险"}],"domain":"financial","mode":"deliberation"}'
```

列举已注册领域:

```bash
curl http://127.0.0.1:8000/api/v1/domains
```

## 目录结构

```text
app/
  api/routes/          chat / domains / document / health
  core/agent/          orchestrator / react_agent / planner / deliberation / reflection
  core/intent/         意图识别器
  core/rag/            MultiRetriever(Milvus + BM25 + RRF + reranker)/ query_analyzer / generator
  core/tools/          ToolRegistry + builtin(rag_search / calculator / table_calculator / database / contract_clause_locator / search)
  core/memory/         短期会话记忆 + 长期用户级记忆
  domains/             领域 Skill 运行时适配契约与 registry
  infrastructure/      llm / vectordb(Milvus)/ cache(Redis)/ database(Postgres)/ trace
  etl/                 parser / chunker / pipeline
skills/
  */SKILL.md           领域事实来源:触发场景、提示词、工具、语料、评测、审议配置
scripts/
  start.ps1            起 docker infra + python app,等待 health 全绿
  chat.ps1             交互对话客户端
  ingest_corpus.py     领域语料灌库
  prepare_benchmark_corpus.py   公开 benchmark 转换
  ingest_benchmark_corpus.py    benchmark 语料灌库
  eval_retrieval_benchmark.py   检索召回评测
  e2e_*_benchmark.py             端到端评测脚本
```