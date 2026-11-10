# -*- coding: utf-8 -*-
"""End-to-end benchmark for PolyAgent deliberation mode.

This script specifically validates the multi-agent deliberation feature:
D1 shared retrieval, D2 participant views, and D3 synthesis. It calls /chat
with mode=deliberation and checks the returned orchestration steps.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


DEFAULT_OUT_DIR = Path("reports/e2e")
DEFAULT_CASES = [
    {
        "case_id": "delib_apple_001",
        "query": "请用多空双方视角分析苹果公司的投资价值。",
        "expected_roles": ["bull", "bear"],
        "expected_keywords": ["苹果", "多头", "空头", "风险"],
    },
    {
        "case_id": "delib_msft_001",
        "query": "请用多视角审议微软 Azure 和 AI 投资带来的机会与风险。",
        "expected_roles": ["bull", "bear"],
        "expected_keywords": ["微软", "Azure", "AI", "风险"],
    },
    {
        "case_id": "delib_nvda_001",
        "query": "请对英伟达做一次多 agent 辩论式投资分析。",
        "expected_roles": ["bull", "bear"],
        "expected_keywords": ["英伟达", "数据中心", "估值", "风险"],
    },
]


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


def _load_cases(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return DEFAULT_CASES
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("cases file must be a JSON list")
    return raw


def _keyword_stats(answer: str, expected_keywords: list[str]) -> dict[str, Any]:
    answer_folded = answer.casefold()
    matched = [kw for kw in expected_keywords if str(kw).casefold() in answer_folded]
    missing = [kw for kw in expected_keywords if str(kw).casefold() not in answer_folded]
    return {
        "expected": len(expected_keywords),
        "matched": len(matched),
        "missing": missing,
        "hit_rate": len(matched) / len(expected_keywords) if expected_keywords else None,
        "all_matched": not missing if expected_keywords else None,
    }


def _deliberation_step_stats(steps: list[dict[str, Any]], expected_roles: list[str]) -> dict[str, Any]:
    phases = [str(step.get("phase") or "") for step in steps]
    d1 = [step for step in steps if step.get("phase") == "d1"]
    d2 = [step for step in steps if "roles" in step and ("ok" in step or "failed" in step)]
    d3 = [step for step in steps if step.get("phase") == "deliberation.d3.done" or "answer_len" in step]

    roles: list[str] = []
    ok_participants = None
    failed_participants = None
    if d2:
        roles = [str(x) for x in d2[-1].get("roles", [])]
        ok_participants = d2[-1].get("ok")
        failed_participants = d2[-1].get("failed")

    role_set = set(roles)
    expected_role_set = {str(role) for role in expected_roles}
    return {
        "step_count": len(steps),
        "has_d1": bool(d1),
        "d1_hits": d1[-1].get("hits") if d1 else None,
        "has_d2": bool(d2),
        "roles": roles,
        "expected_roles_matched": expected_role_set.issubset(role_set) if expected_role_set else bool(roles),
        "ok_participants": ok_participants,
        "failed_participants": failed_participants,
        "has_d3": bool(d3),
        "phases": phases,
    }


def _check_health(client: httpx.Client, base_url: str) -> dict[str, Any]:
    response = client.get(f"{base_url}/api/v1/health")
    response.raise_for_status()
    payload = response.json()
    deps = payload.get("dependencies") or {}
    return {
        "ready": payload.get("status") == "ok"
        and deps.get("milvus") is True
        and deps.get("redis") is True
        and deps.get("postgres") is True,
        "payload": payload,
    }


def _run_case(
    client: httpx.Client,
    *,
    base_url: str,
    case: dict[str, Any],
    domain: str,
    max_tokens: int | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": case["query"]}],
        "domain": domain,
        "mode": "deliberation",
        "conversation_id": f"delib-{case.get('case_id')}-{uuid.uuid4().hex[:8]}",
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    started = time.perf_counter()
    response = client.post(f"{base_url}/api/v1/chat", json=payload)
    latency_ms = (time.perf_counter() - started) * 1000
    result: dict[str, Any] = {
        "case_id": case.get("case_id"),
        "query": case.get("query"),
        "http_status": response.status_code,
        "latency_ms": round(latency_ms, 2),
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
    step_stats = _deliberation_step_stats(steps, [str(x) for x in case.get("expected_roles", [])])
    keyword = _keyword_stats(answer, [str(x) for x in case.get("expected_keywords", [])])
    chain_ok = (
        body.get("success") is True
        and body.get("mode_used") == "deliberation"
        and step_stats["has_d1"]
        and step_stats["has_d2"]
        and step_stats["has_d3"]
        and step_stats["expected_roles_matched"]
        and int(step_stats["ok_participants"] or 0) >= 1
    )
    result.update(
        {
            "ok": bool(chain_ok),
            "api_success": bool(body.get("success")),
            "mode_used": body.get("mode_used"),
            "domain": body.get("domain"),
            "trace_id": body.get("trace_id"),
            "answer_chars": len(answer),
            "answer_preview": answer[:260],
            "keyword": keyword,
            "deliberation": step_stats,
        }
    )
    return result


def _summarize(results: list[dict[str, Any]], health: dict[str, Any]) -> dict[str, Any]:
    total = len(results)
    ok_count = sum(1 for r in results if r.get("ok"))
    api_success = sum(1 for r in results if r.get("api_success"))
    mode_matched = sum(1 for r in results if r.get("mode_used") == "deliberation")
    d1 = sum(1 for r in results if (r.get("deliberation") or {}).get("has_d1"))
    d2 = sum(1 for r in results if (r.get("deliberation") or {}).get("has_d2"))
    d3 = sum(1 for r in results if (r.get("deliberation") or {}).get("has_d3"))
    role_matched = sum(1 for r in results if (r.get("deliberation") or {}).get("expected_roles_matched"))
    keyword_cases = [r for r in results if isinstance(r.get("keyword"), dict) and r["keyword"]["all_matched"] is not None]
    keyword_all = sum(1 for r in keyword_cases if r["keyword"]["all_matched"])
    latencies = [float(r["latency_ms"]) for r in results if "latency_ms" in r]
    return {
        "health_ready": bool(health.get("ready")),
        "total_cases": total,
        "deliberation_chain_success_count": ok_count,
        "deliberation_chain_success_rate": ok_count / total if total else 0.0,
        "api_success_count": api_success,
        "mode_matched_count": mode_matched,
        "d1_present_count": d1,
        "d2_present_count": d2,
        "d3_present_count": d3,
        "roles_matched_count": role_matched,
        "keyword_all_matched_count": keyword_all,
        "keyword_all_matched_rate": keyword_all / len(keyword_cases) if keyword_cases else None,
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
        "# PolyAgent Deliberation E2E Benchmark Report",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Base URL: `{report['base_url']}`",
        f"- Cases: **{summary['total_cases']}**",
        f"- Deliberation chain success: **{summary['deliberation_chain_success_rate']:.2%}**",
        f"- D1/D2/D3 present: **{summary['d1_present_count']} / {summary['d2_present_count']} / {summary['d3_present_count']}**",
        f"- Roles matched: **{summary['roles_matched_count']}/{summary['total_cases']}**",
        f"- Keyword all-matched rate: **{_fmt_rate(summary['keyword_all_matched_rate'])}**",
        f"- Latency P50/P95/Max: **{_fmt_ms(latency['p50'])} / {_fmt_ms(latency['p95'])} / {_fmt_ms(latency['max'])}**",
        "",
        "## Cases",
        "",
        "| Case | OK | Mode | D1 Hits | Roles | D3 | Latency | Keyword | Preview |",
        "|---|---:|---|---:|---|---:|---:|---:|---|",
    ]
    for r in report["results"]:
        d = r.get("deliberation") or {}
        k = r.get("keyword") or {}
        preview = str(r.get("answer_preview") or r.get("error") or "").replace("\n", " ")
        if len(preview) > 90:
            preview = preview[:87] + "..."
        lines.append(
            "| {case} | {ok} | {mode} | {hits} | {roles} | {d3} | {latency} | {keyword} | {preview} |".format(
                case=r.get("case_id"),
                ok="yes" if r.get("ok") else "no",
                mode=r.get("mode_used"),
                hits=d.get("d1_hits"),
                roles=",".join(d.get("roles") or []),
                d3="yes" if d.get("has_d3") else "no",
                latency=_fmt_ms(r.get("latency_ms")),
                keyword=f"{k.get('matched')}/{k.get('expected')}" if k else "n/a",
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
    parser = argparse.ArgumentParser(description="Run PolyAgent deliberation-mode E2E benchmark")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--cases", type=Path, default=None)
    parser.add_argument("--domain", default="financial")
    parser.add_argument("--timeout", type=float, default=360.0)
    parser.add_argument("--max-tokens", type=int, default=700)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--plan", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    cases = _load_cases(args.cases)
    if args.max_cases is not None:
        cases = cases[: max(0, args.max_cases)]
    if args.plan:
        print(json.dumps({"status": "plan", "cases": cases}, ensure_ascii=False, indent=2))
        return 0

    run_id = _now_id()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    base_url = args.base_url.rstrip("/")
    with httpx.Client(timeout=args.timeout) as client:
        health = _check_health(client, base_url)
        if not health["ready"]:
            raise SystemExit(f"Health is not ready: {json.dumps(health['payload'], ensure_ascii=False)}")
        results = [
            _run_case(client, base_url=base_url, case=case, domain=args.domain, max_tokens=args.max_tokens)
            for case in cases
        ]

    report = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "domain": args.domain,
        "summary": _summarize(results, health),
        "health": health["payload"],
        "results": results,
    }
    json_path = args.out_dir / f"e2e_deliberation_benchmark_{run_id}.json"
    md_path = args.out_dir / f"e2e_deliberation_benchmark_{run_id}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    print(json.dumps({"status": "ok", "json": str(json_path), "markdown": str(md_path), "summary": report["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
