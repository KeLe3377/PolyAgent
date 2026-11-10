# -*- coding: utf-8 -*-
"""TableCalculatorTool 确定性契约测试(RAG 质量升级 2026-08-11)。"""

from __future__ import annotations

import json

import pytest

from app.core.tools.builtin.table_calculator import TableCalculatorTool, _parse_number


@pytest.fixture()
def tool() -> TableCalculatorTool:
    return TableCalculatorTool()


# ---------------------------------------------------------------------------
# 数值解析(容忍 TAT-QA 表格里的脏格式)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$  1,452.4", 1452.4),
        ("73,260", 73260.0),
        ("(1,200)", -1200.0),  # 括号负数
        ("12%", 12.0),
        ("$68.1B", 68.1),
        (1146.2, 1146.2),
        ("n/a", None),
        ("", None),
    ],
)
def test_parse_number(raw, expected) -> None:
    assert _parse_number(raw) == expected


# ---------------------------------------------------------------------------
# 操作
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sum_returns_deterministic_answer_and_trace(tool: TableCalculatorTool) -> None:
    out = json.loads(await tool.execute(operation="sum", values="[1452.4, 1146.2, 1036.9]"))

    assert out["ok"] is True
    assert out["operation"] == "sum"
    assert out["answer"] == "3635.5"
    assert out["calculation_trace"]["sum"] == "3635.5"
    assert out["calculation_trace"]["inputs"] == ["1452.4", "1146.2", "1036.9"]


@pytest.mark.asyncio
async def test_difference(tool: TableCalculatorTool) -> None:
    out = json.loads(await tool.execute(operation="difference", values="1452.4, 1146.2"))
    assert out["answer"] == "306.2"
    assert "1452.4 - 1146.2" in out["calculation_trace"]["formula"]


@pytest.mark.asyncio
async def test_ratio(tool: TableCalculatorTool) -> None:
    out = json.loads(await tool.execute(operation="ratio", values="[1452.4, 1146.2]"))
    assert out["answer"] == str(round(1452.4 / 1146.2, 4))
    assert out["calculation_trace"]["ratio"]


@pytest.mark.asyncio
async def test_count(tool: TableCalculatorTool) -> None:
    out = json.loads(await tool.execute(operation="count", values="[1, 2, 3]"))
    assert out["answer"] == "3"
    assert out["calculation_trace"]["count"] == 3


@pytest.mark.asyncio
async def test_ratio_zero_denominator_errors_cleanly(tool: TableCalculatorTool) -> None:
    out = json.loads(await tool.execute(operation="ratio", values="[100, 0]"))
    assert out["ok"] is False
    assert "分母为 0" in out["error"]


@pytest.mark.asyncio
async def test_lookup_by_target_field(tool: TableCalculatorTool) -> None:
    rows = [
        {"row": "Fixed Price", "2019": 1452.4, "2018": 1146.2},
        {"row": "Cost Plus", "2019": 200.0, "2018": 180.0},
    ]
    out = json.loads(await tool.execute(operation="lookup", rows=json.dumps(rows), target="Cost Plus", field="2019"))
    assert out["answer"] == 200.0
    assert out["calculation_trace"]["matched"] == 1


@pytest.mark.asyncio
async def test_lookup_no_match_returns_null(tool: TableCalculatorTool) -> None:
    out = json.loads(
        await tool.execute(operation="lookup", rows='[{"row":"X","value":1}]', target="missing")
    )
    assert out["answer"] is None
    assert out["calculation_trace"]["matched"] == 0


@pytest.mark.asyncio
async def test_unknown_operation_errors(tool: TableCalculatorTool) -> None:
    out = json.loads(await tool.execute(operation="median", values="[1,2,3]"))
    assert out["ok"] is False


@pytest.mark.asyncio
async def test_dirty_currency_values_parse_in_sum(tool: TableCalculatorTool) -> None:
    out = json.loads(await tool.execute(operation="sum", values="[$ 1,452.4, $ 1,146.2]"))
    assert out["answer"] == "2598.6"
