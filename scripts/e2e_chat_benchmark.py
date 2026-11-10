# -*- coding: utf-8 -*-
"""End-to-end natural-language chat benchmark for PolyAgent.

The script calls the public FastAPI chat endpoint with natural-language cases,
measures latency/success/keyword coverage, and writes JSON + Markdown reports.
It never reads or prints .env values.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


DEFAULT_CASES = Path("app/domains/financial/eval_cases.json")
DEFAULT_OUT_DIR = Path("reports/e2e")


@dataclass(frozen=True)
class ChatCase:
    case_id: str
    query: str
    expected_keywords: list[str]
    expected_mode: str | None
    domain: str | None
    category: str


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


def _load_cases(path: Path, default_domain: str) -> list[ChatCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases: list[ChatCase] = []
    for idx, item in enumerate(raw, start=1):
        metadata = item.get("metadata") or {}
        query = str(item.get("query", "")).strip()
        if not query:
            continue
        cases.append(
            ChatCase(
                case_id=str(item.get("id") or f"case_{idx:03d}"),
                query=query,
                expected_keywords=[str(k) for k in item.get("expected_keywords", [])],
                expected_mode=metadata.get("expected_mode"),
                domain=str(item.get("domain") or metadata.get("domain") or default_domain),
                category=str(metadata.get("category") or "general"),
            )
        )
    return cases


def _keyword_stats(answer: str, expected_keywords: list[str]) -> dict[str, Any]:
    if not expected_keywords:
        return {
            "expected": 0,
            "matched": 0,
            "missing": [],
            "hit_rate": None,
            "all_matched": None,
        }
    matched: list[str] = []
    missing: list[str] = []
    answer_folded = answer.casefold()
    for keyword in expected_keywords:
        if keyword.casefold() in answer_folded:
            matched.append(keyword)
        else:
            missing.append(keyword)
    return {
        "expected": len(expected_keywords),
        "matched": len(matched),
        "missing": missing,
        "hit_rate": len(matched) / len(expected_keywords),
        "all_matched": len(missing) == 0,
    }


def _check_health(client: httpx.Client, base_url: str) -> dict[str, Any]:
    response = client.get(f"{base_url}/api/v1/health")
    response.raise_for_status()
    payload = response.json()
    deps = payload.get("dependencies") or {}
    ready = (
        payload.get("status") == "ok"
        and deps.get("milvus") is True
        and deps.get("redis") is True
        and deps.get("postgres") is True
    )
    return {"ready": ready, "payload": payload}


def _post_chat(
    client: httpx.Client,
    base_url: str,
    case: ChatCase,
    mode: str | None,
    repeat_index: int,
    max_tokens: int | None,
) -> dict[str, Any]:
    conversation_id = f"bench-{case.case_id}-{repeat_index}-{uuid.uuid4().hex[:8]}"
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": case.query}],
        "domain": case.domain,
        "conversation_id": conversation_id,
    }
    if mode:
        payload["mode"] = mode
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    started = time.perf_counter()
    response = client.post(f"{base_url}/api/v1/chat", json=payload)
    latency_ms = (time.perf_counter() - started) * 1000

    result: dict[str, Any] = {
        "case_id": case.case_id,
        "category": case.category,
        "query": case.query,
        "domain_requested": case.domain,
        "mode_requested": mode,
        "expected_mode": case.expected_mode,
        "repeat_index": repeat_index,
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

    answer = str(body.get("content", ""))
    keyword = _keyword_stats(answer, case.expected_keywords)
    mode_used = body.get("mode_used")
    success = bool(body.get("success", True))
    result.update(
        {
            "ok": success,
            "api_success": success,
            "degraded": bool(body.get("degraded", False)),
            "domain_used": body.get("domain"),
            "mode_used": mode_used,
            "trace_id": body.get("trace_id"),
            "answer_chars": len(answer),
            "answer_preview": answer[:240],
            "keyword": keyword,
            "mode_matched": case.expected_mode is None or mode_used == case.expected_mode,
        }
    )
    return result


def _summarize(results: list[dict[str, Any]], health: dict[str, Any]) -> dict[str, Any]:
    latencies = [float(r["latency_ms"]) for r in results if r.get("ok") and "latency_ms" in r]
    total = len(results)
    ok_count = sum(1 for r in results if r.get("ok"))
    http_ok_count = sum(1 for r in results if int(r.get("http_status", 0)) < 400)
    keyword_cases = [r for r in results if isinstance(r.get("keyword"), dict) and r["keyword"]["all_matched"] is not None]
    all_keyword_matched = sum(1 for r in keyword_cases if r["keyword"]["all_matched"])
    mode_cases = [r for r in results if r.get("expected_mode")]
    mode_matched = sum(1 for r in mode_cases if r.get("mode_matched"))

    return {
        "health_ready": bool(health.get("ready")),
        "total_requests": total,
        "http_success_count": http_ok_count,
        "agent_success_count": ok_count,
        "agent_success_rate": ok_count / total if total else 0.0,
        "keyword_case_count": len(keyword_cases),
        "keyword_all_matched_count": all_keyword_matched,
        "keyword_all_matched_rate": all_keyword_matched / len(keyword_cases) if keyword_cases else None,
        "mode_case_count": len(mode_cases),
        "mode_matched_count": mode_matched,
        "mode_matched_rate": mode_matched / len(mode_cases) if mode_cases else None,
        "latency_ms": {
            "count": len(latencies),
            "avg": round(statistics.mean(latencies), 2) if latencies else None,
            "p50": round(_percentile(latencies, 0.50), 2) if latencies else None,
            "p95": round(_percentile(latencies, 0.95), 2) if latencies else None,
            "max": round(max(latencies), 2) if latencies else None,
        },
    }


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    latency = summary["latency_ms"]
    lines = [
        "# PolyAgent E2E Chat Benchmark Report",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Base URL: `{report['base_url']}`",
        f"- Cases file: `{report['cases_file']}`",
        f"- Total requests: **{summary['total_requests']}**",
        f"- Agent success rate: **{summary['agent_success_rate']:.2%}**",
        f"- Keyword all-matched rate: **{_fmt_rate(summary['keyword_all_matched_rate'])}**",
        f"- Mode matched rate: **{_fmt_rate(summary['mode_matched_rate'])}**",
        f"- Latency P50/P95/Max: **{_fmt_ms(latency['p50'])} / {_fmt_ms(latency['p95'])} / {_fmt_ms(latency['max'])}**",
        "",
        "## Resume-Safe Metrics",
        "",
        (
            f"- 在本地 Docker 端到端环境中,基于 {summary['total_requests']} 次自然语言对话请求,"
            f"Agent 成功率 {summary['agent_success_rate']:.2%},"
            f"关键词全命中率 {_fmt_rate(summary['keyword_all_matched_rate'])},"
            f"P95 延迟 {_fmt_ms(latency['p95'])}。"
        ),
        "",
        "> Only use the line above in a resume if this report was generated with your real `.env` model provider and the full case set you want to claim.",
        "",
        "## Cases",
        "",
        "| Case | Category | Domain | Mode | OK | Latency | Keyword | Preview |",
        "|---|---|---|---|---:|---:|---:|---|",
    ]
    for r in report["results"]:
        keyword = r.get("keyword") or {}
        keyword_text = "n/a"
        if keyword.get("all_matched") is not None:
            keyword_text = f"{keyword.get('matched')}/{keyword.get('expected')}"
        preview = str(r.get("answer_preview") or r.get("error") or "").replace("\n", " ")
        if len(preview) > 80:
            preview = preview[:77] + "..."
        lines.append(
            "| {case} | {category} | {domain} | {mode} | {ok} | {latency} | {keyword} | {preview} |".format(
                case=r.get("case_id"),
                category=r.get("category"),
                domain=r.get("domain_used") or r.get("domain_requested"),
                mode=r.get("mode_used") or r.get("mode_requested"),
                ok="yes" if r.get("ok") else "no",
                latency=_fmt_ms(r.get("latency_ms")),
                keyword=keyword_text,
                preview=preview.replace("|", "/"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _fmt_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def _fmt_ms(value: float | int | None) -> str:
    return "n/a" if value is None else f"{float(value):.2f} ms"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PolyAgent E2E natural-language chat benchmark")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--domain", default="financial")
    parser.add_argument(
        "--mode",
        default="expected",
        help="expected uses case metadata.expected_mode; otherwise use react/plan_execute/deliberation for every case",
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--plan", action="store_true", help="print the cases that would run, without calling /chat")
    parser.add_argument("--fail-on-error", action="store_true", help="exit 1 when any request fails")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    cases = _load_cases(args.cases, default_domain=args.domain)
    if args.max_cases is not None:
        cases = cases[: max(0, args.max_cases)]
    if args.repeat < 1:
        raise SystemExit("--repeat must be >= 1")

    if args.plan:
        payload = {
            "status": "plan",
            "base_url": args.base_url,
            "cases_file": str(args.cases),
            "repeat": args.repeat,
            "cases": [case.__dict__ for case in cases],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    run_id = _now_id()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=args.timeout) as client:
        health = _check_health(client, args.base_url.rstrip("/"))
        if not health["ready"]:
            raise SystemExit(f"Health is not ready: {json.dumps(health['payload'], ensure_ascii=False)}")

        results: list[dict[str, Any]] = []
        for repeat_index in range(1, args.repeat + 1):
            for case in cases:
                mode = case.expected_mode if args.mode == "expected" else args.mode or None
                results.append(
                    _post_chat(
                        client=client,
                        base_url=args.base_url.rstrip("/"),
                        case=case,
                        mode=mode,
                        repeat_index=repeat_index,
                        max_tokens=args.max_tokens,
                    )
                )

    report = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "cases_file": str(args.cases),
        "repeat": args.repeat,
        "summary": _summarize(results, health),
        "health": health["payload"],
        "results": results,
    }

    json_path = args.out_dir / f"e2e_chat_benchmark_{run_id}.json"
    md_path = args.out_dir / f"e2e_chat_benchmark_{run_id}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")

    print(json.dumps({"status": "ok", "json": str(json_path), "markdown": str(md_path), "summary": report["summary"]}, ensure_ascii=False, indent=2))

    if args.fail_on_error and report["summary"]["agent_success_count"] != report["summary"]["total_requests"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
