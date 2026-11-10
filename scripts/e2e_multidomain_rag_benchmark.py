# -*- coding: utf-8 -*-
"""Multi-domain RAG E2E benchmark runner and report aggregator."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

DEFAULT_CASES = Path("data/benchmarks/e2e_multidomain/cases.json")
DEFAULT_OUT_DIR = Path("reports/e2e")


def _now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lower = int(k)
    upper = min(lower + 1, len(ordered) - 1)
    weight = k - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def load_cases(path: Path, *, start_index: int = 0, batch_size: int | None = None, max_cases: int | None = None) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if start_index < 0:
        raise ValueError("--start-index must be >= 0")
    if batch_size is not None and batch_size < 1:
        raise ValueError("--batch-size must be >= 1")
    cases = cases[start_index:]
    if batch_size is not None:
        cases = cases[:batch_size]
    if max_cases is not None:
        cases = cases[: max(0, max_cases)]
    return cases


def _keyword_stats(answer: str, expected_keywords: list[str]) -> dict[str, Any]:
    folded = answer.casefold()
    matched = [kw for kw in expected_keywords if kw.casefold() in folded]
    missing = [kw for kw in expected_keywords if kw.casefold() not in folded]
    return {
        "expected": len(expected_keywords),
        "matched": len(matched),
        "missing": missing,
        "hit_rate": len(matched) / len(expected_keywords) if expected_keywords else None,
        "all_matched": not missing if expected_keywords else None,
    }


def _step_stats(steps: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    raw = json.dumps(steps, ensure_ascii=False)
    if mode == "deliberation":
        d1 = any(step.get("phase") == "d1" for step in steps)
        d2 = any("roles" in step and ("ok" in step or "failed" in step) for step in steps)
        d3 = any("answer_len" in step for step in steps)
        roles: list[str] = []
        for step in steps:
            if "roles" in step:
                roles = [str(x) for x in step.get("roles", [])]
        return {"rag_used": d1, "deliberation_d1": d1, "deliberation_d2": d2, "deliberation_d3": d3, "roles": roles}
    return {
        "rag_used": "rag_search" in raw or "Observation:" in raw or "observation" in raw,
        "tool_action_count": sum(1 for step in steps if step.get("action")),
        "final_step": any(step.get("final") for step in steps),
    }


def _evidence_stats(steps: list[dict[str, Any]], gold_doc_ids: list[str]) -> dict[str, Any]:
    serialized = json.dumps(steps, ensure_ascii=False)
    retrieved_doc_ids: list[str] = []
    for doc_id in re.findall(r"doc_id=(.*?), source=", serialized):
        if doc_id not in retrieved_doc_ids:
            retrieved_doc_ids.append(doc_id)

    def _iter_strings(value: Any):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from _iter_strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from _iter_strings(item)

    for text in _iter_strings(steps):
        for doc_id in re.findall(r'"doc_id"\s*:\s*"([^"]+)"', text):
            if doc_id not in retrieved_doc_ids:
                retrieved_doc_ids.append(doc_id)
    if not gold_doc_ids:
        return {
            "expected": 0,
            "hit": None,
            "precision": None,
            "recall": None,
            "retrieved_doc_ids": retrieved_doc_ids,
            "matched_doc_ids": [],
            "missing_doc_ids": [],
        }
    matched = [doc_id for doc_id in gold_doc_ids if doc_id in serialized]
    missing = [doc_id for doc_id in gold_doc_ids if doc_id not in serialized]
    matched_retrieved = [doc_id for doc_id in retrieved_doc_ids if doc_id in set(gold_doc_ids)]
    return {
        "expected": len(gold_doc_ids),
        "hit": bool(matched),
        "precision": len(matched_retrieved) / len(retrieved_doc_ids) if retrieved_doc_ids else 0.0,
        "recall": len(matched) / len(gold_doc_ids),
        "retrieved_doc_ids": retrieved_doc_ids,
        "matched_doc_ids": matched,
        "missing_doc_ids": missing,
    }


def summarize_results(results: list[dict[str, Any]], *, health_ready: bool) -> dict[str, Any]:
    total = len(results)
    evidence_cases = [r for r in results if isinstance(r.get("evidence"), dict) and r["evidence"]["hit"] is not None]
    evidence_precisions = [float(r["evidence"]["precision"]) for r in evidence_cases if r["evidence"]["precision"] is not None]
    evidence_recalls = [float(r["evidence"]["recall"]) for r in evidence_cases if r["evidence"]["recall"] is not None]
    latencies = [float(r["latency_ms"]) for r in results if "latency_ms" in r]
    by_domain: dict[str, dict[str, Any]] = {}
    for r in results:
        domain = str(r.get("domain_requested"))
        item = by_domain.setdefault(domain, {"total": 0, "ok": 0, "evidence_cases": 0, "evidence_hit": 0, "precision": [], "recall": []})
        item["total"] += 1
        item["ok"] += 1 if r.get("ok") else 0
        e = r.get("evidence") or {}
        if e.get("hit") is not None:
            item["evidence_cases"] += 1
            item["evidence_hit"] += 1 if e.get("hit") else 0
            if e.get("precision") is not None:
                item["precision"].append(float(e["precision"]))
            if e.get("recall") is not None:
                item["recall"].append(float(e["recall"]))
    return {
        "health_ready": health_ready,
        "total_cases": total,
        "chain_success_count": sum(1 for r in results if r.get("ok")),
        "chain_success_rate": sum(1 for r in results if r.get("ok")) / total if total else 0.0,
        "api_success_count": sum(1 for r in results if r.get("api_success")),
        "rag_used_count": sum(1 for r in results if (r.get("step_stats") or {}).get("rag_used")),
        "evidence_case_count": len(evidence_cases),
        "evidence_hit_count": sum(1 for r in evidence_cases if r["evidence"]["hit"]),
        "evidence_hit_rate": (sum(1 for r in evidence_cases if r["evidence"]["hit"]) / len(evidence_cases)) if evidence_cases else None,
        "evidence_precision_avg": statistics.mean(evidence_precisions) if evidence_precisions else None,
        "evidence_recall_avg": statistics.mean(evidence_recalls) if evidence_recalls else None,
        "keyword_all_matched_count": sum(1 for r in results if (r.get("keyword") or {}).get("all_matched")),
        "keyword_all_matched_rate": (sum(1 for r in results if (r.get("keyword") or {}).get("all_matched")) / total) if total else None,
        "by_domain": {
            domain: {
                "total": item["total"],
                "ok": item["ok"],
                "success_rate": item["ok"] / item["total"] if item["total"] else 0.0,
                "evidence_cases": item["evidence_cases"],
                "evidence_hit": item["evidence_hit"],
                "evidence_hit_rate": item["evidence_hit"] / item["evidence_cases"] if item["evidence_cases"] else None,
                "evidence_precision_avg": statistics.mean(item["precision"]) if item["precision"] else None,
                "evidence_recall_avg": statistics.mean(item["recall"]) if item["recall"] else None,
            }
            for domain, item in sorted(by_domain.items())
        },
        "latency_ms": {
            "count": len(latencies),
            "avg": round(statistics.mean(latencies), 2) if latencies else None,
            "p50": round(_percentile(latencies, 0.50), 2) if latencies else None,
            "p95": round(_percentile(latencies, 0.95), 2) if latencies else None,
            "max": round(max(latencies), 2) if latencies else None,
        },
    }


def aggregate_report_files(paths: list[Path]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        results.extend(data.get("results") or [])
    return {
        "status": "ok",
        "report_count": len(paths),
        "summary": summarize_results(results, health_ready=True),
        "results": results,
    }


def _check_health(client: httpx.Client, base_url: str) -> dict[str, Any]:
    response = client.get(f"{base_url}/api/v1/health")
    response.raise_for_status()
    payload = response.json()
    deps = payload.get("dependencies") or {}
    return {"ready": payload.get("status") == "ok" and all(deps.get(k) is True for k in ("milvus", "redis", "postgres")), "payload": payload}


def _run_case(client: httpx.Client, *, base_url: str, case: dict[str, Any], max_tokens: int | None) -> dict[str, Any]:
    mode = str(case.get("mode") or "react")
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": case["query"]}],
        "domain": case["domain"],
        "mode": mode,
        "conversation_id": f"multi-{case.get('case_id')}-{uuid.uuid4().hex[:8]}",
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    started = time.perf_counter()
    response = client.post(f"{base_url}/api/v1/chat", json=payload)
    latency_ms = (time.perf_counter() - started) * 1000
    result: dict[str, Any] = {
        "case_id": case.get("case_id"),
        "dataset": case.get("dataset"),
        "category": case.get("category"),
        "domain_requested": case.get("domain"),
        "mode_requested": mode,
        "query": case.get("query"),
        "latency_ms": round(latency_ms, 2),
        "http_status": response.status_code,
        "ok": False,
    }
    try:
        body = response.json()
    except Exception:
        body = {"raw_text": response.text[:500]}
    if response.status_code >= 400:
        result["error"] = body
        return result
    answer = str(body.get("content") or "")
    steps = body.get("steps") if isinstance(body.get("steps"), list) else []
    step_stats = _step_stats(steps, mode)
    evidence = _evidence_stats(steps, [str(x) for x in case.get("gold_evidence_doc_ids", [])])
    keyword = _keyword_stats(answer, [str(x) for x in case.get("expected_keywords", [])])
    chain_ok = bool(body.get("success")) and body.get("mode_used") == mode
    chain_ok = chain_ok and (
        step_stats.get("deliberation_d1") and step_stats.get("deliberation_d2") and step_stats.get("deliberation_d3")
        if mode == "deliberation"
        else step_stats.get("rag_used") and step_stats.get("final_step")
    )
    result.update(
        {
            "ok": bool(chain_ok),
            "api_success": bool(body.get("success")),
            "mode_used": body.get("mode_used"),
            "domain_used": body.get("domain"),
            "trace_id": body.get("trace_id"),
            "answer_chars": len(answer),
            "answer_preview": answer[:260],
            "keyword": keyword,
            "evidence": evidence,
            "step_stats": step_stats,
        }
    )
    return result


def _fmt_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def _markdown_report(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# PolyAgent Multi-Domain RAG E2E Benchmark",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Cases file: `{report['cases_file']}`",
        f"- Start / batch: **{report.get('start_index')} / {report.get('batch_size')}**",
        f"- Total cases: **{s['total_cases']}**",
        f"- Chain success rate: **{s['chain_success_rate']:.2%}**",
        f"- Evidence hit rate: **{_fmt_rate(s['evidence_hit_rate'])}**",
        f"- Evidence Precision / Recall: **{_fmt_rate(s['evidence_precision_avg'])} / {_fmt_rate(s['evidence_recall_avg'])}**",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or aggregate PolyAgent multi-domain E2E benchmark")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=420.0)
    parser.add_argument("--max-tokens", type=int, default=600)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--aggregate-reports", type=Path, nargs="*", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.aggregate_reports is not None:
        report = aggregate_report_files(args.aggregate_reports)
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        return 0
    cases = load_cases(args.cases, start_index=args.start_index, batch_size=args.batch_size, max_cases=args.max_cases)
    if args.plan:
        print(json.dumps({"status": "plan", "cases_file": str(args.cases), "start_index": args.start_index, "batch_size": args.batch_size, "case_count": len(cases), "cases": cases}, ensure_ascii=False, indent=2))
        return 0
    run_id = _now_id()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    base_url = args.base_url.rstrip("/")
    with httpx.Client(timeout=args.timeout) as client:
        health = _check_health(client, base_url)
        if not health["ready"]:
            raise SystemExit(f"Health is not ready: {json.dumps(health['payload'], ensure_ascii=False)}")
        results = [_run_case(client, base_url=base_url, case=case, max_tokens=args.max_tokens) for case in cases]
    report = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "cases_file": str(args.cases),
        "start_index": args.start_index,
        "batch_size": args.batch_size,
        "summary": summarize_results(results, health_ready=health["ready"]),
        "health": health["payload"],
        "results": results,
    }
    json_path = args.out_dir / f"e2e_multidomain_rag_benchmark_{run_id}.json"
    md_path = args.out_dir / f"e2e_multidomain_rag_benchmark_{run_id}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    print(json.dumps({"status": "ok", "json": str(json_path), "markdown": str(md_path), "summary": report["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
