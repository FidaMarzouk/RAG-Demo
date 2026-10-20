# RAG demo   an elyaeval case study

A retrieval-augmented QA app over a small renewable-energy knowledge base, built with
**LlamaIndex** (pgvector + Ollama), and evaluated with
[elyaeval](https://github.com/FidaMarzouk/DeepEval-based-Testing-Framework-for-LLM-Applications):
end-to-end evaluation over HTTP, span-level (component) evaluation, and CI through elyaeval's Tekton
pipeline.

**Stack** (everything runs locally by default)
- Framework: LlamaIndex
- Vector store: Postgres + pgvector (Docker)
- Embeddings: `nomic-embed-text` via Ollama
- Generator: `llama3.2:3b` via Ollama; set `LLM_PROVIDER=groq` (+ `GROQ_API_KEY`) to use Groq instead
- Judge (evaluation only): `llama3.1` via Ollama, configured in `elyaeval.toml` (any provider works
  there)   a different model from the generator, so the app is never graded by the model that wrote
  the answer
- Knowledge base: 8 short documents in `sample_docs/` (solar, wind, storage, hydropower, geothermal,
  grid integration, green hydrogen, heat pumps)

## Project layout

```
rag-demo/
├── src/                               # the application
│   ├── config.py                      # settings from env / .env (see table below)
│   ├── store.py                       # LlamaIndex: embeddings, PGVectorStore (HNSW), index, LLM
│   ├── rag.py                         # retrieve -> generate_answer -> answer(), traced with @observe
│   ├── ingest.py                      # python -m src.ingest
│   └── api.py                         # FastAPI: POST /query, GET /health
├── db/schema.sql                      # enables pgvector (LlamaIndex creates the table)
├── sample_docs/                       # the knowledge base
├── docker-compose.yml                 # Postgres + pgvector
├── requirements.txt                   # the app's dependencies
│
├── elyaeval.toml                      # evaluation config: judge, thresholds, cache, budget, regression gate
├── goldens_rag_demo.jsonl             # 31 goldens (see "The goldens")
├── test_elyaeval_rag_qa.py            # e2e suite: calls the running API over HTTP
├── test_elyaeval_rag_qa_component.py  # component suite: scores retrieve / generate_answer in-process
├── requirements-eval.txt              # app deps + elyaeval, for running the suites locally
├── pipelinerun.yaml                   # CI: this project's run of elyaeval's Tekton pipeline
└── redteam/                           # promptfoo security scan (separate from quality evaluation)
```

## 1. Run the app

Prerequisites: Docker and [Ollama](https://ollama.com):

```bash
ollama pull nomic-embed-text      # embeddings
ollama pull llama3.2:3b           # generator
ollama pull llama3.1              # evaluation judge

python -m venv .venv && source .venv/bin/activate     # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements-eval.txt                  # app + elyaeval

docker compose up -d                 # Postgres + pgvector
python -m src.ingest                 # chunk + embed sample_docs into pgvector (idempotent)
uvicorn src.api:app --host 0.0.0.0 --port 8000
```

`GET /health` → `{"status": "ok", "llm": "ollama:llama3.2:3b", "top_k": 3}`;
`POST /query` with `{"query": "...", "top_k": 3}` (top_k optional) →
`{"query", "answer", "retrieval_context", "usage": {"input_tokens", "output_tokens"}, "latency_seconds"}`.

| Setting (env or `.env`) | Default | |
|---|---|---|
| `DATABASE_URL` | `postgresql://raguser:ragpass@127.0.0.1:5432/ragdb` | matches docker-compose |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | |
| `LLM_PROVIDER` / `LLM_MODEL` | `ollama` / `llama3.2:3b` | `groq` / `openai/gpt-oss-120b` with `GROQ_API_KEY` |
| `EMBED_MODEL` / `EMBED_DIM` | `nomic-embed-text` / `768` | changing them requires re-ingesting |
| `TOP_K` | `3` | chunks retrieved per question |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `256` / `32` tokens | used by `src.ingest` |

## The goldens

`goldens_rag_demo.jsonl` holds 31 test questions written against the knowledge base, each with a
stable `id`, a reference answer, its source documents, a category and a CI stage (stages are
cumulative: `nightly` also runs the `per_commit` and `merge` goldens).

| Category | What it checks |
|---|---|
| `single_fact`, `numeric` | one fact / figure from one document |
| `multi_hop` | combining two or more documents |
| `false_premise` | the question assumes something false; the answer should correct it |
| `adversarial` | prompt injection inside the question |
| `unanswerable` (`expected_behavior: abstain`) | not in the knowledge base: the app must say so, not guess, scored with the abstention metric |

| Stage | Goldens (cumulative) |
|---|---|
| `per_commit` | 3 (smoke test) |
| `merge` | 10 |
| `nightly` | 22 |
| `release` | 31 |

## 2. Evaluate locally

With the API running, in a second terminal:

```bash
# e2e: every rag_qa golden up to the per_commit stage, through POST /query
ELYAEVAL_CI_STAGE=per_commit pytest test_elyaeval_rag_qa.py          # PowerShell: $env:ELYAEVAL_CI_STAGE="per_commit"; pytest ...

# component: retrieval and generation scored as separate spans (in-process: needs the DB and Ollama)
pytest test_elyaeval_rag_qa_component.py
```

Results land in `report/`: `results_*.csv` (scores), `results_*.html` (open in a browser),
`results_*.meta.json` (which judge/data produced them) and `budget_*.json` (time/calls/tokens used).
A local 8B judge takes minutes per RAG golden: `elyaeval.toml` keeps the result cache on and caps a
run at 30 minutes, highest-priority goldens first. `elyaeval estimate --task-type rag_qa --ci-stage
nightly --dataset goldens_rag_demo.jsonl` projects a run before you start it.

## 3. Evaluate in CI (Tekton)

CI runs the **e2e** suite against the **already-running** API, inside elyaeval's runner image, using
the shared `elyaeval` Pipeline. One-time cluster setup (Pipeline/Tasks, runner image, Secrets, blob
storage) is described in elyaeval's CI guide (`elyaeval/src/elyaeval/recipes/tekton/README.md` in the
elyaeval repo). Then, per run, with the app and Ollama running on your machine:

```powershell
$env:REPO_URL         = "https://github.com/<you>/<this-repo>.git"
$env:SUT_URL          = "http://host.docker.internal:8000"
$env:JUDGE_PROVIDER   = "ollama"
$env:JUDGE_MODEL_NAME = "llama3.1"
$env:JUDGE_BASE_URL   = "http://host.docker.internal:11434"
envsubst < pipelinerun.yaml | kubectl create -n elyaeval -f -
```

The run uploads its reports to the `rag-demo` blob container, fails on metric thresholds
(`check-results`), on an exhausted budget (`check-budget`) and on a regression against the stored
baseline (`check-regression`). Set `promote-baseline` to `"true"` on one deliberate run to create the
baseline (it is only promoted if every gate passes).

To gate on the component suite instead, regenerate the PipelineRun with
`elyaeval init-ci --blob-container rag-demo --test-file test_elyaeval_rag_qa_component.py` and set
`sut-requirements-file: requirements.txt` plus a Secret with the app's env (`DATABASE_URL` and
`OLLAMA_BASE_URL` reachable from the cluster, e.g. via `host.docker.internal`).
