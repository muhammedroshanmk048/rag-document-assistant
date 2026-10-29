from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM: "gemini" (free tier API key) or "ollama" (local, fully offline)
    llm_provider: Literal["gemini", "ollama"] = "gemini"
    google_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    # Used when the main model is overloaded (free tier returns 503 at peak times); empty disables it
    gemini_fallback_model: str = "gemini-flash-lite-latest"
    ollama_model: str = "llama3.2"
    ollama_base_url: str = "http://localhost:11434"

    # Embeddings run locally — no API key, no cost
    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    chroma_dir: str = "data/chroma"
    chunk_size: int = 1000
    chunk_overlap: int = 150
    top_k: int = 4
    max_upload_mb: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
