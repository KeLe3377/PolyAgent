---
name: domain-knowledge-to-skill
description: Use when adding a new business domain, migrating domain prompts/corpus/tools/eval cases, replacing domain-pack style wiring with a project-local skill, or turning financial/legal/medical/enterprise knowledge into reusable skill files.
---

# Domain Knowledge To Skill

## Purpose

Use this skill to turn a business domain into a project-local Skill. The goal is not to build another hard-coded domain pack. The goal is to package domain knowledge, prompt rules, corpus pointers, tool contracts, safety rules, and evaluation examples so the main Agent can load the right domain skill when needed.

This is the replacement path for the old "可插拔领域包" approach: domain capability lives in a Skill directory, while platform code keeps generic routing, RAG, memory, tracing, model routing, and tool execution.

## What Goes Into A Domain Skill

| Domain asset | Put it in | Rule |
|---|---|---|
| Domain positioning, when to use, answer style, must-ask clarifications | `SKILL.md` | Keep it short and always relevant. |
| Domain terms, metrics, policy rules, schema notes, FAQ, few-shot examples | `references/` | Load only when the topic needs it. |
| RAG corpus locations and ingestion notes | `references/corpus.md` | Do not paste large corpora into `SKILL.md`. |
| Tool contracts such as RAG, SQL, calculators, ticket APIs | `references/tools.md` | Document inputs, outputs, side effects, limits, and safety gates. |
| Evaluation cases and bad cases | `references/evaluation.md` | Keep query, expected evidence, expected behavior, failure mode. |
| Source code wiring notes | `references/integration.md` | Only record how the platform discovers/loads the skill. |

## Workflow

### 1. Define The Domain Boundary

Write one sentence for the domain:

- What user problems does it answer?
- What data or documents does it rely on?
- What actions or tools may it call?
- What must it refuse, clarify, or escalate?

If the boundary is fuzzy, split the domain. A legal contract reviewer and a customer support FAQ assistant should be separate skills even if they share the same RAG backend.

### 2. Inventory Domain Assets

Use `references/inventory-template.md` to collect:

- Existing domain prompts and role instructions.
- Corpus folders, document types, metadata fields, and ingestion assumptions.
- Tools needed by the domain, including RAG filters, calculators, SQL wrappers, API clients, or human handoff.
- Evaluation cases, golden evidence, and known bad cases.
- Safety rules, compliance wording, and uncertainty handling.

### 3. Write `SKILL.md`

The domain `SKILL.md` should include:

- Trigger conditions: when this domain skill applies.
- High-level workflow: clarify, retrieve, use tools, synthesize, cite evidence, escalate.
- Answer rules: citation style, confidence handling, do-not-answer boundaries.
- Reference routing: which reference files to read for which task.
- Tool rules: which operations must use deterministic tools rather than model guessing.

Do not encode every case as if/then branches. Turn repeated failures into general principles.

### 4. Move Heavy Content To `references/`

Use references for details:

- `domain-glossary.md`: terms, aliases, metrics.
- `corpus.md`: corpus sources, metadata fields, chunk types.
- `tools.md`: deterministic operation contracts.
- `examples.md`: good answers and few-shot patterns.
- `evaluation.md`: test cases and expected evidence.
- `safety.md`: refusals, clarifications, escalation rules.

### 5. Preserve Deterministic Boundaries

For facts, calculations, lookups, writes, and regulated content:

- Use existing platform tools or documented tool contracts.
- Do not let the skill invent SQL/API behavior.
- Mark write operations and high-risk operations as requiring confirmation.
- Say when evidence is insufficient instead of filling gaps.

### 6. Wire Into The Project

The platform should discover skills by directory or configured registry. A domain skill should not require editing core orchestration logic for every new domain.

Recommended project-local layout:

```text
skills/
  financial-analysis/
    SKILL.md
    references/
      corpus.md
      tools.md
      evaluation.md
  contract-review/
    SKILL.md
    references/
      glossary.md
      tools.md
      safety.md
```

In PolyAgent specifically, these directories are runtime inputs: `DomainRegistry`
scans `skills/*/SKILL.md`, parses frontmatter, and adapts the Skill into the
platform's generic domain contract. Adding a new domain should mean adding a new
Skill directory, not editing core routing or orchestration code.

### 7. Validate With Real Prompts

Run at least 3-5 prompts:

- A normal domain question.
- A question requiring RAG evidence.
- A question requiring a deterministic tool.
- An ambiguous question that should trigger clarification.
- An out-of-domain or unsafe question.

Record failures in `references/evaluation.md` and convert repeated failures into better principles or tool contracts.

## Common Mistakes

- Rebuilding the old domain-pack API inside markdown.
- Putting whole corpora into `SKILL.md`.
- Treating examples as exhaustive routing rules.
- Letting the model do deterministic calculations or database writes without tools.
- Hiding safety requirements in prose instead of making them explicit.
- Claiming a domain is supported without corpus, tool contract, and evaluation examples.

## Quick Output Checklist

- [ ] Domain boundary is clear.
- [ ] `SKILL.md` stays focused on workflow and judgment principles.
- [ ] Corpus, tools, examples, and evaluation are in `references/`.
- [ ] Tool side effects and safety gates are explicit.
- [ ] The skill can be added without changing core Agent orchestration.
- [ ] At least 3-5 realistic prompts have been used for validation.
