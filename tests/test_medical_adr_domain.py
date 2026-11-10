# -*- coding: utf-8 -*-

from app.domains.base import DomainContext
from app.domains.registry import DomainRegistry


def test_medical_adr_domain_is_registered_with_rag_tool() -> None:
    registry = DomainRegistry()
    registry.scan()

    pack = registry.get("medical_adr")

    assert pack is not None
    assert pack.name == "medical_adr"
    assert pack.default_mode == "react"
    tools = pack.tools(DomainContext())
    assert [tool.name for tool in tools] == ["rag_search"]
