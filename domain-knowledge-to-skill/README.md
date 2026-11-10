# Domain Knowledge To Skill

把一个业务领域整理成项目内 Skill,用于替代早期的"可插拔领域包"实现方式。

这个目录不是源码扫描器,也不是自动生成器。它提供的是领域知识迁移方法论:如何把领域提示词、语料、工具契约、安全边界和评测样例整理成一个可复用的 Skill 目录,让平台保持通用,让领域能力随 Skill 扩展。

## 适用场景

- 新增金融、法务、医药、客服、企业知识库等业务领域。
- 现有领域 prompt / corpus / eval cases 分散在代码里,需要整理成可维护 Skill。
- 不想继续为每个领域写一套 domain pack / router / prompt wiring。
- 希望领域能力可以随项目一起版本化、评测和复用。

## 推荐输出结构

```text
skills/
  some-domain/
    SKILL.md
    references/
      corpus.md
      tools.md
      evaluation.md
      safety.md
```

## 核心原则

| 内容 | 去向 |
|---|---|
| 领域定位、触发条件、工作流程、澄清规则 | `SKILL.md` |
| 术语、指标、FAQ、few-shot 示例 | `references/` |
| 语料来源、metadata 字段、chunk 类型 | `references/corpus.md` |
| RAG、SQL、API、计算器等确定性操作 | `references/tools.md` |
| golden cases、bad cases、证据要求 | `references/evaluation.md` |

详见 [`SKILL.md`](SKILL.md) 与 [`references/inventory-template.md`](references/inventory-template.md)。
