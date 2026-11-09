# Interview App

A Streamlit app for AI interview preparation: a conversational AI interviewer, domain-specific practice, job-description analysis, structured interview data, interviewer guides, and developer tools for model configuration, prompt engineering, and security testing. AI features run through OpenRouter (`openai/gpt-6-luna` by default); the advanced workflows use LangChain and LangGraph, and a ChromaDB vector store with `qwen/qwen3-embedding-8b` embeddings avoids repeating questions.

## Core requirements

| Requirement | How it is met | Evidence |
| --- | --- | --- |
| Research the type of interview preparation | Domain-, role-, and difficulty-specific practice; a conversational interviewer that adapts to performance; job-description-grounded questions; interviewer personas; coaching feedback | Practice room, Interview chat, Job description pages |
| Front-end | Streamlit with native components (chat UI with streaming, forms, segmented controls, dataframes, file upload), grouped navigation | `app.py`, `app_pages/` |
| Model | `openai/gpt-6-luna` (recommended default); the model pickers offer only the three approved models. Embeddings: `qwen/qwen3-embedding-8b` (recommended default) | Model settings page · `interview_app/openrouter.py` |
| At least 5 system prompts with different techniques, compared | Zero-shot, few-shot, chain-of-thought, role + rubric, and self-critique prompts for the same task, compared live on 7 human-labelled answers. Few-shot won and is used in the app | Prompt lab page · [docs/PROMPT_TECHNIQUES.md](docs/PROMPT_TECHNIQUES.md) |
| Defensive system prompt | Stays on interview preparation, politely declines off-topic requests, ignores "Ignore all previous instructions…", with delimiters (untrusted text only as JSON data) and a canary. Backed by deterministic input checks and output validation | Interview chat, Practice room · [docs/DEFENSIVE_PROMPT.md](docs/DEFENSIVE_PROMPT.md) (includes the review demo script) |

## Optional tasks

**Medium tasks** (all implemented and verified live)

| Task | Where to see it |
| --- | --- |
| Model configuration and parameter tuning (capability-aware, unsupported parameters never sent) | Model settings page, Model lab page · `interview_app/model_config.py` |
| Structured JSON output formats (Q&A set, evaluation) validated against JSON Schemas | Structured output page · `interview_app/schemas.py` |
| Prompt cost calculator (estimated and actual cost from live OpenRouter pricing) | Structured output page, sidebar, Model settings · `interview_app/pricing.py` |
| Improvement from the OpenRouter docs: retries with backoff, `require_parameters` routing, fallback model | `interview_app/openrouter.py`, `interview_app/chains/llm.py` |
| Security testing and jailbreak experiments (52 tests, all pass), plus a semantic detector for reworded attacks | Security lab page · Excel sheet [docs/SECURITY_TEST_RESULTS.xlsx](docs/SECURITY_TEST_RESULTS.xlsx) · [docs/SECURITY_TEST_REPORT.md](docs/SECURITY_TEST_REPORT.md) |

**Hard tasks** (all implemented and verified live)

| Task | Evidence |
| --- | --- |
| 1. Conversational AI interviewer chatbot | Interview chat page · [docs/demos/interview_transcript.md](docs/demos/interview_transcript.md) |
| 2. LangChain chains (A–E) and LangGraph workflow | [docs/LANGCHAIN.md](docs/LANGCHAIN.md) · [docs/demos/langchain_chains.md](docs/demos/langchain_chains.md) |
| 3. Vector database duplicate detection | Question memory page · [docs/VECTOR_DB.md](docs/VECTOR_DB.md) · [docs/demos/duplicate_detection.md](docs/demos/duplicate_detection.md) |

Full test results: [docs/TESTING_REPORT.md](docs/TESTING_REPORT.md).

## Setup

1. Install [uv](https://docs.astral.sh/uv/) (Python 3.11+).
2. Add your OpenRouter key to `.streamlit/secrets.toml` (git-ignored) or the environment:

   ```toml
   OPENROUTER_API_KEY = "your-key"
   # Optional; defaults to openai/gpt-6-luna
   OPENROUTER_MODEL = "openai/gpt-6-luna"
   # Optional: used automatically if the primary model is unavailable
   OPENROUTER_FALLBACK_MODEL = "anthropic/claude-sonnet-5.5"
   ```

3. Install and run:

   ```powershell
   uv sync
   uv run streamlit run app.py
   ```

   Stored questions live in `data/chroma/` (git-ignored).

4. Tests (offline, no key needed):

   ```powershell
   uv run python -m unittest discover -s tests -t .
   ```

## Deploy to Streamlit Community Cloud

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub and choose **Create app → Deploy a public app from GitHub**.
2. Repository `snehametkari1395/Interview-App`, branch `main`, main file `app.py`. Under **Advanced settings**, choose Python 3.12.
3. In **Secrets**, paste the contents of [.streamlit/secrets.toml.example](.streamlit/secrets.toml.example) with your real key. Set `APP_ACCESS_CODE` so strangers cannot spend your OpenRouter credits.
4. Deploy. Dependencies install from `requirements.txt` (exported from `uv.lock`).

Notes: the question memory (`data/chroma/`) is stored on the app's temporary disk and resets when the app restarts. Each browser session is limited to 40 AI calls per 10 minutes; your OpenRouter spending limit caps total usage.

## Pages

**Practice**

| Page | What it does |
| --- | --- |
| Home | A dashboard of this session's progress: interviews completed, questions answered, average score, highest level reached, a skill breakdown, recent activity, and quick-start cards. |
| Practice room | One-question-at-a-time practice by domain, role, difficulty, response depth, and persona. AI questions come from chain B with duplicate detection (falls back to a curated bank). Off-topic messages get a polite reply instead of a score. |
| Interview chat | A conversational AI interviewer (LangGraph): asks, triages each message (answers are scored; off-topic and manipulation attempts are politely declined), streams feedback, follows up or changes topic, adapts difficulty, tracks a scoreboard, and ends with a summary and learning plan. Interviews can be resumed or cleared within the session. |
| Job description | Paste or upload (.txt, .md, .pdf, .docx) a job description; chain A extracts skills, technical and behavioural competencies, topics, likely questions, and a prep plan. |
| Structured output | Format 1 (Q&A set) and Format 2 (answer evaluation) as JSON validated against JSON Schemas, with estimated and actual cost. |
| Interviewer guide | Evaluation guides with criteria, a 1–5 rubric, indicators, red flags, and follow-ups. |

**Developer tools**

| Page | What it does |
| --- | --- |
| Model settings | The three approved models, fallback model, every supported parameter, request preview, credits, and the session call log. |
| Model lab | Compare parameter configurations on one task. |
| Prompt lab | The five prompt techniques and their comparison results; run the comparison again. |
| Question memory | ChromaDB vector store: similarity thresholds, similarity check, generate-without-repeats demo, browse and delete. |
| Security lab | Guard checks, LLM screen benchmark, and the security test suite. |
| App review | LLM critique of the app's usability, security, and prompt engineering. |

## Scripts

```powershell
uv run python scripts/compare_prompts.py               # compare the 5 prompt techniques -> docs/PROMPT_TECHNIQUES.md
uv run python scripts/run_demos.py all                 # live demos -> docs/demos/
uv run python scripts/run_security_tests.py --live     # security suite -> docs/SECURITY_TEST_REPORT.md
uv run python scripts/calibrate_similarity.py          # embedding similarity on labelled pairs
uv run python scripts/calibrate_attack_detector.py     # threshold for the semantic injection detector
uv run --with openpyxl python scripts/export_security_xlsx.py   # security results -> docs/SECURITY_TEST_RESULTS.xlsx
```

## Documentation

| Document | Contents |
| --- | --- |
| [docs/PROMPT_TECHNIQUES.md](docs/PROMPT_TECHNIQUES.md) | The five system prompts, comparison method, results, and the chosen technique |
| [docs/DEFENSIVE_PROMPT.md](docs/DEFENSIVE_PROMPT.md) | The defensive prompt, protection layers, live results, and the review demo script |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Component, chain, and LangGraph diagrams; context flow; security boundaries |
| [docs/LANGCHAIN.md](docs/LANGCHAIN.md) | Packages, chains A–E, structured output, fallbacks, interview graph |
| [docs/VECTOR_DB.md](docs/VECTOR_DB.md) | ChromaDB design, stored metadata, threshold calibration, duplicate vs similar vs new |
| [docs/TESTING_REPORT.md](docs/TESTING_REPORT.md) | Test results, live verification, defects found and fixed |
| [docs/SECURITY_TEST_REPORT.md](docs/SECURITY_TEST_REPORT.md) | 52 security tests with expected and actual behaviour |
| [docs/SECURITY_TEST_RESULTS.xlsx](docs/SECURITY_TEST_RESULTS.xlsx) | The same 52 jailbreak and security tests as an Excel sheet, with a summary by category |

## Code layout

```
app.py                       navigation (Practice / Developer tools)
app_pages/                   one file per page
interview_app/
  chains/                    LangChain: llm.py (ChatOpenRouter), base.py (chains, streaming), workflows.py (A–E, triage), interview_graph.py (LangGraph)
  prompt_techniques.py       the five prompt techniques and their comparison
  chain_prompts.py, prompts.py         all other prompts (shared security rules, canary, defensive triage prompt)
  chain_schemas.py, schemas.py         JSON Schemas, validation, trimming
  vectorstore.py, services.py          ChromaDB question memory (qwen3 embeddings via OpenRouter)
  model_config.py, openrouter.py, pricing.py   parameters, approved models, client, cost
  security_guard.py, semantic_guard.py, file_ingest.py, security_suite.py   security (rules + embedding-based injection detector)
scripts/                     prompt comparison, demos, security tests, calibration
tests/                       115 offline tests (fake models and embeddings)
```

## Security model

Deterministic checks enforce; LLM checks only advise. Input is sanitised and pattern-checked at the UI and again inside every chain; a semantic detector (qwen3 embeddings compared with known attack phrasings) flags reworded attacks that have no trigger words; then the defensive triage prompt declines off-topic requests and override attempts before anything is scored. Prompts keep trusted settings and untrusted data separate and carry a canary token. Output is schema-validated and sanitised, including incrementally during streaming. The API key stays server-side, and only generated question text and its metadata are stored. These are application-level boundaries, not a guarantee against every prompt-injection risk.
