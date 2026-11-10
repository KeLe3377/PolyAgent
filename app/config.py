"""应用配置：基于 pydantic-settings，支持环境变量与 .env 文件。"""

from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="enterprise-ai-agent", description="服务名称")
    app_env: str = Field(default="development", description="运行环境")
    debug: bool = Field(default=False, description="调试模式")
    api_prefix: str = Field(default="/api/v1", description="API 前缀")
    host: str = Field(default="0.0.0.0", description="监听地址")
    port: int = Field(default=8000, description="监听端口")

    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_API_KEY", "llm_api_key", "OPENAI_API_KEY", "openai_api_key"),
        description="LLM API Key",
    )
    llm_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("LLM_BASE_URL", "llm_base_url", "OPENAI_API_BASE", "openai_api_base"),
        description="OpenAI 兼容 LLM API Base",
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("LLM_MODEL", "llm_model", "OPENAI_MODEL", "openai_model"),
        description="默认对话模型",
    )
    embed_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("EMBED_API_KEY", "embed_api_key"),
        description="Embedding API Key",
    )
    embed_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("EMBED_BASE_URL", "embed_base_url"),
        description="OpenAI 兼容 Embedding API Base",
    )
    embed_model: str = Field(
        default="text-embedding-3-small",
        validation_alias=AliasChoices("EMBED_MODEL", "embed_model"),
        description="默认 Embedding 模型",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/agent_db",
        description="SQLAlchemy 异步数据库 URL（推荐 postgresql+asyncpg）",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis URL")

    milvus_host: str = Field(default="localhost", description="Milvus 主机")
    milvus_port: int = Field(default=19530, description="Milvus 端口")
    milvus_user: str = Field(default="", description="Milvus 用户名")
    milvus_password: str = Field(default="", description="Milvus 密码")
    milvus_collection_name: str = Field(
        default="agent_knowledge",
        description="默认向量集合名",
    )

    log_level: str = Field(default="INFO", description="日志级别")

    @field_validator("debug", mode="before")
    @classmethod
    def _parse_debug(cls, value):
        """Treat deployment-ish strings as false instead of crashing settings."""
        if isinstance(value, str) and value.strip().lower() in {"release", "prod", "production"}:
            return False
        return value

    @property
    def openai_api_key(self) -> str:
        """旧字段兼容：内部统一走 llm_*。"""
        return self.llm_api_key

    @property
    def openai_api_base(self) -> str:
        """旧字段兼容：内部统一走 llm_*。"""
        return self.llm_base_url

    @property
    def openai_model(self) -> str:
        """旧字段兼容：内部统一走 llm_*。"""
        return self.llm_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
