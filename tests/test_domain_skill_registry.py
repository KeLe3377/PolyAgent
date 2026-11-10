# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from app.domains.base import DomainContext
from app.domains.registry import DomainRegistry


def _write_skill(root: Path, name: str, body: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")


def test_registry_loads_project_local_domain_skill(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "demo-support",
        """---
name: demo-support
description: Use when testing project-local domain skills.
domain: demo_support
version: 1.2.3
default_mode: react
tools: rag_search
rag_domain_filter: demo_support
intent_overrides: 知识问答=react
---

# Demo Skill

## System Prompt

你是 Demo 领域助手,必须基于 RAG 证据回答。
""",
    )

    registry = DomainRegistry(skills_root=tmp_path)
    registry.scan()

    assert registry.list_domains() == ["demo_support"]
    assert registry.get("missing") is None
    skill = registry.get("demo_support")
    assert skill is not None
    assert skill.version == "1.2.3"
    assert skill.default_mode == "react"
    assert "Demo 领域助手" in skill.system_prompt
    assert skill.intent_hints().intent_overrides == {"知识问答": "react"}

    tools = skill.tools(DomainContext())
    assert [tool.name for tool in tools] == ["rag_search"]
    assert tools[0].domain_filter == "demo_support"


def test_registry_builds_deliberation_from_skill_sections(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "analysis",
        """---
name: analysis
description: Use when testing deliberation skills.
domain: analysis
default_mode: deliberation
tools: rag_search,table_calculator,contract_clause_locator
deliberation_roles: pro,con
---

# Analysis Skill

## System Prompt

你是分析助手。

## Deliberation Participant Pro

正方观点。

## Deliberation Participant Con

反方观点。

## Deliberation Synthesis

综合观点。
""",
    )

    registry = DomainRegistry(skills_root=tmp_path)
    registry.scan()
    skill = registry.get("analysis")

    assert skill is not None
    assert [tool.name for tool in skill.tools(DomainContext())] == [
        "rag_search",
        "table_calculator",
        "contract_clause_locator",
    ]
    spec = skill.deliberation_spec()
    assert spec is not None
    assert [participant.role for participant in spec.participants] == ["pro", "con"]
    assert spec.synthesis_prompt == "综合观点。"
