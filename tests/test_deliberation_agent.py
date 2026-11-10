# -*- coding: utf-8 -*-
"""Focused tests for the multi-agent deliberation feature."""

from __future__ import annotations

from typing import Any, Sequence

import pytest

from app.core.agent.deliberation import run_deliberation
from app.domains.base import DeliberationSpec, ParticipantSpec
from app.models.schemas import RetrievalResult


class FakeRetriever:
    async def retrieve(self, query: str, top_k: int = 8, mode: str = "hybrid"):
        return [
            RetrievalResult(
                id="doc_apple_001",
                content="Apple services gross margin is above 70%, with risks in China and App Store policy.",
                metadata={"doc_id": "doc_apple_001"},
                source="keyword",
            )
        ]


class FakeDeliberationLLM:
    def __init__(self, *, fail_bear: bool = False) -> None:
        self.fail_bear = fail_bear
        self.calls: list[list[dict[str, str]]] = []

    async def acomplete(self, messages: Sequence[dict[str, str]], **kwargs: Any) -> str:
        self.calls.append(list(messages))
        system = messages[0]["content"].lower()
        if "bear" in system and self.fail_bear:
            raise RuntimeError("bear failed intentionally")
        if "bull" in system:
            return "Bull view: Apple has strong services margin and ecosystem moat."
        if "bear" in system:
            return "Bear view: Apple faces China, App Store, and iPhone cycle risks."
        return "Synthesis: balance bull and bear views, cite services margin above 70% and key risks."


def _spec() -> DeliberationSpec:
    return DeliberationSpec(
        participants=[
            ParticipantSpec(role="bull", stance_prompt="You are bull analyst.", temperature=0.7),
            ParticipantSpec(role="bear", stance_prompt="You are bear analyst.", temperature=0.7),
        ],
        synthesis_prompt="You are synthesis analyst.",
        synthesis_temperature=0.5,
        shared_retrieve_top_k=8,
    )


@pytest.mark.asyncio
async def test_deliberation_runs_d1_d2_d3_with_bull_and_bear() -> None:
    llm = FakeDeliberationLLM()
    steps: list[dict[str, Any]] = []

    result = await run_deliberation(
        query="Analyze Apple investment value from bull and bear views.",
        spec=_spec(),
        llm=llm,
        retriever=FakeRetriever(),
        trace_id="trace-test",
        steps=steps,
    )

    assert result.success is True
    assert "Synthesis" in result.final_answer
    assert len(llm.calls) == 3  # bull + bear + synthesis
    assert any(step.get("phase") == "d1" and step.get("hits") == 1 for step in steps)
    assert any(step.get("ok") == 2 and step.get("failed") == 0 and step.get("roles") == ["bull", "bear"] for step in steps)
    assert any(step.get("answer_len", 0) > 0 for step in steps)


@pytest.mark.asyncio
async def test_deliberation_tolerates_single_participant_failure() -> None:
    llm = FakeDeliberationLLM(fail_bear=True)
    steps: list[dict[str, Any]] = []

    result = await run_deliberation(
        query="Analyze Apple investment value from bull and bear views.",
        spec=_spec(),
        llm=llm,
        retriever=FakeRetriever(),
        trace_id="trace-test",
        steps=steps,
    )

    assert result.success is True
    assert len(llm.calls) == 3  # failed bear call still counted, synthesis still runs
    assert any(step.get("ok") == 1 and step.get("failed") == 1 and step.get("roles") == ["bull", "bear"] for step in steps)
    assert any(step.get("answer_len", 0) > 0 for step in steps)
