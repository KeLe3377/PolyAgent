# 领域资产到 Skill 文件映射

## 领域包 / Domain Pack

| 原资产 | Skill 去向 |
|---|---|
| domain name / description | `SKILL.md` 触发条件 |
| system prompt | `SKILL.md` 回答原则,长内容拆到 `references/examples.md` |
| tools(ctx) | `references/tools.md` |
| corpus/ | `references/corpus.md` 记录来源和 ingestion 规则 |
| eval_cases.json | `references/evaluation.md` |
| deliberation roles | `SKILL.md` 或 `references/examples.md`,写成分析视角而不是固定流程 |

## RAG 领域

| 原资产 | Skill 去向 |
|---|---|
| 文档类型和 metadata | `references/corpus.md` |
| 检索策略 | `references/tools.md` |
| 引用和证据要求 | `SKILL.md` 答案规则 |
| bad cases | `references/evaluation.md` |

## SQL / 数据分析领域

| 原资产 | Skill 去向 |
|---|---|
| schema / 表关系 | `references/schema.md` |
| 指标口径 | `references/metrics.md` |
| 只读查询工具 | `references/tools.md` |
| 示例 SQL | `references/examples.md` |
| 禁止写库规则 | `SKILL.md` 安全边界 + `references/tools.md` |

## 客服 / 工单领域

| 原资产 | Skill 去向 |
|---|---|
| FAQ 和话术 | `references/faq.md` / `references/tone.md` |
| 必填槽位 | `SKILL.md` 澄清规则 |
| 工单 API | `references/tools.md` |
| 转人工条件 | `SKILL.md` 安全边界 |

## 医药 / 法务 / 金融高风险领域

| 原资产 | Skill 去向 |
|---|---|
| 免责声明和边界 | `SKILL.md` |
| 必须引用证据的规则 | `SKILL.md` |
| 权威语料来源 | `references/corpus.md` |
| 禁止给出的建议 | `references/safety.md` |
| 评测集和证据命中要求 | `references/evaluation.md` |
