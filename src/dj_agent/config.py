"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Cost control
    monthly_budget_usd: float = 50.0
    daily_quota_per_user: int = 20
    max_response_tokens: int = 600

    # Admin
    admin_api_key: str = "change-me-to-a-strong-secret"

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "dj-agent-v2"

    # Pricing per 1M tokens (gpt-4o-mini defaults)
    price_input_per_mtok: float = 0.15
    price_output_per_mtok: float = 0.60

    # Deployment
    root_path: str = ""  # e.g. "/dj_project" when behind reverse proxy

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
