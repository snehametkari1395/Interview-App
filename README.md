# Fieldnotes Interview Practice

A Streamlit app for AI interview preparation: a conversational AI interviewer, domain-specific practice, job-description analysis, structured interview data, interviewer guides, and developer tools for model configuration, evaluation, and security testing. AI features run through OpenRouter; the advanced workflows use LangChain and LangGraph, open-weight models by default, and a local ChromaDB vector store to avoid repeating questions.

## Setup

1. Install [uv](https://docs.astral.sh/uv/) (Python 3.11+).
2. Add your OpenRouter key to `.streamlit/secrets.toml` (git-ignored) or the environment:

   ```toml
   OPENROUTER_API_KEY = "your-key"
   # Default model. The advanced features are designed for an open-weight model:
   OPENROUTER_MODEL = "qwen/qwen3-235b-a22b-2507"
   # Optional: used automatically if the primary model is unavailable
   OPENROUTER_FALLBACK_MODEL = "deepseek/deepseek-v3.2"
   ```

   If your OpenRouter workspace has model **guardrails**, allow the models you want to use at https://openrouter.ai/workspaces/default/guardrails. A blocked model returns "unavailable to this account". For this project: `qwen/qwen3-235b-a22b-2507`, `deepseek/deepseek-v3.2`, `mistralai/mistral-small-3.2-24b-instruct`, and the judge `moonshotai/kimi-k2-0905`.

3. Install and run:

   ```powershell
   uv sync
   uv run streamlit run app.py
   ```

   The first use of question memory downloads the open-source embedding model (`all-MiniLM-L6-v2`, about 80 MB) to `~/.cache/chroma`. Stored questions live in `data/chroma/` (git-ignored).

4. Tests (offline, no key needed):

   ```powershell
   uv run python -m unittest discover -s tests -t .
   ```

## Pages

**Practice**

| Page | What it does |
| --- | --- |
| Practice room | One-question-at-a-time practice by domain, role, difficulty, response depth, and persona. AI questions come from chain B with duplicate detection (falls back to a curated bank). |
| Interview chat | A conversational AI interviewer (LangGraph): asks, scores, streams feedback, follows up or changes topic, adapts difficulty, tracks a scoreboard, and ends with a summary and learning plan. Interviews can be resumed or cleared within the session. |
| Job description | Paste or upload (.txt, .md, .pdf, .docx) a job description; chain A extracts skills, technical and behavioural competencies, topics, likely questions, and a prep plan. |
| Structured output | Format 1 (Q&A set) and Format 2 (answer evaluation) as JSON validated against JSON Schemas, with estimated and actual cost. |
| Interviewer guide | Evaluation guides with criteria, a 1–5 rubric, indicators, red flags, and follow-ups. |

**Developer tools**

| Page | What it does |
| --- | --- |
| Model settings | Provider and model from the live OpenRouter catalog, licence label, open-weight filter, fallback model, every supported parameter, request preview, credits, and the session call log. |
| Model lab | Compare parameter configurations on one task. |
| Evaluation | LLM-as-a-judge evaluation of prompts and models on a dataset, with deterministic checks. |
| Question memory | ChromaDB vector store: similarity thresholds, similarity check, generate-without-repeats demo, browse and delete. |
| Security lab | Guard checks, LLM screen benchmark, and the security test suite. |
| App review | LLM critique of the app's usability, security, and prompt engineering. |

## Scripts

```powershell
uv run python scripts/run_demos.py all                 # live demos -> docs/demos/
uv run python scripts/run_evaluation.py                # evaluation plan and cost estimate (add --yes to run)
uv run python scripts/run_security_tests.py --live     # security suite -> docs/SECURITY_TEST_REPORT.md
uv run python scripts/calibrate_similarity.py          # embedding similarity on labelled pairs
```

## Documentation

| Document | Contents |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Component, chain, and LangGraph diagrams; context flow; security boundaries |
| [docs/LANGCHAIN.md](docs/LANGCHAIN.md) | Packages, chains A–E, structured output, fallbacks, interview graph |
| [docs/VECTOR_DB.md](docs/VECTOR_DB.md) | ChromaDB design, stored metadata, threshold calibration, duplicate vs similar vs new |
| [docs/MODEL_COMPARISON.md](docs/MODEL_COMPARISON.md) | Selected open-weight models, open source vs open weight, licensing and deployment limitations, comparison status |
| [docs/EVALUATION.md](docs/EVALUATION.md) | Dataset, deterministic checks, judge rubric, bias controls, limitations |
| [docs/TESTING_REPORT.md](docs/TESTING_REPORT.md) | Test results, live verification, defects found and fixed |
| [docs/SECURITY_TEST_REPORT.md](docs/SECURITY_TEST_REPORT.md) | 48 security tests with expected and actual behaviour |
| [evals/dataset.json](evals/dataset.json) | Evaluation dataset (8 cases, 7 domains, 3 difficulty levels) |

## Code layout

```
app.py                       navigation (Practice / Developer tools)
app_pages/                   one file per page
interview_app/
  chains/                    LangChain: llm.py (ChatOpenRouter), base.py (chains, streaming), workflows.py (A–E), interview_graph.py (LangGraph)
  chain_prompts.py, prompts.py         all prompts (shared security rules and canary)
  chain_schemas.py, schemas.py         JSON Schemas, validation, trimming
  evaluation/                checks, judge, runner, report
  vectorstore.py, services.py          ChromaDB question memory
  licensing.py               model licence classification and default models
  model_config.py, openrouter.py, pricing.py   parameters, client, cost
  security_guard.py, file_ingest.py, security_suite.py   security
evals/dataset.json           evaluation dataset
scripts/                     demos, evaluation, security tests, calibration
tests/                       101 offline tests (fake models and embeddings)
```

## Security model

Deterministic checks enforce; LLM checks only advise. Input is sanitised and pattern-checked at the UI and again inside every chain. Prompts keep trusted settings and untrusted data separate and carry a canary token. Output is schema-validated and sanitised, including incrementally during streaming. The API key stays server-side, and only generated question text and its metadata are stored. See the security test report for details. These are application-level boundaries, not a guarantee against every prompt-injection risk.
