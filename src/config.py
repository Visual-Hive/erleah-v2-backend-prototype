from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str
    anthropic_model: str = "claude-sonnet-4-20250514"

    # OpenAI (Embeddings)
    openai_api_key: str
    embedding_model: str = "text-embedding-3-small"

    # Databases
    directus_url: str
    directus_api_key: str
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    redis_url: str = "redis://localhost:6379"

    # Anthropic (Haiku for evaluation)
    anthropic_haiku_model: str = "claude-haiku-4-5-20251001"

    # xAI / Grok (acknowledgments)
    xai_api_key: str = ""
    xai_model: str = "grok-3-mini-fast-latest"

    # App Config
    environment: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = True
    cors_origins: str = "*"
    log_level: str = "INFO"
    max_iterations: int = 10

    # Concurrency (configurable via env vars)
    worker_pool_size: int = 20
    max_queue_size: int = 100

    # Retry settings
    max_retry_count: int = 2
    relaxed_score_threshold: float = 0.25

    # Evaluation
    evaluation_enabled: bool = True

    # OpenTelemetry
    otel_exporter_endpoint: str = ""
    otel_service_name: str = "erleah-backend"

    # Sentry
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",")]


settings = Settings()
