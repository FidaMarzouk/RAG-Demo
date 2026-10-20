"""
Component (span-level) evaluation of the RAG pipeline (started from
`elyaeval init --task-type rag_qa --eval-mode component`).

Runs the pipeline IN-PROCESS (src.rag.answer) and scores its two stages
separately, so a regression points at the stage that caused it:

  retrieve         -> retrieval_metrics(): contextual precision / recall / relevancy
  generate_answer  -> generation_metrics(): answer relevancy / faithfulness

The app's spans only record what they saw and produced; the metrics are
attached here by span name, and reference answers come from the goldens   the
app imports no judge and never sees them. Needs the database and Ollama
(same environment as the API, see README). Unanswerable goldens are left to
the e2e suite, which scores them with the abstention metric.
"""

import pytest
from deepeval.dataset import Golden
from elyaeval import load_standard_dataset, new_report_path
from elyaeval.core.dataset import golden_id
from elyaeval.core.metrics import generation_metrics, retrieval_metrics
from elyaeval.core.stages import resolve_stage
from elyaeval.reporting.tracing_report import (
    TracedRunner,
    append_traced_csv_rows,
    failed_results,
    traced_test_result_to_csv_rows,
)

from src.rag import answer

REPORT_CSV = new_report_path("rag_qa_component")

SPAN_METRICS = {
    "retrieve": retrieval_metrics,
    "generate_answer": generation_metrics,
}

GOLDENS = [
    g
    for g in load_standard_dataset(
        task_type="rag_qa", ci_stage=resolve_stage("nightly"), dataset_path="goldens_rag_demo.jsonl"
    )
    if (g.additional_metadata or {}).get("expected_behavior") != "abstain"
]


def call_sut(golden: Golden) -> None:
    answer(golden.input)


@pytest.mark.parametrize("golden", GOLDENS, ids=[golden_id(g) for g in GOLDENS])
def test_rag_qa_component(golden):
    result = TracedRunner(golden, span_metrics=SPAN_METRICS).run(call_sut)

    gid = golden_id(golden)
    priority = (golden.additional_metadata or {}).get("priority", "")
    rows = []
    for test_result in result.test_results:
        rows.extend(traced_test_result_to_csv_rows(gid, priority, test_result))
    append_traced_csv_rows(REPORT_CSV, rows)

    failed = failed_results(result)
    assert not failed, f"span(s) failed: {failed}   see {REPORT_CSV} for per-metric scores"
