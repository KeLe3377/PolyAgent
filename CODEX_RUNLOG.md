# CODEX_RUNLOG.md — codex/rag-retrieval-rerank-eval

## 2026-08-11 — RAG retrieval/rerank/eval infra

**Scope**
- Worktree:`D:\project\PolyAgent\.worktrees\codex-rag-infra`
- Branch:`codex/rag-retrieval-rerank-eval`
- Task:Codex side of `docs/superpowers/specs/2026-08-11-rag-quality-upgrade-plan.md`.

**Implemented**
- Added `app/core/rag/types.py` with `RetrievalRequest`.
- Added `app/core/rag/reranker.py` with `Reranker`, `NoopReranker`, and lazy `CrossEncoderReranker`.
- Extended `app/core/rag/retriever.py`:
  - Backward-compatible `retrieve(query, top_k, mode)` remains supported.
  - Supports `domain`, `dataset`, `filters`, `top_n`, `rerank`.
  - Parses Milvus JSON metadata.
  - Applies metadata exact/list filters for vector, keyword, and hybrid retrieval.
  - Pushes available scalar filters (`id`, `domain`, `source`) down to Milvus `expr`.
  - Runs first-stage top-N retrieval followed by optional rerank top-K.
- Extended `app/infrastructure/vectordb/milvus_client.py` to pass `expr` to `Collection.search`.
- Extended `app/core/tools/builtin/rag_search.py`:
  - Accepts `domain_filter`, `dataset_filter`, `default_filters`.
  - Emits `doc_id/source/dataset/chunk_type` in observations for evidence tracing.
- Added benchmark scripts:
  - `scripts/ingest_benchmark_corpus.py`
  - `scripts/e2e_multidomain_rag_benchmark.py`
  - `scripts/eval_retrieval_benchmark.py`
- Added `.env.example` empty `RERANK_*` knobs.
- Added focused tests:
  - `tests/test_rag_retriever_filters.py`
  - `tests/test_reranker.py`
  - `tests/test_e2e_batch_aggregation.py`
  - updated `tests/test_rag_search_tool.py`

**Validation**
- `D:\conda_envs\PolyAgent\python.exe -m py_compile app\core\rag\types.py app\core\rag\reranker.py app\core\rag\retriever.py app\core\tools\builtin\rag_search.py app\infrastructure\vectordb\milvus_client.py scripts\ingest_benchmark_corpus.py scripts\e2e_multidomain_rag_benchmark.py scripts\eval_retrieval_benchmark.py` -> passed.
- `D:\conda_envs\PolyAgent\python.exe -m pytest tests\test_rag_search_tool.py tests\test_rag_retriever_filters.py tests\test_reranker.py tests\test_e2e_batch_aggregation.py -q` -> 5 passed.
- `D:\conda_envs\PolyAgent\python.exe -m pytest tests -q` -> 13 passed.

**Notes**
- The first pytest run failed because Windows denied access to the default temp root under `C:\Users\cxsy5\AppData\Local\Temp\pytest-of-cxsy5`; rerun with `TMP/TEMP` pointed to `.pytest_tmp` passed.
- Pytest still warned that it could not create `.pytest_cache`; this is local cache only and did not affect test results.
- This branch does not modify `app/domains/**`, structured TAT-QA/CUAD ETL, or domain-specific tools; those remain Claude-side scope.
- `RERANK_*` are documented in `.env.example` only. Runtime settings are not wired yet, so callers must inject a reranker object when enabling rerank in application assembly.
