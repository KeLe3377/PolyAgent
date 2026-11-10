# Architecture

`domain-knowledge-to-skill` 是领域知识迁移 playbook,用于把业务领域整理为项目内 Skill。

## Boundary

- 不实现领域包运行时。
- 不生成 domain router / domain pack 代码。
- 不扫描或复制整个项目源码。
- 不把大型语料塞进 `SKILL.md`。
- 不生成没有真实实现的工具脚本。

## Responsibility

这个 skill 只回答一个问题:如何把一个领域的知识、语料、工具契约和评测样例组织成可维护的项目内 Skill。

它提供:

- 领域资产盘点流程。
- 领域 Skill 目录结构。
- 领域知识、语料、工具、评测的拆分规则。
- 确定性工具和安全边界记录方式。
- 真实 prompt 验证与迭代建议。

## Project Integration

平台层仍负责:

- Agent 编排。
- RAG 执行。
- 记忆。
- 工具调用。
- 模型路由。
- 全链路追踪。

领域 Skill 负责:

- 什么时候使用该领域。
- 如何解释领域问题。
- 需要读取哪些 references。
- 必须使用哪些工具契约。
- 找不到证据或有风险时如何澄清/拒答/转人工。

## Output Shape

```text
skills/
  domain-name/
    SKILL.md
    references/
      corpus.md
      tools.md
      evaluation.md
      safety.md
```
