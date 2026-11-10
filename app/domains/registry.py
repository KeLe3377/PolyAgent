# -*- coding: utf-8 -*-
"""项目内领域 Skill 注册表。

运行时扫描 ``skills/<domain>/SKILL.md``。领域知识、提示词、工具契约、
语料路径和评测入口都以 Skill 为事实来源;平台仍只依赖通用 registry 接口。
单个 Skill 解析失败只告警跳过,不阻断启动(可用性优先)。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Optional

from app.core.tools.base import BaseTool
from app.core.tools.builtin.contract_clause_locator import ContractClauseLocatorTool
from app.core.tools.builtin.rag_search import RagSearchTool
from app.core.tools.builtin.table_calculator import TableCalculatorTool
from app.domains.base import (
    CorpusDoc,
    DeliberationSpec,
    DomainContext,
    DomainPack,
    EvalCase,
    EvalDataset,
    IntentHints,
    ParticipantSpec,
)

logger = logging.getLogger(__name__)


@dataclass
class DomainSummary:
    """对外暴露的领域 Skill 摘要(给 GET /api/v1/domains)。不泄漏内部对象。"""

    name: str
    version: str
    default_mode: str
    supports_deliberation: bool
    has_eval: bool
    tool_count: int  # 静态可知的工具数(运行时按 ctx 构建,此处仅指示性)


class DomainRegistry:
    """领域 Skill 注册表:list / get / default / summarize。"""

    def __init__(self, default_name: Optional[str] = "kb_qa", skills_root: Path | None = None) -> None:
        self._packs: dict[str, DomainPack] = {}
        self._default_name = default_name
        self._skills_root = skills_root or Path(__file__).resolve().parents[2] / "skills"

    # ---- 装配 ----
    def scan(self) -> None:
        """扫描 project-local skills 下所有 ``SKILL.md`` 并注册为运行时领域。"""
        self._packs.clear()
        if not self._skills_root.exists():
            logger.warning("领域 Skill 目录不存在:%s", self._skills_root)
            return
        for skill_md in sorted(self._skills_root.glob("*/SKILL.md")):
            self._try_register(skill_md)

    def _try_register(self, skill_md: Path) -> None:
        try:
            pack = DomainSkill.from_file(skill_md)
        except Exception as e:  # noqa: BLE001
            logger.warning("领域 Skill %s 解析失败,已跳过: %s", skill_md, e)
            return

        if pack.name in self._packs:
            logger.warning("领域 Skill 名称冲突:%s 已存在,%s 被忽略", pack.name, skill_md)
            return

        self._packs[pack.name] = pack
        logger.info("已注册领域 Skill: %s (v%s, default_mode=%s)", pack.name, pack.version, pack.default_mode)

    # ---- 查询 ----
    def list_domains(self) -> list[str]:
        return sorted(self._packs.keys())

    def get(self, name: Optional[str]) -> Optional[DomainPack]:
        """按名取 Skill;name 为空时返回默认 Skill,name 不存在时返回 None。"""
        if not name:
            return self.default()
        return self._packs.get(name)

    def default(self) -> Optional[DomainPack]:
        if self._default_name and self._default_name in self._packs:
            return self._packs[self._default_name]
        if self._packs:
            return next(iter(self._packs.values()))
        return None

    def summarize(self) -> list[DomainSummary]:
        """生成对外摘要(不传 ctx,tool_count 取指示性数量)。"""
        out: list[DomainSummary] = []

        for name in self.list_domains():
            pack = self._packs[name]
            try:
                spec = pack.deliberation_spec()
                has_eval = pack.eval_dataset() is not None
                # 用空 ctx 探测工具数(实现应容忍 ctx.retriever 为 None)
                try:
                    tools = pack.tools(DomainContext())
                    tool_count = len(tools)
                except Exception:  # noqa: BLE001
                    tool_count = -1
                out.append(
                    DomainSummary(
                        name=pack.name,
                        version=pack.version,
                        default_mode=pack.default_mode,
                        supports_deliberation=spec is not None,
                        has_eval=has_eval,
                        tool_count=tool_count,
                    )
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("领域 Skill %s 摘要生成失败: %s", name, e)
        return out


class DomainSkill:
    """把 ``skills/<domain>/SKILL.md`` 适配成平台内部 DomainPack 形状。"""

    def __init__(
        self,
        *,
        name: str,
        version: str,
        default_mode: str,
        system_prompt: str,
        metadata: dict[str, str],
        skill_dir: Path,
        sections: dict[str, str],
    ) -> None:
        self.name = name
        self.version = version
        self.default_mode = default_mode
        self.system_prompt = system_prompt
        self.metadata = metadata
        self.skill_dir = skill_dir
        self._sections = sections

    @classmethod
    def from_file(cls, skill_md: Path) -> "DomainSkill":
        raw = skill_md.read_text(encoding="utf-8")
        metadata, body = _split_frontmatter(raw)
        name = metadata.get("domain") or metadata.get("name") or skill_md.parent.name
        version = metadata.get("version") or "0.1.0"
        default_mode = metadata.get("default_mode") or "react"
        sections = _extract_sections(body)
        system_prompt = sections.get("system prompt") or body.strip()
        if not system_prompt:
            raise ValueError("SKILL.md 缺少 System Prompt 正文")
        return cls(
            name=name,
            version=version,
            default_mode=default_mode,
            system_prompt=system_prompt.strip(),
            metadata=metadata,
            skill_dir=skill_md.parent,
            sections=sections,
        )

    def corpus_docs(self) -> list[CorpusDoc]:
        docs: list[CorpusDoc] = []
        for root in _paths_from_csv(self.metadata.get("corpus_paths")):
            corpus_root = _resolve_project_path(root, self.skill_dir)
            if not corpus_root.exists():
                continue
            for path in sorted(corpus_root.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
                    continue
                docs.append(
                    CorpusDoc(
                        id=path.stem,
                        text=path.read_text(encoding="utf-8"),
                        source=str(path),
                        metadata={"domain": self.name, "source": str(path)},
                    )
                )
        return docs

    def tools(self, ctx: DomainContext) -> list[BaseTool]:
        tools: list[BaseTool] = []
        for tool_name in _paths_from_csv(self.metadata.get("tools")):
            if tool_name == "rag_search":
                tools.append(
                    RagSearchTool(
                        retriever=ctx.retriever,
                        description=self.metadata.get("rag_description"),
                        domain_filter=self.metadata.get("rag_domain_filter") or self.name,
                    )
                )
            elif tool_name == "table_calculator":
                tools.append(TableCalculatorTool())
            elif tool_name == "contract_clause_locator":
                tools.append(ContractClauseLocatorTool())
            else:
                logger.warning("领域 Skill %s 声明未知工具:%s", self.name, tool_name)
        return tools

    def deliberation_spec(self) -> DeliberationSpec | None:
        roles = _paths_from_csv(self.metadata.get("deliberation_roles"))
        if not roles:
            return None
        participants: list[ParticipantSpec] = []
        for role in roles:
            prompt = (
                self._sections.get(f"deliberation participant {role}")
                or self._sections.get(f"participant {role}")
                or self._sections.get(role)
            )
            if not prompt:
                logger.warning("领域 Skill %s 缺少审议参与者提示词:%s", self.name, role)
                continue
            participants.append(ParticipantSpec(role=role, stance_prompt=prompt.strip()))
        synthesis_prompt = (
            self._sections.get("deliberation synthesis")
            or self._sections.get("synthesis prompt")
            or self.system_prompt
        )
        if not participants:
            return None
        return DeliberationSpec(
            participants=participants,
            synthesis_prompt=synthesis_prompt.strip(),
            synthesis_temperature=float(self.metadata.get("synthesis_temperature") or 0.5),
            max_rounds=int(self.metadata.get("max_rounds") or 1),
            shared_retrieve_top_k=int(self.metadata.get("shared_retrieve_top_k") or 8),
        )

    def eval_dataset(self) -> EvalDataset | None:
        path_value = self.metadata.get("eval_cases_path")
        if not path_value:
            return None
        path = _resolve_project_path(path_value, self.skill_dir)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.warning("领域 Skill %s 读取评测集失败:%s", self.name, e)
            return None
        cases = [
            EvalCase(
                query=str(it.get("query", "")),
                reference_answer=str(it.get("reference_answer", "")),
                expected_keywords=list(it.get("expected_keywords", [])),
                metadata=dict(it.get("metadata", {})),
            )
            for it in raw
            if isinstance(it, dict) and it.get("query")
        ]
        return EvalDataset(cases=cases) if cases else None

    def intent_hints(self) -> IntentHints | None:
        overrides = _parse_overrides(self.metadata.get("intent_overrides"))
        return IntentHints(intent_overrides=overrides) if overrides else None


def _split_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---"):
        return {}, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, raw
    metadata: dict[str, str] = {}
    for line in parts[1].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"').strip("'")
    return metadata, parts[2].strip()


def _extract_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = ""
    lines: list[str] = []
    for line in body.splitlines():
        match = re.match(r"^##+\s+(.+?)\s*$", line)
        if match:
            if current:
                sections[_norm_section(current)] = "\n".join(lines).strip()
            current = match.group(1)
            lines = []
        elif current:
            lines.append(line)
    if current:
        sections[_norm_section(current)] = "\n".join(lines).strip()
    return sections


def _norm_section(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def _paths_from_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_overrides(value: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in _paths_from_csv(value):
        if "=" not in item:
            continue
        key, val = item.split("=", 1)
        out[key.strip()] = val.strip()
    return out


def _resolve_project_path(value: str, skill_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    project_root = Path(__file__).resolve().parents[2]
    project_path = project_root / path
    if project_path.exists() or str(value).startswith(("app/", "app\\", "data/", "data\\")):
        return project_path
    return skill_dir / path


__all__ = ["DomainRegistry", "DomainSkill", "DomainSummary"]
