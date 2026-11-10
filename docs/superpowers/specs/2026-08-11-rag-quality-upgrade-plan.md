# PolyAgent RAG 质量升级计划

> 日期:2026-08-11  
> 目的:根据近 50 条多领域 Docker `/chat` 分批 E2E 的真实结果,修复 financial TAT-QA 与 legal CUAD 检索偏差,把 RAG 从通用 chunk 相似度检索升级为 metadata-aware retrieval + structured indexing + rerank + deterministic tools。

## 基线

- Total cases:49。
- Chain success:48/49 = 97.96%。
- Evidence recall:28/48 = 58.33%。
- Financial evidence recall:37.50%。
- Legal evidence recall:56.25%。
- Medical ADR evidence recall:81.25%。

## 原因

- TAT-QA 是表格 + 文本 + 数值推理任务,普通文本 chunk 丢失 row/column/year/scale/value。
- CUAD 长合同问题高度同质化,仅 domain filter 不足,需要 contract_name/doc_id/clause_type 强过滤。
- 当前 MultiRetriever 是 first-stage retrieval,缺少 top-N 召回后的 rerank。
- 数值题需要 deterministic calculator,不能让 LLM 自己心算。

## 目标链路

```text
query
-> QueryAnalyzer
-> Metadata filters
-> MultiRetriever first-stage top50
-> Reranker top5
-> domain tools(table_calculator / contract_clause_locator)
-> grounded answer
-> evidence evaluation
```

## Worktree 分工

### Claude: `claude/rag-domain-structured-tools`

负责领域侧结构化与工具:

- `app/core/rag/query_analyzer.py`
- `app/core/tools/builtin/table_calculator.py`
- `app/core/tools/builtin/contract_clause_locator.py`
- `scripts/prepare_benchmark_corpus.py`
- `scripts/prepare_multidomain_e2e_suite.py`
- `app/domains/**` 工具接线
- 对应测试

### Codex: `codex/rag-retrieval-rerank-eval`

负责检索基础设施和评测工具:

- `app/core/rag/types.py`
- `app/core/rag/reranker.py`
- `app/core/rag/retriever.py`
- `app/core/tools/builtin/rag_search.py`
- `app/infrastructure/vectordb/*`
- `scripts/ingest_benchmark_corpus.py`
- `scripts/e2e_multidomain_rag_benchmark.py`
- `scripts/eval_retrieval_benchmark.py`
- 对应测试

## 合并顺序

1. 合并 Codex 检索基础设施。
2. 合并 Claude 领域结构化 ETL 与工具。
3. 重新生成 benchmark corpus。
4. 重新 ingest。
5. 按 5 条一批重跑 49 条 E2E。
6. 对比基线。

## 第一轮目标

- Overall evidence recall:58.33% -> >=70%。
- Financial evidence recall:37.50% -> >=55%。
- Legal evidence recall:56.25% -> >=70%。
- Medical ADR evidence recall:保持 >=80%。
- Chain success:保持 >=95%。

## 第二阶段:Evidence Pack / Grounded Synthesis

> 日期:2026-08-12  
> 背景:medical_adr 修复后,RAG 已能命中 SPL-ADR gold evidence,但 keyword_all_matched 仍偏低。直接新增领域专用答案抽取工具虽然能提升逐字命中,但会带来机械罗列、领域工具膨胀、多轮上下文维护成本高等问题。因此第二阶段采用平台级 Evidence Pack,把“证据整理/校验”和“答案生成”分层。

### 新目标链路

```text
query
-> QueryAnalyzer
-> Metadata filters
-> MultiRetriever
-> EvidenceBuilder
-> EvidencePack(coverage + evidence_items + answer_directives)
-> Grounded Answer Synthesis
-> evidence / keyword / latency evaluation
```

### 设计原则

- 不让领域专用 extractor 直接生成最终答案;工具只负责提供可审计证据包。
- EvidencePack 保留引用来源、doc_id、chunk_type、实体匹配、缺失过滤条件与简短 claims。
- LLM 负责基于 EvidencePack 做归纳、解释和风险提示,避免机械罗列。
- 多轮对话后续可围绕 `evidence_pack_id / source_doc_ids / entity` 做 EvidenceMemory,而不是把上下文状态散落到每个领域工具。

### 当前落地

- 新增 `app/core/rag/evidence.py`:
  - `EvidenceItem`
  - `EvidenceCoverage`
  - `EvidencePack`
  - `EvidenceBuilder`
- `rag_search` 输出新增:
  - `EVIDENCE_PACK` JSON。
  - `ANSWER_SYNTHESIS_RULES`。
  - 原始 `RETRIEVED_CHUNKS` 保持兼容。
- `medical_adr` prompt 改为基于 EvidencePack 进行分析性回答:
  - 先结论。
  - 再按证据来源归纳 ADR / boxed warning / warnings and precautions。
  - 引用 doc_id。
  - 明确非医疗诊断建议。

### 后续可选

- 将 EvidencePack 从工具纯文本升级为 `steps[].artifact` 结构化产物。
- 增加 EvidenceMemory,支持多轮引用上一轮证据包。
- 引入 faithfulness / answer correctness 评测,避免只看 keyword_all_matched。

## 第三阶段:Evidence Extractor / Compressor

> 日期:2026-08-12  
> 背景:EvidencePack 能把证据和生成分层,但 medical_adr 的 keyword 命中仍偏低。直接增加 ADR 最终答案工具会退回“机械列表生成”,并放大多轮上下文维护成本。本阶段只做证据压缩:把检索 chunk 中已经结构化标注的高价值事实提炼进 EvidencePack,仍由模型负责分析性回答。

### 目标链路

```text
retrieval results
-> EvidenceCompressor
-> EvidencePack.key_facts + evidence_items.claims
-> Grounded Answer Synthesis
```

### 当前落地

- `prepare_benchmark_corpus.py` 为 SPL-ADR corpus / eval case 写入:
  - `annotated_reactions`
  - `annotated_reaction_count`
- `EvidencePack` 新增 `key_facts` 字段。
- `EvidenceCompressor` 对 medical_adr 优先使用 SPL-ADR 标注反应生成压缩事实:
  - `annotated ADR: <reaction>`
- `rag_search` 将 `RETRIEVED_EVIDENCE_INDEX` 前置输出,再输出兼容旧链路的 `RETRIEVED_CHUNKS`。
- `medical_adr` prompt 调整为优先使用 `key_facts`,但仍要求归纳、解释和引用来源,避免平铺列表。

### 验证结果

- Milvus 重新 ingest:`795 documents / 1120 chunks / dim=4096`。
- 单元测试:`50 passed`。
- medical_adr 5 条真实 `/chat` E2E:
  - Chain success:5/5。
  - RAG used:5/5。
  - Evidence hit:4/5 = 80%。
  - Evidence Precision / Recall:46.67% / 80%。
  - Keyword all matched:1/5 = 20%。

### 结论

- 相比上一轮 EvidencePack medical_adr 小批结果,precision 从 35% 提升到 46.67%,说明证据压缩能降低噪声。
- Evidence hit / recall 仍为 4/5 / 80%,说明本阶段主要改善证据浓度,没有解决全部召回问题。
- 后续如果继续优化,优先考虑 faithfulness / answer correctness 评测与 EvidenceMemory,不建议把领域 extractor 直接升级为最终答案生成器。
