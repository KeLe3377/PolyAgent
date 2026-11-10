import json

import pytest

from scripts.e2e_multidomain_rag_benchmark import _evidence_stats, aggregate_report_files


def _result(case_id, domain, ok, hit, precision, recall):
    return {
        "case_id": case_id,
        "domain_requested": domain,
        "ok": ok,
        "api_success": ok,
        "latency_ms": 10.0,
        "step_stats": {"rag_used": True},
        "keyword": {"all_matched": ok},
        "evidence": {
            "hit": hit,
            "precision": precision,
            "recall": recall,
        },
    }


def test_aggregate_report_files_uses_case_level_counts(tmp_path):
    report_a = tmp_path / "a.json"
    report_b = tmp_path / "b.json"
    report_a.write_text(
        json.dumps({"results": [_result("a", "financial", True, True, 0.5, 1.0)]}),
        encoding="utf-8",
    )
    report_b.write_text(
        json.dumps(
            {
                "results": [
                    _result("b", "financial", False, False, 0.0, 0.0),
                    _result("c", "medical_adr", True, True, 1.0, 1.0),
                ]
            }
        ),
        encoding="utf-8",
    )

    summary = aggregate_report_files([report_a, report_b])["summary"]

    assert summary["total_cases"] == 3
    assert summary["chain_success_count"] == 2
    assert summary["evidence_hit_count"] == 2
    assert summary["evidence_hit_rate"] == pytest.approx(2 / 3)
    assert summary["by_domain"]["financial"]["evidence_hit_rate"] == pytest.approx(0.5)


def test_evidence_stats_parses_evidence_pack_doc_ids():
    steps = [
        {
            "observation": (
                'EVIDENCE_PACK: {"evidence_items": ['
                '{"doc_id": "spl_adr_gold_actemra", "chunk_id": "chunk-1"}, '
                '{"doc_id": "spl_adr_gold_adempas", "chunk_id": "chunk-2"}'
                "]}"
            )
        }
    ]

    stats = _evidence_stats(steps, ["spl_adr_gold_actemra"])

    assert stats["hit"] is True
    assert stats["precision"] == pytest.approx(0.5)
    assert stats["recall"] == pytest.approx(1.0)
