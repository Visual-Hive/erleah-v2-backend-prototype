"""
Configuration management using Pydantic Settings.

All settings loaded from environment variables (.env file).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Anthropic API
    anthropic_api_key: str
    anthropic_model: str = "claude-sonnet-4-20250514"
    
    # Database URLs
    database_url: str
    qdrant_url: str = "http://localhost:6333"
    redis_url: str = "redis://localhost:6379"
    
    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = True
    
    # CORS
    cors_origins: str = "*"  # Comma-separated list or "*"
    
    # Logging
    log_level: str = "INFO"
    
    # Agent Configuration
    max_iterations: int = 10
    enable_streaming: bool = True
    
    # Rate Limiting
    max_concurrent_requests: int = 10
    
    # Environment
    environment: str = "development"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins into list."""
        if self.cors_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",")]
    
    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.environment == "development"
    
    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.environment == "production"


# Global settings instance
settings = Settings()
