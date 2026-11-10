from app.config import Settings


def test_settings_prefers_provider_agnostic_llm_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "llm-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("LLM_MODEL", "llm-model")
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-key")
    monkeypatch.setenv("OPENAI_API_BASE", "https://legacy.example/v1")
    monkeypatch.setenv("OPENAI_MODEL", "legacy-model")

    settings = Settings(_env_file=None)

    assert settings.llm_api_key == "llm-key"
    assert settings.llm_base_url == "https://llm.example/v1"
    assert settings.llm_model == "llm-model"
    assert settings.openai_api_key == "llm-key"
    assert settings.openai_api_base == "https://llm.example/v1"
    assert settings.openai_model == "llm-model"


def test_settings_keeps_legacy_openai_env_compatible(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-key")
    monkeypatch.setenv("OPENAI_API_BASE", "https://legacy.example/v1")
    monkeypatch.setenv("OPENAI_MODEL", "legacy-model")

    settings = Settings(_env_file=None)

    assert settings.llm_api_key == "legacy-key"
    assert settings.llm_base_url == "https://legacy.example/v1"
    assert settings.llm_model == "legacy-model"


def test_settings_exposes_embedding_env(monkeypatch):
    monkeypatch.setenv("EMBED_API_KEY", "embed-key")
    monkeypatch.setenv("EMBED_BASE_URL", "https://embed.example/v1")
    monkeypatch.setenv("EMBED_MODEL", "embed-model")

    settings = Settings(_env_file=None)

    assert settings.embed_api_key == "embed-key"
    assert settings.embed_base_url == "https://embed.example/v1"
    assert settings.embed_model == "embed-model"
