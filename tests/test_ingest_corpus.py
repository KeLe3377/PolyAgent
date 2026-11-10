from pathlib import Path

from scripts.ingest_corpus import build_ingest_plan


def test_build_ingest_plan_discovers_domain_corpus_files(tmp_path):
    corpus = tmp_path / "app" / "domains" / "financial" / "corpus"
    corpus.mkdir(parents=True)
    (corpus / "market.md").write_text("# Market\n\nRevenue growth", encoding="utf-8")

    plan = build_ingest_plan(tmp_path, domain="financial")

    assert plan.domain == "financial"
    assert [item.domain for item in plan.items] == ["financial"]
    assert plan.items[0].source_path == corpus / "market.md"
    assert plan.items[0].text == "# Market\n\nRevenue growth"
