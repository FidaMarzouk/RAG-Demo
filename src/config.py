"""
App settings, read once from environment variables (and a local .env).

Defaults run everything locally: Postgres+pgvector from docker-compose,
Ollama for embeddings AND generation. Set LLM_PROVIDER=groq (+ GROQ_API_KEY)
to generate with Groq instead.

The generator model is deliberately NOT the model the evaluation judge uses
(llama3.1, see elyaeval.toml), so the app's answers are never graded by the
model that wrote them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_LLM_MODEL = {"ollama": "llama3.2:3b", "groq": "openai/gpt-oss-120b"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    table_name: str
    ollama_base_url: str
    embed_model: str
    embed_dim: int
    llm_provider: str
    llm_model: str
    llm_temperature: float
    llm_timeout_seconds: float
    groq_api_key: str | None
    top_k: int
    chunk_size: int
    chunk_overlap: int
    docs_dir: Path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    # The @observe spans exist for evaluation; outside it, DeepEval would print
    # "No Confident AI API key found. Skipping trace posting." on every request.
    os.environ.setdefault("CONFIDENT_TRACE_VERBOSE", "NO")
    provider =os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider not in _DEFAULT_LLM_MODEL:
        raise ValueError(f"LLM_PROVIDER must be one of {sorted(_DEFAULT_LLM_MODEL)}, got {provider!r}")
    return Settings(
        database_url=os.getenv("DATABASE_URL", "postgresql://raguser:ragpass@127.0.0.1:5432/ragdb"),
        table_name=os.getenv("VECTOR_TABLE", "rag_demo"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        embed_model=os.getenv("EMBED_MODEL", "nomic-embed-text"),
        embed_dim=int(os.getenv("EMBED_DIM", "768")),
        llm_provider=provider,
        llm_model=os.getenv("LLM_MODEL", _DEFAULT_LLM_MODEL[provider]),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
        llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "300")),
        groq_api_key=os.getenv("GROQ_API_KEY"),
        top_k=int(os.getenv("TOP_K", "3")),
        chunk_size=int(os.getenv("CHUNK_SIZE", "256")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "32")),
        docs_dir=Path(os.getenv("DOCS_DIR", PROJECT_ROOT / "sample_docs")),
    )
