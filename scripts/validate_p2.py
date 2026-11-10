# -*- coding: utf-8 -*-
"""P2 验证:领域 Skill 契约 + registry 扫描 + 示例 Skill 产出。"""
import sys
sys.path.insert(0, ".")

from app.domains.base import DomainContext
from app.domains.registry import DomainRegistry

reg = DomainRegistry()
reg.scan()
print("=== 已注册领域 Skill ===", reg.list_domains())

for name in reg.list_domains():
    pack = reg.get(name)
    print(f"\n--- {pack.name} (v{pack.version}) ---")
    print("default_mode:", pack.default_mode)
    print("system_prompt 前60字:", pack.system_prompt[:60].replace("\n", " "))
    docs = pack.corpus_docs()
    print("corpus_docs 数:", len(docs))
    tools = pack.tools(DomainContext())
    print("tools:", [(t.name, type(t).__name__) for t in tools])
    spec = pack.deliberation_spec()
    print("deliberation participants:", [p.role for p in spec.participants] if spec else None)
    ev = pack.eval_dataset()
    print("eval cases:", len(ev.cases) if ev else 0)
    hints = pack.intent_hints()
    print("intent_hints:", hints.intent_overrides if hints else None)

# 默认包
d = reg.default()
print("\n=== 默认 Skill ===", d.name if d else None)

# summarize(给 /domains 用)
print("\n=== summarize ===")
for s in reg.summarize():
    print(f"{s.name}: mode={s.default_mode} deliberation={s.supports_deliberation} eval={s.has_eval} tools={s.tool_count}")

# 验收断言
names = reg.list_domains()
assert "financial" in names and "kb_qa" in names, "示例领域 Skill 未注册完整"
fin = reg.get("financial")
assert fin.deliberation_spec() is not None, "financial 必须有 deliberation_spec"
assert len(fin.corpus_docs()) == 6, "financial corpus 应为 6 篇"
assert fin.eval_dataset() and len(fin.eval_dataset().cases) >= 4, "financial eval 集 >=4"
kb = reg.get("kb_qa")
assert kb.deliberation_spec() is None, "kb_qa 不应有 deliberation_spec"
print("\n✅ P2 Skill registry 验收通过")
