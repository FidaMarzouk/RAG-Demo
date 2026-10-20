"""
HTTP API around the RAG pipeline.

    uvicorn src.api:app --host 0.0.0.0 --port 8000

POST /query  {"query": "...", "top_k": 3}
          -> {"query", "answer", "retrieval_context", "usage": {"input_tokens", "output_tokens"},
              "latency_seconds"}
GET  /health -> {"status": "ok", "llm": "<provider>:<model>", "top_k": 3}

The endpoints are plain `def` (not async): retrieval and generation are
blocking calls, which FastAPI runs in its thread pool instead of stalling the
event loop. The API takes only the question   evaluation data such as
reference answers never travels through it.
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .config import get_settings
from .rag import answer

app = FastAPI(title="RAG demo", description="Retrieval-augmented QA over a renewable-energy knowledge base.")


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: Optional[int] = Field(default=None, ge=1, le=20)


class UsageModel(BaseModel):
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


class QueryResponse(BaseModel):
    query: str
    answer: str
    retrieval_context: list[str]
    usage: UsageModel
    latency_seconds: float


@app.post("/query")
def query(request: QueryRequest) -> QueryResponse:
    return QueryResponse(**answer(request.query, top_k=request.top_k).to_dict())


@app.get("/health")
def health() -> dict:
    s = get_settings()
    return {"status": "ok", "llm": f"{s.llm_provider}:{s.llm_model}", "top_k": s.top_k}
