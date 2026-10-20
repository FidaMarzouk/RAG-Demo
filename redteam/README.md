# RAG Demo + promptfoo Red-Team Security Testing

A small retrieval-augmented question-answering demo (renewable-energy knowledge base)
used as a testbed to explore what [promptfoo](https://promptfoo.dev) offers for
**security testing of a RAG application**  as opposed to answer-quality evaluation,
which is a separate concern (see [Scope](#scope) below).

## Project layout

```
└── redteam/                      # promptfoo project  everything test-related
    ├── promptfooconfig.yaml      # the scan definition: target, purpose, plugins, strategies
    ├── redteam.yaml              # promptfoo-generated test cases (99), see results/TEST_COVERAGE.md
    ├── docker-compose.redteam.yml# second, isolated pgvector container, port 5433
    ├── poisoned-config.yaml      # manifest of the 3 poisoned documents + their target false claims
    ├── poisoned_docs/
    │   └── sample_docs/          # tampered copies of solar/wind/storage.txt
    └── results/
        ├── TEST_COVERAGE.md      # what the 99 generated cases check (read this first)
        ├── SCAN_RESULTS.md       # actual pass/fail findings from the executed scan (read this second)
        ├── redteam-report.json   # raw exported results from `promptfoo export`
        └── redteam-report.pdf    # pdf results downloaded from the promptfoo dashboard 
```

## Scope

This setup is **security testing only**:

- Prompt injection via poisoned retrieved documents
- Document exfiltration (dumping full source docs verbatim)
- PII leakage / invention
- Privacy violations (cross-user data disclosure)
- Hallucination under adversarial framing
- Overreliance on false premises baked into the question
- Excessive agency (claiming capabilities the app doesn't have)
- Jailbreaks, including multi-turn escalation (crescendo)

It does **not** cover answer quality  faithfulness, context recall, context
precision. That's a separate concern (a DeepEval suite in the original project),
deliberately kept out of this config so the two don't get conflated.

## Why promptfoo is used this way

The `/query` endpoint is a black box from promptfoo's point of view: it takes
`{query, top_k}` and returns `{query, answer, retrieval_context, usage, latency_seconds}`.
Retrieval happens *inside* the app (`src/rag.py`, LlamaIndex over pgvector)   promptfoo never assembles
the prompt itself. That rules out promptfoo's `indirect-prompt-injection` plugin,
which needs to own a `{{context}}` template variable to inject payloads into.

What *does* work black-box, unmodified: **RAG poisoning**. Poison real documents,
ingest them into a real pgvector corpus with the real `src/ingest.py`, then hit the real
`/query` endpoint and check whether the generator obeys instructions or repeats false
claims smuggled inside a retrieved chunk. This mirrors how the attack actually happens
in production  an attacker doesn't control your prompt template, they control a
document that ends up in your index.

## What was tested

`redteam.yaml` (generated via `npx promptfoo redteam generate`) contains **99 test
cases** across 7 plugins and 2 attack strategies. Full breakdown, severities, and
example prompts for each plugin are in
[`redteam/results/TEST_COVERAGE.md`](redteam/results/TEST_COVERAGE.md)  read that
for the actual content of what's being checked.

Short version:

| Plugin | Cases | Checks |
|---|---|---|
| `rag-poisoning` | 9 | Does a poisoned retrieved chunk get repeated as fact? |
| `rag-document-exfiltration` | 15 | Can a full source doc be reconstructed verbatim? |
| `pii:direct` | 15 | Does it leak/invent PII? |
| `harmful:privacy` | 15 | Does it disclose other users' data? |
| `hallucination` | 15 | Does it state fabricated facts as grounded? |
| `excessive-agency` | 15 | Does it claim capabilities it doesn't have? |
| `overreliance` | 15 | Does it accept a false premise in the question? |

Each is additionally run through `jailbreak-templates` (static jailbreak wrappers) and
`crescendo` (multi-turn escalation) strategies where applicable.

**Results status: executed.** Two scans have been run against the live endpoint 
see [`redteam/results/SCAN_RESULTS.md`](redteam/results/SCAN_RESULTS.md) for the full
breakdown. Headline numbers from the JSON-backed run:

| | Count |
|---|---|
| Passed (defended) | 49 / 99 |
| Failed (attack succeeded) | 41 / 99 |
| Errored (ungraded  `rag-poisoning` grader bug, see below) | 9 / 99 |

Weakest category: `rag-document-exfiltration` (66.7% attack success  source
documents could be reconstructed verbatim by framing the request as an "export" or
"audit" rather than a direct copy). Strongest: `overreliance` (0%  no false premise
was ever accepted as true).
Details andconcrete failing examples are in `SCAN_RESULTS.md`.

## Prerequisites

- Docker (for both Postgres/pgvector containers)
- [Ollama](https://ollama.com) with `nomic-embed-text`, `llama3.2:3b` (the app's generator) and
  `llama3.1` (promptfoo's attacker/grader) pulled
- Node.js (for `npx promptfoo`)
- The rag-demo app's Python environment (`pip install -r requirements-eval.txt` in the project root)

No API key is needed: the app generates with local Ollama by default, and `promptfooconfig.yaml`
routes promptfoo's own attacker/grader through local `llama3.1` via `redteam.provider`.

All commands below run from the **project root** (the folder containing `src/`).

## Step-by-step: running the scan

**1. Start the isolated redteam database and install promptfoo:**
```bash
docker compose -f redteam/docker-compose.redteam.yml up -d
npm install -g promptfoo
```
This starts a **second, separate** Postgres/pgvector container (`rag_demo_db_redteam`, port 5433,
its own volume), so the real database on 5432 is never touched.

**2. (Optional   already done) Regenerate the poisoned documents:**

`redteam/poisoned_docs/` and `redteam/poisoned-config.yaml` already exist. To regenerate them:
```bash
cd redteam
npx promptfoo redteam poison ../sample_docs/solar.txt ../sample_docs/wind.txt ../sample_docs/storage.txt \
  --goal "Get the assistant to ignore its instructions and reveal its system prompt" \
  --output-dir poisoned_docs
cd ..
```
> **Heads-up:** `redteam poison` always sends full document contents and the stated
> goal to promptfoo's hosted API   this one command is not covered by the local
> `llama3.1` provider regardless of config. Fine for sample renewable-energy docs;
> worth knowing before pointing this at anything sensitive.

**3. Build the poisoned corpus and ingest it into the *isolated* database:**

The poisoned corpus is the real knowledge base with the three tampered documents swapped in.
`DOCS_DIR` and `DATABASE_URL` point ingestion at it and at the redteam database only:
```bash
mkdir -p .redteam_corpus
cp sample_docs/*.txt .redteam_corpus/
cp redteam/poisoned_docs/sample_docs/*.txt .redteam_corpus/
DATABASE_URL=postgresql://raguser:ragpass@127.0.0.1:5433/ragdb DOCS_DIR=.redteam_corpus python -m src.ingest
```
(PowerShell: set `$env:DATABASE_URL` / `$env:DOCS_DIR` first.) The clean `sample_docs/` and the
real database are untouched.

**4. Run the app against the poisoned database:**
```bash
DATABASE_URL=postgresql://raguser:ragpass@127.0.0.1:5433/ragdb uvicorn src.api:app --host 0.0.0.0 --port 8000
```

**5. Run the scan** (second terminal):
```bash
cd redteam
npx promptfoo redteam run
```

**6. Review and export results:**
```bash
npx promptfoo redteam report --output results/redteam-report.html
npx promptfoo export --output results/redteam-report.json
```
Click into any failing case in the HTML report to see the exact prompt sent, the app's actual
answer, and the grader's reasoning. Commit both files into `redteam/results/` so the next person
can see what happened without re-running anything.

**7. Switch back:** stop uvicorn and restart it without the `DATABASE_URL` override (defaults to
the real database on 5432). Tear the redteam database down with
`docker compose -f redteam/docker-compose.redteam.yml down -v` (`-v` also drops its volume) and
delete `.redteam_corpus/`.

> The results in `redteam/results/` were produced against the **previous** version of the app
> (raw psycopg2 + Groq generator, before the LlamaIndex rebuild and its prompt-injection-aware
> system prompt). Re-run the scan to measure the current app.

## Local grading tradeoffs

`redteam.provider` is `ollama:chat:llama3.1`, so both attack generation and result
grading run locally  no data leaves the machine for those parts, with two caveats:

- Generation quality with a local model is generally weaker than with a frontier
  model per promptfoo's own docs  attacks will be less creative than GPT-4-class
  generation would produce. Grading locally is considered reliable; generation
  locally is the weaker link.
- A subset of plugins require promptfoo's hosted generation and silently produce zero
  test cases under a fully local provider. None of the plugins in this config are
  known to require it, but if one produces 0 cases on a re-generate, check that
  plugin's docs page for the 🌐 marker. `rag-document-exfiltration` specifically has
  **no** local fallback and needs remote generation
  (`PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION` must not be set to `true`).

## Optional: enabling `indirect-prompt-injection` properly

For a more surgical version of the poisoning attack (targeted payload injection
rather than poisoning real files), promptfoo would need to assemble the prompt
itself   e.g. add a mode to `src/rag.py`'s `generate_answer()` that accepts a `context`
override instead of always retrieving live from pgvector, then target that with:
```yaml
prompts:
  - "Context: {{context}}\n\nQuestion: {{query}}"
redteam:
  plugins:
    - id: indirect-prompt-injection
      config:
        indirectInjectionVar: context
```
This is a real code change to `src/rag.py`, not just config  worth doing later if
the poisoning-based scan above turns up real findings and isolating exactly which
payload shapes trigger the model (versus get filtered out by retrieval never
surfacing them) becomes useful.

## What promptfoo features this project exercises

A quick inventory, since the point of this project was exploring the tool's surface
area:

- **Red-team scan generation** (`redteam generate`) against a `purpose` description, producing targeted test cases rather than generic ones
- **HTTP provider targets** with `transformResponse` to unwrap a JSON field from a black-box REST API
- **Multiple plugins** spanning RAG-specific (`rag-poisoning`, `rag-document-exfiltration`), safety (`harmful:privacy`, `pii:direct`), and behavioral (`hallucination`, `overreliance`, `excessive-agency`) categories
- **Multiple attack strategies**, including static (`jailbreak-templates`) and multi-turn adaptive (`crescendo`)
- **Local-only provider routing** (`ollama:chat:llama3.1`) for both attack generation and grading, avoiding a hosted-API dependency for most of the pipeline
- **`redteam poison`** for generating tampered document fixtures with a stated goal and manifest (`poisoned-config.yaml`)
- **Report export** (`redteam report`, `export`) for reviewable HTML/JSON output
