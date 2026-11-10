# -*- coding: utf-8 -*-
"""TableCalculator —— 面向 TAT-QA 表格数值推理的确定性计算工具。

RAG 质量升级(2026-08-11)的核心补丁:TAT-QA 是表格 + 文本 + 数值推理任务,
让 LLM 直接生成数值答案会引入算错/幻觉。本工具把 lookup / sum / difference
/ ratio / count 退化为确定性 Python 计算,并输出 ``calculation_trace``,让
最终答案可解释、可复现。

设计取舍:
- **纯确定性,零模型调用**。输入是结构化数值/行(由 agent 从检索到的
  ``cell_fact``/``row_fact`` 观察中整理),输出 JSON 字符串。
- **鲁棒数值解析**:容忍 ``$ 1,452.4`` / ``73,260`` / ``(1,200)``(负数括号)
  / 百分号 / ``scale`` 量纲(thousand/million/billion)。
- **不绑基础设施**:无 retriever/llm 依赖,可独立单测。
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any

from app.core.tools.base import BaseTool, ToolParameter

logger = logging.getLogger(__name__)


_SCALE_FACTOR = {
    "thousand": 1_000,
    "thousands": 1_000,
    "million": 1_000_000,
    "millions": 1_000_000,
    "billion": 1_000_000_000,
    "billions": 1_000_000_000,
}

_NEG_PAREN = re.compile(r"^\((?P<num>.+)\)$")
_NUMBER_CORE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _parse_number(token: Any) -> float | None:
    """把 ``$ 1,452.4`` / ``73,260`` / ``(1,200)`` 解析为 float。无法解析返回 None。"""
    if token is None:
        return None
    if isinstance(token, (int, float)):
        return float(token)
    s = str(token).strip()
    if not s:
        return None
    negative = False
    m = _NEG_PAREN.match(s)
    if m:
        negative = True
        s = m.group("num")
    # 去掉货币符号、百分号、空白
    s = re.sub(r"[\$€£¥%\s]", "", s)
    core = _NUMBER_CORE.search(s)
    if not core:
        return None
    try:
        value = float(core.group(0).replace(",", ""))
    except ValueError:
        return None
    return -value if negative else value


def _to_scale_factor(scale: str | None) -> float:
    if not scale:
        return 1.0
    key = scale.strip().lower()
    # 兼容 "in thousands" 这类短语
    for word in key.split():
        if word in _SCALE_FACTOR:
            return float(_SCALE_FACTOR[word])
    return 1.0


def _fmt(value: float) -> str:
    """人类友好但不损失精度的格式化。"""
    if isinstance(value, float) and value.is_integer():
        return f"{int(value)}"
    # 避免浮点尾噪:保留 4 位再去掉尾零
    return f"{round(value, 4):g}"


class TableCalculatorTool(BaseTool):
    """确定性表格数值计算工具。

    参数:
        - ``operation``:lookup | sum | difference | ratio | count
        - ``values``:数值列表(JSON 字符串或逗号分隔)。sum/difference/ratio/count 用。
        - ``rows``:行字典列表(JSON),用于 lookup。
        - ``target``:lookup 时要匹配/取回的字段值或键。
        - ``field``:lookup 时取回的列字段名(默认 ``value``)。
        - ``scale``:量纲(thousand/million/billion),用于 trace 与归一化。
        - ``label``:可选,本次计算的人类标签(写进 trace)。
    """

    name = "table_calculator"
    description = (
        "对金融表格数值做确定性计算(lookup/sum/difference/ratio/count),"
        "返回精确答案与 calculation_trace。避免 LLM 直接算错。"
    )

    _OPERATIONS = {"lookup", "sum", "difference", "ratio", "count"}

    def __init__(self) -> None:
        super().__init__()
        self.parameters = [
            ToolParameter(
                name="operation",
                type="string",
                description="lookup | sum | difference | ratio | count",
                required=True,
            ),
            ToolParameter(
                name="values",
                type="string",
                description="数值列表(JSON 数组或逗号分隔,如 \"[1452.4, 1146.2]\")",
                required=False,
            ),
            ToolParameter(
                name="rows",
                type="string",
                description="行字典列表(JSON),lookup 用,如 [{\"row\":\"Fixed Price\",\"2019\":1452.4}]",
                required=False,
            ),
            ToolParameter(
                name="target", type="string", description="lookup 要匹配的行/键值", required=False
            ),
            ToolParameter(
                name="field", type="string", description="lookup 取回的列字段名(默认 value)", required=False
            ),
            ToolParameter(
                name="scale", type="string", description="量纲:thousand/million/billion", required=False
            ),
            ToolParameter(name="label", type="string", description="本次计算标签(可选)", required=False),
        ]

    async def execute(self, **kwargs: Any) -> str:
        op = str(kwargs.get("operation") or "").strip().lower()
        if op not in self._OPERATIONS:
            return self._err(f"未知 operation: {op!r},应为 {sorted(self._OPERATIONS)}")

        scale = kwargs.get("scale")
        scale_factor = _to_scale_factor(str(scale) if scale is not None else None)
        label = kwargs.get("label")

        try:
            if op == "lookup":
                result = self._lookup(kwargs)
            else:
                values = self._coerce_values(kwargs.get("values"))
                if op == "sum":
                    result = self._sum(values, scale_factor)
                elif op == "difference":
                    result = self._difference(values, scale_factor)
                elif op == "ratio":
                    result = self._ratio(values)
                else:  # count
                    result = self._count(values)
        except _CalcError as e:
            return self._err(str(e))

        payload: dict[str, Any] = {"operation": op, "answer": result["answer"], "ok": True}
        if label:
            payload["label"] = str(label)
        if scale:
            payload["scale"] = str(scale)
        trace = {"operation": op, **result.get("trace", {})}
        payload["calculation_trace"] = trace
        return json.dumps(payload, ensure_ascii=False)

    # -- 数值解析 ----------------------------------------------------------
    def _coerce_values(self, raw: Any) -> list[float]:
        if raw is None:
            return []
        items: list[Any] = []
        if isinstance(raw, (list, tuple)):
            items = list(raw)
        elif isinstance(raw, str):
            s = raw.strip()
            if s.startswith("[") or s.startswith("{"):
                parsed: Any = None
                try:
                    parsed = json.loads(s)
                except json.JSONDecodeError:
                    parsed = None  # 可能是 "[$ 1,452.4, $ 1,146.2]" 这类非法 JSON
                if parsed is not None:
                    items = parsed if isinstance(parsed, list) else [parsed]
                else:
                    # 去掉外层 [] 后按逗号切分;千分位逗号(两侧都是数字)不视为分隔符
                    inner = s.lstrip("[").rstrip("]")
                    items = [x.strip() for x in re.split(r"(?<=\D),|,(?=\D)", inner) if x.strip()]
            elif s:
                # 逗号 / 分号 / 空白分隔
                items = [x.strip() for x in re.split(r"[;,]\s*|\s+", s) if x.strip()]
        nums: list[float] = []
        for it in items:
            v = _parse_number(it)
            if v is None:
                raise _CalcError(f"无法解析数值: {it!r}")
            nums.append(v)
        return nums

    # -- 操作 --------------------------------------------------------------
    def _sum(self, values: list[float], scale_factor: float) -> dict[str, Any]:
        total = sum(values)
        return {
            "answer": _fmt(total),
            "trace": {"inputs": [_fmt(v) for v in values], "sum": _fmt(total)},
        }

    def _difference(self, values: list[float], scale_factor: float) -> dict[str, Any]:
        if len(values) < 2:
            raise _CalcError("difference 至少需要 2 个数值")
        diff = values[0] - values[1]
        return {
            "answer": _fmt(diff),
            "trace": {
                "inputs": [_fmt(v) for v in values],
                "formula": f"{_fmt(values[0])} - {_fmt(values[1])}",
                "difference": _fmt(diff),
            },
        }

    def _ratio(self, values: list[float]) -> dict[str, Any]:
        if len(values) < 2:
            raise _CalcError("ratio 至少需要 2 个数值")
        if math.isclose(values[1], 0.0):
            raise _CalcError("ratio 分母为 0")
        r = values[0] / values[1]
        return {
            "answer": _fmt(r),
            "trace": {
                "inputs": [_fmt(v) for v in values],
                "formula": f"{_fmt(values[0])} / {_fmt(values[1])}",
                "ratio": _fmt(r),
            },
        }

    def _count(self, values: list[float]) -> dict[str, Any]:
        return {
            "answer": str(len(values)),
            "trace": {"count": len(values)},
        }

    def _lookup(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        rows_raw = kwargs.get("rows")
        if rows_raw is None:
            raise _CalcError("lookup 需要 rows")
        rows = self._coerce_rows(rows_raw)
        target = kwargs.get("target")
        field = str(kwargs.get("field") or "value")
        if target is None:
            raise _CalcError("lookup 需要 target")
        target_str = str(target).strip()

        matched: list[dict[str, Any]] = []
        for row in rows:
            # 行内任意字段值匹配 target → 视为命中该行
            hit = any(str(v).strip() == target_str for v in row.values())
            if hit:
                matched.append(row)

        if not matched:
            return {
                "answer": None,
                "trace": {"target": target_str, "field": field, "matched": 0},
            }
        # 取回 field;没有该字段则取回整行
        pulled: list[Any] = []
        for row in matched:
            if field in row:
                pulled.append(row[field])
            else:
                pulled.append(row)
        answer = pulled[0] if len(pulled) == 1 else pulled
        return {
            "answer": answer,
            "trace": {
                "target": target_str,
                "field": field,
                "matched": len(matched),
                "rows_matched": matched,
            },
        }

    def _coerce_rows(self, raw: Any) -> list[dict[str, Any]]:
        if isinstance(raw, (list, tuple)):
            candidate = list(raw)
        elif isinstance(raw, str):
            s = raw.strip()
            if not s:
                return []
            try:
                parsed = json.loads(s)
            except json.JSONDecodeError as e:
                raise _CalcError(f"rows 不是合法 JSON: {e}") from e
            candidate = parsed if isinstance(parsed, list) else [parsed]
        else:
            raise _CalcError(f"rows 类型不支持: {type(raw).__name__}")
        rows: list[dict[str, Any]] = []
        for i, item in enumerate(candidate):
            if isinstance(item, dict):
                rows.append(item)
            else:
                raise _CalcError(f"rows[{i}] 不是对象: {item!r}")
        return rows

    # -- 错误信封 ----------------------------------------------------------
    @staticmethod
    def _err(message: str) -> str:
        return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


class _CalcError(Exception):
    """计算过程中的可向用户报告的错误。"""


__all__ = ["TableCalculatorTool"]
