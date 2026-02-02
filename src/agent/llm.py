"""LLM instances for the agent pipeline."""

from langchain_anthropic import ChatAnthropic

from src.config import settings

# Sonnet — used by plan_queries, generate_response, update_profile
sonnet = ChatAnthropic(
    model=settings.anthropic_model,
    api_key=settings.anthropic_api_key,
    temperature=0,
)

# Haiku — used by evaluate (cheap + fast)
haiku = ChatAnthropic(
    model=settings.anthropic_haiku_model,
    api_key=settings.anthropic_api_key,
    temperature=0,
)
