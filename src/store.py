"""
LlamaIndex building blocks, created once per process: the embedding model,
the pgvector store (with an HNSW index, which, unlike IVFFlat, needs no
training data and so is fine to create on an empty table), the index, the
reranker and the generator LLM.
"""

from __future__ import annotations

from functools import lru_cache

from llama_index.core import VectorStoreIndex
from llama_index.core.llms import LLM
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.vector_stores.postgres import PGVectorStore
from sqlalchemy.engine import make_url

from .config import get_settings


@lru_cache(maxsize=1)
def embed_model() -> OllamaEmbedding:
    s = get_settings()
    return OllamaEmbedding(model_name=s.embed_model, base_url=s.ollama_base_url)


@lru_cache(maxsize=1)
def vector_store() -> PGVectorStore:
    s = get_settings()
    url = make_url(s.database_url)
    return PGVectorStore.from_params(
        host=url.host or "localhost",
        port=str(url.port or 5432),
        database=url.database,
        user=url.username,
        password=url.password,
        table_name=s.table_name,
        embed_dim=s.embed_dim,
        hnsw_kwargs={
            "hnsw_m": 16,
            "hnsw_ef_construction": 64,
            "hnsw_ef_search": 40,
            "hnsw_dist_method": "vector_cosine_ops",
        },
    )


@lru_cache(maxsize=1)
def index() -> VectorStoreIndex:
    return VectorStoreIndex.from_vector_store(vector_store(), embed_model=embed_model())


@lru_cache(maxsize=1)
def ranker():
    """Cross-encoder reranker (FlashRank: ONNX, CPU, no PyTorch), or None
    when RERANK_MODEL is empty. The model (~22 MB) downloads on first use."""
    s = get_settings()
    if not s.rerank_model:
        return None
    from flashrank import Ranker

    return Ranker(model_name=s.rerank_model, cache_dir=str(s.rerank_cache_dir))


@lru_cache(maxsize=1)
def llm() -> LLM:
    s = get_settings()
    if s.llm_provider == "groq":
        from llama_index.llms.groq import Groq

        if not s.groq_api_key:
            raise RuntimeError("LLM_PROVIDER=groq needs GROQ_API_KEY (in .env or the environment)")
        return Groq(model=s.llm_model, api_key=s.groq_api_key, temperature=s.llm_temperature)

    from llama_index.llms.ollama import Ollama

    return Ollama(
        model=s.llm_model,
        base_url=s.ollama_base_url,
        temperature=s.llm_temperature,
        request_timeout=s.llm_timeout_seconds,
    )
