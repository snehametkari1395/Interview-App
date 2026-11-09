# LangChain and LangGraph workflows

## Packages

| Package | Version | Used for |
| --- | --- | --- |
| `langchain-core` | 1.7 | LCEL runnables, `ChatPromptTemplate`, `RunnableLambda`, `with_fallbacks`, message and usage types |
| `langchain-openrouter` | 0.2.9 | `ChatOpenRouter`, the official OpenRouter chat model (wraps the `openrouter` Python SDK) |
| `langgraph` | 1.2 | `StateGraph`, conditional routing, `InMemorySaver` checkpointing, typed run `context` |

Investigated but not added: `langchain` (the agent framework is not needed; the workflows are explicit chains and a graph), `langchain-community` (no community integration was required), and `langchain-openai` (not needed because `ChatOpenRouter` passes OpenRouter-specific fields such as `provider`, `reasoning`, and `top_k` natively, and returns OpenRouter's billed cost in `response_metadata`).

## Separation of concerns

| Concern | Module |
| --- | --- |
| Prompts | `interview_app/chain_prompts.py` (reuses the security preamble, canary, and context block from `prompts.py`) |
| Output schemas | `interview_app/chain_schemas.py` (JSON Schema; chain C reuses the Format 2 evaluation schema) |
| Model configuration | `interview_app/chains/llm.py` (`ModelSpec`, `build_llm`) on top of `model_config.build_request_body` |
| Chain mechanics | `interview_app/chains/base.py` (`StructuredChain`, `ReplyStream`, `SafeStream`) |
| Chains A–E | `interview_app/chains/workflows.py` |
| Multi-step workflow | `interview_app/chains/interview_graph.py` |
| Application logic | `app_pages/*.py` (UI only: input, display, threading) |

## The chains

Every chain is a `StructuredChain`: `guard → ChatPromptTemplate → ChatOpenRouter (+fallbacks) → validate`.

| Chain | Factory | Input | Output schema | Notable rules |
| --- | --- | --- | --- | --- |
| A · Job description analysis | `jd_analysis_chain` | `job_description` (guarded, ≤12,000 chars) | `JD_ANALYSIS_SCHEMA`: skills with importance and evidence, technical and behavioural competencies, interview topics, likely questions, company, prep plan, `is_job_description` | Non-JDs are recognised and return empty lists |
| B · Question generation | `question_chain`, `generate_unique_questions` | count, focus, `topic_hint` (guarded), `job_context` (from A), `avoid` | `QUESTION_SET_SCHEMA`: question, topic, category, difficulty, expected answer points, follow-ups, hint | Vector de-duplication; mislabelled difficulty is dropped and regenerated |
| C · Answer evaluation | `evaluation_chain` | question, answer (guarded ≤8,000), expected points, job context | Format 2 evaluation: overall + technical accuracy, communication, problem-solving, strengths, weaknesses, missing concepts, suggestions, follow-ups | Persona-free for fairness; calibrated to the question's difficulty |
| D · Follow-up | `followup_chain` | latest turn, previous turn, compact memory, topics covered, target difficulty, avoid, `must_change_topic` | decision (`follow_up` / `new_topic`), rationale, next question, topic, expected points | After two consecutive follow-ups a new topic is enforced in code; near-duplicates are regenerated |
| E · Summary | `summary_chain` | compact per-turn records, difficulty path | overall score, evaluation, readiness, competency scores, strengths, knowledge gaps, learning plan | Score must be consistent with turn scores |
| Streamed reply | `interviewer_reply` | question, compact evaluation | plain text (2–4 sentences, persona voice) | Sanitised incrementally; never states a score |

## Structured output and validation

- When the model lists `structured_outputs`, `response_format` is `json_schema` with `strict: true` (a stripped "wire" copy of the schema). Otherwise JSON mode or prompted JSON is used.
- The full schema (ranges, sizes, enums, no extra fields) is always enforced server-side with `jsonschema`.
- Benign overflow (one list item too many, a string over its length limit) is trimmed and recorded in `ChainOutput.repairs`. This was added after a live run where a valid summary was rejected for listing seven knowledge gaps instead of six.
- Structural problems (missing fields, wrong types, invalid enums) raise `SchemaValidationError` with per-field details and the raw response for inspection.

## Resilience

`build_llm` returns `ChatOpenRouter` composed with LangChain's `with_fallbacks`:

1. The primary model (the OpenRouter SDK retries transient errors with exponential backoff, `max_retries=2`).
2. On HTTP 503 ("no provider meets routing requirements"): the same model without `provider.require_parameters`.
3. On transient or availability errors (429, 5xx, 404, timeouts, no response): the configured fallback model.

Authentication (401), credit (402), and moderation (403) errors are never failed over. SDK errors are mapped to the same fixed user messages as the direct client.

## Interview graph

See the state diagram in [ARCHITECTURE.md](ARCHITECTURE.md). Key decisions:

- **One invocation per user action.** The entry router decides the next node from state, so a failed step can be retried without losing the answer: the input write is checkpointed before nodes run.
- **Deterministic adaptation.** `adapt` records the turn and applies `next_difficulty`: down one level after a score ≤2, up one level after two consecutive scores ≥4 at the current level.
- **Context management.** No node sends the transcript; see the table in ARCHITECTURE.md.
- **Dependencies through `context`.** The model spec, vector store, and thresholds are passed with LangGraph's typed run context (`context_schema=Dependencies`), so they are never written into checkpoints.
- **Streaming with concurrency.** The page runs `graph.stream(stream_mode="updates")` in a worker thread. As soon as the `evaluate` update arrives, the interviewer's feedback streams in the main thread while chain D runs in the worker.

## Demonstrated live

`scripts/run_demos.py` writes:

- [demos/langchain_chains.md](demos/langchain_chains.md): chains A–E run individually (all in `json_schema` strict mode, with token usage and billed cost per call).
- [demos/interview_transcript.md](demos/interview_transcript.md): a five-turn interview with a simulated candidate at planned answer quality (strong, strong, partial, weak, injection attempt).

Both runs used the configured model (`openai/gpt-4o-mini`). Re-run any time with `uv run python scripts/run_demos.py all`, or pass `--model` to try another model.
