"""
End-to-end evaluation of the RAG API (started from `elyaeval init --task-type rag_qa`).

Calls the RUNNING app over HTTP (APP_URL, default http://localhost:8000) for
every golden up to the CI stage (ELYAEVAL_CI_STAGE, default nightly) and
scores the answer:

  - answerable goldens   -> rag_metrics(): answer relevancy, faithfulness and
                            the three contextual (retrieval) metrics;
  - expected_behavior "abstain" (questions the knowledge base can't answer)
                         -> abstention_metrics(): did the app decline instead
                            of inventing an answer?

The judge, thresholds, cache, budget and regression gate come from
elyaeval.toml. Reports land in report/ (CSV + HTML + run metadata + budget
ledger); CI runs this same file through elyaeval's Tekton pipeline.
"""

import os
import time

import pytest
import requests
from deepeval.test_case import LLMTestCase
from elyaeval import evaluate_golden, load_standard_dataset, new_report_path
from elyaeval.core.dataset import golden_id
from elyaeval.core.metrics import metrics_for_golden, rag_metrics
from elyaeval.core.run_contracts import RAGRunResult, SUTUsage
from elyaeval.core.stages import resolve_stage

APP_URL = os.environ.get("APP_URL", "http://localhost:8000").rstrip("/")
REPORT_CSV = new_report_path("rag_qa")

GOLDENS = load_standard_dataset(
    task_type="rag_qa",
    ci_stage=resolve_stage("nightly"),
    dataset_path="goldens_rag_demo.jsonl",
)


def run_app(question: str) -> RAGRunResult:
    response = requests.post(f"{APP_URL}/query", json={"query": question}, timeout=600)
    response.raise_for_status()
    data = response.json()
    usage = data.get("usage") or {}
    return RAGRunResult(
        actual_output=data["answer"],
        retrieval_context=data["retrieval_context"],
        usage=SUTUsage(
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            latency_seconds=data.get("latency_seconds"),
        ),
    )


@pytest.mark.parametrize("golden", GOLDENS, ids=[golden_id(g) for g in GOLDENS])
def test_rag_qa(golden):
    started = time.perf_counter()
    run_result = run_app(golden.input)
    usage = run_result.usage or SUTUsage()
    if usage.latency_seconds is None:
        usage = usage._replace(latency_seconds=time.perf_counter() - started)

    test_case = LLMTestCase(
        input=golden.input,
        actual_output=run_result.actual_output,
        expected_output=golden.expected_output,
        retrieval_context=run_result.retrieval_context,
    )
    result = evaluate_golden(
        golden, test_case, metrics_for_golden(golden, rag_metrics), csv_path=REPORT_CSV, sut_usage=usage
    )
    assert result.success, f"{golden_id(golden)} failed   see {REPORT_CSV} for per-metric scores"
