"""Application configuration (LLD §2). All values come from the environment.

The LLM + embeddings settings are **provider-agnostic**: the gateway speaks to any
OpenAI-compatible endpoint, so changing provider (Gemini ↔ Ollama ↔ Groq ↔ OpenAI)
is a `.env` change, not a code change. Default is Google Gemini (free tier).
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://fixfinance:fixfinance@localhost:5432/fixfinance"

    # LLM (provider-agnostic via an OpenAI-compatible API); default local Ollama
    llm_provider: str = "ollama"  # informational label for traces/logs
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str | None = "ollama"  # Ollama ignores it; OpenAI SDK needs non-empty
    model_main: str = "qwen2.5:7b"
    model_judge: str = "qwen2.5:7b"  # cheaper/faster model can go here, for evals

    # Embeddings (provider-agnostic)
    embeddings_provider: str = "ollama"  # "ollama" | "gemini" | "local"
    embeddings_model: str = "nomic-embed-text"
    embeddings_dim: int = 768  # must match the VECTOR(...) column in schema.sql

    # Auth (temporary, admin-provisioned; FR4.6)
    admin_key: str = "change-me-admin-key"
    session_secret: str = "change-me-session-secret"

    # Orchestration
    max_repair: int = 2
    # Sampling temperature (runtime knobs — "taste the soup"). Low for structured
    # extraction (repeatable facts); a little warmth for free-form questions.
    temperature_structured: float = 0.1
    temperature_text: float = 0.5


settings = Settings()
